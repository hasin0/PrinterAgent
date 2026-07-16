import base64
import requests
import os

from config.freshservice import (
    FRESHSERVICE_DOMAIN,
    FRESHSERVICE_API_KEY,
    DEFAULT_REQUESTER_EMAIL,
    DEFAULT_AGENT_EMAIL,
    DEFAULT_GROUP_ID,
    DEFAULT_CATEGORY,
    DEFAULT_SUB_CATEGORY,
    DEFAULT_ITEM,
    DEFAULT_SAP_MODULE,
    DEFAULT_RESPONDER_ID,
    DEFAULT_TICKET_COMPLEXITY,
)

BASE_URL = f"https://{FRESHSERVICE_DOMAIN}/api/v2"


def _auth_header():
    token = base64.b64encode(
        f"{FRESHSERVICE_API_KEY}:X".encode()
    ).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json"
    }


def _build_payload(subject, description, requester_email):
    payload = {
        "email": requester_email or DEFAULT_REQUESTER_EMAIL,
        "subject": subject,
        "description": description,

        "status": 2,
        "priority": 1,
        "source": 2,
        "urgency": 1,
        "impact": 1,

        "type": "Service Request",

        "category": DEFAULT_CATEGORY,
        "sub_category": DEFAULT_SUB_CATEGORY,
        "item_category": DEFAULT_ITEM,

        "custom_fields": {
            "sap_module": DEFAULT_SAP_MODULE,
            "ticket_complexity": DEFAULT_TICKET_COMPLEXITY
        }
    }

    if DEFAULT_GROUP_ID:
        payload["group_id"] = DEFAULT_GROUP_ID

    if DEFAULT_RESPONDER_ID:
        payload["responder_id"] = DEFAULT_RESPONDER_ID

    return payload


def resolve_ticket(ticket_id, resolution_note):
    url = f"{BASE_URL}/tickets/{ticket_id}"
    r = requests.put(
        url,
        headers=_auth_header(),
        json={"status": 4},
        timeout=15
    )

    if r.status_code in (200, 201):
        add_note(ticket_id, resolution_note, private=True)

    return r.status_code


def add_note(ticket_id, note, private=True):
    url = f"{BASE_URL}/tickets/{ticket_id}/notes"
    return requests.post(
        url,
        headers=_auth_header(),
        json={"body": note, "private": private},
        timeout=15
    )


def attach_file(ticket_id, file_path):
    """
    Upload a file (e.g. installer .bat) to an existing FreshService ticket.
    Note: multipart upload must NOT include Content-Type: application/json.
    """
    url = f"{BASE_URL}/tickets/{ticket_id}"

    token = base64.b64encode(
        f"{FRESHSERVICE_API_KEY}:X".encode()
    ).decode()

    headers = {
        "Authorization": f"Basic {token}"
        # No Content-Type here — requests sets multipart automatically
    }

    try:
        with open(file_path, "rb") as f:
            files = {
                "attachments[]": (
                    os.path.basename(file_path),
                    f,
                    "application/octet-stream"
                )
            }

            r = requests.put(
                url,
                headers=headers,
                files=files,
                timeout=30
            )

        print("ATTACHMENT STATUS:", r.status_code)
        print("ATTACHMENT RESPONSE:", r.text)

        return r.status_code

    except Exception as e:
        print("Attachment error:", str(e))
        return None


def create_freshservice_ticket(
    subject,
    description,
    requester_email,
    status_code=2,
    priority=1,
    printer_name=None,
    printer_ip=None,
    location=None,
    user_code=None,
    installer_path=None
):
    url = f"{BASE_URL}/tickets"
    payload = _build_payload(subject, description, requester_email)

    try:
        r = requests.post(
            url,
            headers=_auth_header(),
            json=payload,
            timeout=15
        )

        print("=== FS CREATE STATUS:", r.status_code)
        print("=== FS CREATE BODY:", r.text)

        if r.status_code not in (200, 201):
            return {
                "ticket_id": None,
                "status": "failed",
                "reason": r.text
            }

        body = r.json()
        ticket_id = (
            body.get("ticket", {}).get("id")
            or body.get("id")
        )

        # ✅ Attach installer if provided
        if ticket_id and installer_path:
            try:
                attach_file(ticket_id, installer_path)
                add_note(
                    ticket_id,
                    f"Installer attached automatically: "
                    f"{os.path.basename(installer_path)}",
                    private=True
                )
            except Exception as e:
                print("Attachment failed:", str(e))

        # ✅ Auto-resolve if successful
        if ticket_id and status_code == 4:
            print(f"Auto resolving FreshService ticket {ticket_id}")
            resolution_note = (
                "PrinterAgent completed the printer access request successfully.\n"
                f"Printer: {printer_name or ''}\n"
                f"IP: {printer_ip or ''}\n"
                f"Location: {location or ''}\n"
                f"User Code: {user_code or ''}\n\n"
                "Ticket auto-resolved by PrinterAgent."
            )
            resolve_ticket(ticket_id, resolution_note)

        return {
            "ticket_id": ticket_id,
            "status": "created"
        }

    except Exception as e:
        return {
            "ticket_id": None,
            "status": "failed",
            "reason": str(e)
        }