"""Optionally manage the existing Ollama executable, never install or download implicitly."""
import os
import shutil
import subprocess
import time
import sys
from contextlib import contextmanager


@contextmanager
def instance_lock(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = open(directory / "instance.lock", "a+b")
    try:
        try:
            if sys.platform == "win32":
                import msvcrt
                handle.seek(0)
                if not handle.read(1):
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("Die Anwendung für diesen Datenordner läuft bereits. Öffne die vorhandene lokale Oberfläche.") from None
        yield
    finally:
        handle.close()

from .net import ServiceError, request_json


def start_ollama(directory):
    try:
        request_json("http://127.0.0.1:11434/api/tags", timeout=2)
        return None  # Never take ownership of, reconfigure or stop someone else's service.
    except ServiceError:
        pass
    executable = shutil.which("ollama")
    if not executable:
        return None
    environment = dict(os.environ)
    environment.update({
        "OLLAMA_HOST": "127.0.0.1:11434", "OLLAMA_MODELS": str(directory / "models"),
        "OLLAMA_NO_CLOUD": "1", "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_CONTEXT_LENGTH": "4096", "OLLAMA_DEBUG": "0", "OLLAMA_DEBUG_LOG_REQUESTS": "false",
    })
    with open(directory / "ollama.log", "a") as log:
        process = subprocess.Popen([executable, "serve"], env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    for _ in range(30):
        if process.poll() is not None:
            return None
        try:
            request_json("http://127.0.0.1:11434/api/tags", timeout=1)
            return process
        except ServiceError:
            time.sleep(0.2)
    # The app can still display setup guidance; the owned process is stopped on app shutdown.
    return process


def stop_ollama(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
