"""
pagecount_db.py
PrinterAgent - Page-count history (SQLite) for "printed today" deltas

Stores one row per printer per reading, so we can compute:
  - current total pages
  - pages printed today (latest total - first total seen today)
  - pages printed since the previous reading

Uses its own table in the same data/ folder. WAL mode = safe concurrent
reads/writes with the toner background scanner.

Public API:
    init_pagecount_db()
    record_page_counts(rows)            # rows from page_counts.read_all_page_counts
    get_today_deltas()                  # [{key, total, printed_today, ...}]
    get_printer_page_history(key, days) # trend rows
"""

import os
import sqlite3
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_FILE = os.path.join(DATA_DIR, "pagecounts.db")
os.makedirs(DATA_DIR, exist_ok=True)


def _connect():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_pagecount_db():
    conn = _connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_readings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                printer_key   TEXT NOT NULL,
                display_name  TEXT,
                ip            TEXT,
                total_pages   INTEGER,
                recorded_at   TEXT NOT NULL,
                recorded_day  TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pc_lookup
            ON page_readings (printer_key, recorded_at);
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pc_day
            ON page_readings (printer_key, recorded_day);
        """)
        conn.commit()
        print(f"pagecount_db: ready at {DB_FILE}")
    finally:
        conn.close()


def record_page_counts(rows):
    """
    Save a batch of readings (only ones with a numeric total).
    `rows` is the list from page_counts.read_all_page_counts().
    """
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    day = now.strftime("%Y-%m-%d")

    batch = []
    for r in rows:
        total = r.get("total_pages")
        if total is None:
            continue
        batch.append((
            r.get("key"), r.get("display_name"), r.get("ip"),
            int(total), ts, day,
        ))

    if not batch:
        return 0

    conn = _connect()
    try:
        conn.executemany("""
            INSERT INTO page_readings
                (printer_key, display_name, ip, total_pages, recorded_at, recorded_day)
            VALUES (?,?,?,?,?,?);
        """, batch)
        conn.commit()
        return len(batch)
    finally:
        conn.close()


def get_today_deltas():
    """
    For each printer, return the current total and how many pages were
    printed TODAY (latest total minus the first total recorded today).
    """
    day = datetime.now().strftime("%Y-%m-%d")
    conn = _connect()
    try:
        # latest reading per printer
        latest = conn.execute("""
            SELECT p.printer_key, p.display_name, p.ip, p.total_pages, p.recorded_at
            FROM page_readings p
            JOIN (
                SELECT printer_key, MAX(id) AS mid
                FROM page_readings GROUP BY printer_key
            ) m ON p.id = m.mid;
        """).fetchall()

        # first reading TODAY per printer
        first_today = conn.execute("""
            SELECT p.printer_key, p.total_pages AS first_total
            FROM page_readings p
            JOIN (
                SELECT printer_key, MIN(id) AS mid
                FROM page_readings
                WHERE recorded_day = ?
                GROUP BY printer_key
            ) m ON p.id = m.mid;
        """, (day,)).fetchall()

        first_map = {r["printer_key"]: r["first_total"] for r in first_today}

        out = []
        for r in latest:
            key = r["printer_key"]
            total = r["total_pages"]
            first = first_map.get(key)
            printed_today = (total - first) if (first is not None and total is not None) else None
            out.append({
                "key": key,
                "display_name": r["display_name"],
                "ip": r["ip"],
                "total_pages": total,
                "printed_today": printed_today,
                "last_reading": r["recorded_at"],
            })
        # busiest first
        out.sort(key=lambda x: (x["total_pages"] or -1), reverse=True)
        return out
    finally:
        conn.close()


def get_printer_page_history(printer_key, days=30):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT total_pages, recorded_at
            FROM page_readings
            WHERE printer_key = ? AND recorded_at >= ?
            ORDER BY recorded_at ASC;
        """, (printer_key, since)).fetchall()
        return [{"total_pages": r["total_pages"], "recorded_at": r["recorded_at"]} for r in rows]
    finally:
        conn.close()


def purge_old(days=365):
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM page_readings WHERE recorded_at < ?;", (cutoff,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


if __name__ == "__main__":
    # Self-test: simulate two readings for one printer (today) -> delta
    init_pagecount_db()
    conn = _connect()
    conn.execute("DELETE FROM page_readings WHERE printer_key='TEST'")
    conn.commit()
    conn.close()

    today = datetime.now().strftime("%Y-%m-%d")
    record_page_counts([{"key": "TEST", "display_name": "Test", "ip": "1.1.1.1", "total_pages": 1000}])
    # simulate a later reading same day
    conn = _connect()
    conn.execute("""INSERT INTO page_readings
        (printer_key, display_name, ip, total_pages, recorded_at, recorded_day)
        VALUES ('TEST','Test','1.1.1.1', 1240, ?, ?)""",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), today))
    conn.commit(); conn.close()

    for d in get_today_deltas():
        if d["key"] == "TEST":
            print("Delta test:", d)
