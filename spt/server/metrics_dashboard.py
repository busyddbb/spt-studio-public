"""Put the workspace's 数据记录 into the 运营/数据 dashboard snapshot.

dashboard.py assembles accounts and posts from the project CSVs; this adds the
posts the index knows from works' 数据/ folders, hangs them on the matching
account (the work's client is the brand) or makes an account entry for them,
and lets account-level rows (工作区/数据/账号) update followers and the like.
Posts from the CSVs stay as they are; a work that appears in both is not merged.
"""
from __future__ import annotations
from typing import Any

from .dashboard_accounts import empty_metrics
from .dashboard_io import PLATFORM_LABELS as DASHBOARD_LABELS
from .metrics import PLATFORM_LABELS, platform_code

ACCOUNT_FIELDS = {"followers": "followers", "views": "views", "reach": "reach",
                  "interactions": "interactions", "likes": "likes", "comments": "comments",
                  "saves": "saves", "shares": "shares", "profile_visits": "profile_visits",
                  "follows": "follows_gained"}
SOURCE = "工作区/数据"


def brand_names(code: str, clients: list[dict[str, Any]]) -> set[str]:
    """What a snapshot account's brand may be called for this client code."""
    names = {code.casefold()}
    for row in clients:
        if row.get("code") == code and row.get("name"):
            names.add(str(row["name"]).casefold())
    return names


def same_platform(account: dict[str, Any], platform: str) -> bool:
    return (platform_code(account.get("platform")) or account.get("platform")) == platform


def matching_account(accounts: list[dict[str, Any]], names: set[str], platform: str,
                     handle: str) -> dict[str, Any] | None:
    """The brand's only account on that platform, else the one whose handle is 账号."""
    owned = [item for item in accounts if same_platform(item, platform)
             and str(item.get("brand") or "").casefold() in names]
    if len(owned) == 1:
        return owned[0]
    return next((item for item in owned
                 if handle and str(item.get("handle") or "").casefold() == handle.casefold()),
                None)


def new_account(code: str, name: str, platform: str, handle: str) -> dict[str, Any]:
    label = PLATFORM_LABELS.get(platform) or DASHBOARD_LABELS.get(platform, platform)
    return {"id": f"{code}:{platform}:{handle}", "brand_id": code, "brand": name,
            "name": handle or name, "platform": platform, "platform_label": label,
            "handle": handle or None, "profile_url": None, "readonly": False,
            "login_state": "not_checked", "data_state": "workspace", "as_of": None,
            "source": SOURCE, "metrics": empty_metrics(), "display_metrics": {},
            "window_start": None, "window_end": None, "history": [],
            "latest_snapshot": None, "posts_count": 0,
            "posts_count_kind": "indexed_records"}


def attach_posts(snapshot: dict[str, Any], posts: list[dict[str, Any]],
                 clients: list[dict[str, Any]]) -> None:
    accounts = snapshot.setdefault("accounts", [])
    counted: dict[str, int] = {}
    for post in posts:
        code = post["client"]
        names = brand_names(code, clients)
        account = matching_account(accounts, names, post["platform"], post["account"])
        if account is None:
            name = next((str(row["name"]) for row in clients
                         if row.get("code") == code and row.get("name")), code)
            account = new_account(code, name, post["platform"], post["account"])
            accounts.append(account)
        post["account_id"] = account["id"]
        counted[account["id"]] = counted.get(account["id"], 0) + 1
        if post["observed_at"] and (account.get("as_of") or "") < post["observed_at"]:
            account["as_of"] = post["observed_at"]
        if account.get("data_state") == "unavailable":
            account["data_state"] = "workspace"
    for account in accounts:
        if account["id"] in counted:
            account["posts_count"] = account.get("posts_count", 0) + counted[account["id"]]


def account_entry(point: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """An account-level observation in the shape of dashboard_accounts.account_snapshot."""
    metrics = empty_metrics()
    for field, target in ACCOUNT_FIELDS.items():
        metrics[target] = point["metrics"].get(field)
    return {"date": point["at"][:10], "observed_at": point["at"], "window_start": None,
            "window_end": None, "metrics": metrics, "display_metrics": {},
            "status": "workspace", "source": point["path"],
            "source_label": point["source"] or None, "notes": point["note"]}


def owner_of(accounts: list[dict[str, Any]], entry: dict[str, Any]) -> dict[str, Any] | None:
    """The snapshot account an 账号 folder belongs to: same platform and the folder's
    账号 is its handle, name or brand."""
    handle = entry["account"].casefold()
    for account in accounts:
        if not same_platform(account, entry["platform"]):
            continue
        if handle in {str(account.get(key) or "").casefold()
                      for key in ("handle", "name", "brand")}:
            return account
    return None


def attach_accounts(snapshot: dict[str, Any], entries: list[dict[str, Any]],
                    clients: list[dict[str, Any]]) -> None:
    accounts = snapshot.setdefault("accounts", [])
    for entry in entries:
        account = owner_of(accounts, entry)
        if account is None:
            code = next((row["code"] for row in clients
                         if entry["account"].casefold() in {str(row.get("code") or "").casefold(),
                                                            str(row.get("name") or "").casefold()}),
                        None)
            account = new_account(code or entry["account"], entry["account"],
                                  entry["platform"], entry["account"])
            account["id"] = f"{code or 'workspace'}:{entry['platform']}:{entry['account']}"
            account["brand_id"] = code
            accounts.append(account)
        history = [account_entry(point, entry) for point in entry["history"]]
        if not history:
            continue
        account["history"] = sorted(account.get("history", []) + history,
                                    key=lambda snap: (snap.get("date") or "",
                                                      snap.get("observed_at") or ""))
        latest = history[-1]
        if (account.get("as_of") or "") < latest["observed_at"]:
            account.update({"as_of": latest["observed_at"], "source": latest["source"],
                            "metrics": latest["metrics"], "display_metrics": {},
                            "latest_snapshot": latest, "data_state": "workspace"})


def merge_workspace_metrics(snapshot: dict[str, Any], store: Any,
                            clients: list[dict[str, Any]]) -> dict[str, Any]:
    """Add the index's 数据记录 to a dashboard snapshot (in place; also returned)."""
    posts = store.metrics_posts() + store.recorded_posts()
    attach_posts(snapshot, posts, clients)
    attach_accounts(snapshot, store.account_metrics(), clients)
    current = snapshot.setdefault("posts", [])
    current.extend(posts)
    current.sort(key=lambda post: post.get("published_at") or post.get("observed_at") or "",
                 reverse=True)
    snapshot["analysis_tags"] = store.metrics_tags()
    snapshot.setdefault("capabilities", {})["workspace_metrics"] = True
    return snapshot
