# AI Mail Responder

Lokaler Gmail-Assistent für Selbstständige und kleine Unternehmen. Die Anwendung analysiert beim ersten Verbinden einmalig das Postfach einschließlich gesendeter Nachrichten, leitet daraus Unternehmenswissen und Schreibstil ab und erstellt mit einem lokalen KI-Modell Antwortentwürfe.

Antworten lassen sich im Rich-Text-Editor bearbeiten, als Gmail-Entwurf speichern und nach ausdrücklicher Bestätigung direkt senden. Die Automatik versendet keine E-Mails.

Unter **Analyseergebnisse ansehen** lassen sich erkannte Unternehmens- und Stilangaben mit den bisherigen Werten vergleichen und einzeln übernehmen. Manuelle Angaben bleiben bis zur bewussten Auswahl erhalten; eine erneute Postfachanalyse ist dafür nicht nötig.

Über **Unternehmenswissen → Website importieren** können öffentlich sichtbare Website-Texte einschließlich passender Unternehmensseiten eingelesen werden. Die lokale KI wählt belegte Textstellen aus; vor dem Speichern lassen sich alle Inhalte bearbeiten. Quellenadressen bleiben im Wissenseintrag nachvollziehbar.

## Dokumentation

Die **[Projektdokumentation](DOKUMENTATION.md)** erklärt Einrichtung, Architektur, Datenfluss, Datenbank, lokale API, Tests und Fehlerbehebung. Sie richtet sich auch an Entwickler, die das Projekt noch nicht kennen.

## Schnellstart

Mit Docker genügt eine Installation von Docker mit Compose. Python und Ollama werden im Image mitgeliefert:

```sh
docker compose up --build -d
```

Beim ersten Start wird das lokale Standardmodell automatisch heruntergeladen. Danach **http://127.0.0.1:8765** öffnen und unter Einstellungen die eigene Google-OAuth-Datei importieren sowie Gmail freigeben. Nachrichten, Anmeldung und Modelle bleiben im Docker-Volume `mail-data` erhalten.

Die [Docker-Anleitung](DOKUMENTATION.md#docker) beschreibt Start, Logs, andere Ports und optionale NVIDIA-Beschleunigung. Die CPU-Konfiguration funktioniert ohne GPU; auf macOS nutzt dieser Linux-Container keine Metal-Beschleunigung.

### Direkt ohne Docker

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
