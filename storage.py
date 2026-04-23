#!/usr/bin/env python3
"""
storage.py — Persistent SQLite backbone for Parcel Scout.

Think of this file as a three-ring binder behind the scenes:
  - `parcels`    — the current roster of every parcel we've ever seen
  - `audit`      — the paper trail behind every decision (why this parcel scored X)
  - `api_calls`  — the receipts folder (who we called, when, and what it cost)
  - `scans`      — the log of each Seed/Refresh run, so audit lines group cleanly

Everything else in the codebase talks to this module via four verbs:
    start_scan() / end_scan()    → bracket a Seed or Refresh run
    upsert_parcel()              → write (or overwrite) a parcel's current state
    log_audit()                  → record a single decision about a parcel
    log_api_call()               → record one external HTTP hit (free or paid)

The DB auto-creates on first import. No migrations or setup scripts needed.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional

# ── Paths ────────────────────────────────────────────────────────────────────
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR    = os.path.join(_PROJECT_DIR, "data")
DB_PATH      = os.path.join(_DATA_DIR, "parcel_scout.sqlite")

os.makedirs(_DATA_DIR, exist_ok=True)

# ── Module-level "current scan" ──────────────────────────────────────────────
# Anything logged between start_scan() and end_scan() gets stamped with this ID.
# Outside a scan (e.g. ad-hoc UI clicks) scan_id is NULL — still recorded, just
# not tied to a run.
_current_scan_id: Optional[int] = None
_scan_lock = threading.Lock()


# ── Connection helper ────────────────────────────────────────────────────────

@contextmanager
def _conn():
    """
    Yield a SQLite connection with foreign keys on and row access by column name.
    Every call opens/closes its own connection — SQLite handles concurrent reads
    fine, and our writes are small enough that per-call connections are the
    simplest correct approach for a multi-threaded Streamlit app.
    """
    c = sqlite3.connect(DB_PATH, timeout=10.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA journal_mode = WAL")   # WAL = better concurrency under Streamlit
    try:
        yield c
        c.commit()
    finally:
        c.close()


# ── Schema ───────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    mode            TEXT NOT NULL,          -- 'SEED' or 'REFRESH'
    region          TEXT,
    duration_s      REAL,
    parcels_added   INTEGER DEFAULT 0,
    parcels_updated INTEGER DEFAULT 0,
    parcels_removed INTEGER DEFAULT 0,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS parcels (
    id                  TEXT PRIMARY KEY,       -- cadastral_id if present, else 'osm:<type>/<id>'
    region              TEXT,
    name                TEXT,
    lat                 REAL,
    lon                 REAL,
    crop_type           TEXT,
    parcel_sqm          REAL,
    parcel_acres        REAL,
    cadastral_id        TEXT,
    cadastral_foglio    TEXT,
    cadastral_particella TEXT,
    opportunity_score   REAL,
    signals_fired       INTEGER,
    status              TEXT NOT NULL DEFAULT 'ACTIVE',   -- ACTIVE or INACTIVE
    full_json           TEXT,                   -- entire parcel dict, for future-proofing
    first_seen          TEXT NOT NULL,
    last_seen           TEXT NOT NULL,
    last_scan_id        INTEGER,
    FOREIGN KEY (last_scan_id) REFERENCES scans(id)
);

CREATE INDEX IF NOT EXISTS idx_parcels_region ON parcels(region);
CREATE INDEX IF NOT EXISTS idx_parcels_status ON parcels(status);
CREATE INDEX IF NOT EXISTS idx_parcels_score  ON parcels(opportunity_score DESC);

CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    scan_id     INTEGER,
    parcel_id   TEXT,                        -- nullable: some audit lines are global (e.g. region-wide)
    step        TEXT NOT NULL,               -- e.g. 'filter.area', 'layer.digital_ghost'
    outcome     TEXT NOT NULL,               -- PASS / FAIL / SKIP / FIRED / NOT_FIRED / ERROR
    detail      TEXT,
    FOREIGN KEY (scan_id)   REFERENCES scans(id),
    FOREIGN KEY (parcel_id) REFERENCES parcels(id)
);

CREATE INDEX IF NOT EXISTS idx_audit_parcel ON audit(parcel_id);
CREATE INDEX IF NOT EXISTS idx_audit_scan   ON audit(scan_id);
CREATE INDEX IF NOT EXISTS idx_audit_ts     ON audit(ts);

CREATE TABLE IF NOT EXISTS api_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    scan_id     INTEGER,
    api         TEXT NOT NULL,               -- 'overpass', 'ade_wfs', 'corine', 'nominatim', ...
    endpoint    TEXT,                        -- URL or endpoint identifier
    status      INTEGER,                     -- HTTP status code, or 0 on exception
    cost_usd    REAL DEFAULT 0.0,
    quota_units REAL DEFAULT 1.0,            -- how many "credits" this call consumes for quota APIs
    cached      INTEGER DEFAULT 0,           -- 1 if served from cache (no quota burned)
    duration_ms INTEGER,
    FOREIGN KEY (scan_id) REFERENCES scans(id)
);

CREATE INDEX IF NOT EXISTS idx_api_ts  ON api_calls(ts);
CREATE INDEX IF NOT EXISTS idx_api_api ON api_calls(api);
"""


def _init_db() -> None:
    """Create all tables + indexes if they don't already exist. Idempotent."""
    with _conn() as c:
        c.executescript(_SCHEMA)


# Run on import — safe because CREATE TABLE IF NOT EXISTS is idempotent.
_init_db()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ── Scan lifecycle ───────────────────────────────────────────────────────────

def start_scan(mode: str, region: str = "") -> int:
    """
    Open a new scan row and remember its ID for subsequent log_* calls.
    mode must be 'SEED' or 'REFRESH'.
    Returns the new scan_id.
    """
    global _current_scan_id
    assert mode in ("SEED", "REFRESH"), f"mode must be SEED or REFRESH, got {mode!r}"
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO scans (started_at, mode, region) VALUES (?, ?, ?)",
            (_now_iso(), mode, region),
        )
        scan_id = cur.lastrowid
    with _scan_lock:
        _current_scan_id = scan_id
    return scan_id


def end_scan(
    added: int = 0,
    updated: int = 0,
    removed: int = 0,
    notes: str = "",
) -> None:
    """Close the current scan with summary counts. Clears the current scan ID."""
    global _current_scan_id
    if _current_scan_id is None:
        return
    scan_id = _current_scan_id
    with _conn() as c:
        row = c.execute("SELECT started_at FROM scans WHERE id = ?", (scan_id,)).fetchone()
        if row:
            started = datetime.fromisoformat(row["started_at"].rstrip("Z"))
            duration = (datetime.utcnow() - started).total_seconds()
        else:
            duration = None
        c.execute(
            """UPDATE scans SET ended_at = ?, duration_s = ?,
                                parcels_added = ?, parcels_updated = ?,
                                parcels_removed = ?, notes = ?
                WHERE id = ?""",
            (_now_iso(), duration, added, updated, removed, notes, scan_id),
        )
    with _scan_lock:
        _current_scan_id = None


def current_scan_id() -> Optional[int]:
    return _current_scan_id


# ── Parcel identity ──────────────────────────────────────────────────────────

def parcel_key(parcel: dict) -> str:
    """
    Build a stable primary key for a parcel.
    Prefers the official cadastral ID (definitive); falls back to OSM type+id.
    """
    cid = parcel.get("cadastral_id") or ""
    if cid:
        return f"cad:{cid}"
    otype = parcel.get("osm_type", "")
    oid   = parcel.get("osm_id", "")
    return f"osm:{otype}/{oid}"


# ── Writes ───────────────────────────────────────────────────────────────────

def upsert_parcel(parcel: dict, region: str = "") -> tuple[str, bool]:
    """
    Insert or update a parcel. Returns (parcel_id, was_new).
    The full parcel dict is JSON-serialised into `full_json` so we never lose
    fields when layer outputs change.
    """
    pid = parcel_key(parcel)
    now = _now_iso()
    blob = json.dumps(parcel, ensure_ascii=False, default=str)

    with _conn() as c:
        existing = c.execute("SELECT id FROM parcels WHERE id = ?", (pid,)).fetchone()
        was_new = existing is None

        if was_new:
            c.execute(
                """INSERT INTO parcels (
                    id, region, name, lat, lon, crop_type,
                    parcel_sqm, parcel_acres,
                    cadastral_id, cadastral_foglio, cadastral_particella,
                    opportunity_score, signals_fired,
                    status, full_json, first_seen, last_seen, last_scan_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)""",
                (
                    pid, region, parcel.get("name", ""),
                    parcel.get("lat"), parcel.get("lon"),
                    parcel.get("primary_crop_type", ""),
                    parcel.get("parcel_sqm"), parcel.get("parcel_acres"),
                    parcel.get("cadastral_id", ""),
                    parcel.get("cadastral_foglio", ""),
                    parcel.get("cadastral_particella", ""),
                    parcel.get("opportunity_score"),
                    parcel.get("signals_fired"),
                    blob, now, now, _current_scan_id,
                ),
            )
        else:
            c.execute(
                """UPDATE parcels SET
                    region = ?, name = ?, lat = ?, lon = ?, crop_type = ?,
                    parcel_sqm = ?, parcel_acres = ?,
                    cadastral_id = ?, cadastral_foglio = ?, cadastral_particella = ?,
                    opportunity_score = ?, signals_fired = ?,
                    status = 'ACTIVE', full_json = ?, last_seen = ?, last_scan_id = ?
                WHERE id = ?""",
                (
                    region, parcel.get("name", ""),
                    parcel.get("lat"), parcel.get("lon"),
                    parcel.get("primary_crop_type", ""),
                    parcel.get("parcel_sqm"), parcel.get("parcel_acres"),
                    parcel.get("cadastral_id", ""),
                    parcel.get("cadastral_foglio", ""),
                    parcel.get("cadastral_particella", ""),
                    parcel.get("opportunity_score"),
                    parcel.get("signals_fired"),
                    blob, now, _current_scan_id, pid,
                ),
            )
    return pid, was_new


def mark_inactive(region: str, seen_ids: set[str]) -> int:
    """
    Mark every ACTIVE parcel in `region` that is NOT in `seen_ids` as INACTIVE.
    Used at the end of a Refresh to note parcels that have vanished from OSM.
    Returns the count of parcels newly marked inactive.
    """
    if not region:
        return 0
    with _conn() as c:
        active = c.execute(
            "SELECT id FROM parcels WHERE region = ? AND status = 'ACTIVE'",
            (region,),
        ).fetchall()
        to_deactivate = [row["id"] for row in active if row["id"] not in seen_ids]
        for pid in to_deactivate:
            c.execute(
                "UPDATE parcels SET status = 'INACTIVE', last_scan_id = ? WHERE id = ?",
                (_current_scan_id, pid),
            )
    return len(to_deactivate)


def log_audit(
    step: str,
    outcome: str,
    detail: str = "",
    parcel_id: Optional[str] = None,
) -> None:
    """
    Record one decision. `step` is a dotted namespace like 'filter.area' or
    'layer.digital_ghost'. `outcome` is one of PASS/FAIL/SKIP/FIRED/NOT_FIRED/ERROR.
    """
    with _conn() as c:
        c.execute(
            """INSERT INTO audit (ts, scan_id, parcel_id, step, outcome, detail)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (_now_iso(), _current_scan_id, parcel_id, step, outcome, detail[:500]),
        )


def log_api_call(
    api: str,
    endpoint: str = "",
    status: int = 0,
    cost_usd: float = 0.0,
    quota_units: float = 1.0,
    cached: bool = False,
    duration_ms: Optional[int] = None,
) -> None:
    """Record one external API call. Free APIs have cost_usd=0 but still track quota_units."""
    with _conn() as c:
        c.execute(
            """INSERT INTO api_calls (ts, scan_id, api, endpoint, status,
                                       cost_usd, quota_units, cached, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (_now_iso(), _current_scan_id, api, endpoint[:300], status,
             cost_usd, quota_units, 1 if cached else 0, duration_ms),
        )


# ── Reads ────────────────────────────────────────────────────────────────────

def list_parcels(
    region: str = "",
    status: str = "ACTIVE",
    limit: int = 10_000,
) -> list[dict]:
    """Return parcels as list of full_json dicts, annotated with id and status."""
    q  = "SELECT id, status, full_json FROM parcels WHERE 1=1"
    args: list = []
    if region:
        q += " AND region = ?"; args.append(region)
    if status:
        q += " AND status = ?"; args.append(status)
    q += " ORDER BY opportunity_score DESC NULLS LAST, last_seen DESC LIMIT ?"
    args.append(limit)

    with _conn() as c:
        rows = c.execute(q, args).fetchall()

    out = []
    for row in rows:
        try:
            parcel = json.loads(row["full_json"]) if row["full_json"] else {}
        except json.JSONDecodeError:
            parcel = {}
        parcel["_db_id"] = row["id"]
        parcel["_db_status"] = row["status"]
        out.append(parcel)
    return out


def get_parcel_audit(parcel_id: str, limit: int = 500) -> list[dict]:
    """Return all audit lines for a parcel, newest first."""
    with _conn() as c:
        rows = c.execute(
            """SELECT ts, step, outcome, detail, scan_id
                 FROM audit WHERE parcel_id = ?
                ORDER BY ts DESC LIMIT ?""",
            (parcel_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def cost_summary() -> dict:
    """
    Return a dict with usage totals for the header badge.
    Shape:
      {
        'today':   {'calls': N, 'cost_usd': X, 'by_api': {api: calls}},
        'month':   {...},
        'all_time':{...},
      }
    """
    today = datetime.utcnow().strftime("%Y-%m-%d")
    month_start = (datetime.utcnow().replace(day=1)).strftime("%Y-%m-%d")

    def _window(since_date: str) -> dict:
        with _conn() as c:
            row = c.execute(
                """SELECT COUNT(*) AS calls,
                          COALESCE(SUM(cost_usd), 0) AS cost,
                          COALESCE(SUM(quota_units), 0) AS units
                     FROM api_calls WHERE ts >= ?""",
                (since_date,),
            ).fetchone()
            by_api = c.execute(
                """SELECT api, COUNT(*) AS n, COALESCE(SUM(cost_usd),0) AS cost
                     FROM api_calls WHERE ts >= ?
                 GROUP BY api ORDER BY n DESC""",
                (since_date,),
            ).fetchall()
        return {
            "calls":    row["calls"] or 0,
            "cost_usd": row["cost"] or 0.0,
            "units":    row["units"] or 0.0,
            "by_api":   [dict(r) for r in by_api],
        }

    return {
        "today":    _window(today),
        "month":    _window(month_start),
        "all_time": _window("0000-00-00"),
    }


def recent_scans(limit: int = 10) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT id, started_at, ended_at, mode, region, duration_s,
                      parcels_added, parcels_updated, parcels_removed, notes
                 FROM scans ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
