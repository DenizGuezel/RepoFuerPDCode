#!/bin/zsh
cd -- "${0:A:h}" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v python3 >/dev/null 2>&1; then
    print -u2 "Zum Starten wird Python 3.11 oder neuer benötigt."
    exit 1
fi

exec python3 run.py --with-ollama --open "$@"
