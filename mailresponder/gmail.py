import base64
import hashlib
import html
import json
import os
import random
import re
import secrets
import threading
import time
import urllib.parse
from email.message import EmailMessage
from email.policy import SMTP
from email.header import decode_header, make_header
from email.utils import parseaddr, getaddresses
from html.parser import HTMLParser

from .net import ServiceError, request_json
from .rich import sanitize_draft_html


API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose"


def b64decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class PlainHTML(HTMLParser):
    def __init__(self, skip_quotes=False):
        super().__init__()
        self.parts, self.hidden = [], 0
        self.skip_quotes=skip_quotes

    def handle_starttag(self, tag, attrs):
        void=tag in {"area","base","br","col","embed","hr","img","input","link","meta","param","source","track","wbr"}
        if self.hidden:
            if not void:self.hidden+=1
            return
        classes=dict(attrs).get("class","") or ""
        if tag in ("script", "style") or self.skip_quotes and (tag=="blockquote" or re.search(r"\b(?:gmail_quote|yahoo_quoted)\b",classes)):
            self.hidden = 1
        elif tag in ("br", "p", "div", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.hidden:
            self.hidden = max(0, self.hidden-1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def body_text(payload, limit=100000, skip_quotes=False):
    plain, markup = [], []
    def visit(part):
        # No attachment downloads and no loading remote images or HTML resources.
        if part.get("filename"):
            return
        encoded = part.get("body", {}).get("data", "")
        if encoded:
            content_type = next((h["value"] for h in part.get("headers", []) if h["name"].lower() == "content-type"), "")
            charset = re.search(r'charset=["\']?([\w-]+)', content_type, re.I)
            try:
                text = b64decode(encoded).decode(charset.group(1) if charset else "utf-8", errors="replace")
            except LookupError:
                text = b64decode(encoded).decode("utf-8", errors="replace")
            if part.get("mimeType") == "text/plain":
                plain.append(text)
            elif part.get("mimeType") == "text/html":
                markup.append(text)
        for child in part.get("parts", []):
            visit(child)
    visit(payload)
    if plain:
        return "\n".join(plain).strip()[:limit]
    parser = PlainHTML(skip_quotes=skip_quotes)
    parser.feed("\n".join(markup))
    return re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()[:limit]


def archive_message(raw):
    headers=headers_of(raw)
    labels=raw.get("labelIds",[])
    return {"id":raw["id"], "thread_id":raw["threadId"], "labels":labels,
            "sender":parseaddr(headers.get("from",""))[1].lower(),
            "recipients":[address.lower() for _,address in getaddresses([headers.get("to",""),headers.get("cc","")]) if address],
            "subject":headers.get("subject","(Ohne Betreff)"), "body":body_text(raw.get("payload",{}),limit=None),
            "own_body":body_text(raw.get("payload",{}),limit=None,skip_quotes=True),
            "outgoing":"SENT" in labels, "received":int(raw.get("internalDate",0))/1000, "headers":headers}


def headers_of(message):
    result = {}
    for header in message.get("payload", {}).get("headers", []):
        try:
            value = str(make_header(decode_header(header["value"])))
        except (LookupError, UnicodeError):
            value = header["value"]
        result[header["name"].lower()] = value
    return result


def parse_thread(raw, account):
    messages = sorted([m for m in raw.get("messages", []) if "DRAFT" not in m.get("labelIds", [])], key=lambda m: int(m.get("internalDate", 0)))
    if not messages:
        return None
    last = messages[-1]
    headers = headers_of(last)
    name, sender = parseaddr(headers.get("from", ""))
    sent = "SENT" in last.get("labelIds", []) or sender.lower() == account.lower()
    automatic = bool(headers.get("list-unsubscribe")) or headers.get("auto-submitted", "no").lower() != "no" or headers.get("precedence", "").lower() in ("bulk", "list", "junk") or bool(re.search(r"(?:no.?reply|do.?not.?reply)", sender, re.I))
    entries = [{"from": headers_of(m).get("from", ""), "body": body_text(m.get("payload", {})), "id": m["id"]} for m in messages]
    return {"id": raw["id"], "source": "gmail", "account": account, "sender": sender.lower(), "sender_name": name or sender.split("@")[0],
            "subject": headers.get("subject", "(Ohne Betreff)"), "body": entries[-1]["body"], "messages": entries,
            "received": int(last.get("internalDate", 0))/1000, "latest_id": last["id"], "headers": headers,
            "status": "skipped" if sent or automatic else "new", "outgoing": sent,
            "external_draft": any("DRAFT" in m.get("labelIds", []) for m in raw.get("messages", []))}


def fingerprint(payload, *, normalize_html=False):
    fields = headers_of({"payload": payload})
    stable = {k: re.sub(r"\s+", " ", fields.get(k, "")).strip() for k in ("from", "to", "cc", "bcc", "subject", "in-reply-to", "references")}
    stable["body"] = body_text(payload).replace("\r\n", "\n").strip()
    def attachments(part):
        return [part.get("filename", "")] + [x for p in part.get("parts", []) for x in attachments(p)]
    stable["attachments"] = [x for x in attachments(payload) if x]
    def rich_text(part):
        own = []
        if part.get("mimeType") == "text/html":
            content = part.get("body", {}).get("data", "")
            if normalize_html:
                try:
                    content = b64decode(content).decode().replace("\r\n", "\n").strip()
                except ValueError:
                    pass
            own.append(content)
        return own + [x for p in part.get("parts", []) for x in rich_text(p)]
    stable["html"] = rich_text(payload)
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def reply_envelope(thread):
    headers = thread["headers"]
    target = parseaddr(headers.get("reply-to", ""))[1] or parseaddr(thread["sender"])[1]
    return target, " ".join(thread["subject"].split())


def make_reply(thread, text, account):
    headers = thread["headers"]
    target, subject = reply_envelope(thread)
    if not target or "@" not in target or any(c in target + account for c in "\r\n"):
        raise ServiceError("Die Antwortadresse ist ungültig.")
    message = EmailMessage(policy=SMTP)
    message["From"] = account
    message["To"] = target
    message["Subject"] = subject
    reply_to = " ".join(headers.get("message-id", "").split())
    if reply_to:
        message["In-Reply-To"] = reply_to
        message["References"] = " ".join((headers.get("references", "") + " " + reply_to).split())
    text = text.replace("\r\n", "\n")
    message.set_content(text)
    plain = {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}
    fields = [{"name": key, "value": str(value)} for key, value in message.items()]
    markup = thread.get("draft_html", "")
    if markup:
        clean, _ = sanitize_draft_html(markup)
        message.add_alternative(clean, subtype="html")
        rich = {"mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(clean.encode()).decode()}}
        digest = "v2:" + fingerprint({"headers": fields, "parts": [plain, rich]}, normalize_html=True)
    else:
        digest = fingerprint({**plain, "headers": fields})
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"message": {"threadId": thread["id"], "raw": raw}}, digest


class Gmail:
    def __init__(self, directory, request=request_json, *, clock=time.monotonic, sleep=time.sleep):
        self.path = directory / "google-auth.json"
        self.request = request
        self.lock = threading.RLock()
        self.pending = None
        self.api_lock = threading.Lock()
        self.clock, self.sleep = clock, sleep
        self.next_request_at = 0

    @staticmethod
    def quota_cost(path, method):
        # Gmail quotas since May 2026: full message bodies cost 60 units, full threads 120.
        # https://developers.google.com/workspace/gmail/api/reference/quota
        endpoint, _, query = path.partition("?")
        parts = endpoint.strip("/").split("/")
        if parts[0] == "profile":
            return 1
        if parts[0] == "history":
            return 2
        if method != "GET":
            return 10 if method == "POST" else 15
        if len(parts) == 1:
            return 10 if parts[0] == "threads" else 5
        # Default formats for these endpoints include bodies too.
        full = urllib.parse.parse_qs(query).get("format", ["full"])[0] in {"full", "raw", "html"}
        return (120 if full else 40) if parts[0] == "threads" else (60 if full else 20)

    def wait_for_quota(self, cost):
        delay = self.next_request_at-self.clock()
        if delay > 64:
            # A long Retry-After must survive subsequent poll attempts without blocking a UI request.
            raise ServiceError("Google begrenzt gerade die Abrufe. Der Import wartet und wird automatisch fortgesetzt.",
                               429, rate_limited=True, retry_after=delay)
        if delay > 0:
            self.sleep(delay)
        # Smooth requests at 80% of the 6,000 units/minute user quota; no initial burst.
        self.next_request_at = self.clock()+cost*60/4800

    def read(self):
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}

    def write(self, data):
        temporary = self.path.with_suffix(".tmp")
        with open(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as file:
            json.dump(data, file)
        temporary.replace(self.path)

    def configured(self):
        return bool(self.read().get("client_id"))

    def connected(self):
        return bool(self.read().get("refresh_token") or self.read().get("access_token"))

    def configure(self, credentials):
        installed = credentials.get("installed")
        if not isinstance(installed, dict) or not installed.get("client_id", "").endswith(".apps.googleusercontent.com"):
            raise ValueError("Bitte importiere eine Google OAuth-Datei vom Typ Desktop-App.")
        if self.connected():
            raise ValueError("Bitte trenne zuerst das verbundene Konto.")
        with self.lock:
            self.write({"client_id": installed["client_id"], "client_secret": installed.get("client_secret", "")})

    def begin_auth(self, base_url, *, expected_account=""):
        credentials = self.read()
        if not credentials.get("client_id"):
            raise ValueError("Importiere zuerst die Google-Zugangskonfiguration.")
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(32)
        self.pending = {"state": state, "verifier": verifier, "redirect": base_url+"/oauth/callback", "expires": time.time()+600,
                        "expected_account": expected_account}
        parameters = {
            "client_id": credentials["client_id"], "redirect_uri": self.pending["redirect"], "response_type": "code", "scope": SCOPES,
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"}
        if expected_account:
            parameters["login_hint"] = expected_account
        return "https://accounts.google.com/o/oauth2/v2/auth?"+urllib.parse.urlencode(parameters)

    def complete_auth(self, query):
        pending = self.pending
        self.pending = None
        if not pending or pending["expires"] < time.time() or not secrets.compare_digest(query.get("state", ""), pending["state"]):
            raise ValueError("Die Anmeldung ist abgelaufen oder ungültig. Bitte starte sie erneut.")
        if query.get("error") or not query.get("code"):
            raise ValueError("Die Google-Anmeldung wurde nicht abgeschlossen.")
        with self.lock:
            config = self.read()
            token = self.request("https://oauth2.googleapis.com/token", "POST", {
                "client_id": config["client_id"], "client_secret": config.get("client_secret", ""),
                "code": query["code"], "code_verifier": pending["verifier"], "redirect_uri": pending["redirect"], "grant_type": "authorization_code"}, form=True)
            granted = set(token.get("scope", "").split())
            if not set(SCOPES.split()) <= granted:
                raise ServiceError("Gmail-Lesezugriff und Entwurfszugriff werden beide benötigt. Bitte verbinde das Konto erneut.")
            access = token.get("access_token")
            if not isinstance(access, str) or not access:
                raise ServiceError("Google hat die Anmeldung nicht vollständig bestätigt. Bitte melde dich erneut an.")
            # Verify the candidate account before replacing credentials. Renewing access must never
            # silently switch accounts or require deleting local messages and onboarding progress.
            profile = self.request(API+"/profile", headers={"Authorization": "Bearer "+access})
            account = profile.get("emailAddress", "") if isinstance(profile, dict) else ""
            if not isinstance(account, str) or "@" not in account:
                raise ServiceError("Google hat das Gmail-Konto nicht bestätigt. Bitte melde dich erneut an.")
            if pending["expected_account"]:
                if account.casefold() != pending["expected_account"].casefold():
                    raise ValueError("Bitte melde dich mit dem bereits verbundenen Gmail-Konto an. Deine bisherigen Daten bleiben erhalten.")
                account = pending["expected_account"]
            config.update(token)
            config["expires_at"] = time.time()+token.get("expires_in", 3600)
            self.write(config)
        return account

    def access_token(self):
        with self.lock:
            config = self.read()
            if config.get("access_token") and config.get("expires_at", 0) > time.time()+60:
                return config["access_token"]
            if not config.get("refresh_token"):
                raise ServiceError("Bitte verbinde zuerst dein Gmail-Konto.")
            refreshed = self.request("https://oauth2.googleapis.com/token", "POST", {
                "client_id": config["client_id"], "client_secret": config.get("client_secret", ""),
                "refresh_token": config["refresh_token"], "grant_type": "refresh_token"}, form=True)
            config.update(refreshed)
            config["expires_at"] = time.time()+refreshed.get("expires_in", 3600)
            self.write(config)
            return config["access_token"]

    def api(self, path, method="GET", data=None):
        # Deliberately no send, delete, label or arbitrary API endpoint surface.
        if not re.fullmatch(r"/(?:profile|threads(?:/[A-Za-z0-9_-]+)?|messages(?:/[A-Za-z0-9_-]+)?|history|drafts(?:/[A-Za-z0-9_-]+)?)(?:\?.*)?", path) or "/send" in path:
            raise ValueError("Nicht unterstützte Gmail-Aktion.")
        if method != "GET" and (method not in ("POST", "PUT") or not re.fullmatch(r"/drafts(?:/[A-Za-z0-9_-]+)?", path)):
            raise ValueError("Nicht unterstützte Gmail-Aktion.")
        options={"max_bytes":64_000_000} if path.startswith("/messages/") and method=="GET" else {}
        with self.api_lock:
            refreshed, retries = False, 0
            while True:
                self.wait_for_quota(self.quota_cost(path, method))
                token = self.access_token()
                try:
                    return self.request(API+path, method, data, headers={"Authorization": "Bearer "+token}, **options)
                except ServiceError as exc:
                    if exc.status == 401 and not refreshed:
                        with self.lock:
                            config = self.read()
                            config["expires_at"] = 0
                            self.write(config)
                        refreshed = True
                        continue
                    if not exc.rate_limited:
                        # In particular, never repeat an uncertain draft write after a server/network error.
                        raise
                    delay = max(exc.retry_after, min(64, 2**retries+random.random()))
                    self.next_request_at = max(self.next_request_at, self.clock()+delay)
                    if retries >= 6 or delay > 64:
                        raise
                    retries += 1

    def disconnect(self):
        with self.lock:
            config = self.read()
            # Disconnect locally. Remote grants can be revoked in the user's Google account.
            self.write({k: config[k] for k in ("client_id", "client_secret") if k in config})
            self.pending = None

    def list_threads(self, query):
        page = ""
        while True:
            data = self.api("/threads?"+urllib.parse.urlencode({"q": query, "maxResults": 100, "pageToken": page}))
            for item in data.get("threads", []):
                yield item["id"]
            page = data.get("nextPageToken", "")
            if not page:
                break

    def list_messages_page(self, page_token=""):
        # No date, inbox, sender or category filter: first-run archive includes Sent and archived mail.
        query={"maxResults":500,"includeSpamTrash":"true"}
        if page_token:
            query["pageToken"]=page_token
        return self.api("/messages?"+urllib.parse.urlencode(query))

    def get_message(self, message_id):
        return self.api("/messages/"+message_id+"?format=full")

    def changed_threads(self, history_id):
        page = ""
        ids = set()
        newest = history_id
        while True:
            data = self.api("/history?"+urllib.parse.urlencode({"startHistoryId": history_id, "pageToken": page, "maxResults": 100}))
            for record in data.get("history", []):
                for added in record.get("messagesAdded", []):
                    msg = added["message"]
                    if "DRAFT" not in msg.get("labelIds", []):
                        ids.add(msg["threadId"])
            newest = data.get("historyId", newest)
            page = data.get("nextPageToken", "")
            if not page:
                return ids, newest

    def get_thread(self, thread_id):
        return self.api("/threads/"+thread_id+"?format=full")

    def check_reply(self, thread, account, *, manual_send=False):
        latest = parse_thread(self.get_thread(thread["id"]), account)
        if (not latest or latest["latest_id"] != thread["latest_id"] or latest["outgoing"]
                or (not manual_send and latest["status"] == "skipped")):
            raise ServiceError("Das Gespräch hat sich inzwischen geändert. Bitte synchronisiere es erneut.")
        if thread["draft_id"]:
            try:
                current = self.api("/drafts/" + thread["draft_id"] + "?format=full")
            except ServiceError as exc:
                if exc.status == 404:
                    raise ServiceError("Der Gmail-Entwurf wurde entfernt oder bereits versendet. Er wird nicht neu angelegt.") from None
                raise
            expected = thread["remote_hash"]
            payload = current["message"]["payload"]
            actual = ("v2:" + fingerprint(payload, normalize_html=True)
                      if expected.startswith("v2:") else fingerprint(payload))
            if actual != expected:
                raise ServiceError("Der Entwurf wurde in Gmail bearbeitet. Deine Änderungen bleiben erhalten.")
        elif latest["external_draft"]:
            raise ServiceError("Zu diesem Gespräch gibt es bereits einen Gmail-Entwurf. Er bleibt erhalten.")

    def save_draft(self, thread, account):
        self.check_reply(thread, account)
        body, digest = make_reply(thread, thread["draft"], account)
        if thread["draft_id"]:
            body["id"] = thread["draft_id"]
            response = self.api("/drafts/" + thread["draft_id"], "PUT", body)
        else:
            response = self.api("/drafts", "POST", body)
        if not isinstance(response, dict) or not response.get("id"):
            raise ServiceError("Gmail hat das Speichern des Entwurfs nicht bestätigt.")
        return response["id"], digest

    def send_reply(self, draft_id, payload, mark_sending):
        # Send only through the explicit confirmation workflow, without automatic retries.
        path = "/drafts/send" if draft_id else "/messages/send"
        body = {**payload, "id": draft_id} if draft_id else payload["message"]
        with self.api_lock:
            delay = self.next_request_at - self.clock()
            if delay > 64:
                raise ServiceError("Gmail begrenzt gerade die Abrufe. Bitte versuche es später erneut.")
            if delay > 0:
                self.sleep(delay)
            token = self.access_token()
            mark_sending()
            self.next_request_at = self.clock() + 100 * 60 / 4800
            try:
                return self.request(API + path, "POST", body, headers={"Authorization": "Bearer " + token})
            except ServiceError as exc:
                if exc.rate_limited:
                    self.next_request_at = max(self.next_request_at, self.clock() + max(1, exc.retry_after))
                raise
