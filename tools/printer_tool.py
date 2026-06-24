import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from printer_list import PRINTERS


def get_all_printers():
    return [
        {
            "id": key,
            "name": value.get("display_name", key),
            "location": value.get("location", ""),
            "ip": value.get("ip", "")
        }
        for key, value in PRINTERS.items()
    ]


def get_printer(printer_id):
    return PRINTERS.get(printer_id)


def get_printer_by_ip(ip):
    for key, value in PRINTERS.items():
        if value.get("ip") == ip:
            return {
                "id": key,
                "name": value.get("display_name", key),
                "location": value.get("location", ""),
                "ip": value.get("ip", "")
            }
    return None