import secrets
import threading
import time

from .gmail import Gmail, make_reply, parse_thread, reply_envelope
from .model import LocalModel
from .net import ServiceError
from .store import DEFAULTS, EMPTY_DRAFT, LOCKED_SEND_STATES, PROFILE_FIELDS, SEND_UNCERTAIN, Store
from .rich import sanitize_draft_html
from .examples import seed_examples
from .learning import MailboxLearner


class Application:
    def __init__(self, directory):
        self.store = Store(directory)
        seed_examples(self.store)
        self.gmail = Gmail(self.store.directory)
        self.model = LocalModel()
        self.stop = threading.Event()
        self.changed = threading.Event()
        self.sync_lock = threading.Lock()
        self.write_lock = threading.RLock()
        self.inference_lock = threading.Lock()
        self.send_confirmation = None
        self.cancel_sync = threading.Event()
        self.disconnecting = False
        self.syncing = False
        self.health_cache = ({"online": False, "models": [], "selected_ready": False, "error": "Noch nicht geprüft."}, 0)
        self.background = []

    def start(self):
        for target in (self.worker, self.poller):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.background.append(thread)

    def health(self, force=False):
        cached, checked = self.health_cache
        if force or time.monotonic()-checked > 15:
            cached = self.model.status(self.store.settings()["model"])
            self.health_cache = cached, time.monotonic()
        return cached

    def state(self):
        settings = self.store.settings()
        initial=self.store.onboarding(settings.get("gmail_email",""))
        onboarding={k:initial[k] for k in ("stage","listed","downloaded","sent","parts_total","parts_done","error","completed")}
        onboarding["imported"]=initial.get("imported",0)
        onboarding["profile_fields"]=list(initial["profile"])
        onboarding["profile"] = {key: value for key, value in initial["profile"].items()
                                 if key in PROFILE_FIELDS and isinstance(value, str) and value.strip()}
        threads = self.store.threads()
        for thread in threads:
            thread["reply_recipient"], _ = reply_envelope(thread)
        return {"settings": {k:settings[k] for k in DEFAULTS}, "onboarding":onboarding,
                "gmail": {"configured": self.gmail.configured(), "connected": self.gmail.connected(), "email": settings.get("gmail_email", ""), "syncing": self.syncing, "last_sync": settings.get("last_sync")},
                "model": self.health(), "threads": threads, "documents": self.store.documents(), "events": self.store.events()}

    def save_settings(self, values):
        values={k:v for k,v in values.items() if k in DEFAULTS}
        current = self.store.settings()
        for key, value in values.items():
            if key in current:
                expected = type(current[key])
                if type(value) is not expected:
                    raise ValueError("Ein Feld hat ein ungültiges Format: "+key)
                if isinstance(value, str) and len(value) > 12000:
                    raise ValueError("Bitte kürze deine Angaben auf maximal 12.000 Zeichen pro Feld.")
        if "context_size" in values and values["context_size"] not in (2048, 4096, 8192):
            raise ValueError("Bitte wähle ein Kontextfenster von 2048, 4096 oder 8192.")
        if "sync_seconds" in values and not 60 <= values["sync_seconds"] <= 3600:
            raise ValueError("Das Abrufintervall muss zwischen 60 und 3600 Sekunden liegen.")
        if "model" in values:
            model = values["model"]
            if not model or len(model) > 160 or "cloud" in model.lower() or "/" in model or any(c.isspace() for c in model):
                raise ValueError("Bitte wähle einen lokalen Modellnamen ohne Cloud-Verweis.")
        if "salutation" in values and values["salutation"] not in ("Du", "Sie", "Wie im Gespräch"):
            raise ValueError("Ungültige Anrede.")
        if "company" in values and len(values["company"]) > 180:
            raise ValueError("Der Unternehmensname darf höchstens 180 Zeichen lang sein.")
        if "gmail_query" in values and not values["gmail_query"].strip():
            raise ValueError("Bitte gib einen Gmail-Suchfilter ein, zum Beispiel in:inbox.")
        if values.get("automatic"):
            merged = {**current, **values}
            if not self.gmail.connected() or not merged["company"].strip() or not merged["description"].strip():
                raise ValueError("Verbinde Gmail und ergänze zuerst dein Unternehmensprofil.")
            if self.store.onboarding(current.get("gmail_email",""))["stage"]!="complete":
                raise ValueError("Die einmalige Postfachanalyse muss zuerst abgeschlossen werden.")
            self.model.validate(merged["model"])
        self.store.save_user_settings(values)
        self.health_cache = (self.health_cache[0], 0)
        self.changed.set()

    def apply_learned_profile(self, account, fields, expected):
        with self.write_lock:
            applied = self.store.apply_learned_profile(account, fields, expected)
            self.store.event("Ausgewählte Analyseergebnisse wurden in das Profil übernommen.")
            self.changed.set()
            return applied

    def enqueue(self, thread_id):
        thread = self.store.thread(thread_id)
        if not thread:
            raise ValueError("Nachricht nicht gefunden.")
        if thread["user_edited"] or thread["status"] == "protected":
            raise ValueError("Dieser Entwurf wurde bearbeitet und bleibt geschützt. Du kannst ihn direkt weiterbearbeiten.")
        if thread["source"]=="gmail" and self.store.onboarding(thread["account"])["stage"]!="complete":
            raise ValueError("Dein Postfach wird zuerst einmalig analysiert. Danach können Antwortentwürfe erstellt werden.")
        if not self.store.settings()["company"].strip() or not self.store.settings()["description"].strip():
            raise ValueError("Ergänze zuerst Unternehmensname und Beschreibung im Unternehmenswissen.")
        self.model.validate(self.store.settings()["model"])
        self.store.queue(thread_id)
        self.changed.set()

    def edit(self, thread_id, text="", markup="", revision=None):
        if not isinstance(markup, str):
            raise ValueError("Ungültige Formatierung.")
        if markup:
            markup, text = sanitize_draft_html(markup)
        if not isinstance(text, str) or not text.strip() or len(text) > 40000:
            raise ValueError("Bitte gib einen Entwurf mit maximal 40.000 Zeichen ein.")
        if revision is not None and (type(revision) is not int or revision < 0):
            raise ValueError("Bitte lade den Entwurf erneut.")
        with self.write_lock:
            row = self.store.thread(thread_id)
            if not row:
                raise ValueError("Nachricht nicht gefunden.")
            if row["status"] in LOCKED_SEND_STATES or (revision is not None and row["revision"] != revision):
                raise ServiceError("Der Entwurf hat sich geändert. Bitte prüfe den aktuellen Stand.")
            updated = self.store.finish_generation(thread_id, row["revision"], {
                "draft": text.strip(), "draft_html": markup, "user_edited": 1,
                "status": "ready", "generated_by": "Manuell bearbeitet", "error": "",
            })
            if not updated:
                raise ServiceError("Der Entwurf hat sich geändert. Bitte prüfe den aktuellen Stand.")
            return row["revision"] + 1

    def _sendable_draft(self, thread_id, revision):
        row = self.store.thread(thread_id)
        if not row or row["source"] != "gmail" or not row["draft"].strip():
            raise ValueError("Nur echte Gmail-Entwürfe können versendet werden.")
        if row["status"] in LOCKED_SEND_STATES or row["status"] in {"queued", "generating"}:
            raise ServiceError("Dieser Entwurf ist gerade nicht zum Versand verfügbar.")
        if row["revision"] != revision:
            raise ServiceError("Der Entwurf hat sich geändert. Öffne die Versandbestätigung erneut.")
        account = self.store.settings().get("gmail_email", "")
        if not account or row["account"] != account or not self.gmail.connected():
            raise ValueError("Das passende Gmail-Konto ist nicht verbunden.")
        return row, account

    def prepare_send(self, thread_id, revision):
        if type(revision) is not int or revision < 0:
            raise ValueError("Bitte lade den Entwurf erneut.")
        with self.write_lock:
            row, account = self._sendable_draft(thread_id, revision)
            target, subject = reply_envelope(row)
            if "@" not in target or any(c in target for c in "\r\n") or target.casefold() == account.casefold():
                raise ValueError("Die Antwortadresse ist ungültig oder gehört zu deinem eigenen Konto.")
            token = secrets.token_urlsafe(32)
            self.send_confirmation = (thread_id, revision, token, time.monotonic() + 300)
            return {"confirmation": token, "recipient": target, "subject": subject}

    def send(self, thread_id, token):
        with self.write_lock:
            confirmation = self.send_confirmation
            if (not confirmation or confirmation[0] != thread_id or time.monotonic() > confirmation[3]
                    or not isinstance(token, str) or not token.isascii()
                    or not secrets.compare_digest(token, confirmation[2])):
                raise ValueError("Bitte öffne die Versandbestätigung und bestätige die Nachricht erneut.")
            self.send_confirmation = None
            row, account = self._sendable_draft(thread_id, confirmation[1])
            self.gmail.check_reply(row, account, manual_send=True)
            payload, _ = make_reply(row, row["draft"], account)
            attempted = False

            def mark_sending():
                nonlocal attempted
                attempted = self.store.finish_generation(thread_id, row["revision"], {"status": "sending", "error": ""})
                if not attempted:
                    raise ServiceError("Der Entwurf hat sich geändert. Öffne die Versandbestätigung erneut.")

            try:
                response = self.gmail.send_reply(row["draft_id"], payload, mark_sending)
                if not isinstance(response, dict) or not response.get("id"):
                    raise ServiceError(SEND_UNCERTAIN)
            except Exception as exc:
                if not attempted:
                    raise
                if isinstance(exc, ServiceError) and exc.status in {400, 401, 403, 404, 405, 413, 422, 429}:
                    self.store.update_thread(thread_id, status=row["status"], error="")
                    raise
                self.store.update_thread(thread_id, status="send_uncertain", error=SEND_UNCERTAIN)
                raise ServiceError(SEND_UNCERTAIN) from None
            self.store.update_thread(thread_id, **EMPTY_DRAFT, status="sent", error="")
            self.store.event("Eine Antwort wurde manuell über Gmail versendet.")

    def publish(self, thread_id):
        with self.write_lock:
            row = self.store.thread(thread_id)
            if not row or row["source"] != "gmail" or not row["draft"].strip():
                raise ValueError("Nur echte Gmail-Nachrichten mit einem Entwurf können gespeichert werden.")
            if row["status"] in LOCKED_SEND_STATES:
                raise ValueError("Der Entwurf ist gerade nicht zum Speichern verfügbar.")
            account = self.store.settings().get("gmail_email", "")
            if not self.gmail.connected() or row["account"] != account:
                raise ValueError("Das passende Gmail-Konto ist nicht verbunden.")
            try:
                draft_id, digest = self.gmail.save_draft(row, account)
            except ServiceError as exc:
                self.store.update_thread(thread_id, status="protected", error=str(exc))
                raise
            self.store.update_thread(thread_id, draft_id=draft_id, remote_hash=digest, status="saved", error="")
            self.store.event("Ein Entwurf wurde in Gmail gespeichert.")

    def disconnect(self):
        self.disconnecting=True
        self.cancel_sync.set()
        try:
            with self.sync_lock, self.write_lock:
                self.send_confirmation = None
                self.gmail.disconnect()
                self.store.save_settings({"automatic": False})
                self.store.remove_gmail_data()
                self.store.event("Gmail wurde getrennt. Lokal importierte E-Mails wurden entfernt; das erkannte Profil und der Abschluss der Ersteinrichtung bleiben gespeichert.")
        finally:
            self.disconnecting=False

    def sync(self):
        if self.disconnecting:
            return
        if not self.sync_lock.acquire(blocking=False):
            return
        self.syncing = True
        self.cancel_sync.clear()
        try:
            settings = self.store.settings()
            if settings["paused"]:
                return
            if not self.gmail.connected():
                raise ValueError("Bitte verbinde zuerst Gmail.")
            account = settings.get("gmail_email", "") or self.gmail.api("/profile")["emailAddress"]
            self.store.save_settings({"gmail_email":account},internal=True)
            initial=self.store.onboarding(account)
            if initial["stage"]!="complete":
                learner=MailboxLearner(self.store,self.gmail,self.model,self.inference_lock,
                    lambda:self.stop.is_set() or self.cancel_sync.is_set() or self.store.settings()["paused"])
                if not learner.run(account):
                    return
                initial=self.store.onboarding(account)
                self.store.save_settings({"history_id":initial["history_id"]},internal=True)
            elif "history_id" not in settings:
                self.store.restore_learned_profile(account)
            settings=self.store.settings()
            history = settings.get("history_id") or initial["history_id"]
            sync_started=time.time()
            # Use a saved time watermark, not a rolling age limit. A large first-run analysis or
            # a long offline period must not hide mail that arrived more than 14 days ago.
            since=max(0,int(settings.get("last_sync") or initial["started"])-60)
            query=settings["gmail_query"]+f" after:{since}"
            # Snapshot before first listing: new arrivals during a full scan are picked up next time.
            newest = self.gmail.api("/profile")["historyId"]
            if history:
                try:
                    changed_ids, newest = self.gmail.changed_threads(history)
                    # Respect arbitrary user Gmail search filters on incremental sync as well.
                    matching = set(self.gmail.list_threads(query))
                    ids = matching.intersection(changed_ids)
                except ServiceError as exc:
                    if exc.status != 404:
                        raise
                    ids = self.gmail.list_threads(query)
            else:
                ids = self.gmail.list_threads(query)
            count = 0
            for thread_id in ids:
                if self.stop.is_set() or self.cancel_sync.is_set():
                    return
                item = parse_thread(self.gmail.get_thread(thread_id), account)
                if not item:
                    continue
                excluded = [x.strip().lower() for x in re_split(settings["excluded_senders"])]
                if any(item["sender"] == x or (x.startswith("@") and item["sender"].endswith(x)) for x in excluded):
                    item["status"] = "skipped"
                if item["external_draft"]:
                    item["status"] = "protected"
                with self.write_lock:
                    now = self.store.settings()
                    if now["paused"]:
                        return
                    queue = now["automatic"] and item["received"] >= initial["started"]
                    if self.store.upsert_thread(item, queue_automatically=queue):
                        count += 1
            self.store.save_settings({"history_id": newest, "gmail_email": account, "last_sync": sync_started}, internal=True)
            self.store.event(f"Gmail synchronisiert · {count} neue oder aktualisierte Gespräche.")
            self.changed.set()
        finally:
            self.syncing = False
            self.sync_lock.release()

    def start_sync(self):
        def run():
            try:
                self.sync()
            except (ServiceError, ValueError) as exc:
                self.store.event(str(exc))
            except Exception:
                self.store.event("Die Synchronisierung wurde unterbrochen. Bitte versuche es erneut.")
        threading.Thread(target=run, daemon=True).start()

    def worker(self):
        while not self.stop.is_set():
            current=self.store.settings()
            learning=self.gmail.connected() and current.get("gmail_email") and self.store.onboarding(current["gmail_email"])["stage"]!="complete"
            if current["paused"] or learning:
                self.changed.wait(1)
                self.changed.clear()
                continue
            with self.write_lock:
                job = self.store.claim()
                row = self.store.thread(job["thread_id"]) if job else None
            if not job:
                self.changed.wait(1)
                self.changed.clear()
                continue
            revision = row["revision"] if row else None
            try:
                if not row or row["user_edited"]:
                    continue
                settings = self.store.settings()
                excluded = [x.strip().lower() for x in re_split(settings["excluded_senders"]) if x.strip()]
                if job["automatic"] and (not settings["automatic"] or any(row["sender"] == x or (x.startswith("@") and row["sender"].endswith(x)) for x in excluded)):
                    self.store.finish_generation(row["id"], revision, {"status": "new" if not settings["automatic"] else "skipped"})
                    continue
                sources = self.store.search(row["subject"]+" "+row["body"])
                history = self.store.history(row["sender"], row["id"], row["account"]) if settings["use_history"] and row["source"] == "gmail" else []
                with self.inference_lock:
                    result = self.model.generate(row, settings, sources, history, allow_skip=bool(job["automatic"]))
                with self.write_lock:
                    saved = self.store.finish_generation(row["id"], revision, {**result, "draft_html": ""})
                    current = self.store.settings()
                    if saved and job["automatic"] and current["automatic"] and not current["paused"] and result["status"] == "ready" and not result["notes"] and row["source"] == "gmail":
                        self.publish(row["id"])
                if saved:
                    self.store.event("Keine Antwort nötig: Die lokale KI hat die Nachricht übersprungen."
                                     if result["status"] == "skipped" else "Ein lokaler Antwortentwurf wurde erstellt.")
            except (ServiceError, ValueError) as exc:
                if row:
                    self.store.finish_generation(row["id"], revision, {"status": "error", "error": str(exc)})
            except Exception:
                if row:
                    self.store.finish_generation(row["id"], revision, {"status": "error", "error": "Der Entwurf konnte nicht erstellt werden. Bitte erneut versuchen."})
            finally:
                self.store.finish_job(job["id"])

    def poller(self):
        last = 0
        while not self.stop.wait(2):
            settings = self.store.settings()
            if self.gmail.connected() and not settings["paused"] and time.monotonic()-last > settings["sync_seconds"]:
                try:
                    self.sync()
                except (ServiceError, ValueError) as exc:
                    self.store.event(str(exc))
                except Exception:
                    self.store.event("Der automatische Gmail-Abruf wurde unterbrochen.")
                last = time.monotonic()


def re_split(text):
    return text.replace(",", "\n").splitlines()
