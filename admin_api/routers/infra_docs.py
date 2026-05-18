"""
infra_docs — operator-facing read API for the SERVER_*.md system map.

Per docs/INFRA_VIEW_PLAN.md: this is a thin read API. The cache is
populated by tasks.infra_docs_sync; this router only exposes it.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from auth import get_current_user
from db import get_pg
from tasks.infra_docs_sync import sync_once

router = APIRouter()


def _row_to_summary(row: dict) -> dict:
    """Trimmed row for list views — content_md kept out."""
    return {
        "slug": row["slug"],
        "title": row["title"],
        "section_num": row["section_num"],
        "bytes": row["bytes"],
        "last_modified": row["last_modified"].isoformat() if row["last_modified"] else None,
        "last_synced_at": row["last_synced_at"].isoformat() if row["last_synced_at"] else None,
    }


def _row_to_full(row: dict) -> dict:
    out = _row_to_summary(row)
    out["source_path"] = row["source_path"]
    out["content_md"] = row["content_md"]
    out["content_hash"] = row["content_hash"]
    return out


@router.get("")
def list_docs(current_user: dict = Depends(get_current_user)):
    """All ingested docs (full content included).

    Total payload is ~150 KB across all SERVER_*.md files; client-side
    search filters this once it's in memory (per the plan).
    """
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT slug, title, source_path, section_num, content_md,
               content_hash, bytes, last_modified, last_synced_at
          FROM infra_docs
         ORDER BY section_num NULLS LAST, slug
        """
    )
    rows = [_row_to_full(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return {"docs": rows, "count": len(rows)}


@router.get("/{slug}")
def get_doc(slug: str, current_user: dict = Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT slug, title, source_path, section_num, content_md,
               content_hash, bytes, last_modified, last_synced_at
          FROM infra_docs
         WHERE slug = %s
        """,
        (slug,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="doc not found")
    return _row_to_full(row)


@router.post("/sync")
def manual_sync(current_user: dict = Depends(get_current_user)):
    """Operator-triggered refresh — same path as the periodic task."""
    return sync_once()
