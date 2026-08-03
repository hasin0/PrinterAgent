"""
toner_monitor.py
PrinterAgent - Toner & Consumables Monitoring Module

SNMP-based toner/supply level checking for Sharp MFPs.

Features:
  - Single printer check (check_toner_sync) - safe to call from
    normal sync code (FastAPI routes, scripts, etc.)
  - Full fleet check (check_all_toner_sync) - scans every printer
    in PRINTERS sequentially, using the async SNMP path internally
    (never calls asyncio.run() from inside an already-running loop)
  - In-memory TONER_CACHE - updated immediately after each printer
    completes, so partial results are never lost even if a later
    printer fails or the scan is interrupted
  - Snapshot persistence (toner_snapshot.json) - saved progressively
    after every printer, using atomic writes so the file is never
    left corrupted
  - DEMO_MODE - returns realistic sample data when off the refinery
    network (set env var PRINTERAGENT_DEMO=1)
"""

import os
import json
import asyncio
import random
from datetime import datetime

# pysnmp is only needed for LIVE (on-network) checks. In DEMO_MODE the app
# can run without it, so the import is optional and never blocks startup.
try:
    from pysnmp.hlapi.v3arch.asyncio import (
        SnmpEngine,
        CommunityData,
        ContextData,
        ObjectType,
        ObjectIdentity,
        UdpTransportTarget,
        next_cmd,
        get_cmd,
    )
    PYSNMP_AVAILABLE = True
except Exception:
    PYSNMP_AVAILABLE = False


# =============================================================
# CONFIG
# =============================================================

# Turn on demo mode by setting environment variable before starting uvicorn:
#   PowerShell:  $env:PRINTERAGENT_DEMO = "1"
#   Turn off:    Remove-Item Env:PRINTERAGENT_DEMO
DEMO_MODE = os.environ.get("PRINTERAGENT_DEMO", "0") == "1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SNAPSHOT_FILE = os.path.join(DATA_DIR, "toner_snapshot.json")

os.makedirs(DATA_DIR, exist_ok=True)

SNMP_TIMEOUT = 2
SNMP_RETRIES = 0
MAX_ROWS = 40

# Small delay between printers in the sequential fleet scan, to avoid
# flooding SNMP/UDP port 161 on the network.
FLEET_SCAN_DELAY = 0.3


# =============================================================
# PRINTER FLEET REGISTRY
# =============================================================

PRINTERS = {
    "19A_PRINTER": {
        "display_name": "19A PRINTER",
        "ip": "172.16.16.31",
        "location": "E-BLOCK 19A"
    },
    "19B_EIL_OFFICE_PRINTER": {
        "display_name": "19B EIL OFFICE PRINTER",
        "ip": "172.16.16.40",
        "location": "E-BLOCK 19B"
    },
    "19C_PRINTER": {
        "display_name": "19C PRINTER",
        "ip": "172.16.16.33",
        "location": "E-BLOCK 19C"
    },
    "19D_PRINTER": {
        "display_name": "ASSET INTEGRITY PRINTER",
        "ip": "172.16.18.88",
        "location": "E-BLOCK 19D"
    },
    "SN_REDDY_PRINTER": {
        "display_name": "SN REDDY NEW SHARP PRINTER",
        "ip": "172.16.18.116",
        "location": "E-BLOCK 21A"
    },
    "DANIELE_OFFICE_PRINTER": {
        "display_name": "DANIELE OFFICE PRINTER",
        "ip": "172.16.16.42",
        "location": "E-BLOCK 21B"
    },
    "GED_OFFICE_PRINTER": {
        "display_name": "GED OFFICE",
        "ip": "172.16.16.47",
        "location": "GED OFFICE"
    },
    "DR_NIKE_OFFICE_PRINTER": {
        "display_name": "DR. NIKE OFFICE",
        "ip": "172.16.16.46",
        "location": "DR. NIKE OFFICE"
    },
    "DCC_PRINTER": {
        "display_name": "DCC PRINTER",
        "ip": "172.16.16.48",
        "location": "E-BLOCK 16A"
    },
    "ANIL_DHAWAN_TRANSPORT_PRINTER": {
        "display_name": "ANIL DHAWAN PRINTER TRANSPORT",
        "ip": "172.16.2.190",
        "location": "TRANSPORT LOGISTICS"
    },
    "WAREHOUSE_EIL_PRINTER": {
        "display_name": "WAREHOUSE EIL PRINTER",
        "ip": "172.16.14.165",
        "location": "WAREHOUSE EIL"
    },
    "PROCUREMENT_PRINTER": {
        "display_name": "PROCUREMENT PRINTER",
        "ip": "172.20.231.74",
        "location": "NEW ADMIN BLOCK PROCUREMENT"
    },
    "FINANCE_PRINTER": {
        "display_name": "FINANCE PRINTER",
        "ip": "172.20.229.92",
        "location": "NEW ADMIN BLOCK FINANCE OFFICE"
    },
    "ICD_PRINTER": {
        "display_name": "ICD PRINTER",
        "ip": "172.16.18.137",
        "location": "E-BLOCK LOCK ICD"
    },
    "21C_PRINTER": {
        "display_name": "INTERNATIONAL PROCUREMENT OFFICE SHARP PRINTER",
        "ip": "172.16.18.211",
        "location": "21C PROCUREMENT OFFICE"
    },
}


# =============================================================
# SNMP OIDs
# =============================================================

SYS_NAME_OID = "1.3.6.1.2.1.1.5.0"
DESCRIPTION_OID = "1.3.6.1.2.1.43.11.1.1.6.1"
MAX_CAPACITY_OID = "1.3.6.1.2.1.43.11.1.1.8.1"
CURRENT_LEVEL_OID = "1.3.6.1.2.1.43.11.1.1.9.1"


def get_status_from_percent(percent):
    if percent is None:
        return "Unknown"
    if percent <= 10:
        return "Critical"
    if percent <= 25:
        return "Low"
    if percent <= 50:
        return "Moderate"
    return "Healthy"


# =============================================================
# IN-MEMORY TONER CACHE
# =============================================================

TONER_CACHE = {}

SCAN_STATUS = {
    "running": False,
    "completed": 0,
    "total": 0,
    "last_started": None,
    "last_finished": None
}


def update_toner_cache(key, result):
    """
    Store each printer result immediately.
    This allows the dashboard/API to show partial results
    while the fleet scan is still running, and preserves
    every successfully-checked printer even if a later
    printer in the scan fails.
    """
    TONER_CACHE[key] = result


def get_toner_cache():
    """
    Return current in-memory toner cache.
    If the memory cache is empty (e.g. right after a server restart),
    fall back to the last saved snapshot on disk.
    """
    if TONER_CACHE:
        return list(TONER_CACHE.values())

    snapshot = load_snapshot()

    if snapshot and snapshot.get("data"):
        for item in snapshot["data"]:
            key = item.get("key") or item.get("ip")
            TONER_CACHE[key] = item

        return list(TONER_CACHE.values())

    return []


# =============================================================
# SNAPSHOT PERSISTENCE (atomic, never fatal)
# =============================================================

def save_snapshot(results):
    """
    Save toner readings atomically to disk.

    Snapshot failure must NEVER crash or interrupt the live toner
    scan - this function always catches its own exceptions.
    """
    temporary_file = SNAPSHOT_FILE + ".tmp"

    snapshot = {
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(results),
        "data": results
    }

    try:
        with open(temporary_file, "w", encoding="utf-8") as file:
            json.dump(snapshot, file, indent=2, ensure_ascii=False)

        os.replace(temporary_file, SNAPSHOT_FILE)
        return True

    except Exception as exc:
        print(f"WARNING: Toner snapshot could not be saved: {exc}")

        try:
            if os.path.exists(temporary_file):
                os.remove(temporary_file)
        except Exception:
            pass

        return False


def load_snapshot():
    """
    Load the most recently saved toner readings.
    Returns None when no valid snapshot exists yet.
    """
    try:
        if not os.path.exists(SNAPSHOT_FILE):
            return None

        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    except Exception as exc:
        print(f"WARNING: Toner snapshot could not be loaded: {exc}")
        return None


# =============================================================
# DEMO DATA (for off-network / home development)
# =============================================================

def _demo_toners(seed_key):
    """Deterministic-ish sample CMYK levels so the UI looks realistic."""
    rnd = random.Random(seed_key)

    # Keep PROCUREMENT matching the real observed data (Black critical)
    if seed_key == "PROCUREMENT_PRINTER":
        levels = {"Cyan": 18, "Magenta": 21, "Yellow": 32, "Black": 1}
    else:
        levels = {
            "Cyan": rnd.randint(5, 95),
            "Magenta": rnd.randint(5, 95),
            "Yellow": rnd.randint(5, 95),
            "Black": rnd.randint(5, 95),
        }

    toners = []
    for color, pct in levels.items():
        toners.append({
            "name": f"{color} Toner",
            "index": color[0],
            "max_capacity": "100",
            "current_level": str(pct),
            "percentage": float(pct),
            "status": get_status_from_percent(pct)
        })
    return toners


def _demo_result(key, meta):
    # Simulate a couple of offline/no-SNMP printers for realism, matching
    # the actual fleet behaviour observed on the refinery network.
    no_snmp_keys = {
        "19B_EIL_OFFICE_PRINTER",
        "19C_PRINTER",
        "SN_REDDY_PRINTER",
        "ANIL_DHAWAN_TRANSPORT_PRINTER",
        "WAREHOUSE_EIL_PRINTER",
    }

    if key in no_snmp_keys:
        return {
            "key": key,
            "ip": meta["ip"],
            "display_name": meta["display_name"],
            "location": meta["location"],
            "printer_name": None,
            "online": False,
            "overall_status": "Offline",
            "toners": [],
            "maintenance": [],
            "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error": "[DEMO] No SNMP response (simulated)"
        }

    toners = _demo_toners(key)

    overall = "Healthy"
    for t in toners:
        if t["status"] == "Critical":
            overall = "Critical"
            break
        elif t["status"] == "Low" and overall != "Critical":
            overall = "Low"
        elif t["status"] == "Moderate" and overall not in ("Critical", "Low"):
            overall = "Moderate"

    return {
        "key": key,
        "ip": meta["ip"],
        "display_name": meta["display_name"],
        "location": meta["location"],
        "printer_name": meta["display_name"],
        "online": True,
        "overall_status": overall,
        "toners": toners,
        "maintenance": [],
        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "error": None,
        "demo": True
    }


def _demo_fleet():
    return [_demo_result(key, meta) for key, meta in PRINTERS.items()]


# =============================================================
# SNMP CORE (async)
# =============================================================

async def snmp_get(ip, oid, community="public"):
    try:
        transport = await UdpTransportTarget.create(
            (ip, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES
        )

        error_indication, error_status, error_index, var_binds = await get_cmd(
            SnmpEngine(),
            CommunityData(community, mpModel=1),
            transport,
            ContextData(),
            ObjectType(ObjectIdentity(oid))
        )

        if error_indication or error_status:
            return None

        for var_bind in var_binds:
            return str(var_bind[1])

        return None
    except Exception:
        return None


async def snmp_walk_limited(ip, base_oid, community="public", max_rows=MAX_ROWS):
    results = {}
    try:
        transport = await UdpTransportTarget.create(
            (ip, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES
        )

        current_oid = ObjectIdentity(base_oid)

        for _ in range(max_rows):
            error_indication, error_status, error_index, var_binds = await next_cmd(
                SnmpEngine(),
                CommunityData(community, mpModel=1),
                transport,
                ContextData(),
                ObjectType(current_oid),
                lexicographicMode=False
            )

            if error_indication or error_status:
                break

            if not var_binds:
                break

            for var_bind in var_binds:
                oid_text = str(var_bind[0])
                value_text = str(var_bind[1])

                if not oid_text.startswith(base_oid):
                    return results

                results[oid_text] = value_text
                current_oid = ObjectIdentity(oid_text)

        return results
    except Exception:
        return results


async def get_toner_levels(ip, community="public", key=None, meta=None):
    """
    Query a single printer for toner/supply levels via SNMP (async).

    This is the core function - always await it from inside async code.
    Never call check_toner_sync()/asyncio.run() from inside an already
    running event loop (e.g. from inside get_all_toner_status()).
    """
    meta = meta or {}

    if DEMO_MODE and key:
        return _demo_result(key, {
            "ip": ip,
            "display_name": meta.get("display_name", key),
            "location": meta.get("location", "")
        })

    try:
        printer_name = await asyncio.wait_for(
            snmp_get(ip, SYS_NAME_OID, community), timeout=SNMP_TIMEOUT + 1
        )
    except asyncio.TimeoutError:
        printer_name = None

    if printer_name is None:
        return {
            "key": key,
            "ip": ip,
            "display_name": meta.get("display_name", key),
            "location": meta.get("location", ""),
            "printer_name": None,
            "online": False,
            "overall_status": "Offline",
            "toners": [],
            "maintenance": [],
            "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error": "No SNMP response (printer offline or SNMP disabled)"
        }

    descriptions = await snmp_walk_limited(ip, DESCRIPTION_OID, community)
    max_capacities = await snmp_walk_limited(ip, MAX_CAPACITY_OID, community)
    current_levels = await snmp_walk_limited(ip, CURRENT_LEVEL_OID, community)

    toner_items = []
    maintenance_items = []

    for desc_oid, description in descriptions.items():
        index = desc_oid.split(".")[-1]

        max_oid = f"{MAX_CAPACITY_OID}.{index}"
        level_oid = f"{CURRENT_LEVEL_OID}.{index}"

        max_value = max_capacities.get(max_oid)
        current_value = current_levels.get(level_oid)

        percentage = None
        try:
            max_int = int(max_value)
            current_int = int(current_value)
            if max_int > 0 and current_int >= 0:
                percentage = round((current_int / max_int) * 100, 2)
        except Exception:
            percentage = None

        item = {
            "name": description,
            "index": index,
            "max_capacity": max_value,
            "current_level": current_value,
            "percentage": percentage,
            "status": get_status_from_percent(percentage)
        }

        if "toner" in description.lower():
            toner_items.append(item)
        else:
            maintenance_items.append(item)

    overall_status = "Healthy"
    for item in toner_items:
        if item["status"] == "Critical":
            overall_status = "Critical"
            break
        elif item["status"] == "Low" and overall_status != "Critical":
            overall_status = "Low"
        elif item["status"] == "Moderate" and overall_status not in ("Critical", "Low"):
            overall_status = "Moderate"

    return {
        "key": key,
        "ip": ip,
        "display_name": meta.get("display_name", printer_name),
        "location": meta.get("location", ""),
        "printer_name": printer_name,
        "online": True,
        "overall_status": overall_status,
        "toners": toner_items,
        "maintenance": maintenance_items,
        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "error": None
    }


# =============================================================
# FLEET SCAN (async) - the function app.py's sync wrapper calls
# =============================================================

async def get_all_toner_status(community="public"):
    """
    Check every registered printer sequentially.

    IMPORTANT: this function is async and calls `await get_toner_levels(...)`
    directly. It must NEVER call check_toner_sync() (which internally does
    asyncio.run()) because this function itself already runs inside an
    event loop - nesting asyncio.run() inside a running loop raises:
        "asyncio.run() cannot be called from a running event loop"

    Behaviour:
      - Checks printers one by one (sequential -> reliable on this network)
      - Updates TONER_CACHE immediately after each printer's result
      - Saves a snapshot to disk after every single printer, so progress
        is never lost even if a later printer hangs or the scan is
        interrupted
      - Returns the full merged cache at the end
    """

    results = []

    if DEMO_MODE:
        demo_results = _demo_fleet()
        for item in demo_results:
            update_toner_cache(item["key"], item)
        save_snapshot(list(TONER_CACHE.values()))
        return list(TONER_CACHE.values())

    SCAN_STATUS["running"] = True
    SCAN_STATUS["completed"] = 0
    SCAN_STATUS["total"] = len(PRINTERS)
    SCAN_STATUS["last_started"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    SCAN_STATUS["last_finished"] = None

    for key, meta in PRINTERS.items():
        try:
            print(f"Checking toner: {meta['display_name']} ({meta['ip']})")

            result = await get_toner_levels(
                ip=meta["ip"],
                community=community,
                key=key,
                meta=meta
            )

            # Ensure inventory metadata is always present/consistent
            result["key"] = key
            result["ip"] = meta["ip"]
            result["display_name"] = meta["display_name"]
            result["location"] = meta["location"]

            update_toner_cache(key, result)
            results.append(result)

            print(f"Result: {meta['display_name']} = {result.get('overall_status')}")

        except Exception as exc:
            print(f"Toner check failed for {meta['display_name']}: {exc}")

            failed_result = {
                "key": key,
                "ip": meta["ip"],
                "display_name": meta["display_name"],
                "location": meta["location"],
                "printer_name": None,
                "online": False,
                "overall_status": "Offline",
                "toners": [],
                "maintenance": [],
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": str(exc)
            }

            update_toner_cache(key, failed_result)
            results.append(failed_result)

        SCAN_STATUS["completed"] = len(results)

        # Save progress after every printer - never let this crash the scan
        try:
            save_snapshot(list(TONER_CACHE.values()))
        except Exception as exc:
            print(f"WARNING: Snapshot operation failed: {exc}")

        await asyncio.sleep(FLEET_SCAN_DELAY)

    SCAN_STATUS["running"] = False
    SCAN_STATUS["last_finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return list(TONER_CACHE.values())


# =============================================================
# SYNC WRAPPERS
# =============================================================
# Use these ONLY from normal synchronous code (FastAPI sync routes,
# plain scripts, __main__ block, etc). NEVER call these from inside
# an async function that is already running on an event loop.

def check_toner_sync(ip, community="public"):
    return asyncio.run(get_toner_levels(ip, community))


def check_all_toner_sync(community="public"):
    return asyncio.run(get_all_toner_status(community))


if __name__ == "__main__":
    print(f"DEMO_MODE = {DEMO_MODE}")
    print(f"PYSNMP_AVAILABLE = {PYSNMP_AVAILABLE}\n")

    results = check_all_toner_sync()

    print("\n" + "=" * 60)
    print(f"Fleet scan complete: {len(results)} printer(s)")
    print("=" * 60)

    for r in results:
        print(f"{r['display_name']:45s} {r['overall_status']}")
