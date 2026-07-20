import csv
import os
from datetime import datetime


LOG_FILE = "logs/install_log.csv"

FIELDNAMES = [
    "timestamp",
    "name",
    "code",
    "email",
    "printer_name",
    "printer_ip",
    "location",
    "status",
    "details",
    "ticket_id"
]


def write_install_log(
    name,
    code,
    email,
    printer_name,
    printer_ip,
    location,
    status,
    details="",
    ticket_id=None
):
    """
    Append a registration attempt to the install log CSV.
    Creates the file + header if it does not exist yet.
    """
    os.makedirs("logs", exist_ok=True)

    file_exists = os.path.exists(LOG_FILE)

    with open(LOG_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(FIELDNAMES)

        writer.writerow([
            datetime.now().isoformat(),
            name,
            code,
            email,
            printer_name,
            printer_ip,
            location,
            status,
            details,
            ticket_id or ""
        ])


def read_install_logs(limit=None):
    """
    Read the install log CSV and return a list of dicts.
    If limit is provided, return only the most recent N rows.
    """
    if not os.path.exists(LOG_FILE):
        return []

    with open(LOG_FILE, encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    if limit:
        return reader[-limit:]

    return reader


def find_open_ticket(user_code, printer_name):
    """
    Return the ticket_id of an existing UNRESOLVED request
    for the same user + printer, or None if not found.

    Logic:
    - If the most recent matching record is already SUCCESS -> return None
      (no reuse needed, a new request is fine)
    - If the most recent matching record is a failure
      (TIMEOUT / LOGIN_FAILED / REGISTRATION_FAILED / UNKNOWN)
      and has a ticket_id -> return that ticket_id to reuse it.
    """
    logs = read_install_logs()

    for row in reversed(logs):

        if (
            row.get("code") == user_code
            and row.get("printer_name") == printer_name
            and row.get("ticket_id")
        ):
            status = (row.get("status") or "").upper()

            # Already resolved successfully -> no reuse
            if status == "REGISTRATION_SUCCESS":
                return None

            # Failed states -> reuse the existing ticket
            if status in [
                "TIMEOUT",
                "LOGIN_FAILED",
                "REGISTRATION_FAILED",
                "UNKNOWN"
            ]:
                return row.get("ticket_id")

    return None
