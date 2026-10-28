"""Rebuildable relational index. All lists use child tables, not JSON blobs."""
from __future__ import annotations
SCHEMA_VERSION = 4   # 3: works.cover_rule, items.client; 4: 数据记录 tables
TABLES = ("metric_analysis_tags", "metric_analyses", "metric_retention",
          "metric_observations", "account_analysis_tags", "account_analyses",
          "account_observations",
          "timeline", "issues", "evidence", "archives", "documents",
          "package_sections", "publish_records", "media", "versions",
          "item_versions", "item_thumbs", "items", "works", "index_meta")
SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS works (
 id TEXT PRIMARY KEY, category TEXT, date TEXT, client TEXT, title TEXT,
 status TEXT, verified INTEGER, path TEXT, relative_path TEXT, updated_at TEXT,
 created_at TEXT, latest_version TEXT, current_version TEXT, media_match TEXT,
 expected_sha256 TEXT, cover_source TEXT, cover_cache TEXT,
 note TEXT, tags TEXT, tool TEXT,
 cover_rule TEXT
);
CREATE TABLE IF NOT EXISTS versions (
 work_id TEXT REFERENCES works ON DELETE CASCADE, name TEXT, prompt TEXT,
 prompt_path TEXT, created_at TEXT, media_count INTEGER, returns_count INTEGER,
 PRIMARY KEY(work_id,name)
);
CREATE TABLE IF NOT EXISTS media (
 work_id TEXT REFERENCES works ON DELETE CASCADE, version_name TEXT, name TEXT,
 path TEXT, role TEXT, mime_type TEXT, size INTEGER, modified_at TEXT,
 position INTEGER, sha256 TEXT, PRIMARY KEY(work_id,path)
);
CREATE TABLE IF NOT EXISTS publish_records (
 work_id TEXT REFERENCES works ON DELETE CASCADE, position INTEGER,
 platform TEXT, account TEXT, url TEXT, published_at TEXT, sha256 TEXT,
 verified INTEGER, state TEXT, source_path TEXT, source_heading TEXT,
 evidence TEXT,
 PRIMARY KEY(work_id,position)
);
CREATE TABLE IF NOT EXISTS package_sections (
 work_id TEXT REFERENCES works ON DELETE CASCADE, platform TEXT, caption TEXT,
 PRIMARY KEY(work_id,platform)
);
CREATE TABLE IF NOT EXISTS documents (
 work_id TEXT REFERENCES works ON DELETE CASCADE, name TEXT, content TEXT,
 modified_at TEXT, PRIMARY KEY(work_id,name)
);
CREATE TABLE IF NOT EXISTS archives (
 work_id TEXT REFERENCES works ON DELETE CASCADE, position INTEGER, path TEXT,
 PRIMARY KEY(work_id,position)
);
CREATE TABLE IF NOT EXISTS evidence (
 work_id TEXT REFERENCES works ON DELETE CASCADE, position INTEGER,
 kind TEXT, description TEXT, source TEXT, PRIMARY KEY(work_id,position)
);
CREATE TABLE IF NOT EXISTS issues (
 work_id TEXT REFERENCES works ON DELETE CASCADE, position INTEGER,
 description TEXT,
 PRIMARY KEY(work_id,position)
);
CREATE TABLE IF NOT EXISTS timeline (
 work_id TEXT REFERENCES works ON DELETE CASCADE, position INTEGER,
 kind TEXT, at TEXT, description TEXT, source TEXT,
 PRIMARY KEY(work_id,position)
);
CREATE TABLE IF NOT EXISTS items (
 id TEXT PRIMARY KEY, kind TEXT, section TEXT, title TEXT, text TEXT,
 body TEXT, note TEXT, tags TEXT, tool TEXT, source TEXT, path TEXT,
 file TEXT, modified_at TEXT, work_id TEXT, code TEXT, status TEXT,
 client TEXT
);
-- thumbnail name per picture/video item (its own table, so an index built by an
-- older SPT that shares this file keeps working); as_is: small enough to show as is
CREATE TABLE IF NOT EXISTS item_thumbs (
 item_id TEXT PRIMARY KEY, name TEXT, as_is INTEGER
);
-- the version folder of a prompt from a work's V*/正文.txt (see Item in models.py);
-- superseded rows stay out of lists and counts unless all versions are asked for.
-- Its own table for the same reason as item_thumbs; an SPT that does not know it
-- empties items on rebuild, which takes these rows along instead of leaving stale ones.
CREATE TABLE IF NOT EXISTS item_versions (
 item_id TEXT PRIMARY KEY REFERENCES items ON DELETE CASCADE, version TEXT,
 superseded INTEGER, adopted INTEGER
);
-- 数据记录 (spt/docs/数据记录格式.md). One row per 表现.csv line; `at` is UTC ISO so
-- rows sort as text, age_hours is hours since publication on that platform (NULL
-- without a publish time). Numbers are REAL and NULL when the cell was empty.
CREATE TABLE IF NOT EXISTS metric_observations (
 work_id TEXT REFERENCES works ON DELETE CASCADE, position INTEGER,
 at TEXT, age_hours REAL, platform TEXT, account TEXT,
 views REAL, reach REAL, likes REAL, comments REAL, saves REAL, shares REAL,
 profile_visits REAL, follows REAL, ctr REAL, three_sec_rate REAL,
 completion_rate REAL, avg_watch_sec REAL, source TEXT, note TEXT, path TEXT,
 PRIMARY KEY(work_id,position)
);
CREATE TABLE IF NOT EXISTS metric_retention (
 work_id TEXT REFERENCES works ON DELETE CASCADE, position INTEGER,
 at TEXT, platform TEXT, account TEXT, second REAL, rate REAL, path TEXT,
 PRIMARY KEY(work_id,position)
);
CREATE TABLE IF NOT EXISTS metric_analyses (
 work_id TEXT REFERENCES works ON DELETE CASCADE, path TEXT, date TEXT,
 platform TEXT, account TEXT, node TEXT, conclusion TEXT, body TEXT,
 modified_at TEXT, PRIMARY KEY(work_id,path)
);
CREATE TABLE IF NOT EXISTS metric_analysis_tags (
 work_id TEXT REFERENCES works ON DELETE CASCADE, path TEXT, tag TEXT,
 PRIMARY KEY(work_id,path,tag)
);
-- account level: 工作区/数据/账号/<平台>-<账号>/
CREATE TABLE IF NOT EXISTS account_observations (
 platform TEXT, account TEXT, position INTEGER, at TEXT,
 followers REAL, views REAL, reach REAL, interactions REAL, likes REAL,
 comments REAL, saves REAL, shares REAL, profile_visits REAL, follows REAL,
 source TEXT, note TEXT, path TEXT, PRIMARY KEY(platform,account,position)
);
CREATE TABLE IF NOT EXISTS account_analyses (
 platform TEXT, account TEXT, path TEXT PRIMARY KEY, date TEXT, node TEXT,
 conclusion TEXT, body TEXT, modified_at TEXT
);
CREATE TABLE IF NOT EXISTS account_analysis_tags (
 path TEXT REFERENCES account_analyses ON DELETE CASCADE, tag TEXT,
 PRIMARY KEY(path,tag)
);
CREATE INDEX IF NOT EXISTS metric_observations_account
 ON metric_observations(platform,account);
CREATE INDEX IF NOT EXISTS metric_retention_work ON metric_retention(work_id,at);
CREATE INDEX IF NOT EXISTS metric_analyses_account
 ON metric_analyses(platform,account);
CREATE INDEX IF NOT EXISTS metric_analysis_tag ON metric_analysis_tags(tag);
CREATE INDEX IF NOT EXISTS account_analysis_tag ON account_analysis_tags(tag);
CREATE INDEX IF NOT EXISTS works_category_status ON works(category,status);
CREATE INDEX IF NOT EXISTS record_url ON publish_records(url);
CREATE INDEX IF NOT EXISTS items_kind_section ON items(kind,section);
CREATE INDEX IF NOT EXISTS items_work ON items(work_id);
CREATE INDEX IF NOT EXISTS items_client ON items(client);
"""
