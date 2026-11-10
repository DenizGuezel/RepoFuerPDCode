import http.client
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
from email.message import Message
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from mailresponder.gmail import API, SCOPES
from mailresponder.net import ServiceError, request_json
from mailresponder.server import handler_for
from mailresponder.service import Application


class OAuthErrorTests(unittest.TestCase):
    def rejection(self, reason, *, url="https://oauth2.googleapis.com/token", payload=None):
        body = payload if payload is not None else json.dumps({
            "error": reason, "error_description": "private upstream data and credentials"}).encode()
        error = urllib.error.HTTPError(url, 400, "Bad Request", Message(), io.BytesIO(body))
        with patch("urllib.request.OpenerDirector.open", side_effect=error):
            with self.assertRaises(ServiceError) as caught:
                request_json(url, "POST", {})
        self.assertEqual(caught.exception.status, 400)
        self.assertNotIn("private upstream", str(caught.exception))
        return str(caught.exception)

    def test_expired_grant_explains_how_to_sign_in_again(self):
        message = self.rejection("invalid_grant")
        self.assertIn("abgelaufen", message)
        self.assertIn("Erneut anmelden", message)

    def test_client_configuration_error_is_not_reported_as_an_expired_grant(self):
        self.assertIn("OAuth-Konfiguration", self.rejection("invalid_client"))

    def test_untrusted_or_malformed_errors_stay_generic(self):
        for payload in (b'null', b'[]', b'not json', b'{"error":{}}', b'{"error":"private upstream data"}'):
            with self.subTest(payload=payload):
                self.assertEqual(self.rejection(None, payload=payload), "Google hat die Anfrage abgelehnt (Status 400).")

    def test_gmail_bad_request_does_not_incorrectly_request_reauthentication(self):
        self.assertEqual(self.rejection("invalid_grant", url=API+"/drafts"),
                         "Google hat die Anfrage abgelehnt (Status 400).")


class ReconnectTests(unittest.TestCase):
    account = "team@example.test"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Application(self.temp.name)
        self.old_credentials = {"client_id": "test.apps.googleusercontent.com", "client_secret": "test-secret",
                                "access_token": "expired-access", "refresh_token": "expired-refresh", "expires_at": 0}
        self.app.gmail.write(self.old_credentials)
        self.app.store.save_settings({"gmail_email": self.account, "history_id": "cursor", "last_sync": 1234}, internal=True)
        self.app.store.begin_onboarding(self.account, "cursor")
        self.app.store.complete_onboarding(self.account, {"company": "Testbetrieb"})
        self.app.store.record_mail_page(self.account, [{"id": "archived", "threadId": "t1"}], "")
        # The saved complete marker must remain unchanged throughout renewal.
        self.app.store.onboarding_update(self.account, stage="complete")
        self.app.store.upsert_thread({
            "id": "t1", "source": "gmail", "account": self.account, "sender": "contact@example.test",
            "sender_name": "Contact", "subject": "Question", "body": "Incoming text", "received": 1,
            "latest_id": "m1", "messages": [], "headers": {},
        })
        self.app.store.update_thread("t1", draft="My existing draft", draft_html="<p>My existing draft</p>", status="ready")
        self.snapshot = self.saved_data()
        self.profile_account = self.account
        self.profile_failure = False
        self.new_token = {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600, "scope": SCOPES}
        self.syncs = []
        self.app.start_sync = lambda: self.syncs.append(True)

        def request(url, method="GET", data=None, **kwargs):
            if url == "https://oauth2.googleapis.com/token":
                return self.new_token
            self.assertEqual(url, API+"/profile")
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer new-access")
            if self.profile_failure:
                raise ServiceError("Profile temporarily unavailable", 503)
            return {"emailAddress": self.profile_account}

        self.app.gmail.request = request
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.app, "local-test-token"))
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)
        self.temp.cleanup()

    def saved_data(self):
        with self.app.store.connection() as db:
            return {table: [tuple(row) for row in db.execute("SELECT * FROM "+table+" ORDER BY 1,2")]
                    for table in ("settings", "onboarding", "mail_archive", "threads", "jobs")}

    def call(self, path, method="POST"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request(method, path, "{}" if method == "POST" else None,
                           {"X-Local-Token": "local-test-token", "Content-Type": "application/json"})
        response = connection.getresponse()
        status, body = response.status, response.read()
        connection.close()
        return status, body

    def begin(self):
        status, body = self.call("/api/gmail/reconnect")
        self.assertEqual(status, 200)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(json.loads(body)["url"]).query)
        self.assertEqual(query["login_hint"], [self.account])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        return "/oauth/callback?"+urllib.parse.urlencode({"state": query["state"][0], "code": "new-code"})

    def test_renewal_keeps_messages_drafts_profile_and_sync_progress(self):
        callback = self.begin()
        self.assertEqual(self.call(callback, "GET")[0], 303)
        self.assertEqual(self.saved_data(), self.snapshot)
        self.assertEqual(self.app.gmail.read()["refresh_token"], "new-refresh")
        self.assertEqual(self.syncs, [True])
        # The authorization response is single-use.
        self.assertEqual(self.call(callback, "GET")[0], 400)

    def test_other_account_cannot_replace_credentials_or_local_data(self):
        self.profile_account = "other@example.test"
        status, body = self.call(self.begin(), "GET")
        self.assertEqual(status, 400)
        self.assertIn("bereits verbundenen", body.decode())
        self.assertEqual(self.app.gmail.read(), self.old_credentials)
        self.assertEqual(self.saved_data(), self.snapshot)
        self.assertEqual(self.syncs, [])

    def test_case_variation_keeps_the_original_account_and_onboarding_key(self):
        self.profile_account = self.account.upper()
        self.assertEqual(self.call(self.begin(), "GET")[0], 303)
        self.assertEqual(self.saved_data(), self.snapshot)

    def test_unverified_profile_does_not_replace_credentials(self):
        self.profile_failure = True
        self.assertEqual(self.call(self.begin(), "GET")[0], 400)
        self.assertEqual(self.app.gmail.read(), self.old_credentials)
        self.assertEqual(self.saved_data(), self.snapshot)

    def test_missing_scope_does_not_replace_credentials(self):
        self.new_token["scope"] = SCOPES.split()[0]
        self.assertEqual(self.call(self.begin(), "GET")[0], 400)
        self.assertEqual(self.app.gmail.read(), self.old_credentials)
        self.assertEqual(self.saved_data(), self.snapshot)

    def test_renewal_requires_an_existing_account(self):
        self.app.gmail.write({"client_id": "test.apps.googleusercontent.com"})
        self.assertEqual(self.call("/api/gmail/reconnect")[0], 400)


if __name__ == "__main__":
    unittest.main()
