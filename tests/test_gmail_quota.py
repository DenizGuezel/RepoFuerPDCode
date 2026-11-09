import io
import json
import tempfile
import time
import unittest
import urllib.error
from email.message import Message
from email.utils import formatdate
from pathlib import Path
from unittest.mock import patch

from mailresponder.gmail import API, Gmail
from mailresponder.net import ServiceError, request_json


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.waits = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.gmail = Gmail(Path(self.temp.name), clock=self.clock, sleep=self.clock.sleep)
        self.gmail.access_token = lambda: "test-token"

    def tearDown(self):
        self.temp.cleanup()

    def test_import_paces_full_bodies_under_current_per_minute_quota(self):
        calls = []
        self.gmail.request = lambda *a, **kw: calls.append(self.clock()) or {}
        for _ in range(150):
            self.gmail.get_message("test")
        self.assertTrue(all(b-a >= .75 for a, b in zip(calls, calls[1:])))
        # Any sliding minute, including its first request, stays below Google's 6,000 units.
        self.assertLessEqual(max(sum(start <= at < start+60 for at in calls)*60 for start in calls), 4800)
        self.assertEqual(self.gmail.quota_cost("/threads/test?format=full", "GET"), 120)

    def test_rate_rejection_backs_off_and_resumes_same_message(self):
        calls = []
        def request(*args, **kwargs):
            calls.append(self.clock())
            if len(calls) < 4:
                raise ServiceError("quota", 403, rate_limited=True)
            return {"id": "same"}
        self.gmail.request = request
        self.assertEqual(self.gmail.get_message("same"), {"id": "same"})
        self.assertEqual(len(calls), 4)
        self.assertGreaterEqual(calls[1]-calls[0], 1)
        self.assertGreaterEqual(calls[2]-calls[1], 2)
        self.assertGreaterEqual(calls[3]-calls[2], 4)

    def test_retry_after_is_respected_for_rejected_draft(self):
        calls = []
        def request(*args, **kwargs):
            calls.append(self.clock())
            if len(calls) == 1:
                raise ServiceError("quota", 429, rate_limited=True, retry_after=12)
            return {"id": "draft"}
        self.gmail.request = request
        self.assertEqual(self.gmail.api("/drafts", "POST", {}), {"id": "draft"})
        self.assertGreaterEqual(calls[1]-calls[0], 12)

    def test_long_cooldown_prevents_new_requests_across_poll_attempts(self):
        calls = []
        def request(*args, **kwargs):
            calls.append(self.clock())
            if len(calls) == 1:
                raise ServiceError("quota", 429, rate_limited=True, retry_after=3600)
            return {}
        self.gmail.request = request
        with self.assertRaises(ServiceError):
            self.gmail.get_message("same")
        self.clock.now += 120
        with self.assertRaises(ServiceError):
            self.gmail.get_message("same")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.clock.waits, [])
        self.clock.now += 3480
        self.gmail.get_message("same")
        self.assertEqual(len(calls), 2)

    def test_persistent_quota_error_has_bounded_retries(self):
        calls = []
        def request(*args, **kwargs):
            calls.append(self.clock())
            raise ServiceError("quota", 403, rate_limited=True)
        self.gmail.request = request
        with self.assertRaises(ServiceError):
            self.gmail.get_message("same")
        self.assertEqual(len(calls), 7)

    def test_permission_errors_and_uncertain_writes_are_never_retried(self):
        for status in (403, 500, 0):
            with self.subTest(status=status):
                calls = []
                def request(*args, **kwargs):
                    calls.append(args)
                    raise ServiceError("failure", status)
                self.gmail.request = request
                with self.assertRaises(ServiceError):
                    self.gmail.api("/drafts", "POST", {})
                self.assertEqual(len(calls), 1)

    def test_expired_auth_refreshes_once_before_quota_retry(self):
        del self.gmail.access_token
        self.gmail.write({"access_token": "old", "expires_at": time.time()+3600,
                          "refresh_token": "refresh", "client_id": "test"})
        calls, refreshed = [], []
        def request(url, *args, **kwargs):
            if url.endswith("/token"):
                refreshed.append(url)
                return {"access_token": "new", "expires_in": 3600}
            calls.append(kwargs["headers"]["Authorization"])
            if len(calls) == 1:
                raise ServiceError("expired", 401)
            if len(calls) == 2:
                raise ServiceError("quota", 403, rate_limited=True)
            return {}
        self.gmail.request = request
        self.gmail.get_message("same")
        self.assertEqual(len(refreshed), 1)
        self.assertEqual(calls, ["Bearer old", "Bearer new", "Bearer new"])


class ErrorParsingTests(unittest.TestCase):
    def error(self, status, reason=None, retry_after=None, payload=None, url=API+"/messages/test"):
        headers = Message()
        if retry_after is not None:
            headers["Retry-After"] = retry_after
        body = payload if payload is not None else json.dumps({
            "error": {"message": "private upstream contents", "errors": [{"reason": reason}]}}).encode()
        error = urllib.error.HTTPError(url, status, "upstream", headers, io.BytesIO(body))
        with patch("urllib.request.OpenerDirector.open", side_effect=error):
            with self.assertRaises(ServiceError) as caught:
                request_json(url)
        self.assertNotIn("private upstream contents", str(caught.exception))
        return caught.exception

    def test_known_google_quota_reasons_are_recognized_without_leaking_payload(self):
        for reason in ("rateLimitExceeded", "userRateLimitExceeded"):
            self.assertTrue(self.error(403, reason).rate_limited)
        self.assertFalse(self.error(403, "insufficientPermissions").rate_limited)
        self.assertFalse(self.error(403, payload=b"not json").rate_limited)
        self.assertFalse(self.error(403, payload=b'{"error":null}').rate_limited)

    def test_retry_after_accepts_seconds_and_http_date(self):
        self.assertEqual(self.error(429, retry_after="17").retry_after, 17)
        with patch("mailresponder.net.time.time", return_value=1000000):
            error = self.error(429, retry_after=formatdate(1000120, usegmt=True))
        self.assertEqual(error.retry_after, 120)
        self.assertEqual(self.error(429, retry_after="invalid").retry_after, 0)


if __name__ == "__main__":
    unittest.main()
