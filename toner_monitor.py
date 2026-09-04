"""
toner_monitor.py
PrinterAgent - Toner & Consumables Monitoring Module

Provides SNMP-based toner/supply level checking for Sharp MFPs.
Supports single-printer checks and concurrent fleet-wide checks.
"""

import asyncio
from datetime import datetime

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
# CACHE / SNAPSHOT (in-memory + persisted snapshot for fast startup)
# =============================================================

import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SNAPSHOT_FILE = os.path.join(DATA_DIR, "toner_snapshot.json")

os.makedirs(DATA_DIR, exist_ok=True)

# Keyed cache of the latest reading per printer (key/ip -> dict)
TONER_CACHE = {}

# Lightweight scan status used by the HTTP endpoints
SCAN_STATUS = {
    "running": False,
    "completed": 0,
    "total": len(PRINTERS),
    "last_started": None,
    "last_finished": None,
}


def get_toner_cache():
    return list(TONER_CACHE.values())


def load_snapshot():
    if not os.path.exists(SNAPSHOT_FILE):
        return None
    try:
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_snapshot():
    snapshot = {
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data": list(TONER_CACHE.values()),
    }
    try:
        with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def update_toner_cache(key, item):
    # Ensure the item has a key
    k = key or item.get("key") or item.get("ip")
    item["key"] = k
    TONER_CACHE[k] = item
    _save_snapshot()
    return True



# =============================================================
# SNMP OIDs
# =============================================================

SYS_NAME_OID = "1.3.6.1.2.1.1.5.0"
DESCRIPTION_OID = "1.3.6.1.2.1.43.11.1.1.6.1"
MAX_CAPACITY_OID = "1.3.6.1.2.1.43.11.1.1.8.1"
CURRENT_LEVEL_OID = "1.3.6.1.2.1.43.11.1.1.9.1"

SNMP_TIMEOUT = 2
SNMP_RETRIES = 0
MAX_ROWS = 40


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
    Query a single printer for toner/supply levels via SNMP.
    Returns a dict even on failure (status = Offline/Unknown) so the
    dashboard can always render a card for every printer in the fleet.
    """
    meta = meta or {}

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


async def get_all_toner_status(community="public", concurrency_limit=8):
    """
    Query the entire PRINTERS fleet concurrently (bounded by a semaphore
    so we don't flood the network with 15 simultaneous SNMP sessions).
    """
    # Update scan status and run bounded concurrent SNMP checks
    SCAN_STATUS["running"] = True
    SCAN_STATUS["last_started"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    SCAN_STATUS["total"] = len(PRINTERS)

    semaphore = asyncio.Semaphore(concurrency_limit)

    async def bounded_check(key, meta):
        async with semaphore:
            return await get_toner_levels(
                meta["ip"], community=community, key=key, meta=meta
            )

    tasks = [bounded_check(key, meta) for key, meta in PRINTERS.items()]
    results = await asyncio.gather(*tasks)

    # Store results in the in-memory cache and persist a snapshot
    for r in results:
        # mark source and persist
        r["data_source"] = "live"
        update_toner_cache(r.get("key") or r.get("ip"), r)

    SCAN_STATUS["running"] = False
    SCAN_STATUS["completed"] = len(results)
    SCAN_STATUS["last_finished"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return list(results)


def check_toner_sync(ip, community="public"):
    return asyncio.run(get_toner_levels(ip, community))


def check_all_toner_sync(community="public"):
    return asyncio.run(get_all_toner_status(community))


if __name__ == "__main__":
    import json
    print("Checking full printer fleet toner levels...\n")
    results = check_all_toner_sync()
    print(json.dumps(results, indent=2))


# =============================================================
# reload_printers - refresh PRINTERS in place from the web-UI store
# =============================================================
def reload_printers():
    """Reload the fleet from data/printers.json so UI edits take effect."""
    try:
        from printers_store import load_printers
        fresh = load_printers()
        PRINTERS.clear()
        PRINTERS.update(fresh)
    except Exception as _e:
        print("reload_printers: could not refresh fleet:", _e)
    return PRINTERS
