"""Docker startup: own a local Ollama, prepare the selected model, then serve the app."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

from .model import LocalModel
from .net import ServiceError
from .runtime import instance_lock, start_ollama, stop_ollama
from .server import _serve
from .store import Store


def configuration():
    try:
        port = int(os.environ.get("AMR_PORT", "8765"))
    except ValueError:
        raise ValueError("AMR_PORT muss eine Portnummer zwischen 1 und 65535 sein.") from None
    if not 1 <= port <= 65535:
        raise ValueError("AMR_PORT muss eine Portnummer zwischen 1 und 65535 sein.")
    download = os.environ.get("AMR_DOWNLOAD_MODEL", "1")
    if download not in ("0", "1"):
        raise ValueError("AMR_DOWNLOAD_MODEL muss 0 oder 1 sein.")
    return Path("/data"), port, download == "1"


def ensure_model(model):
    if not model or "cloud" in model.lower() or "/" in model or any(c.isspace() for c in model):
        raise ValueError("Für Docker wird ein lokaler Modellname ohne Cloud-Verweis benötigt.")
    local = LocalModel()
    if not local.status(model)["selected_ready"]:
        print(f"Lokales Modell {model} wird vorbereitet. Der erste Download kann mehrere Minuten dauern.", flush=True)
        process = subprocess.Popen(["ollama", "pull", model])
        try:
            if process.wait() != 0:
                raise ServiceError("Der Modelldownload ist fehlgeschlagen. Internetverbindung prüfen und den Container erneut starten.")
        finally:
            stop_ollama(process)
    local.validate(model)


def healthcheck():
    _, port, download = configuration()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/", timeout=5) as response:
        if response.status != 200:
            return 1
    if download:
        # Do not touch the store or recover jobs from a periodic health check.
        with opener.open("http://127.0.0.1:11434/api/tags", timeout=5) as response:
            if response.status != 200:
                return 1
    return 0


def run():
    directory, port, download = configuration()
    os.umask(0o077)
    os.environ["OLLAMA_HOST"] = "127.0.0.1:11434"
    os.environ["OLLAMA_NO_CLOUD"] = "1"
    owned = None
    with instance_lock(directory):
        try:
            owned = start_ollama(directory)
            deadline = time.monotonic() + 60
            local = LocalModel()
            while not local.status("")["online"]:
                if (owned and owned.poll() is not None) or time.monotonic() >= deadline:
                    raise ServiceError("Ollama konnte im Container nicht gestartet werden. Prüfe /data/ollama.log.")
                time.sleep(.5)
            if download:
                ensure_model(Store(directory).settings()["model"])
            _serve(port, directory, False, False, host="0.0.0.0")
        finally:
            stop_ollama(owned)


def main():
    parser = argparse.ArgumentParser(description="AI Mail Responder im Docker-Container")
    parser.add_argument("mode", nargs="?", choices=("serve", "healthcheck"), default="serve")
    args = parser.parse_args()
    if args.mode == "healthcheck":
        try:
            return healthcheck()
        except Exception:
            return 1

    def terminate(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        run()
    except KeyboardInterrupt:
        return 0
    except (ValueError, ServiceError) as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
