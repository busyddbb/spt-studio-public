"""dashboard_sources.json is rejected before it can break the 情报 page."""
from __future__ import annotations
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from ..tools import validate_sources as vs

SERVER = Path(__file__).resolve().parents[1]
REAL = SERVER / "dashboard_sources.example.json"
SCRIPT = SERVER / "tools" / "validate_sources.py"
HELPER = SERVER.parent.parent / "scripts" / "save_intelligence.py"


def item(**updates: Any) -> dict[str, Any]:
    base = {"id": "meta-20261013", "title": "Facebook 推荐偏好更新",
            "url": "https://about.fb.com/news/2026/10/introducing-your-algorithm-facebook/",
            "source": "Meta Newsroom", "published_at": "2026-10-13",
            "checked_at": "2026-10-20", "summary": "官方介绍；不是流量奖励的证明。",
            "state": "已核官方资料"}
    base.update(updates)
    return base


def doc(news: list[Any] | None = None, research: list[Any] | None = None,
        **top: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"checked_at": "2026-10-20",
                            "news": [item()] if news is None else news,
                            "research": [] if research is None else research}
    data.update(top)
    return data


def distinct(count: int) -> list[dict[str, Any]]:
    return [item(id=f"x-{i}", url=f"https://example.com/{i}", title=f"第{i}条")
            for i in range(count)]


class ValidateSourcesTests(unittest.TestCase):
    def problem(self, data: Any) -> str:
        return vs.first_problem(data) or ""

    def test_current_file_passes(self) -> None:
        self.assertIsNone(vs.validate_file(REAL))

    def test_valid_documents_pass(self) -> None:
        self.assertIsNone(vs.first_problem(doc()))
        self.assertIsNone(vs.first_problem({"checked_at": "2026-10-20"}))
        self.assertIsNone(vs.first_problem(doc(
            source_document="outputs/情报来源.md",
            research=[item(id="r-1", state="待用", title="房产影像研究",
                           url="https://chatgpt.com/space/page_1")])))

    def test_unknown_fields_are_named(self) -> None:
        top = self.problem(doc(as_of="2026-10-20"))
        self.assertIn("不认识的字段", top)
        self.assertIn("as_of", top)
        self.assertIn("candidates", self.problem(doc(candidates=[])))
        inner = self.problem(doc(news=[item(link="x")]))
        self.assertIn("news 第 1 条", inner)
        self.assertIn("link", inner)

    def test_missing_or_empty_url_and_dates(self) -> None:
        for field in vs.ITEM_FIELDS:
            with self.subTest(field=field):
                bad = item()
                del bad[field]
                self.assertIn(f"缺少 {field}", self.problem(doc(news=[bad])))
                self.assertIn(f"{field} 为空", self.problem(doc(news=[item(**{field: " "})])))
        self.assertIn("meta-20261013", self.problem(doc(news=[item(url="")])))
        self.assertIn("缺少顶层 checked_at", self.problem({"news": []}))

    def test_bad_dates(self) -> None:
        for value in ("2026-13-01", "2026-02-30", "10/20/2026",
                      "2026-10-27T00:00:00Z", "昨天"):
            with self.subTest(value=value):
                self.assertIn("日期", self.problem(doc(news=[item(published_at=value)])))
                self.assertIn("顶层 checked_at", self.problem(doc(checked_at=value)))
        # A number is not text, so an item says so before the date check runs.
        self.assertIn("不是文字", self.problem(doc(news=[item(published_at=20261020)])))
        self.assertIn("顶层 checked_at 不是日期", self.problem(doc(checked_at=20261020)))

    def test_bad_urls(self) -> None:
        for value in ("about.fb.com/news", "ftp://x.y/z", "javascript:alert(1)",
                      "https://a b.com"):
            with self.subTest(value=value):
                self.assertIn("http", self.problem(doc(news=[item(url=value)])))

    def test_checked_at_cannot_precede_published_at(self) -> None:
        message = self.problem(doc(checked_at="2026-10-21",
                                   news=[item(published_at="2026-10-21")]))
        self.assertIn("早于 published_at", message)

    def test_top_level_checked_at_must_be_latest(self) -> None:
        message = self.problem(doc(news=[item(checked_at="2026-10-27")]))
        self.assertIn("顶层 checked_at（2026-10-20）早于", message)
        self.assertIn("2026-10-27", message)

    def test_size_caps(self) -> None:
        for name, limit in vs.LIMITS.items():
            with self.subTest(name=name):
                self.assertIsNone(vs.first_problem(doc(**{name: distinct(limit)})))
                message = self.problem(doc(**{name: distinct(limit + 1)}))
                self.assertIn(f"{name} 超过 {limit} 条", message)
                self.assertIn(f"现在 {limit + 1} 条", message)

    def test_duplicates(self) -> None:
        self.assertIn("id 和 news 第 1 条", self.problem(doc(news=[item(), item()])))
        same_page = self.problem(doc(news=[item(), item(id="other")]))
        self.assertIn("url 和标题都相同", same_page)
        across = self.problem(doc(news=[item()], research=[item(id="r-1")]))
        self.assertIn("research 第 1 条（r-1） 和 news 第 1 条", across)
        # The real file keeps two research notes on one workspace page.
        self.assertIsNone(vs.first_problem(doc(research=[
            item(id="r-1", title="一"), item(id="r-2", title="二")])))

    def test_structure_errors(self) -> None:
        self.assertIn("顶层必须是对象", self.problem([]))
        self.assertIn("news 必须是列表", self.problem(doc(news={})))
        self.assertIn("research 第 1 条 不是对象", self.problem(doc(research=["x"])))
        self.assertIn("source_document", self.problem(doc(source_document="")))

    def test_file_level_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            self.assertIn("文件不存在", vs.validate_file(path) or "")
            path.write_text("{not json", encoding="utf-8")
            self.assertIn("JSON", vs.validate_file(path) or "")
            path.write_bytes(b"\xff\xfe")
            self.assertIn("UTF-8", vs.validate_file(path) or "")
            path.write_bytes(b"\xef\xbb\xbf" + json.dumps(doc()).encode("utf-8"))
            self.assertIsNone(vs.validate_file(path))  # BOM, as the loader accepts
            path.write_bytes(b" " * (vs.MAX_BYTES + 1))
            self.assertIn("2 MiB", vs.validate_file(path) or "")

    def test_cli_exit_codes_and_standalone_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            good, bad = Path(tmp) / "good.json", Path(tmp) / "bad.json"
            good.write_text(json.dumps(doc()), encoding="utf-8")
            bad.write_text(json.dumps(doc(as_of="x")), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(vs.main([str(good)]), 0)
                self.assertEqual(vs.main([str(bad)]), 1)
                self.assertEqual(vs.main([]), 2)
            self.assertIn("通过：news 1 条、research 0 条、checked_at 2026-10-20",
                          out.getvalue())
            self.assertIn("不通过：顶层有不认识的字段：as_of", err.getvalue())
            # The script runs on its own, in an isolated interpreter.
            run = subprocess.run([sys.executable, "-I", str(SCRIPT), str(good)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            run = subprocess.run([sys.executable, "-I", str(SCRIPT), str(bad)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            self.assertIn("不认识的字段", run.stderr)

    def test_import_has_no_side_effects(self) -> None:
        code = ("import importlib.util, sys\n"
                "spec = importlib.util.spec_from_file_location('v', sys.argv[1])\n"
                "module = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(module)\n"
                "print('ok')\n")
        run = subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPT)],
                             capture_output=True, text=True)
        self.assertEqual((run.returncode, run.stdout, run.stderr), (0, "ok\n", ""))

    def test_save_helper_refuses_invalid_and_replaces_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "dashboard_sources.json"
            target.write_text(json.dumps(doc()), encoding="utf-8")
            draft = Path(tmp) / "draft.json"
            env = {**os.environ, "SPT_INTEL_TARGET": str(target)}
            draft.write_text(json.dumps(doc(as_of="x")), encoding="utf-8")
            run = subprocess.run([sys.executable, str(HELPER), str(draft)],
                                 capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 1)
            self.assertIn("as_of", run.stderr)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), doc())
            newer = doc(checked_at="2026-10-27", news=[
                item(checked_at="2026-10-27"),
                item(id="tiktok-20261022", url="https://newsroom.tiktok.com/x",
                     title="TikTok 更新", published_at="2026-10-22",
                     checked_at="2026-10-27", source="TikTok Newsroom")])
            draft.write_text(json.dumps(newer), encoding="utf-8")
            run = subprocess.run([sys.executable, str(HELPER), str(draft)],
                                 capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), newer)
            self.assertEqual(list(Path(tmp).glob("*.tmp-*")), [])
            history = list((Path(tmp) / ".cache" / "sources-history").glob("*.json"))
            self.assertEqual(len(history), 1)
            self.assertEqual(json.loads(history[0].read_text(encoding="utf-8")), doc())
            run = subprocess.run([sys.executable, str(HELPER), str(target)],
                                 capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 2)


if __name__ == "__main__":
    unittest.main()
