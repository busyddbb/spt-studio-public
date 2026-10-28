"""SPT 读数据 matching: list rows from 小红书, TikTok and Meta against works' publish records."""
from __future__ import annotations
import datetime as dt
import unittest

from spt.server import metrics_capture as capture

OBSERVED = dt.datetime(2026, 10, 24, 16, 0, tzinfo=dt.timezone.utc)
LOCAL = capture.LOCAL_ZONE  # platform list times use the computer's local zone


def work(identifier: str, title: str, ids: set[str], published: dt.datetime | None,
         caption: str = "") -> dict:
    return {"id": identifier, "title": title, "note_ids": ids, "published": published,
            "caption": capture.caption_key(caption)}


class ListTimeTests(unittest.TestCase):
    def test_meta_and_tiktok_times_are_local_and_this_year(self) -> None:
        self.assertEqual(capture.list_time("Fri Oct 23, 11:53pm", "facebook", OBSERVED),
                         dt.datetime(2026, 10, 23, 23, 53, tzinfo=capture.LOCAL_ZONE))
        self.assertEqual(capture.list_time("Oct 23, 11:59 PM", "tiktok", OBSERVED),
                         dt.datetime(2026, 10, 23, 23, 59, tzinfo=capture.LOCAL_ZONE))
        self.assertEqual(capture.list_time("Dec 30, 1:00 PM", "tiktok", OBSERVED).year, 2025)

    def test_rednote_times_stay_china_time(self) -> None:
        self.assertEqual(capture.list_time("2026-10-23 19:49").utcoffset(), dt.timedelta(hours=8))

    def test_unreadable_time_is_none(self) -> None:
        self.assertIsNone(capture.list_time("2 days ago", "tiktok", OBSERVED))


class MatchTests(unittest.TestCase):
    def test_tiktok_row_matches_by_video_id(self) -> None:
        works = [work("a", "北京鸭 窗光暗调", {"1000000000000000003"}, None),
                 work("b", "三道菜剪辑V4", {"1000000000000000002"}, None)]
        row = {"note_id": "1000000000000000003", "title": "For the duck-skin lovers", "time": "Oct 23, 11:59 PM"}
        self.assertEqual(capture.match(row, works, "tiktok", OBSERVED)["id"], "a")

    def test_meta_row_matches_the_one_work_published_at_that_moment(self) -> None:
        works = [work("a", "北京鸭 窗光暗调", set(), dt.datetime(2026, 10, 23, 23, 52, tzinfo=LOCAL)),
                 work("b", "三道菜剪辑V4", set(), dt.datetime(2026, 10, 21, 19, 51, tzinfo=LOCAL))]
        row = {"note_id": "1000000000000000001", "title": "Bring your duck craving to Sample Studio.",
               "time": "Fri Oct 23, 11:52pm"}
        self.assertEqual(capture.match(row, works, "facebook", OBSERVED)["id"], "a")

    def test_two_works_at_the_same_moment_match_nothing(self) -> None:
        at = dt.datetime(2026, 10, 23, 23, 52, tzinfo=LOCAL)
        works = [work("a", "一", set(), at), work("b", "二", set(), at)]
        row = {"title": "Something", "time": "Fri Oct 23, 11:53pm"}
        self.assertIsNone(capture.match(row, works, "facebook", OBSERVED))

    def test_caption_start_names_the_work(self) -> None:
        works = [work("a", "北京鸭 窗光暗调", set(), None,
                      "For the duck-skin lovers: Peking Duck at Sample Studio, San Francisco.\n\n#PekingDuck")]
        row = {"title": "For the duck-skin lovers: Peking Duck at Sample Studio, San Francisco. 101 Cyril", "time": ""}
        self.assertEqual(capture.match(row, works, "instagram", OBSERVED)["id"], "a")

    def test_rednote_still_matches_by_note_id_and_title(self) -> None:
        works = [work("a", "印树叶，他挑了有洞的那片", {"000000000000000000000066"},
                      dt.datetime(2026, 10, 23, 19, 49, tzinfo=LOCAL))]
        self.assertEqual(capture.match({"note_id": "000000000000000000000066"}, works)["id"], "a")
        self.assertEqual(capture.match({"title": "印树叶，他挑了有洞的那片", "time": "2026-10-24 10:49"}, works)["id"], "a")


class ValuesTests(unittest.TestCase):
    def test_named_metrics_and_empty_cells(self) -> None:
        values = capture.note_values({"metrics": {"views": "390", "reach": "191", "likes": "‑‑", "comments": ""}})
        self.assertEqual(values, {"views": 390, "reach": 191, "likes": None, "comments": None})

    def test_rednote_numbers_keep_icon_order(self) -> None:
        self.assertEqual(capture.note_values({"numbers": ["30", "1", "2", "0", "0"]}),
                         {"views": 30, "comments": 1, "likes": 2, "saves": 0, "shares": 0})


class AccountTests(unittest.TestCase):
    def test_handle_is_the_label_off_rednote(self) -> None:
        self.assertEqual(capture.account_label({"platform": "tiktok", "handle": "@sample_studio", "name": "Sample Studio · TikTok"}), "sample_studio")
        self.assertEqual(capture.account_label({"platform": "xiaohongshu", "handle": "https://www.rednote.com/user/profile/abc", "name": "示例创作者 · 小红书"}), "示例创作者")

    def test_rows_can_name_the_account(self) -> None:
        account = {"platform": "tiktok", "handle": "sample_studio", "name": "Sample Studio · TikTok", "brand": "Sample Studio"}
        self.assertFalse(capture.same_account("sample_studio", account, ["Posts 17", "TikTok Studio"]))
        self.assertTrue(capture.same_account("sample_studio", account, ["Posts 17"],
                                             [{"url": "https://www.tiktok.com/@sample_studio/video/1"}]))
        self.assertTrue(capture.same_account("Sample Studio", {"platform": "facebook", "name": "Sample Studio · Facebook", "brand": "Sample Studio", "handle": "Sample Studio"},
                                             ["Content"], [{"owner": "Sample Studio, sample_studio"}]))


if __name__ == "__main__":
    unittest.main()


class FakeStore:
    """Just enough of the index for node_passed: current publish records with times."""

    def __init__(self, rows: list[tuple[str, str, str]]) -> None:
        self.rows = [{"title": title, "platform": platform, "published_at": at}
                     for title, platform, at in rows]

    def connect(self):
        store = self

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def execute(self, *_):
                return self

            def fetchall(self):
                return list(store.rows)
        return Connection()


class NodeTests(unittest.TestCase):
    def test_a_post_reaching_d1_since_the_last_read_is_due(self) -> None:
        store = FakeStore([("北京鸭 窗光暗调", "instagram", "2026-10-23T23:53-07:00")])
        d1 = dt.datetime(2026, 10, 24, 23, 53, tzinfo=LOCAL)
        self.assertEqual(capture.node_passed(store, "2026-10-24T20:00:00+00:00", d1), "北京鸭 窗光暗调 D1")
        self.assertIsNone(capture.node_passed(store, "2026-10-24T20:00:00+00:00",
                                              d1 - dt.timedelta(minutes=1)))

    def test_a_node_already_covered_by_the_last_read_is_not_due_again(self) -> None:
        store = FakeStore([("北京鸭 窗光暗调", "facebook", "2026-10-23T23:52-07:00")])
        later = dt.datetime(2026, 10, 25, 12, 0, tzinfo=LOCAL)
        self.assertIsNone(capture.node_passed(store, "2026-10-25T08:00:00+00:00", later))
        self.assertEqual(capture.node_passed(store, None, later), "北京鸭 窗光暗调 D1")

    def test_platforms_the_app_cannot_read_do_not_trigger(self) -> None:
        store = FakeStore([("北京鸭 窗光暗调", "google_business", "2026-10-23T23:52-07:00")])
        self.assertIsNone(capture.node_passed(store, None, dt.datetime(2026, 10, 30, tzinfo=LOCAL)))
