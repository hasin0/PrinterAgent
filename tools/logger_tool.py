import csv
import os
from datetime import datetime


LOG_FILE = "logs/install_log.csv"


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

    os.makedirs("logs", exist_ok=True)

    file_exists = os.path.exists(LOG_FILE)

    with open(
        LOG_FILE,
        mode="a",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.writer(f)

        if not file_exists:
            writer.writerow([
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
            ])

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


def read_install_logs(limit=50):

    if not os.path.exists(LOG_FILE):
        return []

    with open(
        LOG_FILE,
        encoding="utf-8"
    ) as f:

        reader = list(csv.DictReader(f))

        return reader[-limit:]