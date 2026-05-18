"""
infra_docs_sync — ingest the SERVER_*.md system map from the local
glitch-trade-app working tree into the admin_api `infra_docs` cache.

Source-of-truth path: /home/support/glitch-trade-app/docs/SERVER_*.md
(plus SERVER_CONSOLIDATION_LOG.md + SERVER_CONSOLIDATION_CHECKLIST.md).

The cache is read-only from the admin panel — every operator-visible
row here is derivable from re-running this sync. Per
docs/INFRA_VIEW_PLAN.md §2: 5-minute cadence via FastAPI background
task; manual button hits sync_once() through POST /api/infra-docs/sync.
"""
from __future__ import annotations

import asyncio
import glob
import hashlib
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from db import get_pg

SOURCE_DIR = Path(os.environ.get(
    "INFRA_DOCS_SOURCE_DIR",
    "/home/support/glitch-trade-app/docs",
))

# Files to ingest: the 12 SERVER_* sectional artifacts + the
# consolidation log + checklist. Anything else matching SERVER_*.md
# is also picked up (e.g. SERVER_INCIDENT_*) so the surface stays in
# step with the docs track.
GLOB_PATTERNS = ["SERVER_*.md"]

# Section-number extractor for the 12 sectional docs. The
# consolidation log + checklist + ad-hoc artifacts get NULL.
_SECTION_PATTERNS = [
    (re.compile(r"section\s+1\b", re.IGNORECASE), "SERVER_PRODUCT_MAP.md",         1),
    (re.compile(r"section\s+2\b", re.IGNORECASE), "SERVER_DB_OWNERSHIP.md",        2),
    (re.compile(r"section\s+3\b", re.IGNORECASE), "SERVER_REPO_MAP.md",            3),
    (re.compile(r"section\s+4\b", re.IGNORECASE), "SERVER_RUNTIME_MAP.md",         4),
    (re.compile(r"section\s+5\b", re.IGNORECASE), "SERVER_ENV_MAP.md",             5),
    (re.compile(r"section\s+6\b", re.IGNORECASE), "SERVER_ROUTING_MAP.md",         6),
    (re.compile(r"section\s+7\b", re.IGNORECASE), "SERVER_STORAGE_MAP.md",         7),
    (re.compile(r"section\s+8\b", re.IGNORECASE), "SERVER_CRON_MAP.md",            8),
    (re.compile(r"section\s+9\b", re.IGNORECASE), "SERVER_OBSERVABILITY.md",       9),
    (re.compile(r"section\s+10\b", re.IGNORECASE), "SERVER_BACKUPS.md",           10),
    (re.compile(r"section\s+11\b", re.IGNORECASE), "SERVER_OWNERSHIP_RULES.md",   11),
    (re.compile(r"section\s+12\b", re.IGNORECASE), "SERVER_RETIREMENT_QUEUE.md",  12),
]


def _slug_for(path: Path) -> str:
    """server-product-map for SERVER_PRODUCT_MAP.md."""
    name = path.stem  # 'SERVER_PRODUCT_MAP'
    return name.lower().replace("_", "-")


def _section_num_for(path: Path) -> int | None:
    """Section number for the 12 sectional docs; None otherwise."""
    fname = path.name
    for _pat, expected, num in _SECTION_PATTERNS:
        if fname == expected:
            return num
    return None


def _title_for(content: str, fallback: str) -> str:
    """First '# …' line; falls back to filename if absent."""
    for line in content.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return fallback


def _iter_source_files() -> Iterable[Path]:
    for pat in GLOB_PATTERNS:
        for raw in glob.glob(str(SOURCE_DIR / pat)):
            p = Path(raw)
            if p.is_file():
                yield p


def sync_once() -> dict:
    """Run one sync pass. Returns a summary the caller can log / return.

    Strategy: upsert by slug. If a file's content hash is unchanged we
    only bump last_synced_at (so freshness is visible). Files missing
    from disk get their row deleted — the system-map track does retire
    artifacts occasionally and the panel should reflect that.
    """
    started_at = time.time()
    summary = {"inserted": 0, "updated": 0, "deleted": 0, "unchanged": 0, "errors": []}

    if not SOURCE_DIR.is_dir():
        summary["errors"].append(f"source dir missing: {SOURCE_DIR}")
        summary["elapsed_ms"] = int((time.time() - started_at) * 1000)
        return summary

    seen_slugs: set[str] = set()

    conn = get_pg()
    try:
        cur = conn.cursor()
        for path in _iter_source_files():
            try:
                content = path.read_text(encoding="utf-8")
            except Exception as e:
                summary["errors"].append(f"read {path.name}: {e}")
                continue

            slug = _slug_for(path)
            seen_slugs.add(slug)
            title = _title_for(content, path.stem)
            section_num = _section_num_for(path)
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            bytes_len = len(content.encode("utf-8"))
            try:
                mtime_ts = path.stat().st_mtime
                last_modified = datetime.fromtimestamp(mtime_ts, tz=timezone.utc)
            except Exception:
                last_modified = datetime.now(tz=timezone.utc)
            now = datetime.now(tz=timezone.utc)

            cur.execute("SELECT content_hash FROM infra_docs WHERE slug = %s", (slug,))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """
                    INSERT INTO infra_docs
                        (slug, title, source_path, section_num, content_md,
                         content_hash, bytes, last_modified, last_synced_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (slug, title, str(path), section_num, content,
                     content_hash, bytes_len, last_modified, now),
                )
                summary["inserted"] += 1
            elif row["content_hash"] != content_hash:
                cur.execute(
                    """
                    UPDATE infra_docs
                       SET title = %s,
                           source_path = %s,
                           section_num = %s,
                           content_md = %s,
                           content_hash = %s,
                           bytes = %s,
                           last_modified = %s,
                           last_synced_at = %s
                     WHERE slug = %s
                    """,
                    (title, str(path), section_num, content, content_hash,
                     bytes_len, last_modified, now, slug),
                )
                summary["updated"] += 1
            else:
                cur.execute(
                    "UPDATE infra_docs SET last_synced_at = %s WHERE slug = %s",
                    (now, slug),
                )
                summary["unchanged"] += 1

        # DELETE rows whose source file is gone from disk.
        if seen_slugs:
            placeholders = ",".join(["%s"] * len(seen_slugs))
            cur.execute(
                f"DELETE FROM infra_docs WHERE slug NOT IN ({placeholders})",
                tuple(seen_slugs),
            )
            summary["deleted"] = cur.rowcount or 0
        else:
            # No files at all on disk — nuke the cache so the panel
            # shows an honest empty state rather than stale rows.
            cur.execute("DELETE FROM infra_docs")
            summary["deleted"] = cur.rowcount or 0

        conn.commit()
        cur.close()
    finally:
        conn.close()

    summary["elapsed_ms"] = int((time.time() - started_at) * 1000)
    return summary


async def _periodic_loop(interval_sec: int) -> None:
    # First pass runs immediately on startup so the panel is populated
    # before the operator's first request.
    while True:
        try:
            sync_once()
        except Exception as e:
            print(f"[infra_docs_sync] error: {e}")
        await asyncio.sleep(interval_sec)


def start_background_sync(app, interval_sec: int = 300) -> None:
    """Wire the periodic sync into FastAPI's startup lifecycle.

    Called from main.py once. Uses on_event so the existing on_event
    startup pattern is preserved — switching to lifespan handlers is
    a separate cleanup.
    """
    @app.on_event("startup")
    async def _kick_off_sync():
        # Schedule but don't await — the periodic loop runs forever.
        asyncio.create_task(_periodic_loop(interval_sec))
