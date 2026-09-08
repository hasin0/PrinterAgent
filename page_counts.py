"""
page_counts.py
PrinterAgent - Fleet page-count (meter reading) via SNMP

Reads the lifetime TOTAL page counter from every printer in the managed
fleet (printers_store.py -> data/printers.json), so it always follows the
same list as toner monitoring and the Manage Printers page.

Confirmed OID across the Sharp fleet:
    1.3.6.1.2.1.43.10.2.1.4.1.1   -> total pages printed (lifetime)

Mono/colour split is NOT exposed by these Sharp models on the standard
MIB, so we report the reliable TOTAL only.

CLI:
    python page_counts.py                 # read whole fleet
    python page_counts.py 172.20.231.74   # read one IP
    python page_counts.py 172.20.231.74 discover   # dump all marker OIDs

Public API:
    read_page_count(ip)          -> int | None
    read_fleet_page_counts()     -> list[dict]  (sync)
    async read_all_page_counts() -> list[dict]  (async, for the app)
"""

import sys
import asyncio
from datetime import datetime

try:
    from pysnmp.hlapi.v3arch.asyncio import (
        SnmpEngine, CommunityData, ContextData,
        ObjectType, ObjectIdentity, UdpTransportTarget,
        get_cmd, next_cmd,
    )
    PYSNMP_AVAILABLE = True
except Exception:
    PYSNMP_AVAILABLE = False

from printers_store import load_printers

# Confirmed working fleet-wide (lifetime total pages)
TOTAL_OID = "1.3.6.1.2.1.43.10.2.1.4.1.1"

# Base of the marker-counter table (for `discover` mode)
MARKER_BASE_OID = "1.3.6.1.2.1.43.10.2.1.4"

SNMP_TIMEOUT = 2
SNMP_RETRIES = 0
FLEET_DELAY = 0.2


def _close_engine(engine):
    """Release the engine's sockets (prevents FD leak on Windows)."""
    if engine is None:
        return
    fn = getattr(engine, "close_dispatcher", None)
    if callable(fn):
        try:
            fn()
            return
        except Exception:
            pass
    for attr in ("transport_dispatcher", "transportDispatcher"):
        disp = getattr(engine, attr, None)
        if disp is not None:
            for meth in ("close_dispatcher", "closeDispatcher"):
                f = getattr(disp, meth, None)
                if callable(f):
                    try:
                        f()
                        return
                    except Exception:
                        pass


async def _snmp_get_int(engine, ip, oid, community="public"):
    try:
        transport = await UdpTransportTarget.create(
            (ip, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES
        )
        ei, es, ex, var_binds = await get_cmd(
            engine, CommunityData(community, mpModel=1),
            transport, ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        if ei or es:
            return None
        for vb in var_binds:
            try:
                return int(vb[1])
            except Exception:
                return None
        return None
    except Exception:
        return None


async def get_page_count(ip, community="public"):
    """Return the lifetime total page count for one IP, or None."""
    if not PYSNMP_AVAILABLE:
        return None
    engine = SnmpEngine()
    try:
        return await _snmp_get_int(engine, ip, TOTAL_OID, community)
    finally:
        _close_engine(engine)


async def discover_markers(ip, community="public"):
    """Walk the marker-counter table and print every OID/value found."""
    engine = SnmpEngine()
    found = {}
    try:
        current = ObjectIdentity(MARKER_BASE_OID)
        for _ in range(40):
            ei, es, ex, var_binds = await next_cmd(
                engine, CommunityData(community, mpModel=1),
                await UdpTransportTarget.create((ip, 161), timeout=SNMP_TIMEOUT, retries=SNMP_RETRIES),
                ContextData(),
                ObjectType(current),
                lexicographicMode=False,
            )
            if ei or es or not var_binds:
                break
            oid_text = str(var_binds[0][0])
            if not oid_text.startswith(MARKER_BASE_OID):
                break
            found[oid_text] = str(var_binds[0][1])
            current = ObjectIdentity(oid_text)
    except Exception:
        pass
    finally:
        _close_engine(engine)
    return found


async def read_all_page_counts(community="public"):
    """
    Read the total page count for the whole managed fleet.
    Returns a list of dicts, one per printer.
    """
    fleet = load_printers()
    results = []
    for key, meta in fleet.items():
        ip = meta.get("ip")
        total = await get_page_count(ip, community) if ip else None
        results.append({
            "key": key,
            "ip": ip,
            "display_name": meta.get("display_name", key),
            "location": meta.get("location", ""),
            "total_pages": total,
            "online": total is not None,
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        await asyncio.sleep(FLEET_DELAY)
    return results


# ---- sync wrappers ----

def read_page_count(ip, community="public"):
    return asyncio.run(get_page_count(ip, community))


def read_fleet_page_counts(community="public"):
    return asyncio.run(read_all_page_counts(community))


if __name__ == "__main__":
    args = sys.argv[1:]

    if len(args) >= 2 and args[1].lower() == "discover":
        ip = args[0]
        print(f"\nMarker counters on {ip}:")
        print("=" * 60)
        found = asyncio.run(discover_markers(ip))
        for oid, val in found.items():
            print(f"  {oid}  =  {val}")
        print("\nTip: the largest number is usually TOTAL; a smaller second/third")
        print("index is often mono/colour. Put those OIDs in MONO_OIDS/COLOR_OIDS.")

    elif len(args) == 1:
        ip = args[0]
        total = read_page_count(ip)
        print(f"{ip}: total_pages = {total}")

    else:
        print("Reading page counts for the whole fleet...\n")
        rows = read_fleet_page_counts()
        rows_sorted = sorted(rows, key=lambda r: (r["total_pages"] or -1), reverse=True)
        print(f"{'PRINTER':40s} {'IP':16s} {'TOTAL PAGES':>12s}")
        print("=" * 72)
        for r in rows_sorted:
            tp = "—" if r["total_pages"] is None else f"{r['total_pages']:,}"
            print(f"{r['display_name']:40s} {r['ip']:16s} {tp:>12s}")
