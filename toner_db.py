"""
toner_db.py
PrinterAgent - Toner History Database (SQLite)

Why this exists:
  - Flat JSON snapshots only hold the LATEST reading.
  - To show trends (sparklines) and forecasts ("~3 days until empty")
    we need HISTORY: every toner reading over time.
  - SQLite is a single file, zero-install, no admin, handles this
    scale easily, and avoids the file-lock issues of JSON writes.

What it stores:
  - One row per (printer, colour) per scan, with timestamp + percentage.

Public functions:
  init_db()                       -> create tables if missing
  record_fleet(results)           -> save a whole scan's readings
  get_history(key, color, days)   -> list of {ts, percentage}
  get_sparkline(key, color, pts)  -> compact list of percentages
  get_forecast(key, color)        -> {days_left, rate_per_day, ...}
  get_all_forecasts()             -> {key: {color: forecast}}
"""

import os
import sqlite3
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_FILE = os.path.join(DATA_DIR, "toner_history.db")

os.makedirs(DATA_DIR, exist_ok=True)

# Only track the 4 CMYK toners for trends/forecasts (ignore drums, fuser, etc.)
TRACKED_COLORS = ("Black", "Cyan", "Magenta", "Yellow")


# =============================================================
# CONNECTION
# =============================================================

def _connect():
    """
    Open a connection. WAL mode + timeout make concurrent reads/writes
    from the background scanner and the dashboard safe.
    """
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


# =============================================================
# SCHEMA
# =============================================================

def init_db():
    """Create tables and indexes if they don't already exist."""
    conn = _connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS toner_readings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                printer_key   TEXT    NOT NULL,
                display_name  TEXT,
                ip            TEXT,
                color         TEXT    NOT NULL,
                percentage    REAL,
                status        TEXT,
                recorded_at   TEXT    NOT NULL
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_toner_lookup
            ON toner_readings (printer_key, color, recorded_at);
        """)
        conn.commit()
        print(f"toner_db: ready at {DB_FILE}")
    finally:
        conn.close()


# =============================================================
# WRITE
# =============================================================

def _color_from_name(name):
    """'Black Toner' -> 'Black'. Returns None if not a tracked colour."""
    if not name:
        return None
    for c in TRACKED_COLORS:
        if c.lower() in name.lower():
            return c
    return None


def record_fleet(results):
    """
    Save every CMYK toner reading from one fleet scan.

    `results` is the list returned by get_all_toner_status() /
    the /api/toner-status-all cache. Only online printers with real
    percentages are recorded.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    for p in results:
        if not p.get("online"):
            continue
        key = p.get("key")
        display = p.get("display_name")
        ip = p.get("ip")

        for t in p.get("toners", []):
            color = _color_from_name(t.get("name"))
            pct = t.get("percentage")
            if color is None or pct is None:
                continue
            rows.append((key, display, ip, color, float(pct),
                         t.get("status"), now))

    if not rows:
        return 0

    conn = _connect()
    try:
        conn.executemany("""
            INSERT INTO toner_readings
                (printer_key, display_name, ip, color, percentage, status, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, rows)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


# =============================================================
# READ - HISTORY / SPARKLINE
# =============================================================

def get_history(printer_key, color, days=14):
    """Return [{ts, percentage}] for one printer+colour over N days."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect()
    try:
        cur = conn.execute("""
            SELECT recorded_at AS ts, percentage
            FROM toner_readings
            WHERE printer_key = ? AND color = ? AND recorded_at >= ?
            ORDER BY recorded_at ASC;
        """, (printer_key, color, since))
        return [{"ts": r["ts"], "percentage": r["percentage"]} for r in cur.fetchall()]
    finally:
        conn.close()


def get_sparkline(printer_key, color="Black", points=20):
    """
    Return up to `points` recent percentages (oldest -> newest) for a
    compact sparkline. Downsamples evenly if there are more rows.
    """
    conn = _connect()
    try:
        cur = conn.execute("""
            SELECT percentage FROM toner_readings
            WHERE printer_key = ? AND color = ?
            ORDER BY recorded_at DESC LIMIT 500;
        """, (printer_key, color))
        vals = [r["percentage"] for r in cur.fetchall()][::-1]  # oldest->newest
    finally:
        conn.close()

    if len(vals) <= points:
        return vals

    # Even downsample to `points`
    step = len(vals) / points
    return [vals[int(i * step)] for i in range(points)]


# =============================================================
# READ - FORECAST ("days until empty")
# =============================================================

def get_forecast(printer_key, color="Black", lookback_days=14):
    """
    Estimate days until this toner hits 0%, using linear regression
    (least squares) over recent readings.

    Returns:
      {
        "color": "Black",
        "current": 8.0,
        "rate_per_day": 2.5,      # % consumed per day (positive = depleting)
        "days_left": 3.2,         # None if not enough data / not depleting
        "empty_date": "2026-08-26",
        "confidence": "low|medium|high"
      }
    """
    history = get_history(printer_key, color, days=lookback_days)

    if len(history) < 2:
        return {
            "color": color, "current": history[-1]["percentage"] if history else None,
            "rate_per_day": None, "days_left": None,
            "empty_date": None, "confidence": "none"
        }

    # Convert timestamps to days since first reading (x), percentage (y)
    t0 = datetime.strptime(history[0]["ts"], "%Y-%m-%d %H:%M:%S")
    xs, ys = [], []
    for h in history:
        t = datetime.strptime(h["ts"], "%Y-%m-%d %H:%M:%S")
        xs.append((t - t0).total_seconds() / 86400.0)
        ys.append(h["percentage"])

    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = (n * sxx - sx * sx)

    current = ys[-1]

    if denom == 0:
        return {
            "color": color, "current": current, "rate_per_day": None,
            "days_left": None, "empty_date": None, "confidence": "low"
        }

    slope = (n * sxy - sx * sy) / denom          # % change per day
    rate_per_day = -slope                          # positive = depleting

    # If not depleting (refilled / flat / rising), no forecast
    if rate_per_day <= 0.01:
        return {
            "color": color, "current": round(current, 1),
            "rate_per_day": round(rate_per_day, 2),
            "days_left": None, "empty_date": None,
            "confidence": "low"
        }

    days_left = current / rate_per_day
    empty_date = (datetime.now() + timedelta(days=days_left)).strftime("%Y-%m-%d")

    # Confidence from number of data points + span
    span_days = xs[-1] - xs[0]
    if n >= 10 and span_days >= 5:
        confidence = "high"
    elif n >= 4:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "color": color,
        "current": round(current, 1),
        "rate_per_day": round(rate_per_day, 2),
        "days_left": round(days_left, 1),
        "empty_date": empty_date,
        "confidence": confidence
    }


def get_all_forecasts(color="Black"):
    """
    Return {printer_key: forecast} for every printer that has history
    for the given colour. Defaults to Black (the usual first-to-empty).
    """
    conn = _connect()
    try:
        cur = conn.execute("""
            SELECT DISTINCT printer_key FROM toner_readings WHERE color = ?;
        """, (color,))
        keys = [r["printer_key"] for r in cur.fetchall()]
    finally:
        conn.close()

    return {k: get_forecast(k, color) for k in keys}


# =============================================================
# MAINTENANCE
# =============================================================

def purge_old(days=90):
    """Delete readings older than N days to keep the DB small."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM toner_readings WHERE recorded_at < ?;", (cutoff,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


if __name__ == "__main__":
    # Quick self-test with synthetic depleting data
    init_db()

    from datetime import datetime as _dt
    demo = []
    # Simulate 10 days of Black toner dropping 5%/day from 60% -> 15%
    conn = _connect()
    conn.execute("DELETE FROM toner_readings WHERE printer_key='TEST_PRINTER';")
    for d in range(10):
        ts = (_dt.now() - timedelta(days=9 - d)).strftime("%Y-%m-%d %H:%M:%S")
        pct = 60 - d * 5
        conn.execute("""INSERT INTO toner_readings
            (printer_key, display_name, ip, color, percentage, status, recorded_at)
            VALUES (?,?,?,?,?,?,?)""",
            ("TEST_PRINTER", "Test Printer", "1.2.3.4", "Black", pct, "Low", ts))
    conn.commit()
    conn.close()

    print("\nSparkline:", get_sparkline("TEST_PRINTER", "Black"))
    print("Forecast :", get_forecast("TEST_PRINTER", "Black"))
