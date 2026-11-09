import base64
import http.client
import json
import tempfile
import threading
import time
import unittest
from email import policy
from email.parser import BytesParser
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from mailresponder.gmail import API, fingerprint, parse_thread
from mailresponder.net import ServiceError
from mailresponder.server import handler_for
from mailresponder.store import Store
from mailresponder.service import Application


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = Application(cls.temp.name)
        cls.app.health_cache = ({"online":False,"models":[],"selected_ready":False,"error":"Test"},float('inf'))
        cls.server = ThreadingHTTPServer(("127.0.0.1",0),handler_for(cls.app,"test-local-token"))
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)
        cls.temp.cleanup()

    def call(self,path,method="GET",data=None,token="test-local-token",origin=None,host=None):
        connection=http.client.HTTPConnection("127.0.0.1",self.port,timeout=5)
        headers={"X-Local-Token":token,"Content-Type":"application/json"}
        if origin:headers["Origin"]=origin
        if host:headers["Host"]=host
        connection.request(method,path,json.dumps(data) if data is not None else None,headers)
        response=connection.getresponse()
        status,body,headers=response.status,response.read(),dict(response.getheaders())
        connection.close()
        return status,body,headers

    def test_index_serves_local_assets_and_token(self):
        status,body,headers=self.call("/")
        self.assertEqual(status,200)
        self.assertIn(b"test-local-token",body)
        self.assertIn("frame-ancestors 'none'",headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"],"no-store")

    def test_api_requires_local_token(self):
        self.assertEqual(self.call("/api/state",token="")[0],403)

    def test_cross_origin_and_rebinding_are_blocked(self):
        self.assertEqual(self.call("/api/settings","POST",{"company":"intruder"},origin="https://attacker.test")[0],403)
        self.assertEqual(self.call("/",host="attacker.test")[0],403)

    def test_traversal_cannot_read_database(self):
        for path in ("/../.data/google-auth.json","/%2e%2e/.data/google-auth.json","/mailresponder/server.py"):
            with self.subTest(path=path):self.assertEqual(self.call(path)[0],404)

    def test_profile_and_knowledge_roundtrip(self):
        self.assertEqual(self.call("/api/settings","POST",{"company":"Mein Betrieb"})[0],200)
        status,body,_=self.call("/api/knowledge","POST",{"title":"Öffnungszeiten","content":"Montag bis Freitag"})
        self.assertEqual(status,200)
        doc_id=json.loads(body)["id"]
        state=json.loads(self.call("/api/state")[1])
        self.assertEqual(state["settings"]["company"],"Mein Betrieb")
        self.assertTrue(any(d["id"]==doc_id for d in state["documents"]))
        self.assertNotIn("access_token",state["gmail"])

    def test_local_edit_does_not_require_a_model_or_gmail(self):
        status,_,_=self.call("/api/thread/edit","POST",{"id":"demo-angebot","text":"Meine eigene Antwort"})
        self.assertEqual(status,200)
        state=json.loads(self.call("/api/state")[1])
        thread=next(t for t in state["threads"] if t["id"]=="demo-angebot")
        self.assertTrue(thread["user_edited"])
        self.assertEqual(thread["draft"],"Meine eigene Antwort")

    def test_unconfirmed_send_and_sample_export_rejected(self):
        self.assertEqual(self.call("/api/thread/send","POST",{})[0],400)
        self.assertEqual(self.call("/api/thread/publish","POST",{"id":"demo-angebot"})[0],400)

    def test_rich_send_confirmation_and_delivery_guard(self):
        account = "team@example.test"
        config = {"access_token": "local-fixture-only", "expires_at": time.time() + 3600}
        original_settings = self.app.store.settings
        raw_message = {
            "id": "incoming", "internalDate": "1900000000000", "labelIds": ["INBOX"],
            "payload": {"mimeType": "text/plain", "body": {"data": "QW5mcmFnZQ=="}, "headers": [
                {"name": "From", "value": "Alex <source@example.test>"},
                {"name": "Reply-To", "value": "reply@example.test"},
                {"name": "Subject", "value": "Rückfrage"},
                {"name": "Message-ID", "value": "<incoming@example.test>"},
            ]},
        }
        for kind in ("new", "saved", "uncertain"):
            with self.subTest(kind=kind):
                thread_id = "test-" + kind
                raw_thread = {"id": thread_id, "messages": [raw_message]}
                self.app.store.upsert_thread(parse_thread(raw_thread, account))
                remote = {
                    "mimeType": "multipart/alternative", "headers": [],
                    "parts": [{"mimeType": "text/html", "body": {"data": "PGI-QWx0PC9iPg0K"}}],
                }
                if kind == "saved":
                    self.app.store.update_thread(thread_id, draft_id="remote",
                                                 remote_hash="v2:" + fingerprint(remote, normalize_html=True))
                writes = []

                def gmail(endpoint, method="GET", data=None, **kwargs):
                    if method == "GET" and endpoint == API + "/threads/" + thread_id + "?format=full":
                        return raw_thread
                    if method == "GET" and endpoint == API + "/drafts/remote?format=full" and kind == "saved":
                        return {"message": {"payload": remote}}
                    if method != "POST":
                        self.fail(f"Unexpected Gmail method {method}")
                    writes.append((endpoint, data))
                    if kind == "uncertain":
                        raise ServiceError("Keine Antwort von Gmail.")
                    return {"id": "sent-id"}

                with (patch.object(self.app.gmail, "read", return_value=config),
                      patch.object(self.app.gmail, "request", side_effect=gmail),
                      patch.object(self.app.gmail, "sleep"),
                      patch.object(self.app.store, "settings", side_effect=lambda: {**original_settings(), "gmail_email": account})):
                    content = {"id": thread_id, "html": '<p><strong onclick="bad()">Danke</strong>!</p><script>bad()</script>'}
                    def post(path, value, expected):
                        status, body, _ = self.call(path, "POST", value)
                        self.assertEqual(status, expected, body)
                        return json.loads(body)

                    revision = post("/api/thread/edit", content, 200)["revision"]
                    prepare = "/api/thread/send/prepare"
                    send = "/api/thread/send"
                    confirmation = post(prepare, {"id": thread_id, "revision": revision}, 200)
                    self.assertEqual(confirmation["recipient"], "reply@example.test")
                    self.assertEqual(confirmation["subject"], "Rückfrage")
                    self.assertEqual(writes, [])
                    revision = post("/api/thread/edit", {**content, "revision": revision}, 200)["revision"]
                    post(send, {"id": thread_id, "confirmation": confirmation["confirmation"]}, 409)
                    self.assertEqual(writes, [])
                    confirmation = post(prepare, {"id": thread_id, "revision": revision}, 200)
                    request = {"id": thread_id, "confirmation": confirmation["confirmation"]}
                    post(send, request, 409 if kind == "uncertain" else 200)
                    post(send, request, 400)
                    self.assertEqual(len(writes), 1)
                    endpoint, body = writes[0]
                    if kind == "saved":
                        self.assertEqual(endpoint, API + "/drafts/send")
                        self.assertEqual(body["id"], "remote")
                        body = body["message"]
                    else:
                        self.assertEqual(endpoint, API + "/messages/send")
                    self.assertEqual(body["threadId"], thread_id)
                    email = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(body["raw"]))
                    self.assertEqual(email["To"], "reply@example.test")
                    self.assertEqual(email["In-Reply-To"], "<incoming@example.test>")
                    self.assertEqual(email.get_body(("plain",)).get_content().strip(), "Danke!")
                    markup = email.get_body(("html",)).get_content()
                    self.assertIn("<strong>Danke</strong>", markup)
                    self.assertNotIn("bad()", markup)
                    row = self.app.store.thread(thread_id)
                    if kind == "uncertain":
                        self.assertEqual(row["status"], "send_uncertain")
                        self.assertEqual(row["draft"], "Danke!")
                        post(prepare, {"id": thread_id, "revision": row["revision"]}, 409)
                    else:
                        self.assertEqual(row["status"], "sent")
                        self.assertEqual(row["draft_id"], "")

    def test_existing_draft_and_interrupted_send_survive_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            with store.connection() as db:
                db.execute("ALTER TABLE threads DROP COLUMN draft_html")
                db.execute("""INSERT INTO threads(id,source,sender,sender_name,subject,body,messages,
                              received,latest_id,headers,draft,status) VALUES
                              ('fixture','gmail','a@example.test','A','Betreff','Text','[]',1,'m','{}','Entwurf','sending')""")
            row = Store(directory).thread("fixture")
            self.assertEqual(row["draft"], "Entwurf")
            self.assertEqual(row["draft_html"], "")
            self.assertEqual(row["status"], "send_uncertain")
            self.assertIn("nicht eindeutig", row["error"])


if __name__=="__main__":unittest.main()
