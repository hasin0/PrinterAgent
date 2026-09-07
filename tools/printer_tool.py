"""
tools/printer_tool.py
PrinterAgent - Printer registry accessor for the REGISTRATION portal

UNIFIED SOURCE OF TRUTH:
  This now reads from the SAME store as toner monitoring / the Manage
  Printers page  ->  printers_store.py  ->  data/printers.json

So a printer added on /manage-printers appears immediately in the portal
dropdown (/api/printers) on the next page load. One list, everywhere.

Shapes returned (kept identical to what app.py / portal.html expect):
  get_all_printers() -> [ {"id": key, "name": display_name,
                           "location": location, "ip": ip}, ... ]
  get_printer(key)   -> {"ip": ip, "display_name": name,
                          "location": location}  |  None
"""

import os
import sys

# printers_store.py lives in the project ROOT (one level up from tools/).
# Ensure the root is importable no matter where the app is launched from.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from printers_store import load_printers  # noqa: E402


def get_all_printers():
    """
    Return the fleet as a list for the portal dropdown.
    Each item: id (registry key), name, location, ip.
    """
    fleet = load_printers()
    out = []
    for key, meta in fleet.items():
        out.append({
            "id": key,
            "name": meta.get("display_name", key),
            "location": meta.get("location", ""),
            "ip": meta.get("ip", ""),
        })
    # Sort alphabetically by name for a tidy dropdown
    out.sort(key=lambda p: (p["name"] or "").upper())
    return out


def get_printer(key):
    """
    Look up one printer by its registry key (the dropdown 'id').
    Returns the shape app.py's register()/retry() expect, or None.
    """
    meta = load_printers().get(key)
    if not meta:
        return None
    return {
        "ip": meta.get("ip", ""),
        "display_name": meta.get("display_name", key),
        "location": meta.get("location", ""),
    }


# Backwards-compat: some code referenced a PRINTERS dict directly.
# Expose a live view so old imports don't break.
def _load_printers_dict():
    return load_printers()


try:
    PRINTERS = load_printers()
except Exception:
    PRINTERS = {}


if __name__ == "__main__":
    printers = get_all_printers()
    print(f"{len(printers)} printers in registry:\n")
    for p in printers:
        print(f"  {p['id']:32s} {p['ip']:16s} {p['name']}")
    if printers:
        first = printers[0]["id"]
        print("\nget_printer(first):", get_printer(first))
