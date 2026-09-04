"""
toner_service.py
PrinterAgent - Background Toner Scan Service

Sits between app.py (HTTP routes) and:
  - toner_monitor.py  (SNMP fleet scan + in-memory cache + snapshot)
  - reachability.py   (Online vs SNMP-Disabled classification)  [optional]
  - toner_db.py        (history for forecasts + sparklines)       [optional]

Why:
  The dashboard / Toner Center must NEVER wait for a live 15-printer SNMP
  scan. This service keeps a warm cache and runs scans in the background,
  so /api/toner-status-all and /api/toner-attention respond instantly.

Scan schedule:
  - Runs once shortly after startup (so there is fresh data immediately)
  - Then repeats every SCAN_INTERVAL_SECONDS  (DEFAULT: once per day)
  - Users get on-demand LIVE detail any time via /api/toner-check

Flow per scan:
  1. get_all_toner_status()   -> SNMP results (+ in-memory cache + snapshot)
  2. enrich_fleet()           -> add network_status/snmp_status (if available)
  3. record_fleet()           -> persist readings for trend/forecast history
"""

import asyncio
from datetime import datetime

from toner_monitor import (
    PRINTERS,
    TONER_CACHE,
    SCAN_STATUS,
    get_all_toner_status,
    get_toner_cache,
    load_snapshot,
    update_toner_cache,
)

# --- optional integrations (guarded so the service still runs if missing) ---
try:
    from reachability import enrich_fleet
    _HAS_REACH = True
except Exception:
    _HAS_REACH = False

try:
    from toner_db import record_fleet, init_db
    _HAS_DB = True
except Exception:
    _HAS_DB = False


# =============================================================
# CONFIG
# =============================================================

# DAILY scan (was 5 * 60 for every-5-minutes). Change here if you want a
# different cadence, e.g. 12 * 60 * 60 for twice a day.
SCAN_INTERVAL_SECONDS = 24 * 60 * 60      # once every 24 hours

# Wait this long after startup before the first background scan, so the
# app finishes booting and serves the cached page immediately.
INITIAL_SCAN_DELAY_SECONDS = 5

_SCAN_LOCK = asyncio.Lock()
_BACKGROUND_TASK = None


# =============================================================
# CACHE WARM-UP
# =============================================================

def warm_cache_from_snapshot():
    """
    Load the last saved snapshot into memory at startup so the dashboard
    shows last-known levels immediately after a server restart.
    """
    if _HAS_DB:
        try:
            init_db()
        except Exception as exc:
            print(f"WARNING: toner_db init failed: {exc}")

    snapshot = load_snapshot()
    if not snapshot or not snapshot.get("data"):
        print("Toner cache: no snapshot found, starting empty.")
        return 0

    for item in snapshot["data"]:
        key = item.get("key") or item.get("ip")
        item["data_source"] = "cached"
        update_toner_cache(key, item)

    count = len(TONER_CACHE)
    print(f"Toner cache warmed from snapshot: {count} printer(s) "
          f"(saved {snapshot.get('saved_at')})")
    return count


# =============================================================
# SCAN CONTROL
# =============================================================

def is_scan_running():
    return SCAN_STATUS.get("running", False)


def get_scan_status():
    return {
        "running": SCAN_STATUS.get("running", False),
        "completed": SCAN_STATUS.get("completed", 0),
        "total": SCAN_STATUS.get("total", len(PRINTERS)),
        "last_started": SCAN_STATUS.get("last_started"),
        "last_finished": SCAN_STATUS.get("last_finished"),
        "cached_count": len(TONER_CACHE),
    }


async def run_fleet_scan(community="public"):
    """
    Run one full fleet scan, guarded by a lock:
      SNMP scan -> reachability enrich -> record history.
    Skips if a scan is already running.
    """
    if _SCAN_LOCK.locked():
        print("Toner scan already in progress - skipping duplicate request.")
        return {"started": False, "reason": "A scan is already in progress"}

    async with _SCAN_LOCK:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n=== Toner fleet scan started {started_at} ===")

        try:
            # 1) SNMP scan (updates in-memory cache + snapshot inside)
            results = await get_all_toner_status(community)

            # 2) Reachability: Online vs SNMP-Disabled vs Offline
            if _HAS_REACH:
                try:
                    results = await enrich_fleet(results)
                    for r in results:
                        r["data_source"] = "live"
                        update_toner_cache(r.get("key") or r.get("ip"), r)
                except Exception as exc:
                    print(f"WARNING: reachability enrich failed: {exc}")
            else:
                for r in results:
                    r["data_source"] = "live"

            # 3) History for forecasts/sparklines
            if _HAS_DB:
                try:
                    saved = record_fleet(results)
                    print(f"toner_db: recorded {saved} reading(s)")
                except Exception as exc:
                    print(f"WARNING: toner history not recorded: {exc}")

            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"=== Toner fleet scan finished {finished_at} ===\n")
            return {"started": True, "count": len(results)}

        except Exception as exc:
            print(f"ERROR: Toner fleet scan failed: {exc}")
            SCAN_STATUS["running"] = False
            return {"started": True, "error": str(exc)}


async def trigger_scan_background(community="public"):
    """Fire a scan without blocking the HTTP request (manual Refresh)."""
    if is_scan_running():
        return {
            "started": False,
            "message": "A toner scan is already in progress",
            "status": get_scan_status(),
        }
    asyncio.create_task(run_fleet_scan(community))
    return {
        "started": True,
        "message": "Toner scan started in background",
        "status": get_scan_status(),
    }


# =============================================================
# BACKGROUND LOOP  (runs once on boot, then every SCAN_INTERVAL_SECONDS)
# =============================================================

async def _background_scan_loop(community="public"):
    await asyncio.sleep(INITIAL_SCAN_DELAY_SECONDS)
    while True:
        try:
            await run_fleet_scan(community)
        except asyncio.CancelledError:
            print("Toner background scanner cancelled.")
            raise
        except Exception as exc:
            print(f"WARNING: Background toner scan error: {exc}")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


def start_background_scanner(community="public"):
    """Call from the FastAPI startup event."""
    global _BACKGROUND_TASK
    if _BACKGROUND_TASK and not _BACKGROUND_TASK.done():
        return _BACKGROUND_TASK
    _BACKGROUND_TASK = asyncio.create_task(_background_scan_loop(community))
    hrs = SCAN_INTERVAL_SECONDS // 3600
    print(f"Toner background scanner started (every {hrs} hour(s)).")
    return _BACKGROUND_TASK


def stop_background_scanner():
    """Call from the FastAPI shutdown event."""
    global _BACKGROUND_TASK
    if _BACKGROUND_TASK and not _BACKGROUND_TASK.done():
        _BACKGROUND_TASK.cancel()
        print("Toner background scanner stopped.")


# =============================================================
# READ API (what the dashboard / Toner Center call)
# =============================================================

def get_cached_fleet():
    """
    Return the current cache instantly - no SNMP, no waiting.
    Any printer never scanned yet is returned as a 'pending' placeholder
    so the UI always renders a full fleet.
    """
    cached = {item.get("key"): item for item in get_toner_cache()}

    fleet = []
    for key, meta in PRINTERS.items():
        if key in cached:
            fleet.append(cached[key])
        else:
            fleet.append({
                "key": key,
                "ip": meta["ip"],
                "display_name": meta["display_name"],
                "location": meta["location"],
                "printer_name": None,
                "online": False,
                "overall_status": "Unknown",
                "network_status": "Unknown",
                "snmp_status": "Unknown",
                "toners": [],
                "maintenance": [],
                "last_checked": None,
                "data_source": "pending",
                "error": "Not scanned yet",
            })
    return fleet
