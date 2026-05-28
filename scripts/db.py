"""
SQLite storage for website analyses.

Tables:
  analyses — one row per analysis run (append-only)
  sites    — one row per unique domain (upserted on each run)
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "analyses.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS analyses (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                url                     TEXT NOT NULL,
                domain                  TEXT NOT NULL,
                analysis_date           TEXT NOT NULL,
                business_model          TEXT,
                site_intelligence_score INTEGER,
                seo_score               INTEGER,
                technical_score         INTEGER,
                business_score          INTEGER,
                trust_score             INTEGER,
                full_report_json        TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sites (
                domain      TEXT PRIMARY KEY,
                first_seen  TEXT NOT NULL,
                category    TEXT,
                location    TEXT,
                is_seed     INTEGER DEFAULT 0
            );
        """)


def save_analysis(
    final_report: dict,
    category: str | None = None,
    location: str | None = None,
    is_seed: bool = False,
) -> int:
    """
    Insert a new row into analyses, upsert the matching sites row.
    Returns the new analysis id.
    """
    score = final_report.get("site_intelligence_score", {})
    summary = final_report.get("summary", {})

    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO analyses
                (url, domain, analysis_date, business_model,
                 site_intelligence_score, seo_score, technical_score,
                 business_score, trust_score, full_report_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                final_report.get("url"),
                final_report.get("domain"),
                final_report.get("analysis_date"),
                summary.get("business_model"),
                score.get("total"),
                score.get("seo_health"),
                score.get("technical_health"),
                score.get("business_clarity"),
                score.get("trust_signals"),
                json.dumps(final_report, default=str),
            ),
        )
        analysis_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO sites (domain, first_seen, category, location, is_seed)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                category = COALESCE(excluded.category, category),
                location = COALESCE(excluded.location, location),
                is_seed  = MAX(is_seed, excluded.is_seed)
            """,
            (
                final_report.get("domain"),
                final_report.get("analysis_date"),
                category,
                location,
                1 if is_seed else 0,
            ),
        )

    return analysis_id or 0


def get_analysis(url: str) -> dict | None:
    """Return the most recent analysis for a URL, or None if not found."""
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT full_report_json FROM analyses
            WHERE url = ?
            ORDER BY analysis_date DESC
            LIMIT 1
            """,
            (url,),
        ).fetchone()
    return json.loads(row["full_report_json"]) if row else None


def get_all_analyses() -> list[dict]:
    """Return summary rows for every analysis, newest first (for history sidebar)."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, url, domain, analysis_date, business_model,
                   site_intelligence_score
            FROM analyses
            ORDER BY analysis_date DESC
            """,
        ).fetchall()
    return [dict(r) for r in rows]
