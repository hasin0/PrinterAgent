"""
page_counts_db.py
PrinterAgent - Page-count history + toner-yield tracking (SQLite)

Builds on page_counts.py (which reads total/mono/color from SNMP).
This stores a daily reading per printer so we can compute:

  1. pages_per_day(key, days=7)
       -> [{date, total, mono, color, delta_total, delta_mono, delta_color}]
     'delta_*' = pages printed THAT day (today's counter - yesterday's).
     Powers the 7-day pages-per-day trend chart.

  2. pages_per_toner(key, color="Black")
       -> how many pages were printed on the CURRENT toner cartridge, by
          detecting the last refill (toner % jumped UP) and summing the
          page deltas since then. This is the "print per toner" / yield.

Storage: data/page_counts.db  (WAL mode, safe with the daily scanner)

Public API:
  init_db()
  record(key, ip, total, mono, color, black_pct=None)   # once per scan/day
  pages_per_day(key, days=7)
  pages_per_toner(key, color="Black")
  latest(key)
"""

import os
import sqlite3
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_FILE = os.path.join(DATA_DIR, "page_counts.db")
os.makedirs(DATA_DIR, exist_ok=True)


def _connect():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db():
    conn = _connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_readings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                printer_key TEXT NOT NULL,
                ip          TEXT,
                total       INTEGER,
                mono        INTEGER,
                color       INTEGER,
                black_pct   REAL,
                recorded_at TEXT NOT NULL,
                day         TEXT NOT NULL          -- YYYY-MM-DD (one row/day/printer)
            );
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_page_day
            ON page_readings (printer_key, day);
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS ix_page_key
            ON page_readings (printer_key, recorded_at);
        """)
        conn.commit()
        print(f"page_counts_db: ready at {DB_FILE}")
    finally:
        conn.close()


def record(key, ip, total, mono=None, color=None, black_pct=None):
    """
    Store today's counters for a printer. One row per printer per day -
    re-running the scan the same day UPDATES that day's row (upsert), so
    the latest read of the day wins.
    """
    if key is None or total is None:
        return False

    now = datetime.now()
    day = now.strftime("%Y-%m-%d")
    ts = now.strftime("%Y-%m-%d %H:%M:%S")

    conn = _connect()
    try:
        conn.execute("""
            INSERT INTO page_readings
                (printer_key, ip, total, mono, color, black_pct, recorded_at, day)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(printer_key, day) DO UPDATE SET
                ip=excluded.ip, total=excluded.total, mono=excluded.mono,
                color=excluded.color, black_pct=excluded.black_pct,
                recorded_at=excluded.recorded_at;
        """, (key, ip, total, mono, color, black_pct, ts, day))
        conn.commit()
        return True
    finally:
        conn.close()


def _rows(key, days):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = _connect()
    try:
        cur = conn.execute("""
            SELECT day, total, mono, color, black_pct
            FROM page_readings
            WHERE printer_key=? AND day>=?
            ORDER BY day ASC;
        """, (key, since))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def pages_per_day(key, days=7):
    """
    Return per-day pages PRINTED (deltas), oldest -> newest.
    Needs at least 2 daily readings to produce a delta.
    """
    rows = _rows(key, days + 1)   # +1 so the first day in-range has a prior
    out = []
    prev = None
    for r in rows:
        entry = {"date": r["day"], "total": r["total"],
                 "mono": r["mono"], "color": r["color"],
                 "delta_total": None, "delta_mono": None, "delta_color": None}
        if prev is not None:
            if r["total"] is not None and prev["total"] is not None:
                entry["delta_total"] = max(r["total"] - prev["total"], 0)
            if r["mono"] is not None and prev["mono"] is not None:
                entry["delta_mono"] = max(r["mono"] - prev["mono"], 0)
            if r["color"] is not None and prev["color"] is not None:
                entry["delta_color"] = max(r["color"] - prev["color"], 0)
        out.append(entry)
        prev = r

    # Trim to the requested window (drop the extra prior day)
    return out[-days:] if len(out) > days else out


def pages_per_toner(key, color="Black"):
    """
    Estimate pages printed on the CURRENT toner cartridge (yield so far).

    Method: find the most recent REFILL - a day where black_pct jumped UP
    by a meaningful amount vs the previous day - then sum total-page deltas
    from that day to now. If no refill detected, sums over all history.
    """
    rows = _rows(key, 400)   # look back up to ~13 months
    if len(rows) < 2:
        return {"key": key, "color": color, "pages_on_current_toner": None,
                "since": None, "reason": "Not enough history yet."}

    # locate last refill index (black_pct rises by >= 20 points)
    refill_idx = 0
    for i in range(1, len(rows)):
        prev_pct = rows[i - 1].get("black_pct")
        cur_pct = rows[i].get("black_pct")
        if prev_pct is not None and cur_pct is not None:
            if cur_pct - prev_pct >= 20:
                refill_idx = i

    start = rows[refill_idx]
    end = rows[-1]

    if start["total"] is None or end["total"] is None:
        return {"key": key, "color": color, "pages_on_current_toner": None,
                "since": start["day"], "reason": "Missing total counts."}

    pages = max(end["total"] - start["total"], 0)
    return {
        "key": key,
        "color": color,
        "pages_on_current_toner": pages,
        "since": start["day"],
        "current_black_pct": end.get("black_pct"),
        "reason": "since last detected refill" if refill_idx > 0
                  else "since monitoring began (no refill detected yet)",
    }


def latest(key):
    conn = _connect()
    try:
        cur = conn.execute("""
            SELECT day, total, mono, color, black_pct, recorded_at
            FROM page_readings WHERE printer_key=?
            ORDER BY day DESC LIMIT 1;
        """, (key,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


if __name__ == "__main__":
    # Self-test: simulate 8 days of printing + a toner refill on day 5
    init_db()
    conn = _connect()
    conn.execute("DELETE FROM page_readings WHERE printer_key='TESTP';")
    conn.commit(); conn.close()

    base_total = 100000
    black = 80
    for d in range(8):
        day = (datetime.now() - timedelta(days=7 - d)).strftime("%Y-%m-%d")
        base_total += 300 + d * 10          # ~300+ pages/day
        black -= 12                          # toner draining
        if d == 5:                           # refill on day 5
            black = 95
        conn = _connect()
        conn.execute("""INSERT INTO page_readings
            (printer_key, ip, total, mono, color, black_pct, recorded_at, day)
            VALUES ('TESTP','1.2.3.4',?,?,?,?,?,?)
            ON CONFLICT(printer_key,day) DO UPDATE SET
              total=excluded.total, black_pct=excluded.black_pct;""",
            (base_total, int(base_total*0.85), int(base_total*0.15),
             black, day + " 09:00:00", day))
        conn.commit(); conn.close()

    print("\n7-day pages/day:")
    for r in pages_per_day("TESTP", 7):
        print(f"  {r['date']}  total={r['total']}  printed={r['delta_total']}")

    print("\nPages per toner:", pages_per_toner("TESTP"))
