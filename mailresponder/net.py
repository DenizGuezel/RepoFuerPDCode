import json
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime


class ServiceError(Exception):
    def __init__(self, message, status=0, *, rate_limited=False, retry_after=0):
        super().__init__(message)
        self.status = status
        self.rate_limited = rate_limited
        self.retry_after = retry_after


def retry_after_seconds(value):
    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp()-time.time())
        except (ValueError, TypeError, OverflowError):
            return 0


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_json(url, method="GET", data=None, headers=None, timeout=30, form=False, max_bytes=8_000_000):
    headers = dict(headers or {})
    raw = None
    if data is not None:
        raw = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    req = urllib.request.Request(url, data=raw, method=method, headers=headers)
    # Never inherit a proxy for private email data, or follow a model/API redirect.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as response:
            payload = response.read(max_bytes+1)
        if len(payload)>max_bytes:
            raise ServiceError("Die Antwort des Dienstes ist zu groß und wurde nicht übernommen.")
        return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        # Only recognize fixed machine reasons. Never expose upstream messages, tokens or content.
        rate_limited = exc.code == 429
        if exc.code == 403 and urllib.parse.urlparse(url).hostname == "gmail.googleapis.com":
            try:
                error = json.loads(exc.read(65536)).get("error", {})
                rate_limited = any(item.get("reason") in {"rateLimitExceeded", "userRateLimitExceeded"}
                                   for item in error.get("errors", []) if isinstance(item, dict))
            except (ValueError, TypeError, AttributeError, OSError):
                pass
        retry_after = retry_after_seconds(exc.headers.get("Retry-After")) if exc.headers else 0
        exc.close()
        if exc.code == 401:
            message = "Die Anmeldung ist abgelaufen. Bitte verbinde Gmail erneut."
        elif rate_limited:
            message = ("Google begrenzt gerade die Abrufe. Der Import wartet und wird automatisch fortgesetzt."
                       if urllib.parse.urlparse(url).hostname == "gmail.googleapis.com"
                       else "Der Dienst ist ausgelastet. Bitte versuche es später erneut.")
        elif "127.0.0.1" in url:
            message = "Das lokale Modell konnte die Anfrage nicht verarbeiten. Prüfe Modell und Ollama."
        else:
            message = f"Google hat die Anfrage abgelehnt (Status {exc.code})."
        raise ServiceError(message, exc.code, rate_limited=rate_limited, retry_after=retry_after) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ServiceError("Ollama ist nicht erreichbar. Starte den lokalen Modelldienst." if "127.0.0.1" in url else "Google ist nicht erreichbar. Prüfe die Internetverbindung.") from None
    except (ValueError, UnicodeError):
        raise ServiceError("Der Dienst hat eine ungültige Antwort zurückgegeben.") from None
