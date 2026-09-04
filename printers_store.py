"""
printers_store.py
PrinterAgent - Printer fleet registry (web-UI managed)

Single source of truth: data/printers.json
Seeded from DEFAULT_PRINTERS on first run.

API (MUST match app.py's calls):
    load_printers()                              -> dict {key: {...}}
    save_printers(dict)                          -> bool
    add_printer(display_name, ip, location)      -> (key, printer)   <-- 2-tuple
    update_printer(key, display_name=, ip=, location=) -> printer dict
    delete_printer(key)                          -> bool
    get_printer(key)                             -> printer | None
"""

import os
import re
import json
import uuid
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PRINTERS_FILE = os.path.join(DATA_DIR, "printers.json")
os.makedirs(DATA_DIR, exist_ok=True)

_LOCK = threading.RLock()


# =============================================================
# DEFAULT SEED (only used if data/printers.json is missing)
# =============================================================

DEFAULT_PRINTERS = {
    "19A_PRINTER": {"display_name": "19A PRINTER", "ip": "172.16.16.31", "location": "E-BLOCK 19A"},
    "19B_EIL_OFFICE_PRINTER": {"display_name": "19B EIL OFFICE PRINTER", "ip": "172.16.16.40", "location": "E-BLOCK 19B"},
    "19C_PRINTER": {"display_name": "19C PRINTER", "ip": "172.16.16.33", "location": "E-BLOCK 19C"},
    "19D_PRINTER": {"display_name": "ASSET INTEGRITY PRINTER", "ip": "172.16.18.88", "location": "E-BLOCK 19D"},
    "SN_REDDY_PRINTER": {"display_name": "SN REDDY NEW SHARP PRINTER", "ip": "172.16.18.116", "location": "E-BLOCK 21A"},
    "DANIELE_OFFICE_PRINTER": {"display_name": "DANIELE OFFICE PRINTER", "ip": "172.16.16.42", "location": "E-BLOCK 21B"},
    "GED_OFFICE_PRINTER": {"display_name": "GED OFFICE", "ip": "172.16.16.47", "location": "GED OFFICE"},
    "DR_NIKE_OFFICE_PRINTER": {"display_name": "DR. NIKE OFFICE", "ip": "172.16.16.46", "location": "DR. NIKE OFFICE"},
    "DCC_PRINTER": {"display_name": "DCC PRINTER", "ip": "172.16.16.48", "location": "E-BLOCK 16A"},
    "ANIL_DHAWAN_TRANSPORT_PRINTER": {"display_name": "ANIL DHAWAN PRINTER TRANSPORT", "ip": "172.16.2.190", "location": "TRANSPORT LOGISTICS"},
    "WAREHOUSE_EIL_PRINTER": {"display_name": "WAREHOUSE EIL PRINTER", "ip": "172.16.14.165", "location": "WAREHOUSE EIL"},
    "PROCUREMENT_PRINTER": {"display_name": "PROCUREMENT PRINTER", "ip": "172.20.231.74", "location": "NEW ADMIN BLOCK PROCUREMENT"},
    "FINANCE_PRINTER": {"display_name": "FINANCE PRINTER", "ip": "172.20.229.92", "location": "NEW ADMIN BLOCK FINANCE OFFICE"},
    "ICD_PRINTER": {"display_name": "ICD PRINTER", "ip": "172.16.18.137", "location": "E-BLOCK LOCK ICD"},
    "21C_PRINTER": {"display_name": "INTERNATIONAL PROCUREMENT OFFICE SHARP PRINTER", "ip": "172.16.18.211", "location": "21C PROCUREMENT OFFICE"},
}


# =============================================================
# HELPERS
# =============================================================

_IP_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


def is_valid_ip(ip):
    if not ip:
        return False
    m = _IP_RE.match(ip.strip())
    return bool(m) and all(0 <= int(o) <= 255 for o in m.groups())


def make_key(display_name):
    key = re.sub(r"[^A-Za-z0-9]+", "_", (display_name or "").strip()).strip("_").upper()
    return key or "PRINTER"


# =============================================================
# PERSISTENCE
# =============================================================

def _write_atomic(printers):
    tmp = f"{PRINTERS_FILE}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(printers, f, indent=2, ensure_ascii=False)
        os.replace(tmp, PRINTERS_FILE)
        return True
    except Exception as exc:
        print(f"WARNING: could not save printers.json: {exc}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def load_printers():
    with _LOCK:
        if not os.path.exists(PRINTERS_FILE):
            _write_atomic(DEFAULT_PRINTERS)
            return dict(DEFAULT_PRINTERS)
        try:
            with open(PRINTERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else dict(DEFAULT_PRINTERS)
        except Exception as exc:
            print(f"WARNING: printers.json unreadable ({exc}); using defaults.")
            return dict(DEFAULT_PRINTERS)


def save_printers(printers):
    with _LOCK:
        return _write_atomic(printers)


# =============================================================
# CRUD  (return shapes MUST match app.py)
# =============================================================

def get_printer(key):
    return load_printers().get(key)


def add_printer(display_name, ip, location=""):
    """
    Add a printer. Returns (key, printer_dict)  <-- 2-tuple, matches app.py.
    Raises ValueError on bad input or duplicate IP.
    """
    display_name = (display_name or "").strip()
    ip = (ip or "").strip()
    location = (location or "").strip()

    if not display_name:
        raise ValueError("Display name is required.")
    if not is_valid_ip(ip):
        raise ValueError(f"Invalid IP address: '{ip}'")

    with _LOCK:
        printers = load_printers()

        # unique key
        base_key = make_key(display_name)
        new_key = base_key
        n = 2
        while new_key in printers:
            new_key = f"{base_key}_{n}"
            n += 1

        # no duplicate IP
        for k, p in printers.items():
            if p.get("ip") == ip:
                raise ValueError(f"IP {ip} already exists as '{p.get('display_name')}'.")

        printer = {"display_name": display_name, "ip": ip, "location": location}
        printers[new_key] = printer
        save_printers(printers)
        return new_key, printer


def update_printer(key, display_name=None, ip=None, location=None):
    """Update a printer. Returns the updated printer dict."""
    with _LOCK:
        printers = load_printers()
        if key not in printers:
            raise ValueError(f"Printer '{key}' not found.")

        printer = printers[key]

        if display_name is not None:
            display_name = display_name.strip()
            if not display_name:
                raise ValueError("Display name cannot be empty.")
            printer["display_name"] = display_name

        if ip is not None:
            ip = ip.strip()
            if not is_valid_ip(ip):
                raise ValueError(f"Invalid IP address: '{ip}'")
            for k, p in printers.items():
                if k != key and p.get("ip") == ip:
                    raise ValueError(f"IP {ip} already used by '{p.get('display_name')}'.")
            printer["ip"] = ip

        if location is not None:
            printer["location"] = location.strip()

        printers[key] = printer
        save_printers(printers)
        return printer


def delete_printer(key):
    """Delete a printer. Returns True if it existed."""
    with _LOCK:
        printers = load_printers()
        if key not in printers:
            return False
        del printers[key]
        save_printers(printers)
        return True


if __name__ == "__main__":
    print("Loaded:", len(load_printers()), "printers")
    k, p = add_printer("Bench Test", "10.0.0.250", "Lab")
    print("add ->", k, p)
    print("update ->", update_printer(k, location="Lab 2"))
    print("delete ->", delete_printer(k))
    print("final:", len(load_printers()))
