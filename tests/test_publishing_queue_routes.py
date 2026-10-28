"""HTTP contract tests for the local publishing queue routes.

These tests mock the queue adapter: they verify routing and origin checks only,
without touching real queue rows, accounts, browsers or platform sessions.
"""
from __future__ import annotations

import http.client
import json
import threading
import unittest
from unittest.mock import patch

from app import core, server, work_publishing


class PublishingQueueRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.http.server_port
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=3)

    def request(self, path, method="GET", headers=None, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        headers = {"Content-Type": "application/json", **(headers or {})}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read() or b"{}")
        connection.close()
        return result

    def test_preview_and_queue_get_routes(self):
        with patch.object(work_publishing, "preview", return_value={"work_id": "w1", "media": []}) as preview, \
             patch.object(work_publishing, "snapshot", return_value={"jobs": [], "accounts": [], "max_uploads": 2}) as snapshot:
            status, body = self.request("/api/publishing/work?work_id=w1")
            self.assertEqual(status, 200)
            self.assertEqual(body["work_id"], "w1")
            preview.assert_called_once_with("w1")
            status, body = self.request("/api/publishing/queue")
            self.assertEqual(status, 200)
            self.assertEqual(body["max_uploads"], 2)
            snapshot.assert_called_once_with()

    def test_action_is_routed_without_running_real_queue(self):
        result = {"jobs": [{"id": "j1", "state": "queued"}]}
        with patch.object(work_publishing, "dispatch", return_value=result) as dispatch:
            status, body = self.request("/api/publishing/action", "POST", payload={
                "action": "enqueue_work", "arguments": {"work_id": "w1", "account_ids": ["a1"]}})
        self.assertEqual(status, 200)
        self.assertEqual(body, result)
        dispatch.assert_called_once_with("enqueue_work", {"work_id": "w1", "account_ids": ["a1"]})

    def test_validation_error_is_http_400(self):
        with patch.object(work_publishing, "dispatch", side_effect=core.ValidationError("缺少作品")):
            status, body = self.request("/api/publishing/action", "POST", payload={"action": "enqueue_work", "arguments": {}})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "缺少作品")

    def test_cross_origin_is_rejected_for_queue_routes(self):
        headers = {"Origin": "https://example.org"}
        status, body = self.request("/api/publishing/queue", headers=headers)
        self.assertEqual(status, 403)
        self.assertIn("跨站", body["error"])


if __name__ == "__main__":
    unittest.main()
