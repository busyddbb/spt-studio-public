"""SPT work to native publishing queue adapter.

This module is deliberately local-only: it prepares existing drafts and native
upload jobs, never opens a platform or reads credentials.  One queue row is
created per account and work fingerprint; media paths remain references to the
original SPT files.
"""
from __future__ import annotations

import hashlib
import json
import base64
import os
import re
import sqlite3
import uuid
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

if __package__:
    from . import core, operations, publishing, media_uploads
else:  # pragma: no cover
    import core, operations, publishing, media_uploads

MAX_UPLOADS = 2
PLATFORM = "xiaohongshu"
STATES = {"queued", "checking_login", "uploading", "processing", "preflight",
          "submit_intent", "checking_result", "under_review", "published",
          "needs_login", "needs_attention", "failed", "unknown", "cancelled"}
TERMINAL = {"published", "under_review", "failed", "unknown", "cancelled"}
UPLOADING = {"checking_login", "uploading"}


class MediaSelectionError(Exception):
    pass


@contextmanager
def _db():
    c = core.connect()
    # Schema creation is process-wide and keyed by the actual DB inode.  This
    # keeps polling connections cheap while still initializing a recreated
    # temporary database at the same path.
    db_path = Path(core.DB).expanduser().resolve()
    try:
        stat = db_path.stat()
        schema_key = (str(db_path), stat.st_dev, stat.st_ino)
    except OSError:
        schema_key = (str(db_path), None, None)
    global _SCHEMA_KEYS
    with _SCHEMA_LOCK:
        if schema_key not in _SCHEMA_KEYS:
            c.executescript("""
      CREATE TABLE IF NOT EXISTS publishing_queue (
        id TEXT PRIMARY KEY, work_id TEXT NOT NULL, account_id TEXT NOT NULL,
        draft_id TEXT NOT NULL, native_job_id TEXT, fingerprint TEXT NOT NULL,
        payload TEXT NOT NULL, state TEXT NOT NULL, executor_id TEXT, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, UNIQUE(work_id, account_id, fingerprint));
      CREATE INDEX IF NOT EXISTS publishing_queue_state ON publishing_queue(state, created_at);
      CREATE TABLE IF NOT EXISTS publishing_defaults (
        account_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
    """)
            # Older databases created native_job_id as NOT NULL, but a job only
            # gets its native id after claim(); rebuild that table, keeping rows.
            if any(col[1] == "native_job_id" and col[3] for col in c.execute("PRAGMA table_info(publishing_queue)")):
                c.executescript("""
      DROP INDEX IF EXISTS publishing_queue_state;
      ALTER TABLE publishing_queue RENAME TO publishing_queue_old;
      CREATE TABLE publishing_queue (
        id TEXT PRIMARY KEY, work_id TEXT NOT NULL, account_id TEXT NOT NULL,
        draft_id TEXT NOT NULL, native_job_id TEXT, fingerprint TEXT NOT NULL,
        payload TEXT NOT NULL, state TEXT NOT NULL, executor_id TEXT, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, UNIQUE(work_id, account_id, fingerprint));
      INSERT INTO publishing_queue SELECT * FROM publishing_queue_old;
      DROP TABLE publishing_queue_old;
      CREATE INDEX publishing_queue_state ON publishing_queue(state, created_at);
    """)
            c.commit()
            _SCHEMA_KEYS.add(schema_key)
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


_SCHEMA_LOCK = threading.Lock()
_SCHEMA_KEYS: set[tuple[str, int | None, int | None]] = set()


def _workspace() -> Path:
    try:
        from spt.server.config import default_config
        return default_config().resolved_workspace
    except Exception:
        value = os.environ.get("SPT_WORKSPACE")
        return Path(value).expanduser() if value else Path(core.ROOT) / "工作区"


def _work(work_id: str) -> tuple[Path, dict[str, Any]]:
    """Resolve an indexed SPT work and enforce the configured workspace boundary."""
    if not isinstance(work_id, str) or not work_id.strip():
        raise core.ValidationError("work_id 不能为空")
    try:
        from spt.server.config import default_config
        from spt.server.indexer import Indexer
        indexer = Indexer(default_config())
        detail = indexer.store.detail(work_id)
        if detail:
            return indexer.work_folder(detail["work"]), detail
    except Exception:
        pass
    candidate = Path(work_id).expanduser()
    workspace = _workspace().resolve()
    try:
        resolved = candidate.resolve(strict=True)
        if resolved.is_dir() and resolved.is_relative_to(workspace) and not candidate.is_symlink():
            return resolved, {"work": {"id": work_id, "title": candidate.name, "path": str(resolved)}}
    except OSError:
        pass
    raise core.ValidationError("SPT 作品不存在或尚未建索引")


def _read_first(root: Path, names: list[str]) -> str:
    for name in names:
        path = root / name
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def _media(root: Path, detail: dict[str, Any]) -> list[dict[str, Any]]:
    paths: list[Path] = []
    work = detail.get("work", detail)
    manifest = root / "manifest.json"
    if not manifest.is_file():
        manifest = root / "资料" / "manifest.json"
    if manifest.is_file():
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
            listed = value.get("images_in_order", value.get("image_order", value.get("media", value.get("assets", [])))) if isinstance(value, dict) else []
            if isinstance(listed, list):
                paths = []
                missing = []
                for item in listed:
                    rel = item.get("path", item.get("name", item)) if isinstance(item, dict) else item
                    rel_path = Path(str(rel))
                    candidate = root / rel_path
                    try:
                        resolved_root = root.resolve(strict=True)
                        resolved_candidate = candidate.resolve(strict=False)
                        if not resolved_candidate.is_relative_to(resolved_root) or any(part.startswith(".") for part in rel_path.parts):
                            raise MediaSelectionError(f"manifest 媒体路径越界或隐藏: {rel}")
                    except OSError as exc:
                        raise MediaSelectionError(f"manifest 媒体路径无效: {rel}") from exc
                    if "参考" in candidate.name or candidate.name.startswith("."):
                        raise MediaSelectionError(f"manifest 包含参考或隐藏素材: {rel}")
                    # Imported SPT package images mirror the V1 originals; the
                    # manifest's basename is authoritative while its package
                    # copy is not uploaded.
                    source = root / "V1" / Path(str(rel)).name
                    candidate = source if source.is_file() else candidate
                    if candidate.is_file():
                        if candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve()):
                            raise MediaSelectionError(f"manifest 媒体路径不安全: {rel}")
                        paths.append(candidate)
                    else:
                        missing.append(str(rel))
                if missing:
                    raise MediaSelectionError("manifest 指定媒体缺失: " + ", ".join(missing))
                paths = [p for p in paths if p.is_file() and not p.is_symlink()]
        except (OSError, ValueError):
            pass
    finals = [root / m["path"] for m in detail.get("finals", []) if m.get("role") == "final"]
    final_videos = [p for p in finals if p.suffix.lower() in {".mp4", ".mov"}]
    if final_videos:
        paths = final_videos[:1]
    current = work.get("current_version") or work.get("latest_version") or ""
    for version in detail.get("versions", []):
        if paths:
            break
        if version.get("name") == current and version.get("is_current"):
            paths = [root / m["path"] for m in version.get("media", []) if m.get("role", "input") == "input"]
            break
    if not paths:
        versions = sorted([p for p in root.glob("V*") if p.is_dir()], key=lambda p: p.name)
        if versions:
            paths = sorted([p for p in versions[-1].iterdir() if p.is_file() and p.suffix.lower() in
                            {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov"}], key=lambda p: p.name)
    if not paths:
        paths = [root / m["path"] for m in detail.get("finals", []) if m.get("role") == "final"]
    if not paths:
        paths = [root / n for n in ("成片.mp4", "成片_video.mp4", "发布版.mp4") if (root / n).is_file()]
    safe_paths = []
    root_resolved = root.resolve()
    for path in paths:
        if "参考" in path.name or path.name.startswith(".") or path.is_symlink():
            continue
        try:
            if path.resolve().is_relative_to(root_resolved):
                safe_paths.append(path)
        except OSError:
            continue
    paths = safe_paths
    result = []
    for index, path in enumerate(paths, 1):
        stat = path.stat()
        result.append({"order": index, "path": str(path), "name": path.name,
                       "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                       "kind": "video" if path.suffix.lower() in {".mp4", ".mov"} else "image"})
    return result


def _topics(root: Path) -> list[str]:
    text = _read_first(root, ["发布话题.txt", "话题.txt", "topics.txt"])
    for base in (root, root / "资料"):
        for name in ("manifest.json", "content.json", "structured-topics.json"):
            path = base / name
            if path.is_file():
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    raw = value.get("required_structured_topics", value.get("required_topics", value.get("tags", value.get("topics", [])))) if isinstance(value, dict) else []
                    if isinstance(raw, list) and raw:
                        return [str(x).lstrip("#").strip() for x in raw if str(x).strip()]
                except (OSError, ValueError):
                    pass
    if not text:
        for name in ("manifest.json", "content.json"):
            path = root / name
            if path.is_file():
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    raw = value.get("topics", value.get("tags", [])) if isinstance(value, dict) else []
                    if isinstance(raw, list):
                        return [str(x).lstrip("#").strip() for x in raw if str(x).strip()]
                except (OSError, ValueError):
                    pass
    if not text:
        return []
    return [x.lstrip("#").strip() for x in re.split(r"[\n,，、#]+", text) if x.strip()]


def preview(work_id: str) -> dict[str, Any]:
    root, detail = _work(work_id)
    # A title file ends with a newline the platform's one-line field cannot hold.
    title = _read_first(root, ["发布标题.txt", "标题.txt"]).strip()
    body = _read_first(root, ["发布正文.txt", "正文发布.txt"])
    if not title:
        title = str(detail.get("work", detail).get("title") or root.name)
    try:
        media = _media(root, detail)
    except MediaSelectionError as exc:
        media = []
        media_issue = str(exc)
    else:
        media_issue = ""
    topics = _topics(root)
    issues = []
    if not (root / "发布标题.txt").is_file():
        issues.append("缺少发布标题.txt，不能把作品名当作已核对标题")
    if not body:
        issues.append("缺少发布正文.txt")
    if not media:
        issues.append("当前版本没有可发布图片或视频")
    if media_issue:
        issues.append(media_issue)
    if len(media) > 1 and any(x["kind"] == "video" for x in media):
        issues.append("视频发布必须只有一个视频文件")
    fingerprint = hashlib.sha256(json.dumps({"title": title, "body": body,
                                              "media": media, "topics": topics},
                                             ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {"work_id": work_id, "root": str(root), "title": title, "body": body,
            "cover": str(root / "封面.png") if (root / "封面.png").is_file() else None,
            "media": media, "topics": topics, "fingerprint": fingerprint, "issues": issues}


def _accounts(ids: list[str]) -> dict[str, dict[str, Any]]:
    available = {a["id"]: a for a in core.state("real")["accounts"]}
    if not ids or any(i not in available for i in ids):
        raise core.ValidationError("请选择已登记的目标账号")
    return {i: available[i] for i in ids}


def _profile_id(account: dict[str, Any]) -> str:
    """Return the platform profile ID; publishing must never proceed anonymously."""
    value = account.get("profile_id") or account.get("handle", "")
    value = str(value).rstrip("/").split("/")[-1]
    if not re.fullmatch(r"[0-9a-fA-F]{24}", value):
        raise core.ValidationError(f"账号 {account.get('id')} 缺少有效的24位 profile ID")
    return value


def snapshot() -> dict[str, Any]:
    with _db() as c:
        rows = [json.loads(r["payload"]) for r in c.execute("SELECT payload FROM publishing_queue ORDER BY rowid DESC")]
        rows = [row for row in rows if not row.get("hidden")]   # cleared records stay in the table, off the list
        defaults = {r["account_id"]: json.loads(r["payload"])
                    for r in c.execute("SELECT account_id,payload FROM publishing_defaults")}
    accounts = []
    for account in core.state("real")["accounts"]:
        item = dict(account)
        item["defaults"] = defaults.get(item["id"], {})
        accounts.append(item)
    return {"jobs": rows, "accounts": accounts, "max_uploads": MAX_UPLOADS,
            "auto_platforms": [PLATFORM]}


def enqueue_work(args: dict[str, Any]) -> dict[str, Any]:
    work_id = args.get("work_id")
    scheduled_at = args.get("scheduled_at")
    if scheduled_at:
        if not isinstance(scheduled_at, str) or not re.search(r"(?:Z|[+-]\d\d:\d\d)$", scheduled_at):
            raise core.ValidationError("scheduled_at 必须带时区偏移")
        try:
            datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise core.ValidationError("scheduled_at 格式无效") from exc
    data = preview(work_id)
    account_ids = list(dict.fromkeys(args.get("account_ids") or []))
    accounts = _accounts(account_ids)
    profile_ids = {aid: _profile_id(account) for aid, account in accounts.items()}
    unsupported = [a["id"] for a in accounts.values() if a.get("platform") != PLATFORM]
    if unsupported:
        raise core.ValidationError("当前自动发布仅支持 rednote；其他平台明确不支持")
    defaults_by_account = {}
    with _db() as c:
        for aid in account_ids:
            row = c.execute("SELECT payload FROM publishing_defaults WHERE account_id=?", (aid,)).fetchone()
            if row:
                defaults_by_account[aid] = json.loads(row["payload"])
    if data["issues"]:
        raise core.ValidationError("；".join(data["issues"]))
    # Resolve existing rows before registering media or creating another draft.
    # This keeps retries idempotent and avoids duplicate local imports.
    with _db() as c:
        existing = []
        existing_by_account = {}
        for account_id in account_ids:
            # Closed tasks (failed after a checked void, or cancelled before any submit) do not stand in for a new one.
            row = c.execute("SELECT payload,state,fingerprint FROM publishing_queue WHERE work_id=? AND account_id=? AND state NOT IN ('failed','cancelled') ORDER BY rowid DESC LIMIT 1",
                            (work_id, account_id)).fetchone()
            if row and row["fingerprint"] != data["fingerprint"]:
                raise core.ValidationError(f"账号 {account_id} 已有该作品任务，内容指纹变化也不能新建重发")
            if row:
                item = json.loads(row["payload"])
                existing.append(item); existing_by_account[account_id] = item
        if len(existing) == len(account_ids):
            return {"jobs": existing}
    # Existing SPT publish records are a hard duplicate guard per account/URL.
    detail = _work(work_id)[1]
    account_map = accounts
    receipt_accounts = {}
    receipt_dir = Path(data["root"]) / "资料" / "发布记录"
    if receipt_dir.is_dir():
        for receipt in receipt_dir.glob("*-回执.json"):
            try:
                item = json.loads(receipt.read_text(encoding="utf-8"))
                if item.get("url") and item.get("account_id"):
                    receipt_accounts[_safe_url(item["url"])] = item["account_id"]
            except (OSError, ValueError, core.ValidationError):
                continue
    for aid, account in account_map.items():
        for record in detail.get("records", []):
            if record.get("url") and (record.get("account") in {aid, account.get("id"), account.get("handle"), account.get("name")}):
                raise core.ValidationError(f"账号 {aid} 已有该作品发布记录，请先核对线上原帖")
            if record.get("url") and not record.get("account"):
                mapped = receipt_accounts.get(_safe_url(record["url"]))
                if mapped != aid:
                    if mapped:
                        continue
                    raise core.ValidationError("作品已有缺少账号身份的发布记录，需人工核对后再入队")
                raise core.ValidationError(f"账号 {aid} 已有该作品发布记录，请先核对线上原帖")
    # Register only references; SPT originals are never copied or transformed.
    if existing:
        draft_id = existing[0]["draft_id"]
    else:
        registered = media_uploads.register_files([m["path"] for m in data["media"]])["jobs"]
        draft = core.create_draft({"title": data["title"], "body": data["body"],
                                   "platforms": [PLATFORM], "account_ids": account_ids,
                                   "media_ids": [m["id"] for m in registered]})["draft"]
        core.update_draft(draft["id"], {"status": "review"})
        core.update_draft(draft["id"], {"status": "approved"})
        operations.bind_draft({"draft_id": draft["id"], "checklist": {"content": True, "media": True, "account": True}})
        draft_id = draft["id"]
    jobs = []
    with _db() as c:
        for account_id in account_ids:
            queue_id = uuid.uuid4().hex
            own_topics = list(data["topics"])
            if not own_topics and isinstance(defaults_by_account.get(account_id, {}).get("topics"), list):
                own_topics = [str(x) for x in defaults_by_account[account_id]["topics"] if str(x).strip()]
            payload = {"id": queue_id, "work_id": work_id, "account_id": account_id,
                       "draft_id": draft_id, "native_job_id": None,
                       "fingerprint": data["fingerprint"], "title": data["title"],
                       "body": data["body"], "topics": own_topics, "media": data["media"],
                       "state": "queued", "events": [], "submit_intent": None,
                       "options": {**defaults_by_account.get(account_id, {}), **(args.get("options") or {}),
                                   "expected_profile_id": profile_ids[account_id],
                                   "expected_name": accounts[account_id].get("name")},
                       "scheduled_at": scheduled_at or None, "submit_enabled": bool(args.get("submit_enabled", False)),
                       "created_at": core.now(), "updated_at": core.now()}
            try:
                c.execute("INSERT INTO publishing_queue VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (queue_id, work_id, account_id, draft_id, None, data["fingerprint"],
                           json.dumps(payload, ensure_ascii=False), "queued", None, payload["created_at"], payload["updated_at"]))
            except sqlite3.IntegrityError:
                existing = c.execute("SELECT payload FROM publishing_queue WHERE work_id=? AND account_id=? AND fingerprint=?",
                                     (work_id, account_id, data["fingerprint"])).fetchone()
                if existing:
                    payload = json.loads(existing["payload"])
                else:
                    raise
            jobs.append(payload)
    return {"jobs": jobs}


def claim(args: dict[str, Any]) -> dict[str, Any]:
    executor = str(args.get("executor_id") or "local")
    selected = []
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        # A crashed executor must release its account lock as attention-needed;
        # it is never silently retried.
        stale = c.execute("SELECT * FROM publishing_queue WHERE state IN ('checking_login','uploading','processing','preflight','submit_intent','checking_result')").fetchall()
        for old in stale:
            try:
                age = (datetime.now().astimezone() - datetime.fromisoformat(old["updated_at"])).total_seconds()
            except (TypeError, ValueError):
                age = 999999
            if age > 300:
                p = json.loads(old["payload"])
                next_state = "unknown" if p.get("submit_intent") else "needs_attention"
                p["state"] = next_state; p["message"] = "执行者失联，需人工核对"
                c.execute("UPDATE publishing_queue SET payload=?,state=?,updated_at=? WHERE id=?", (json.dumps(p, ensure_ascii=False), next_state, core.now(), old["id"]))
        active = c.execute("SELECT COUNT(*) FROM publishing_queue WHERE state IN ('checking_login','uploading')").fetchone()[0]
        slots = max(0, MAX_UPLOADS - active)
        rows = c.execute("SELECT * FROM publishing_queue WHERE state='queued' ORDER BY created_at,rowid").fetchall()
        tasks = []
        # A stopped task (unknown / needs_attention) keeps its account locked until a person closes it
        # (queue_void / queue_confirm) or clears it off the list (queue_hide): cleared means checked.
        locked_accounts, blockers = set(), {}
        for lock in c.execute("SELECT id, account_id, state, payload FROM publishing_queue WHERE state IN ('checking_login','uploading','processing','preflight','submit_intent','checking_result','unknown','needs_attention')"):
            held = json.loads(lock["payload"])
            if lock["state"] in ("unknown", "needs_attention") and held.get("hidden"):
                continue
            locked_accounts.add(lock["account_id"])
            if lock["state"] in ("unknown", "needs_attention"):
                blockers[lock["account_id"]] = str(held.get("title") or lock["id"][:8])
        for row in rows:
            if row["account_id"] in blockers:
                note = f"同账号上一条「{blockers[row['account_id']]}」还停着，核对后作废、确认或清除它，这条才会开始"
                payload = json.loads(row["payload"])
                if payload.get("message") != note:
                    payload.update(message=note, updated_at=core.now())
                    c.execute("UPDATE publishing_queue SET payload=?,updated_at=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), payload["updated_at"], row["id"]))
                continue
            if slots <= 0 or row["account_id"] in locked_accounts:
                continue
            payload = json.loads(row["payload"])
            if payload.get("scheduled_at"):
                value = payload["scheduled_at"]
                if not re.search(r"(?:Z|[+-]\d\d:\d\d)$", value):
                    payload["state"] = "needs_attention"
                    c.execute("UPDATE publishing_queue SET payload=?,state=?,updated_at=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), "needs_attention", core.now(), row["id"]))
                    locked_accounts.add(row["account_id"])
                    continue
                try:
                    if datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() > datetime.now().timestamp():
                        continue
                except ValueError:
                    payload["state"] = "needs_attention"
                    payload["message"] = "排期时间无效，需人工修正"
                    payload["updated_at"] = core.now()
                    c.execute("UPDATE publishing_queue SET payload=?,state=?,updated_at=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), "needs_attention", payload["updated_at"], row["id"]))
                    locked_accounts.add(row["account_id"])
                    continue
            payload.update(state="checking_login", executor_id=executor, updated_at=core.now())
            c.execute("UPDATE publishing_queue SET payload=?,state=?,executor_id=?,updated_at=? WHERE id=?",
                      (json.dumps(payload, ensure_ascii=False), "checking_login", executor, payload["updated_at"], row["id"]))
            selected.append((row["id"], row["native_job_id"], payload.get("options", {})))
            locked_accounts.add(row["account_id"]); slots -= 1
    tasks = []
    for queue_id, native_id, options in selected:
        try:
            with _db() as c:
                p, _ = _find(queue_id, c)
            if not native_id:
                native = publishing.prepare_upload({"account_id": p["account_id"], "draft_id": p["draft_id"]})["job"]
                with _db() as c:
                    p, _ = _find(queue_id, c); p["native_job_id"] = native["id"]; p["updated_at"] = core.now()
                    c.execute("UPDATE publishing_queue SET payload=?,native_job_id=?,updated_at=? WHERE id=?", (json.dumps(p, ensure_ascii=False), native["id"], p["updated_at"], queue_id))
                native_id = native["id"]
            context = publishing.upload_context(native_id)
            account = _accounts([p["account_id"]])[p["account_id"]]
            options.update({"submit_enabled": bool(p.get("submit_enabled")),
                            "topics": list(p.get("topics", [])),
                            "allow_body_copy": bool(p.get("options", {}).get("allow_body_copy", p.get("options", {}).get("copy_body", False))),
                            "scheduled": False, "expected_profile_id": p.get("options", {}).get("expected_profile_id"),
                            "expected_name": account.get("name"), "title": p.get("title"), "body": p.get("body"),
                            "cover": p.get("media", [{}])[0].get("path") if p.get("media") else None})
            tasks.append({"queue_id": queue_id, "job": context["job"],
                          "workspace": context["workspace"], "options": options})
        except core.ValidationError as exc:
            event({"id": queue_id, "event": "needs_attention", "executor_id": executor, "message": str(exc)})
    return {"tasks": tasks}


def _find(identifier: str, c) -> tuple[dict[str, Any], sqlite3.Row]:
    row = c.execute("SELECT * FROM publishing_queue WHERE id=?", (identifier,)).fetchone()
    if not row: raise core.ValidationError("发布队列任务不存在")
    return json.loads(row["payload"]), row


def _media_unchanged(payload: dict[str, Any]) -> bool:
    for item in payload.get("media", []):
        try:
            stat = Path(item["path"]).stat()
        except OSError:
            return False
        if stat.st_size != item.get("size") or stat.st_mtime_ns != item.get("mtime_ns"):
            return False
    return True


def _preflight_evidence(payload: dict[str, Any], proof: Any) -> dict[str, Any]:
    if not isinstance(proof, dict):
        raise core.ValidationError("preflight evidence 必须是对象")
    required = ("identity_verified", "account_profile_id", "duplicate_checked", "upload_complete",
                "media_count", "media_order", "title", "body", "topics", "topics_complete",
                "settings", "settings_verified")
    if any(key not in proof for key in required):
        raise core.ValidationError("preflight evidence 字段不完整")
    if proof["identity_verified"] is not True or proof["duplicate_checked"] is not True or proof["upload_complete"] is not True or proof["topics_complete"] is not True or proof["settings_verified"] is not True:
        raise core.ValidationError("preflight evidence 未通过")
    if proof["title"] != payload["title"] or proof["body"] != payload["body"] or proof["topics"] != payload["topics"]:
        raise core.ValidationError("preflight 文案或话题与任务不一致")
    if proof["media_count"] != len(payload.get("media", [])) or proof["media_order"] != [m["name"] for m in payload.get("media", [])]:
        raise core.ValidationError("preflight 媒体顺序或数量不一致")
    settings = proof["settings"]
    if not isinstance(settings, dict) or settings.get("scheduled") is not False or settings.get("allow_body_copy") not in (True, False) or settings.get("visibility") not in {"public", "private"}:
        raise core.ValidationError("preflight 设置证据不完整")
    options = payload.get("options", {})
    expected_copy = options.get("allow_body_copy", options.get("copy_body", False))
    expected_visibility = options.get("visibility", "public")
    if settings["allow_body_copy"] != bool(expected_copy) or settings["visibility"] != expected_visibility:
        raise core.ValidationError("preflight 设置与任务选项不一致")
    if proof["account_profile_id"] != options.get("expected_profile_id"):
        raise core.ValidationError("preflight 账号身份与目标账号不一致")
    return {k: v for k, v in proof.items() if k != "png_base64"}


def _result_evidence(payload: dict[str, Any], proof: Any, state: str) -> dict[str, Any]:
    if not isinstance(proof, dict) or proof.get("content_verified") is not True or proof.get("result_status") != state:
        raise core.ValidationError("最终回查证据不完整")
    for key in ("account_profile_id", "title", "body", "topics", "media_count"):
        if proof.get(key) != (payload.get("options", {}).get("expected_profile_id") if key == "account_profile_id" else payload.get(key) if key != "media_count" else len(payload.get("media", []))):
            raise core.ValidationError("最终回查内容与任务不一致")
    return {k: v for k, v in proof.items() if k != "png_base64"}


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise core.ValidationError("作品 URL 不安全")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _save_screenshot(payload: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    evidence = dict(evidence)
    raw = evidence.pop("png_base64", None)
    if raw:
        if not isinstance(raw, str) or len(raw) > 6 * 1024 * 1024:
            raise core.ValidationError("截图证据过大")
        try:
            data = base64.b64decode(raw, validate=True)
        except (ValueError, TypeError):
            raise core.ValidationError("截图证据不是有效 PNG") from None
        if len(data) > 4 * 1024 * 1024 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise core.ValidationError("截图证据不是有效 PNG")
        root = Path(preview(payload["work_id"])["root"])
        target = root / "资料" / "发布记录" / f"{payload['id']}-evidence.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        evidence["screenshot_path"] = str(target)
    return evidence


def _archive(payload: dict[str, Any]) -> None:
    root = Path(preview(payload["work_id"])["root"])
    now = payload.get("published_at") or core.now()
    status = payload["state"]
    record = {"queue_id": payload["id"], "account_id": payload["account_id"], "platform": PLATFORM,
              "status": status, "note_id": payload.get("note_id"), "url": payload.get("url"),
              "title": payload.get("title"), "published_at": now,
              "verified_at": payload.get("verified_at") or core.now(),
              "basis": payload.get("basis") if status == "published" else None,
              "source": "auto_verified" if status == "published" else "platform_review"}
    receipt_dir = root / "资料" / "发布记录"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = receipt_dir / f"{payload['id']}-回执.json"
    receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    target = root / "发布记录.md"
    if not target.exists() or payload.get("state") in {"under_review", "published"}:
        with target.open("a", encoding="utf-8") as stream:
            # Keep review records URL-free: SPT's conservative parser treats
            # URLs in 发布记录.md as current published facts.  The canonical
            # URL remains in the structured receipt until publication is
            # actually verified.
            reference = ((payload.get("url") + " · 官方后台与内容已核验") if status == "published" else
                         f"note_id:{payload.get('note_id') or '待核验'} · receipt:{receipt.name}")
            stream.write(f"\n- {now} · {PLATFORM} · {payload['account_id']} · {status} · {reference}\n")


def event(args: dict[str, Any]) -> dict[str, Any]:
    identifier, state = args.get("id"), args.get("event")
    if not isinstance(args.get("executor_id"), str) or not args.get("executor_id"):
        raise core.ValidationError("queue_event 必须带 executor_id")
    if state not in STATES: raise core.ValidationError("不支持的队列状态")
    archive = False
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        payload, row = _find(identifier, c)
        owner = args.get("executor_id")
        if payload.get("executor_id") and owner and payload.get("executor_id") != owner:
            raise core.ValidationError("任务已被其他执行者占用")
        if state in {"preflight", "submit_intent", "checking_result", "under_review", "published", "unknown"}:
            if not payload.get("native_job_id") or payload.get("executor_id") != owner:
                raise core.ValidationError("任务尚未被该执行者 claim")
        if state == "needs_attention" and payload.get("executor_id") != owner:
            raise core.ValidationError("任务尚未被该执行者 claim")
        if payload["state"] in {"published", "failed", "cancelled"} and state not in {payload["state"]}:
            raise core.ValidationError("已结束任务不能改变为可重发状态")
        # A progress heartbeat that was in flight when the executor stopped must not wake a stopped task.
        if payload["state"] in {"needs_attention", "unknown", "needs_login"} and state in {"checking_login", "uploading", "processing", "checking_result"}:
            return {"job": payload}
        if payload["state"] == "published" and state == "published":
            return {"job": payload, "submit_granted": False} if args.get("event") == "submit_intent" else {"job": payload}
        if payload["state"] == "under_review" and state == "under_review":
            return {"job": payload}
        if state == "submit_intent":
            if payload.get("submit_intent"):
                return {"job": payload, "submit_granted": False}
            if not payload.get("submit_enabled"):
                raise core.ValidationError("该任务未授权提交")
            if payload["state"] not in {"preflight", "checking_result", "uploading", "processing"}:
                raise core.ValidationError("必须先完成上传和发布前核对")
            if not payload.get("title") or not payload.get("body") or not payload.get("media"):
                raise core.ValidationError("提交前核对未完成")
            if not _media_unchanged(payload):
                raise core.ValidationError("原素材已变化，请重新预览并建立发布任务")
            if not payload.get("evidence"):
                raise core.ValidationError("必须先保存 preflight evidence")
            _preflight_evidence(payload, payload["evidence"])
            payload["submit_intent"] = {"at": core.now(), "executor_id": payload.get("executor_id"), "once": True}
        if state in {"under_review", "published"} and not payload.get("submit_intent"):
            raise core.ValidationError("最终回查前必须存在 submit_intent")
        payload["state"] = state
        for key in ("message", "evidence", "note_id", "url", "published_at", "verified_at"):
            if key in args: payload[key] = args[key]
        if "url" in payload:
            payload["url"] = _safe_url(payload.get("url"))
        if state == "preflight":
            raw_evidence = args.get("evidence")
            clean_evidence = _preflight_evidence(payload, raw_evidence)
            saved_evidence = _save_screenshot(payload, raw_evidence)
            if "screenshot_path" in saved_evidence:
                clean_evidence["screenshot_path"] = saved_evidence["screenshot_path"]
            payload["evidence"] = clean_evidence
        if state in {"under_review", "published"}:
            if not payload.get("note_id") or not payload.get("url"):
                raise core.ValidationError("最终回查必须同时提供 note_id 和 canonical URL")
            raw_evidence = args.get("evidence") or {}
            clean_evidence = _result_evidence(payload, raw_evidence, state)
            saved_evidence = _save_screenshot(payload, raw_evidence)
            if "screenshot_path" in saved_evidence:
                clean_evidence["screenshot_path"] = saved_evidence["screenshot_path"]
            payload["evidence"] = clean_evidence
            if payload.get("note_id") and (not re.fullmatch(r"[0-9a-fA-F]{24}", str(payload["note_id"]))):
                raise core.ValidationError("note_id 必须是24位十六进制 ID")
            if payload.get("url") and payload.get("note_id") and payload["note_id"].lower() not in payload["url"].lower():
                raise core.ValidationError("URL 与 note_id 不一致")
            if state == "published":
                if not payload.get("published_at"):
                    raise core.ValidationError("已发布结果必须提供实际发布时间")
                if args.get("basis") != "click_proxy":
                    raise core.ValidationError("published_at 必须标记为 click_proxy")
                payload["basis"] = "click_proxy"
            archive = True
        payload.setdefault("events", []).append({
            "event": state, "at": core.now(), "message": args.get("message", ""),
            "evidence": payload.get("evidence") if state in {"preflight", "under_review", "published"} else None,
        })
        payload["updated_at"] = core.now()
        c.execute("UPDATE publishing_queue SET payload=?,state=?,updated_at=? WHERE id=?",
                  (json.dumps(payload, ensure_ascii=False), state, payload["updated_at"], identifier))
    if archive:
        try:
            _archive(payload)
        except OSError as exc:
            with _db() as c:
                payload["archive_error"] = str(exc)
                c.execute("UPDATE publishing_queue SET payload=?,state=?,updated_at=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), payload["state"], core.now(), identifier))
            raise core.ValidationError("归档失败，真实结果已保留，禁止重发") from exc
    return {"job": payload, **({"submit_granted": True} if state == "submit_intent" else {})}


def cancel(args: dict[str, Any]) -> dict[str, Any]:
    with _db() as c:
        payload, _ = _find(args.get("id"), c)
        if payload.get("submit_intent") or payload.get("archive_error") or payload["state"] in {"processing", "submit_intent", "checking_result", "under_review", "published", "unknown"}:
            raise core.ValidationError("已提交或结果不明，不能取消为可重发任务")
    return event({"id": args.get("id"), "event": "cancelled", "executor_id": args.get("executor_id") or "local", "message": "本地队列已取消"})


PRE_UPLOAD_EVENTS = {"queued", "checking_login", "needs_login", "needs_attention"}


def retry(args: dict[str, Any]) -> dict[str, Any]:
    """Put a task that stopped before any upload back in the queue, keeping the same task."""
    identifier = args.get("id")
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        payload, row = _find(identifier, c)
        if payload["state"] not in {"needs_attention", "needs_login"}:
            raise core.ValidationError("只有停住的任务可以重试")
        history = payload.get("events", [])
        starts = [i for i, e in enumerate(history) if e.get("event") == "queued"]
        events = history[starts[-1]:] if starts else history   # this attempt only
        # The executor tags a stop that happened before its one click with "[未点击]"; such a task has sent nothing.
        never_clicked = (bool(payload.get("submit_intent")) and bool(events) and events[-1].get("event") == "needs_attention"
                         and str(events[-1].get("message", "")).startswith("[未点击]")
                         and not any(e.get("event") in {"checking_result", "unknown", "under_review", "published"} for e in events))
        if payload.get("archive_error") or (payload.get("submit_intent") and not never_clicked):
            raise core.ValidationError("已提交或结果不明，不能重试，请先核对后台")
        if not never_clicked and any(e.get("event") in {"processing", "preflight", "submit_intent", "checking_result"} for e in events):
            raise core.ValidationError("任务已越过上传阶段，不能直接重试，请先核对后台草稿")
        if never_clicked:
            payload["submit_intent"] = None
        native_id = row["native_job_id"]
        if native_id:
            c.execute("CREATE TABLE IF NOT EXISTS native_upload_jobs (id TEXT PRIMARY KEY, account_id TEXT NOT NULL, draft_id TEXT NOT NULL, payload TEXT NOT NULL)")
            job_row = c.execute("SELECT payload FROM native_upload_jobs WHERE id=?", (native_id,)).fetchone()
            if job_row:
                job = json.loads(job_row[0])
                if job.get("state") not in {"prepared", "checking_login", "selecting_media", "uploading", "needs_login", "needs_attention", "interrupted"}:
                    raise core.ValidationError("上传任务已越过核对账号阶段，不能直接重试")
                job.update(state="prepared", message="等待重试", updated_at=core.now())
                c.execute("UPDATE native_upload_jobs SET payload=? WHERE id=?", (json.dumps(job, ensure_ascii=False), native_id))
        payload.update(state="queued", executor_id=None, message="已重试，等待执行", updated_at=core.now())
        payload.setdefault("events", []).append({"event": "queued", "at": payload["updated_at"], "message": "人工重试（原任务）", "evidence": None})
        c.execute("UPDATE publishing_queue SET payload=?,state=?,executor_id=NULL,updated_at=? WHERE id=?",
                  (json.dumps(payload, ensure_ascii=False), "queued", payload["updated_at"], identifier))
    return {"job": payload}


def void(args: dict[str, Any]) -> dict[str, Any]:
    """A person has checked the platform and found nothing: close a stopped task as failed so a fresh one can be queued."""
    if args.get("checked_backstage") is not True:
        raise core.ValidationError("作废前必须先在平台后台核对没有这篇笔记，并带 checked_backstage: true")
    message = str(args.get("message") or "").strip()
    if not message:
        raise core.ValidationError("作废必须写明核对结果")
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        payload, row = _find(args.get("id"), c)
        if payload["state"] not in {"needs_attention", "unknown", "needs_login"}:
            raise core.ValidationError("只有停住的任务可以作废")
        payload.update(state="failed", message=message, updated_at=core.now(),
                       voided={"at": core.now(), "message": message, "checked_backstage": True})
        payload.setdefault("events", []).append({"event": "failed", "at": payload["updated_at"], "message": "人工作废：" + message, "evidence": None})
        # The (work, account, fingerprint) slot is unique; a voided row keeps its history but gives the slot up.
        c.execute("UPDATE publishing_queue SET payload=?,state=?,updated_at=?,fingerprint=fingerprint||':void:'||id WHERE id=?",
                  (json.dumps(payload, ensure_ascii=False), "failed", payload["updated_at"], args.get("id")))
        native_id = row["native_job_id"]
        if native_id:
            c.execute("CREATE TABLE IF NOT EXISTS native_upload_jobs (id TEXT PRIMARY KEY, account_id TEXT NOT NULL, draft_id TEXT NOT NULL, payload TEXT NOT NULL)")
            job_row = c.execute("SELECT payload FROM native_upload_jobs WHERE id=?", (native_id,)).fetchone()
            if job_row:
                job = json.loads(job_row[0])
                job.update(state="cancelled", message="队列任务已人工作废", updated_at=core.now())
                c.execute("UPDATE native_upload_jobs SET payload=? WHERE id=?", (json.dumps(job, ensure_ascii=False), native_id))
    return {"job": payload}


def confirm(args: dict[str, Any]) -> dict[str, Any]:
    """A person has checked the platform and found the post live: close a stopped task as published."""
    if args.get("checked_backstage") is not True:
        raise core.ValidationError("确认前必须先在平台后台看到这篇笔记，并带 checked_backstage: true")
    message = str(args.get("message") or "").strip()
    if not message:
        raise core.ValidationError("确认必须写明在哪里看到的")
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        payload, _ = _find(args.get("id"), c)
        if payload["state"] not in {"needs_attention", "unknown"}:
            raise core.ValidationError("只有停住的任务可以确认为已发布")
        payload.update(state="published", message=message, updated_at=core.now(),
                       confirmed={"at": core.now(), "message": message, "checked_backstage": True})
        for key in ("url", "note_id", "published_at"):
            if args.get(key):
                payload[key] = str(args[key])
        payload.setdefault("events", []).append({"event": "published", "at": payload["updated_at"], "message": "人工确认已发布：" + message, "evidence": None})
        c.execute("UPDATE publishing_queue SET payload=?,state=?,updated_at=? WHERE id=?",
                  (json.dumps(payload, ensure_ascii=False), "published", payload["updated_at"], args.get("id")))
    return {"job": payload}


def hide(args: dict[str, Any]) -> dict[str, Any]:
    """Take a finished or stopped task off the queue list; the row and its history stay."""
    with _db() as c:
        c.execute("BEGIN IMMEDIATE")
        payload, _ = _find(args.get("id"), c)
        if payload["state"] not in {"published", "under_review", "failed", "cancelled", "needs_attention", "unknown", "needs_login"}:
            raise core.ValidationError("进行中的任务不能清除")
        payload["hidden"] = {"at": core.now(), "message": str(args.get("message") or "").strip()[:200]}
        payload["updated_at"] = core.now()
        c.execute("UPDATE publishing_queue SET payload=?,updated_at=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), payload["updated_at"], args.get("id")))
    return {"job": payload}


def save_defaults(args: dict[str, Any]) -> dict[str, Any]:
    account_id = args.get("account_id")
    _accounts([account_id])
    defaults = args.get("defaults")
    if not isinstance(defaults, dict): raise core.ValidationError("defaults 必须是对象")
    with _db() as c:
        row = c.execute("SELECT payload FROM publishing_defaults WHERE account_id=?", (account_id,)).fetchone()
        value = json.loads(row["payload"]) if row else {}
    incoming = {k: v for k, v in defaults.items() if k in {"topics", "copy_body", "allow_body_copy", "visibility", "allow_comment", "allow_save"}}
    if "copy_body" in incoming and "allow_body_copy" not in incoming:
        incoming["allow_body_copy"] = incoming["copy_body"]
    incoming.pop("copy_body", None)
    if "topics" in incoming:
        if not isinstance(incoming["topics"], list) or any(not isinstance(x, str) or not x.strip() for x in incoming["topics"]):
            raise core.ValidationError("defaults.topics 必须是非空字符串列表")
        incoming["topics"] = list(dict.fromkeys(x.strip().lstrip("#") for x in incoming["topics"]))
    if "visibility" in incoming and incoming["visibility"] not in {"public", "private"}:
        raise core.ValidationError("defaults.visibility 必须是 public 或 private")
    for key in ("allow_body_copy", "allow_comment", "allow_save"):
        if key in incoming and not isinstance(incoming[key], bool):
            raise core.ValidationError(f"defaults.{key} 必须是布尔值")
    value.update(incoming)
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO publishing_defaults VALUES(?,?,?)", (account_id, json.dumps(value, ensure_ascii=False), core.now()))
    return {"defaults": value, "account_id": account_id}


def dispatch(action: str, args: dict[str, Any]) -> dict[str, Any]:
    handlers = {"preview": lambda value: preview(value.get("work_id") if isinstance(value, dict) else value),
                "snapshot": lambda _: snapshot(), "enqueue_work": enqueue_work,
                "claim": claim, "event": event, "cancel": cancel, "retry": retry, "void": void, "confirm": confirm, "hide": hide, "save_defaults": save_defaults}
    if action not in handlers:
        raise core.ValidationError("没有这个发布队列操作")
    return handlers[action](args)

