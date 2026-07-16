import requests
from tools.printer_tool import get_all_printers

requests.packages.urllib3.disable_warnings()
import requests
import subprocess

def check_printer(ip):

    try:

        ping = subprocess.run(
            ["ping", "-n", "1", ip],
            capture_output=True,
            text=True,
            timeout=5
        )

        if ping.returncode != 0:

            return {
                "status": "offline",
                "response_time": None
            }

        r = requests.get(
            f"http://{ip}",
            timeout=5,
            verify=False,
            allow_redirects=True
        )

        if r.status_code != 200:

            return {
                "status": "offline",
                "response_time": None
            }

        return {
            "status": "reachable",
            "response_time": round(
                r.elapsed.total_seconds() * 1000
            )
        }

    except requests.Timeout:

        return {
            "status": "timeout",
            "response_time": None
        }

    except Exception:

        return {
            "status": "offline",
            "response_time": None
        }

def get_printer_statuses():
    results = []

    printers = get_all_printers()

    for printer in printers:

        status = check_printer(printer["ip"])

        results.append({
            "name": printer["name"],
            "ip": printer["ip"],
            "location": printer["location"],
            **status
        })

    return results