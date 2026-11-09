import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path

from mailresponder.gmail import Gmail, SCOPES, body_text, fingerprint, make_reply, parse_thread
from mailresponder.model import LocalModel, prepare_draft
from mailresponder.net import ServiceError
from mailresponder.service import Application
from mailresponder.store import Store
from mailresponder.runtime import instance_lock


def message(mid="m1", sender="Marie <marie@example.com>", text="Hallo, was kostet Ihre Beratung?", labels=None):
    return {"id": mid, "internalDate": "1700000000000", "labelIds": labels or ["INBOX"], "payload": {
        "mimeType": "text/plain", "headers": [{"name": k, "value": v} for k, v in {
            "From": sender, "To": "team@example.com", "Subject": "Beratungsanfrage", "Message-ID": "<"+mid+"@example.com>",
        }.items()], "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}}


def row(tid="t1"):
    return parse_thread({"id": tid, "messages": [message()]}, "team@example.com")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_profile_persists_without_changing_defaults(self):
        self.store.save_settings({"company": "Testbetrieb", "automatic": False, "unknown": "ignored"})
        settings = Store(self.temp.name).settings()
        self.assertEqual(settings["company"], "Testbetrieb")
        self.assertEqual(settings["context_size"], 4096)
        self.assertNotIn("unknown", settings)

    def test_second_instance_cannot_recover_an_active_workers_queue(self):
        with instance_lock(Path(self.temp.name)):
            with self.assertRaises(SystemExit):
                with instance_lock(Path(self.temp.name)):
                    pass
        with instance_lock(Path(self.temp.name)):
            pass

    def test_search_chunks_update_and_delete(self):
        doc = self.store.save_document("Beratungspreise", "Beratung kostet 80 Euro. "+"Projekt "*400)
        self.assertTrue(self.store.search("Was kostet Beratung?"))
        self.store.save_document("Neue Leistung", "Fotografie im Studio.", doc)
        self.assertEqual(self.store.search("Beratung"), [])
        self.assertTrue(self.store.search("Fotografie"))
        self.store.delete_document(doc)
        self.assertEqual(self.store.search("Fotografie"), [])

    def test_reimport_is_idempotent(self):
        self.assertTrue(self.store.upsert_thread(row()))
        self.store.update_thread("t1", draft="Antwort", status="ready")
        self.assertFalse(self.store.upsert_thread(row()))
        self.assertEqual(self.store.thread("t1")["draft"], "Antwort")
        self.assertEqual(self.store.thread("t1")["status"], "ready")

    def test_new_arrival_protects_manually_edited_draft(self):
        self.store.upsert_thread(row())
        self.store.update_thread("t1", draft="Meine Antwort", user_edited=1)
        updated = row()
        updated["latest_id"] = "m2"
        self.store.upsert_thread(updated)
        self.assertEqual(self.store.thread("t1")["status"], "protected")
        self.assertEqual(self.store.thread("t1")["draft"], "Meine Antwort")

    def test_generation_cannot_overwrite_concurrent_edit(self):
        self.store.upsert_thread(row())
        revision = self.store.thread("t1")["revision"]
        self.store.update_thread("t1", draft="Von Hand", user_edited=1)
        self.assertFalse(self.store.finish_generation("t1", revision, {"draft": "Vom Modell"}))
        self.assertEqual(self.store.thread("t1")["draft"], "Von Hand")

    def test_queue_deduplicates_and_recovers_interruption(self):
        self.store.upsert_thread(row())
        self.assertTrue(self.store.queue("t1"))
        self.assertFalse(self.store.queue("t1"))
        self.assertIsNotNone(self.store.claim())
        self.assertIsNone(self.store.claim())
        recovered = Store(self.temp.name)
        self.assertIsNotNone(recovered.claim())

    def test_history_is_scoped_to_sender_and_account(self):
        a = row("t1")
        b = row("t2")
        b["account"] = "other@example.com"
        self.store.upsert_thread(a)
        self.store.upsert_thread(b)
        self.assertEqual(len(self.store.history(a["sender"], "t0", a["account"])), 1)


class GmailTests(unittest.TestCase):
    def test_non_utf8_mail_and_encoded_headers_are_decoded(self):
        m = message()
        m["payload"]["headers"].extend([{"name":"Content-Type", "value":"text/plain; charset=iso-8859-1"}, {"name":"Subject", "value":"=?utf-8?b?R3LDvMOfZQ==?="}])
        m["payload"]["body"]["data"] = base64.urlsafe_b64encode("Schöne Grüße".encode("iso-8859-1")).decode()
        parsed = parse_thread({"id":"t1","messages":[m]},"team@example.com")
        self.assertEqual(parsed["subject"],"Grüße")
        self.assertEqual(parsed["body"],"Schöne Grüße")

    def test_recipient_or_formatting_edits_change_fingerprint(self):
        original=message()["payload"]
        changed=json.loads(json.dumps(original))
        changed["headers"].append({"name":"Cc","value":"other@example.com"})
        self.assertNotEqual(fingerprint(original),fingerprint(changed))
        rich=json.loads(json.dumps(original))
        rich["parts"]=[{"mimeType":"text/html","body":{"data":"PGI+SGFsbG88L2I+"}}]
        self.assertNotEqual(fingerprint(original),fingerprint(rich))

    def test_nested_body_ignores_attachments_and_html_resources(self):
        payload = {"parts": [{"mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(b'<script>secret()</script><p>Hallo</p><img src="https://tracker.test">').decode()}}, {"mimeType": "text/plain", "filename": "secret.txt", "body": {"data": base64.urlsafe_b64encode(b'Private attachment').decode()}}]}
        self.assertEqual(body_text(payload), "Hallo")

    def test_latest_draft_is_not_treated_as_incoming_mail(self):
        first = message()
        draft = message("d1", labels=["DRAFT"])
        parsed = parse_thread({"id": "t1", "messages": [first, draft]}, "team@example.com")
        self.assertEqual(parsed["latest_id"], "m1")
        self.assertTrue(parsed["external_draft"])

    def test_sent_and_automated_mail_are_skipped(self):
        sent = message(sender="Team <team@example.com>", labels=["SENT"])
        self.assertEqual(parse_thread({"id":"t1", "messages":[sent]}, "team@example.com")["status"], "skipped")
        automatic = message(sender="noreply@example.com")
        self.assertEqual(parse_thread({"id":"t1", "messages":[automatic]}, "team@example.com")["status"], "skipped")

    def test_reply_has_conversation_headers_and_fixed_recipient(self):
        data, _ = make_reply(row(), "Guten Tag!", "team@example.com")
        from email import policy
        from email.parser import BytesParser
        parsed = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(data["message"]["raw"]))
        self.assertEqual(parsed["To"], "marie@example.com")
        self.assertEqual(parsed["In-Reply-To"], "<m1@example.com>")
        self.assertEqual(parsed["Subject"], "Beratungsanfrage")
        self.assertEqual(data["message"]["threadId"], "t1")

    def test_external_edit_stops_remote_update(self):
        with tempfile.TemporaryDirectory() as temp:
            gmail = Gmail(Path(temp))
            thread = {**row(), "draft": "Original", "draft_id": "d1", "remote_hash": "previous"}
            calls = []
            def api(path, method="GET", data=None):
                calls.append((path, method))
                if path.startswith("/threads"):
                    return {"id":"t1", "messages":[message()]}
                return {"message":message("d1", text="In Gmail geändert")}
            gmail.api = api
            with self.assertRaisesRegex(ServiceError, "bearbeitet"):
                gmail.save_draft(thread, "team@example.com")
            self.assertTrue(all(method == "GET" for _, method in calls))

    def test_existing_foreign_draft_prevents_duplicate_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            gmail = Gmail(Path(temp))
            gmail.get_thread = lambda tid: {"id":"t1", "messages":[message(), message("d1", labels=["DRAFT"])]}
            with self.assertRaisesRegex(ServiceError, "bereits"):
                gmail.save_draft({**row(), "draft":"Antwort", "draft_id":""}, "team@example.com")

    def test_conversation_changed_before_publish_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            gmail = Gmail(Path(temp))
            gmail.get_thread = lambda tid: {"id":"t1", "messages":[message("new-message")]}
            with self.assertRaisesRegex(ServiceError, "geändert"):
                gmail.save_draft({**row(), "draft":"Antwort", "draft_id":""}, "team@example.com")

    def test_no_send_delete_or_label_api_surface(self):
        with tempfile.TemporaryDirectory() as temp:
            gmail = Gmail(Path(temp))
            for endpoint, method in [("/drafts/send", "POST"), ("/messages/send", "POST"), ("/drafts/x", "DELETE"), ("/threads/x", "POST")]:
                with self.subTest(endpoint=endpoint, method=method), self.assertRaises(ValueError):
                    gmail.api(endpoint, method)

    def test_pkce_state_is_required_and_single_use(self):
        with tempfile.TemporaryDirectory() as temp:
            gmail = Gmail(Path(temp))
            gmail.configure({"installed":{"client_id":"test.apps.googleusercontent.com", "client_secret":"test"}})
            url = gmail.begin_auth("http://127.0.0.1:8765")
            self.assertIn("code_challenge_method=S256", url)
            with self.assertRaises(ValueError):
                gmail.complete_auth({"state":"wrong", "code":"code"})
            self.assertIsNone(gmail.pending)

    def test_missing_scope_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            gmail = Gmail(Path(temp), request=lambda *args, **kwargs: {"access_token":"test", "scope":SCOPES.split()[0]})
            gmail.configure({"installed":{"client_id":"test.apps.googleusercontent.com"}})
            gmail.begin_auth("http://127.0.0.1:8765")
            state = gmail.pending["state"]
            with self.assertRaisesRegex(ServiceError,"beide"):
                gmail.complete_auth({"state":state,"code":"code"})
            self.assertFalse(gmail.connected())


class ModelTests(unittest.TestCase):
    def test_manual_draft_cannot_be_silently_skipped_but_automatic_processing_can(self):
        chats = []
        def request(url, method, data, **kwargs):
            if url.endswith("/show"):
                return {"model_info": {"architecture": "qwen3"}}
            chats.append(data)
            answer = ({"action": "skip", "body": "", "notes": []}
                      if "skip" in data["format"]["properties"]["action"]["enum"]
                      else {"action": "review", "body": "Vielen Dank für die Information.", "notes": ["Empfänger prüfen"]})
            return {"message": {"content": json.dumps(answer)}}
        with tempfile.TemporaryDirectory() as temp:
            settings = Store(temp).settings()
            model = LocalModel(request)
            manual = model.generate(row(), settings, [], [], allow_skip=False)
            automatic = model.generate(row(), settings, [], [], allow_skip=True)
        self.assertEqual(manual["status"], "review")
        self.assertTrue(manual["draft"])
        self.assertNotIn("skip", chats[0]["format"]["properties"]["action"]["enum"])
        self.assertEqual(chats[0]["format"]["properties"]["body"]["minLength"], 1)
        self.assertIn("ausdrücklich einen Antwortentwurf", chats[0]["messages"][0]["content"])
        self.assertEqual(automatic["status"], "skipped")
        self.assertEqual(automatic["draft"], "")
        self.assertTrue(automatic["notes"])
        self.assertIn("skip", chats[1]["format"]["properties"]["action"]["enum"])
        self.assertNotIn("minLength", chats[1]["format"]["properties"]["body"])

    def test_manual_skip_response_is_reported_as_an_error(self):
        for action in ("skip", "review"):
            with self.subTest(action=action):
                def request(url, *args, **kwargs):
                    if url.endswith("/show"):
                        return {"model_info": {"architecture": "qwen3"}}
                    return {"message": {"content": json.dumps({"action": action, "body": "", "notes": []})}}
                with tempfile.TemporaryDirectory() as temp:
                    with self.assertRaisesRegex(ServiceError, "keinen verwendbaren Entwurf"):
                        LocalModel(request).generate(row(), Store(temp).settings(), [], [], allow_skip=False)

    def test_invented_signature_is_removed_and_configured_signature_used_once(self):
        text,issues=prepare_draft("Guten Tag,\n\nvielen Dank.\n\nFreundliche Grüße\nDas erfundene Team", "Alex · Mein Betrieb", "")
        self.assertNotIn("erfundene",text)
        self.assertEqual(text.count("Alex · Mein Betrieb"),1)
        text,_=prepare_draft(text,"Alex · Mein Betrieb","")
        self.assertEqual(text.count("Alex · Mein Betrieb"),1)

    def test_unconfirmed_prices_and_example_services_require_review(self):
        _,issues=prepare_draft("Das kostet 500 Euro, beispielsweise für SEO.","","Beratung kostet 80 Euro.")
        self.assertEqual(len(issues),2)
        _,issues=prepare_draft("Das kostet 80,00 Euro.","","Beratung kostet 80 EUR.")
        self.assertEqual(issues,[])

    def test_failed_fact_check_cannot_mark_draft_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            settings=Store(temp).settings()
            def request(url,method,data,**kwargs):
                if url.endswith("/show"):return {"model_info":{"architecture":"qwen3"}}
                if "approved" in data["format"].get("properties",{}):return {"message":{"content":'{"approved":false,"issues":["Nicht bestätigte Zusage"]}'}}
                return {"message":{"content":'{"action":"draft","body":"Unsere Zusage.","notes":[]}'}}
            result=LocalModel(request).generate(row(),settings,[],[])
            self.assertEqual(result["status"],"review")
            self.assertIn("Nicht bestätigte Zusage",result["notes"])

    def test_cloud_alias_is_blocked_before_any_prompt_is_sent(self):
        calls = []
        def request(url, *args, **kwargs):
            calls.append(url)
            return {"remote_host":"https://ollama.com", "model_info":{"general.architecture":"qwen3"}}
        model = LocalModel(request)
        with self.assertRaisesRegex(ServiceError, "Cloud"):
            model.validate("innocent-alias")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith("/api/show"))

    def test_malformed_model_output_is_not_saved_as_a_draft(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Store(temp).settings()
            def request(url, *args, **kwargs):
                return {"model_info":{"architecture":"qwen3"}} if url.endswith("/show") else {"message":{"content":"not json"}}
            with self.assertRaisesRegex(ServiceError, "verwendbaren"):
                LocalModel(request).generate(row(), settings, [], [])

    def test_generation_uses_local_endpoint_and_separates_internal_notes(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            settings = Store(temp).settings()
            def request(url, method, data, **kwargs):
                calls.append((url,data))
                if url.endswith("/show"):
                    return {"model_info":{"architecture":"qwen3"}}
                return {"message":{"content":json.dumps({"action":"review", "body":"Guten Tag!", "notes":["Preis bitte prüfen"]})}, "done_reason":"stop"}
            result = LocalModel(request).generate(row(), settings, [{"title":"Preise","content":"Beratung 80 Euro"}], [])
        self.assertEqual(result["draft"], "Guten Tag!")
        self.assertNotIn("Preis bitte prüfen", result["draft"])
        self.assertEqual(result["status"], "review")
        self.assertTrue(all(url.startswith("http://127.0.0.1:11434/") for url,_ in calls))
        chat = calls[-1][1]
        self.assertFalse(chat["stream"])
        self.assertEqual(chat["options"]["num_ctx"],4096)
        self.assertEqual(result["sources"],["Preise"])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(self.temp.name)
        self.app.store.save_settings({"company":"Testbetrieb", "description":"Beratung"})

    def tearDown(self):
        self.app.stop.set()
        self.app.changed.set()
        for thread in self.app.background:
            thread.join(timeout=3)
        self.temp.cleanup()

    def test_examples_cannot_be_published_to_gmail(self):
        with self.assertRaises(ValueError):
            self.app.publish("demo-angebot")

    def test_unconfigured_automatic_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            self.app.save_settings({"automatic":True})

    def test_manual_click_creates_a_local_draft_for_a_skipped_notification(self):
        app = self.app
        notification = parse_thread({"id": "notification", "messages": [message(sender="noreply@example.com")]}, "team@example.com")
        self.assertEqual(notification["status"], "skipped")
        app.store.upsert_thread(notification)
        app.store.begin_onboarding("team@example.com", "100")
        app.store.complete_onboarding("team@example.com", {})
        app.store.save_settings({"automatic": True})
        choices = []
        def request(url, method, data, **kwargs):
            if url.endswith("/show"):
                return {"model_info": {"architecture": "qwen3"}}
            choices.extend(data["format"]["properties"]["action"]["enum"])
            return {"message": {"content": '{"action":"review","body":"Danke für Ihre Nachricht.","notes":["Empfänger prüfen"]}'}}
        app.model = LocalModel(request)
        published = []
        app.publish = lambda tid: published.append(tid)
        completed = threading.Event()
        original_finish = app.store.finish_job
        def finish(job_id):
            original_finish(job_id)
            completed.set()
        app.store.finish_job = finish
        app.enqueue("notification")
        worker = threading.Thread(target=app.worker, daemon=True)
        app.background.append(worker)
        worker.start()
        self.assertTrue(completed.wait(2))
        result = app.store.thread("notification")
        self.assertEqual(result["status"], "review")
        self.assertTrue(result["draft"])
        self.assertNotIn("skip", choices)
        self.assertEqual(published, [])

    def test_automatic_skip_does_not_claim_that_a_draft_was_created(self):
        app = self.app
        app.store.upsert_thread(row())
        app.store.save_settings({"automatic": True})
        allow_skip_values = []
        class Model:
            def generate(_, *args, allow_skip):
                allow_skip_values.append(allow_skip)
                return {"status": "skipped", "draft": "", "notes": [], "error": ""}
        app.model = Model()
        completed = threading.Event()
        original_finish = app.store.finish_job
        def finish(job_id):
            original_finish(job_id)
            completed.set()
        app.store.finish_job = finish
        app.store.queue("t1", automatic=True)
        worker = threading.Thread(target=app.worker, daemon=True)
        app.background.append(worker)
        worker.start()
        self.assertTrue(completed.wait(2))
        self.assertEqual(allow_skip_values, [True])
        self.assertEqual(app.store.thread("t1")["draft"], "")
        events = [e["message"] for e in app.store.events()]
        self.assertTrue(any("übersprungen" in text for text in events))
        self.assertFalse(any("Antwortentwurf wurde erstellt" in text for text in events))

    def test_worker_creates_local_draft_and_respects_pause(self):
        self.app.store.upsert_thread(row())
        self.app.store.save_settings({"paused":True})
        done = threading.Event()
        class Model:
            def generate(_, *args, **kwargs):
                done.set()
                return {"status":"ready", "draft":"Meine Antwort", "notes":[], "sources":[], "duration":1, "generated_by":"local-test", "processed_id":"m1", "error":""}
        self.app.model = Model()
        self.app.store.queue("t1")
        worker = threading.Thread(target=self.app.worker,daemon=True)
        self.app.background.append(worker)
        worker.start()
        self.assertFalse(done.wait(.08))
        self.app.store.save_settings({"paused":False})
        self.app.changed.set()
        self.assertTrue(done.wait(2))
        self.app.stop.set()
        self.app.changed.set()
        worker.join(3)
        self.assertEqual(self.app.store.thread("t1")["draft"],"Meine Antwort")

    def test_invalid_settings_and_remote_model_names_are_rejected(self):
        for data in [{"context_size":100000}, {"model":"qwen:cloud"}, {"automatic":"true"}, {"sync_seconds":1}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.app.save_settings(data)

    def test_disconnect_removes_only_gmail_records(self):
        self.app.store.upsert_thread(row())
        self.app.store.save_settings({"gmail_email":"team@example.com", "history_id":"123"},internal=True)
        self.app.disconnect()
        self.assertIsNone(self.app.store.thread("t1"))
        self.assertIsNotNone(self.app.store.thread("demo-angebot"))
        self.assertNotIn("history_id",self.app.store.settings())

    def test_repeated_sync_does_not_duplicate_messages_or_jobs(self):
        class Mailbox:
            def connected(_):return True
            def api(_,path):return {"emailAddress":"team@example.com","historyId":"100"}
            def list_threads(_,query):return iter(["t1"])
            def get_thread(_,tid):return {"id":"t1","messages":[message()]}
            def changed_threads(_,history):return {"t1"},"101"
        self.app.gmail=Mailbox()
        self.app.store.save_settings({"automatic":True})
        self.app.store.begin_onboarding("team@example.com","100")
        self.app.store.complete_onboarding("team@example.com",{})
        with self.app.store.connection() as db:
            db.execute("UPDATE onboarding SET started=0 WHERE account='team@example.com'")
        self.app.sync()
        self.app.sync()
        self.assertEqual(len([t for t in self.app.store.threads() if t["source"]=="gmail"]),1)
        self.assertIsNotNone(self.app.store.claim())
        self.assertIsNone(self.app.store.claim())

    def test_automatic_review_stays_local_but_ready_draft_is_exported(self):
        completed=threading.Event()
        app=self.app
        app.store.upsert_thread(row())
        app.store.save_settings({"automatic":True})
        class Model:
            def generate(_, *args, **kwargs):
                return {"status":"review", "draft":"Zu prüfen", "notes":["Entscheidung fehlt"], "sources":[], "duration":1, "generated_by":"local-test", "processed_id":"m1", "error":""}
        app.model=Model()
        published=[]
        app.publish=lambda thread_id: published.append(thread_id)
        original_finish=app.store.finish_job
        def finish(job_id):
            original_finish(job_id)
            completed.set()
        app.store.finish_job=finish
        app.store.queue("t1",automatic=True)
        worker=threading.Thread(target=app.worker,daemon=True)
        app.background.append(worker)
        worker.start()
        self.assertTrue(completed.wait(2))
        self.assertEqual(published,[])
        completed.clear()
        app.model.generate=lambda *args, **kwargs: {"status":"ready", "draft":"Fertiger Entwurf", "notes":[], "sources":[], "duration":1, "generated_by":"local-test", "processed_id":"m1", "error":""}
        app.store.queue("t1",automatic=True)
        app.changed.set()
        self.assertTrue(completed.wait(2))
        self.assertEqual(published,["t1"])


if __name__ == "__main__":
    unittest.main()
