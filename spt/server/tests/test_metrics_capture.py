"""SPT 读数据: matching what the Mac app read to works, append-only writes, the request queue."""
from __future__ import annotations
import datetime as dt
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from .. import metrics_capture as capture
from ..api import Server
from ..indexer import Indexer
from ..parsing import parse_records
from .support import fixture_config, populate, write

SHOES = "运营/2026-10-22-示例创作者-小狗闻鞋"
CLOTHES = "运营/2026-10-20-示例创作者-收小衣服"
SHOES_RECORD = ("# 第58篇发布记录\n\n当前采用：V1\n平台：rednote\n"
                "发布时间：2026-10-23T00:13:19.637-07:00\n"
                "发布时间依据：唯一点击时间\n"
                "作品链接：https://www.rednote.com/discovery/item/000000000000000000000065\n"
                "D1：2026-10-24T00:13:19.637-07:00\n")
CLOTHES_RECORD = ("# 当前采用：V1\n"
                  "- 小红书 https://www.rednote.com/user/profile/x 2026-10-20 17:57:45 PDT；已发布\n")
ACCOUNT = {"id": "cc4add2af42d93cf17b1", "platform": "xiaohongshu", "name": "示例创作者",
           "brand": "示例创作者"}
AT = "2026-10-23T16:00:00Z"


def read(**changes: Any) -> dict[str, Any]:
    value = {"account": ACCOUNT, "status": "done", "observed_at": AT,
             "header": ["创作服务平台", "示例创作者"],
             "notes": [
                 {"title": "他叫了半天，小狗只顾闻我的鞋", "time": "2026-10-23 15:13",
                  "note_id": "000000000000000000000065",
                  "numbers": ["48", "0", "3", "2", "0"]},
                 {"title": "收小衣服，最后给我留了一件", "time": "2026-10-21 08:57",
                  "numbers": ["1,087", "3", "12", "1", "0"]},
                 {"title": "没有这篇作品", "time": "2026-10-19 08:00",
                  "numbers": ["5", "0", "0", "0", "0"]},
                 {"title": "还在审核", "time": "2026-10-23 16:00", "state": "审核中",
                  "numbers": ["0", "0", "0", "0", "0"]}],
             "profile": {"followers": "200"}}
    value.update(changes)
    return value


class ParsingTests(unittest.TestCase):
    def test_numbers_titles_times_and_labels(self) -> None:
        self.assertEqual(capture.exact_number("1,087"), 1087)
        self.assertIsNone(capture.exact_number("1.2万"))
        self.assertIsNone(capture.exact_number("1.7K"))
        self.assertIsNone(capture.exact_number(""))
        self.assertEqual(capture.title_key("爷爷一喊“儿子”， 我俩都答应了"),
                         capture.title_key("爷爷一喊儿子,我俩都答应了"))
        self.assertEqual(capture.list_time("2026-10-23 15:13"),
                         dt.datetime(2026, 10, 23, 7, 13, tzinfo=dt.timezone.utc))
        self.assertEqual(capture.account_label({"name": "示例创作者 · 小红书"}), "示例创作者")
        self.assertTrue(capture.same_account("示例创作者", ACCOUNT, ["创作服务平台", "示例创作者"]))
        self.assertFalse(capture.same_account("示例创作者", ACCOUNT, ["别人的号"]))
        self.assertFalse(capture.same_account("示例创作者", ACCOUNT, []))

    def test_publish_time_on_its_own_line(self) -> None:
        records = parse_records(SHOES_RECORD, "发布记录.md", False)
        self.assertEqual([record.published_at for record in records],
                         ["2026-10-23T00:13:19.637-07:00"])


class RecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.config = fixture_config(Path(self.temporary.name))
        workspace = self.config.workspace
        populate(workspace)
        write(workspace / SHOES / "发布记录.md", SHOES_RECORD)
        write(workspace / SHOES / "封面.jpg", b"cover")
        write(workspace / CLOTHES / "发布记录.md", CLOTHES_RECORD)
        write(workspace / CLOTHES / "封面.jpg", b"cover")
        write(workspace / CLOTHES / "说明.md", "---\n标题: 收小衣服，最后给我留了一件\n---\n")
        write(workspace / SHOES / "说明.md", "---\n标题: 他叫了半天，小狗只顾闻我的鞋\n---\n")
        self.indexer = Indexer(self.config)
        self.indexer.reindex()
        self.later = patch.object(capture, "now",
                                  return_value=dt.datetime(2026, 10, 23, 16, 5, tzinfo=dt.timezone.utc))
        self.later.start()

    def tearDown(self) -> None:
        self.later.stop()
        self.temporary.cleanup()

    def rows(self, folder: str) -> list[str]:
        path = self.config.workspace / folder / "数据/表现.csv"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def test_matches_by_note_id_then_title_and_writes_rows(self) -> None:
        summary = capture.record_account_read(self.indexer, read())
        self.assertTrue(summary["ok"], summary)
        self.assertEqual((summary["recorded"], summary["unmatched"], summary["followers"]),
                         (2, ["没有这篇作品（2026-10-19 08:00）"], 200))
        self.assertEqual(self.rows(SHOES)[1],
                         "2026-10-23T16:00:00+00:00,rednote,示例创作者,48,,3,0,2,0,,,,,,,SPT 读数据 · 笔记管理,")
        self.assertEqual(self.rows(CLOTHES)[1].split(",")[3:9], ["1087", "", "12", "3", "1", "0"])
        account = self.config.workspace / "数据/账号/rednote-示例创作者/表现.csv"
        self.assertIn(",200,", account.read_text(encoding="utf-8"))
        self.assertEqual(summary["message"], "示例创作者：新记 2 篇，粉丝 200，1 篇没对上作品")
        # the index sees the new readings: post 58 now has a publish time and an age
        shoes = self.indexer.store.lookup_work("2026-10-22-示例创作者-小狗闻鞋")[0]
        latest = self.indexer.store.work_metrics(shoes["id"])["latest"]
        self.assertEqual((latest["metrics"]["views"], latest["age_hours"]), (48, 8.78))

    def test_same_read_again_is_not_written_twice(self) -> None:
        capture.record_account_read(self.indexer, read())
        again = capture.record_account_read(self.indexer, read(observed_at="2026-10-23T16:20:00Z"))
        self.assertEqual((again["recorded"], again["unchanged"]), (0, 2))
        self.assertEqual(len(self.rows(SHOES)), 2)
        with patch.object(capture, "now",
                          return_value=dt.datetime(2026, 10, 24, 1, 0, tzinfo=dt.timezone.utc)):
            changed = read(observed_at="2026-10-24T01:00:00Z")
            changed["notes"][0]["numbers"] = ["60", "1", "4", "2", "0"]
            later = capture.record_account_read(self.indexer, changed)
        self.assertEqual((later["recorded"], later["unchanged"]), (1, 1))
        self.assertEqual(len(self.rows(SHOES)), 3)

    def test_title_match_needs_a_close_publish_time(self) -> None:
        value = read()
        value["notes"] = [{"title": "收小衣服，最后给我留了一件", "time": "2026-09-01 08:57",
                           "numbers": ["9", "0", "1", "0", "0"]}]
        summary = capture.record_account_read(self.indexer, value)
        self.assertEqual((summary["recorded"], summary["unmatched"]),
                         (0, ["收小衣服，最后给我留了一件（2026-09-01 08:57）"]))

    def test_rounded_numbers_stay_empty(self) -> None:
        value = read()
        value["notes"] = [{"title": "他叫了半天，小狗只顾闻我的鞋", "time": "2026-10-23 15:13",
                           "numbers": ["1.2万", "3", "", "2", "0"]}]
        capture.record_account_read(self.indexer, value)
        self.assertEqual(self.rows(SHOES)[1].split(",")[3:9], ["", "", "", "3", "2", "0"])

    def test_wrong_account_login_and_failures_write_nothing(self) -> None:
        other = capture.record_account_read(self.indexer, read(header=["别人的号"]))
        self.assertFalse(other["ok"])
        self.assertEqual(other["message"], "登录的好像不是 示例创作者，这次没有记")
        login = capture.record_account_read(self.indexer, read(status="login"))
        self.assertIn("需要重新登录", login["message"])
        broken = capture.record_account_read(self.indexer, read(status="attention", reason="笔记列表没有出来"))
        self.assertEqual(broken["message"], "示例创作者：笔记列表没有出来")
        self.assertEqual(self.rows(SHOES), [])


class QueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "metrics-capture.json"
        self.clock = dt.datetime(2026, 10, 23, 16, 0, tzinfo=dt.timezone.utc)
        self.patch = patch.object(capture, "now", side_effect=lambda: self.clock)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temporary.cleanup()

    def test_request_claim_finish_and_schedule(self) -> None:
        queue = capture.CaptureQueue(self.path)
        self.assertIsNone(queue.claim())                  # nothing asked, not auto
        run = queue.request("手动")
        self.assertEqual(queue.request()["id"], run["id"])  # one at a time
        task = queue.claim()
        self.assertEqual(task, {"id": run["id"], "reason": "手动"})
        self.assertIsNone(queue.claim())
        queue.current["accounts"].append({"ok": True, "message": "示例创作者：新记 2 篇"})
        done = queue.finish({"id": run["id"]})
        self.assertEqual((done["state"], done["message"]), ("done", "示例创作者：新记 2 篇"))
        # the schedule: nothing for 8 hours after a good read, then the app gets one
        self.clock += dt.timedelta(hours=7)
        self.assertIsNone(queue.claim(auto=True))
        self.clock += dt.timedelta(hours=1, minutes=1)
        self.assertEqual(queue.claim(auto=True)["reason"], "定时")
        # the status survives a restart
        queue.finish({"id": queue.current["id"], "reason": "还没有在 SPT 里登录过小红书账号"})
        again = capture.CaptureQueue(self.path)
        self.assertEqual(again.status()["last"]["state"], "failed")
        self.assertEqual(again.status()["last_good_at"], "2026-10-23T16:00:00+00:00")
        self.clock += dt.timedelta(hours=1)
        self.assertIsNone(again.claim(auto=True))         # waits 2 hours after a failure
        self.clock += dt.timedelta(hours=1, minutes=1)
        self.assertIsNotNone(again.claim(auto=True))

    def test_nobody_claims_it_without_the_mac_app(self) -> None:
        queue = capture.CaptureQueue(self.path)
        queue.request()
        self.clock += dt.timedelta(seconds=capture.CLAIM_SECONDS + 1)
        last = queue.status()["last"]
        self.assertEqual(last["state"], "failed")
        self.assertIn("只有 Mac 上打开的 SPT 应用", last["message"])
        with self.assertRaises(ValueError):
            queue.finish({"id": last["id"]})


class HTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        config = fixture_config(Path(self.temporary.name))
        populate(config.workspace)
        write(config.workspace / SHOES / "发布记录.md", SHOES_RECORD)
        write(config.workspace / SHOES / "封面.jpg", b"cover")
        self.indexer = Indexer(config)
        self.indexer.reindex()
        self.server = Server(self.indexer)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        capture._QUEUES.clear()
        self.temporary.cleanup()

    def call(self, method: str, path: str, value: object | None = None) -> tuple[int, Any]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        body = json.dumps(value).encode() if value is not None else None
        connection.request(method, path, body=body,
                           headers={"Content-Type": "application/json"} if body else {})
        response = connection.getresponse()
        result = response.status, json.loads(response.read() or b"null")
        connection.close()
        return result

    def test_round_trip(self) -> None:
        status, body = self.call("POST", "/api/metrics/capture/request", {"reason": "手动"})
        self.assertEqual(status, 200, body)
        run_id = body["run"]["id"]
        status, body = self.call("POST", "/api/metrics/capture/claim", {"auto": True})
        self.assertEqual(body["task"]["id"], run_id)
        status, body = self.call("POST", "/api/metrics/capture/result",
                                 {**read(observed_at=dt.datetime.now(dt.timezone.utc).isoformat()),
                                  "id": run_id})
        self.assertEqual((status, body["recorded"]), (200, 1), body)
        status, body = self.call("POST", "/api/metrics/capture/finish", {"id": run_id})
        self.assertEqual(body["state"], "done")
        status, body = self.call("GET", "/api/metrics/capture")
        self.assertEqual((status, body["current"], body["last"]["id"]), (200, None, run_id))
        status, body = self.call("POST", "/api/metrics/capture/result", {"id": run_id})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
