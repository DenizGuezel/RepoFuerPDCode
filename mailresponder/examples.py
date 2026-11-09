import time


def seed_examples(store):
    if any(t["source"] == "demo" for t in store.threads()):
        return
    examples = [
        ("demo-angebot", "Marie Schneider", "marie.schneider@example.com", "Anfrage zur Zusammenarbeit", "Hallo,\n\nwir möchten unsere Website überarbeiten und sind auf Ihr Unternehmen aufmerksam geworden. Können Sie uns sagen, wie eine Zusammenarbeit abläuft und welche Informationen Sie für ein Angebot benötigen?\n\nViele Grüße\nMarie Schneider", "ready", "Guten Tag Frau Schneider,\n\nvielen Dank für Ihre Nachricht und Ihr Interesse an einer Zusammenarbeit. Gern möchten wir mehr über Ihr Vorhaben erfahren.\n\nKönnten Sie uns den Link zu Ihrer aktuellen Website schicken und kurz beschreiben, was Sie verändern möchten? Hilfreich wären außerdem Ihr gewünschter Zeitrahmen und ein ungefährer Budgetrahmen.\n\nAuf dieser Grundlage können wir die nächsten Schritte mit Ihnen besprechen.\n\nFreundliche Grüße\nIhr Team", []),
        ("demo-termin", "Jonas Weber", "jonas.weber@example.com", "Kurzes Kennenlernen nächste Woche?", "Guten Tag,\n\nhätten Sie nächste Woche Dienstag um 10 Uhr Zeit für ein kurzes Kennenlernen? Alternativ würde bei mir Donnerstag am Nachmittag passen.\n\nBeste Grüße\nJonas Weber", "review", "Guten Tag Herr Weber,\n\nvielen Dank für Ihre Terminvorschläge. Wir prüfen die beiden Zeitfenster und melden uns mit einer Bestätigung bei Ihnen.\n\nMöchten Sie das Gespräch telefonisch oder per Video führen?\n\nFreundliche Grüße\nIhr Team", ["Die Verfügbarkeit muss persönlich geprüft werden. Es besteht keine Kalenderanbindung."]),
        ("demo-rueckfrage", "Lena Hoffmann", "lena.hoffmann@example.com", "Rückfrage zu Ihren Leistungen", "Hallo zusammen,\n\nbieten Sie auch eine längerfristige Betreuung nach dem Projektabschluss an? Mich würde interessieren, welche Möglichkeiten es gibt.\n\nLiebe Grüße\nLena Hoffmann", "new", "", []),
        ("demo-newsletter", "Design Weekly", "newsletter@example.com", "Neue Inspiration für deinen Freitag", "Unsere wöchentliche Auswahl: neue Arbeiten, spannende Projekte und die besten Links aus der Designwelt.\n\nNewsletter abbestellen", "skipped", "", ["Beispiel für eine Nachricht, die keine persönliche Antwort benötigt."]),
    ]
    for index, (thread_id, name, sender, subject, body, status, draft, notes) in enumerate(examples):
        store.upsert_thread({"id": thread_id, "source": "demo", "sender_name": name, "sender": sender,
                             "subject": subject, "body": body, "messages": [{"from": name+" <"+sender+">", "body": body, "id": thread_id}],
                             "latest_id": thread_id, "headers": {"from": sender, "subject": subject},
                             "received": time.time()-index*2600, "status": status})
        store.update_thread(thread_id, draft=draft, notes=notes, generated_by="Beispielentwurf" if draft else "")
