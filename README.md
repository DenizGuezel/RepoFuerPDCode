# AI Mail Responder

Lokaler Gmail-Assistent für Selbstständige und kleine Unternehmen. Die Anwendung analysiert beim ersten Verbinden einmalig das Postfach einschließlich gesendeter Nachrichten, leitet daraus Unternehmenswissen und Schreibstil ab und erstellt mit einem lokalen KI-Modell Antwortentwürfe.

Antworten lassen sich im Rich-Text-Editor bearbeiten, als Gmail-Entwurf speichern und nach ausdrücklicher Bestätigung direkt senden. Die Automatik versendet keine E-Mails.

## Dokumentation

Die **[Projektdokumentation](DOKUMENTATION.md)** erklärt Einrichtung, Architektur, Datenfluss, Datenbank, lokale API, Tests und Fehlerbehebung. Sie richtet sich auch an Entwickler, die das Projekt noch nicht kennen.

## Schnellstart

Voraussetzungen: **Python 3.11+ mit SQLite/FTS5**, ein Browser und **[Ollama](https://ollama.com/download)** für die lokale KI. Der Python-Code benötigt keine zusätzlichen Pakete; die Oberfläche benötigt keinen Build.

Im Projektordner starten:

```sh
python3 run.py --with-ollama --open
```

Unter Windows: `py -3 run.py --with-ollama --open`. Alternativ auf macOS `Start.command` öffnen, unter Windows `start.bat`.

Die Oberfläche läuft unter **http://127.0.0.1:8765**. Falls das Standardmodell noch fehlt, bei laufendem Ollama in einem zweiten Terminal herunterladen:

```sh
ollama pull qwen3:4b-instruct
```

Anschließend unter **Einstellungen** das Modell prüfen und Gmail mit einer eigenen Google-OAuth-Konfiguration verbinden. Die [vollständige Anleitung](DOKUMENTATION.md#2-installation-und-start) erklärt auch Modellablage, Google-Einrichtung und das Verhalten beim Erstimport.

## Technik und Daten

- Backend: Python-Standardbibliothek, lokaler HTTP-Server, SQLite mit FTS5.
- Oberfläche: HTML, CSS und JavaScript mit Rich-Text-Editor.
- KI: Ollama auf `127.0.0.1:11434`, standardmäßig `qwen3:4b-instruct` mit 4.096 Kontext-Tokens.
- Daten: standardmäßig `.data/`, einschließlich Postfacharchiv und Google-Zugangsdaten. Dieser Ordner gehört niemals ins Repository.

**6 GB VRAM sind ein Planungsziel, kein verifizierter Mindestwert.** Die KI verarbeitet lokal; Gmail benötigt Internet für Anmeldung, Abruf, Entwürfe und Versand. Das Projekt ist ein Entwicklerprototyp.

## Tests

```sh
python3 -m unittest discover -s tests
node --check static/app.js
node --check static/editor.js
```

Node.js wird nur für die optionalen JavaScript-Syntaxprüfungen benötigt. Die Python-Tests verwenden temporäre Daten und simulierte Gmail-/Ollama-Antworten.
