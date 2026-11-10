import argparse
import json
import mimetypes
import os
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .net import ServiceError
from .service import Application
from .store import LOCKED_SEND_STATES
from .runtime import start_ollama, stop_ollama, instance_lock


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"


def handler_for(app, local_token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            # Authorization codes, email addresses and content must never appear in request logs.
            pass

        def respond(self, status, body, mime="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def authenticated(self):
            token = self.headers.get("X-Local-Token", "")
            origin = self.headers.get("Origin")
            allowed = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
            return self.valid_host() and secrets.compare_digest(token, local_token) and (not origin or origin in allowed)

        def do_GET(self):
            if not self.valid_host():
                return self.respond(403, {"error": "Ungültiger lokaler Zugriff."})
            url = urllib.parse.urlparse(self.path)
            if url.path == "/oauth/callback":
                try:
                    with app.write_lock:
                        account = app.gmail.complete_auth({k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()})
                        app.store.save_settings({"gmail_email": account}, internal=True)
                        app.store.event("Gmail wurde verbunden.")
                    app.start_sync()
                    self.send_response(303)
                    self.send_header("Location", "/#settings")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.end_headers()
                except (ValueError, ServiceError) as exc:
                    import html
                    self.respond(400, "<!doctype html><html lang='de'><meta charset='utf-8'><title>Anmeldung</title><h1>Anmeldung nicht abgeschlossen</h1><p>"+html.escape(str(exc))+"</p><a href='/#settings'>Zur Anwendung</a></html>", "text/html; charset=utf-8")
                return
            if url.path.startswith("/api/"):
                if not self.authenticated():
                    return self.respond(403, {"error": "Bitte lade die lokale Anwendung neu."})
                if url.path == "/api/state":
                    return self.respond(200, app.state())
                if url.path == "/api/health":
                    return self.respond(200, app.health(force=True))
                return self.respond(404, {"error": "Nicht gefunden."})
            filename = "index.html" if url.path == "/" else url.path.removeprefix("/")
            # A strict static-root boundary prevents access to the database and OAuth credentials.
            target = (STATIC / filename).resolve()
            if not target.is_relative_to(STATIC) or not target.is_file() or target.suffix not in (".html", ".js", ".css", ".svg", ".ico", ".woff2"):
                return self.respond(404, {"error": "Nicht gefunden."})
            payload = target.read_bytes()
            if filename == "index.html":
                payload = payload.replace(b"__LOCAL_TOKEN__", local_token.encode())
            self.respond(200, payload, mimetypes.guess_type(target)[0] or "application/octet-stream")

        def do_POST(self):
            if not self.authenticated():
                return self.respond(403, {"error": "Bitte lade die lokale Anwendung neu."})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 <= size <= 2_000_000:
                    return self.respond(413, {"error": "Diese Datei ist zu groß (maximal 2 MB)."})
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self.respond(415, {"error": "Ungültiges Datenformat."})
                data = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("Ungültige Eingabe.")
                path = urllib.parse.urlparse(self.path).path
                result = {"ok": True}
                if path == "/api/settings":
                    app.save_settings(data)
                elif path == "/api/profile/apply":
                    result["applied"] = app.apply_learned_profile(data.get("account"), data.get("fields"), data.get("expected"))
                elif path == "/api/knowledge":
                    result["id"] = app.store.save_document(data.get("title", ""), data.get("content", ""), data.get("id"))
                elif path == "/api/knowledge/website":
                    result.update(app.import_website(data.get("url")))
                elif path == "/api/knowledge/delete":
                    app.store.delete_document(data.get("id", ""))
                elif path == "/api/gmail/configure":
                    with app.write_lock:
                        app.gmail.configure(data)
                elif path == "/api/gmail/connect":
                    with app.write_lock:
                        if app.gmail.connected():
                            raise ValueError("Bitte trenne zuerst das bestehende Gmail-Konto.")
                        result["url"] = app.gmail.begin_auth(f"http://127.0.0.1:{self.server.server_port}")
                elif path == "/api/gmail/reconnect":
                    with app.write_lock:
                        account = app.store.settings().get("gmail_email", "")
                        if not app.gmail.connected() or not account:
                            raise ValueError("Bitte verbinde zuerst dein Gmail-Konto.")
                        result["url"] = app.gmail.begin_auth(f"http://127.0.0.1:{self.server.server_port}", expected_account=account)
                elif path == "/api/gmail/disconnect":
                    app.disconnect()
                elif path == "/api/gmail/sync":
                    if not app.gmail.connected():
                        raise ValueError("Bitte verbinde zuerst Gmail.")
                    app.start_sync()
                elif path == "/api/thread/generate":
                    app.enqueue(data.get("id", ""))
                elif path == "/api/thread/edit":
                    result["revision"] = app.edit(data.get("id", ""), data.get("text", ""),
                                                  data.get("html", ""), data.get("revision"))
                elif path == "/api/thread/publish":
                    app.publish(data.get("id", ""))
                elif path == "/api/thread/send/prepare":
                    result.update(app.prepare_send(data.get("id", ""), data.get("revision")))
                elif path == "/api/thread/send":
                    app.send(data.get("id", ""), data.get("confirmation", ""))
                elif path == "/api/thread/skip":
                    with app.write_lock:
                        row = app.store.thread(data.get("id", ""))
                        if not row:
                            raise ValueError("Nachricht nicht gefunden.")
                        if row["status"] in LOCKED_SEND_STATES:
                            raise ValueError("Der Versandstatus kann hier nicht geändert werden.")
                        app.store.update_thread(row["id"], status="skipped")
                else:
                    return self.respond(404, {"error": "Nicht gefunden."})
                return self.respond(200, result)
            except (ValueError, TypeError, AttributeError):
                # ValueErrors generated by application code are safe and useful; malformed JSON is generic.
                import sys
                exc = sys.exception()
                message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else "Ungültige Eingabe."
                self.respond(400, {"error": message})
            except ServiceError as exc:
                self.respond(409, {"error": str(exc)})
            except Exception:
                self.respond(500, {"error": "Die Aktion konnte nicht abgeschlossen werden. Bitte erneut versuchen."})
    return Handler


def serve(port=8765, data_dir=None, browser=False, with_ollama=False, host="127.0.0.1"):
    os.umask(0o077)
    directory = Path(data_dir or ROOT / ".data")
    with instance_lock(directory):
        _serve(port, directory, browser, with_ollama, host)


def _serve(port, data_dir, browser, with_ollama, host="127.0.0.1"):
    os.umask(0o077)
    app = Application(data_dir or ROOT / ".data")
    token = secrets.token_urlsafe(32)
    try:
        server = ThreadingHTTPServer((host, port), handler_for(app, token))
    except OSError as exc:
        raise SystemExit(f"Der lokale Port {port} ist nicht verfügbar. Wähle mit --port einen anderen.") from exc
    owned_ollama = start_ollama(app.store.directory) if with_ollama else None
    app.start()
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"AI Mail Responder läuft lokal: {url}", flush=True)
    print("Beenden mit Strg+C. Daten bleiben im Datenordner erhalten.", flush=True)
    if browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        app.changed.set()
        server.server_close()
        stop_ollama(owned_ollama)


def main():
    parser = argparse.ArgumentParser(description="AI Mail Responder · lokal")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1",
                        help="Bind-Adresse; 0.0.0.0 ist für den Containerbetrieb vorgesehen")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--open", action="store_true", help="Oberfläche im Browser öffnen")
    parser.add_argument("--with-ollama", action="store_true", help="Installiertes Ollama bei Bedarf lokal mitstarten")
    args = parser.parse_args()
    serve(args.port, args.data_dir, args.open, args.with_ollama, args.host)
