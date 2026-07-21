from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
from urllib.parse import urlencode
import os

from tools.printer_tool import get_all_printers, get_printer
from tools.logger_tool import (
    write_install_log,
    read_install_logs,
    find_open_ticket
)
from tools.sharp_web_register import register_user_on_sharp
from tools.freshservice_tool import (
    create_freshservice_ticket,
    update_ticket_on_retry
)
from tools.printer_monitor import get_printer_statuses

app = FastAPI()


# ================================
# CONFIG
# ================================
DRIVER_FILE_NAME = "sharp_driver.exe"
SERVER_BASE_URL = "http://172.20.228.49:8000"   # <-- your deployed server IP
INSTALLER_DIR = "generated_installers"

os.makedirs(INSTALLER_DIR, exist_ok=True)


# ================================
# MODELS
# ================================
class RequestModel(BaseModel):
    printer: str
    name: str
    user_number: str
    email: str


class RetryModel(BaseModel):
    printer: str
    name: str
    user_number: str
    email: str
    ticket_id: int


# ================================
# HELPERS
# ================================
def map_status_to_freshservice(log_status):
    """
    2 = Open, 3 = Pending, 4 = Resolved
    """
    if log_status == "REGISTRATION_SUCCESS":
        return 4
    elif log_status == "ALREADY_EXISTS":
        return 3
    else:
        return 2


def classify_result(registration_result):
    text = registration_result.lower()

    if "success" in text:
        return "REGISTRATION_SUCCESS"
    elif "already_exists" in text:
        return "ALREADY_EXISTS"
    elif "login_failed" in text:
        return "LOGIN_FAILED"
    elif "timeout" in text:
        return "TIMEOUT"
    elif "failed" in text:
        return "REGISTRATION_FAILED"
    else:
        return "UNKNOWN"


def build_description(name, code, email, printer_name, printer_ip,
                      location, log_status, registration_result):
    return (
        "<b>Printer Access Request via PrinterAgent</b><br><br>"
        f"<b>User:</b> {name}<br>"
        f"<b>User Code:</b> {code}<br>"
        f"<b>Email:</b> {email}<br>"
        f"<b>Printer:</b> {printer_name}<br>"
        f"<b>Printer IP:</b> {printer_ip}<br>"
        f"<b>Location:</b> {location}<br>"
        f"<b>Business Unit:</b> DPRP<br>"
        f"<b>Unit:</b> Dangote FTZ Ibeju Lekki<br>"
        f"<b>Ticket Complexity:</b> Low<br>"
        f"<b>Status:</b> {log_status}<br><br>"
        f"<b>Details:</b><br>{registration_result}"
    )


def generate_installer_file(printer_ip, printer_name, name, code):
    safe_code = "".join(c for c in code if c.isalnum())
    path = os.path.join(INSTALLER_DIR, f"install_printer_{safe_code}.bat")
    try:
        script = get_installer_script(printer_ip, printer_name, name, code)
        with open(path, "w", encoding="utf-8") as f:
            f.write(script)
        return path
    except Exception as e:
        print("Installer file generation failed:", e)
        return None


# ================================
# GET PRINTERS
# ================================
@app.get("/api/printers")
def api_printers():
    return get_all_printers()


# ================================
# GET PRINTER STATUS (Monitoring)
# ================================
@app.get("/api/printer-status")
def printer_status():
    return get_printer_statuses()


# ================================
# REGISTER API
# ================================
@app.post("/api/register")
def register(req: RequestModel):

    selected_printer = get_printer(req.printer)
    if not selected_printer:
        return {"success": False, "message": "Invalid printer selected."}

    printer_ip = selected_printer["ip"]
    printer_name = selected_printer["display_name"]
    printer_location = selected_printer["location"]

    # Sharp Registration
    try:
        registration_result = register_user_on_sharp(
            printer_ip=printer_ip,
            user_name=req.name,
            user_number=req.user_number,
            email=req.email
        )
    except Exception as e:
        registration_result = f"FAILED: {str(e)}"

    log_status = classify_result(registration_result)

    # Generate installer only on success
    installer_file_path = None
    if log_status == "REGISTRATION_SUCCESS":
        installer_file_path = generate_installer_file(
            printer_ip, printer_name, req.name, req.user_number
        )

    fs_status_code = map_status_to_freshservice(log_status)

    description = build_description(
        req.name, req.user_number, req.email,
        printer_name, printer_ip, printer_location,
        log_status, registration_result
    )

    # ---- Duplicate ticket prevention ----
    existing_ticket_id = find_open_ticket(
        user_code=req.user_number,
        printer_name=printer_name
    )

    if existing_ticket_id:
        ticket_id = existing_ticket_id
        resolved = (log_status == "REGISTRATION_SUCCESS")
        try:
            update_ticket_on_retry(
                ticket_id=ticket_id,
                result_text=registration_result,
                resolved=resolved
            )
            # ✅ Attach installer on success even for reused tickets
            if resolved and installer_file_path:
                from tools.freshservice_tool import attach_file
                attach_file(ticket_id, installer_file_path)

            print(f"Reused existing ticket {ticket_id} (no duplicate created)")
        except Exception as e:
            print("Ticket update failed:", e)
    else:
        try:
            ticket_response = create_freshservice_ticket(
                subject=f"Printer Access Request — {printer_name}",
                description=description,
                requester_email=req.email,
                status_code=fs_status_code,
                printer_name=printer_name,
                printer_ip=printer_ip,
                location=printer_location,
                user_code=req.user_number,
                installer_path=installer_file_path
            )
            ticket_id = ticket_response.get("ticket_id")
        except Exception as e:
            print("Ticket creation failed:", e)
            ticket_id = None

    # Logging
    try:
        write_install_log(
            name=req.name,
            code=req.user_number,
            email=req.email,
            printer_name=printer_name,
            printer_ip=printer_ip,
            location=printer_location,
            status=log_status,
            details=registration_result,
            ticket_id=ticket_id
        )
    except Exception as e:
        print("Log Error:", e)

    # Installer download URL
    query_params = urlencode({
        "ip": printer_ip,
        "name": printer_name,
        "user": req.name,
        "code": req.user_number
    })

    download_url = (
        "/api/installer?" + query_params
        if log_status == "REGISTRATION_SUCCESS"
        else None
    )

    return {
        "success": True,
        "message": registration_result,
        "status": log_status,
        "ticket_id": ticket_id,
        "download": download_url
    }


# ================================
# RETRY API (reuses existing ticket)
# ================================
@app.post("/api/retry")
def retry(req: RetryModel):

    selected_printer = get_printer(req.printer)
    if not selected_printer:
        return {"success": False, "message": "Invalid printer selected."}

    printer_ip = selected_printer["ip"]
    printer_name = selected_printer["display_name"]
    printer_location = selected_printer["location"]

    try:
        registration_result = register_user_on_sharp(
            printer_ip=printer_ip,
            user_name=req.name,
            user_number=req.user_number,
            email=req.email
        )
    except Exception as e:
        registration_result = f"FAILED: {str(e)}"

    log_status = classify_result(registration_result)
    success = (log_status == "REGISTRATION_SUCCESS")

    # Generate installer if success
    if success:
        generate_installer_file(
            printer_ip, printer_name, req.name, req.user_number
        )

    # Update the SAME ticket (no new ticket)
    try:
        update_ticket_on_retry(
            ticket_id=req.ticket_id,
            result_text=registration_result,
            resolved=success
        )
    except Exception as e:
        print("Retry ticket update failed:", e)

    # Logging
    try:
        write_install_log(
            name=req.name,
            code=req.user_number,
            email=req.email,
            printer_name=printer_name,
            printer_ip=printer_ip,
            location=printer_location,
            status=log_status,
            details=registration_result,
            ticket_id=req.ticket_id
        )
    except Exception as e:
        print("Log Error:", e)

    query_params = urlencode({
        "ip": printer_ip,
        "name": printer_name,
        "user": req.name,
        "code": req.user_number
    })

    download_url = "/api/installer?" + query_params if success else None

    return {
        "success": True,
        "status": log_status,
        "ticket_id": req.ticket_id,
        "message": registration_result,
        "download": download_url
    }


# ================================
# CONFIG SCRIPT
# ================================
@app.get("/printer_config.py")
def get_config_script():
    return FileResponse("printer_config.py")


# ================================
# INSTALLER ENDPOINT
# ================================
@app.get("/api/installer")
def installer(ip: str, name: str, user: str = "", code: str = ""):
    script = get_installer_script(ip, name, user, code)
    return Response(
        content=script,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=install_printer.bat"}
    )


# ================================
# LOGS ENDPOINT
# ================================
@app.get("/api/logs")
def api_logs():
    return read_install_logs()


# ================================
# PAGE ROUTES
# ================================
@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/portal")
def portal():
    return FileResponse("static/portal.html")


@app.get("/dashboard")
def dashboard():
    return FileResponse("static/dashboard.html")


# ================================
# INSTALLER SCRIPT GENERATOR (Python-based)
# ================================
def get_installer_script(ip, name, user, code):

    lines = []

    lines.append("@echo off")
    lines.append("echo ============================================")
    lines.append("echo   Sharp Printer Auto Installer")
    lines.append(f"echo   Printer: {name}")
    lines.append(f"echo   IP: {ip}")
    lines.append(f"echo   User: {user}")
    lines.append(f"echo   Code: {code}")
    lines.append("echo ============================================")
    lines.append("echo.")

    # DRIVER CHECK
    lines.append("echo Checking if Sharp driver is already installed...")
    lines.append(
        "powershell -Command \"$d = (Get-PrinterDriver | "
        "Where-Object { $_.Name -like '*Sharp*' } | "
        "Select-Object -First 1).Name; "
        "if ($d) { echo DRIVER_EXISTS } else { echo DRIVER_MISSING }\" "
        "> \"%TEMP%\\driver_check.txt\""
    )
    lines.append("findstr /C:\"DRIVER_EXISTS\" \"%TEMP%\\driver_check.txt\" >nul")

    lines.append("if %errorlevel%==0 (")
    lines.append("    echo Driver already installed - skipping download")
    lines.append("    goto ADD_PRINTER")
    lines.append(")")

    # DRIVER DOWNLOAD
    lines.append("echo Driver not found - downloading...")
    lines.append(
        f"powershell -Command \"Invoke-WebRequest -Uri '{SERVER_BASE_URL}/drivers/{DRIVER_FILE_NAME}' "
        "-OutFile '%TEMP%\\sharp_driver.exe'\""
    )

    lines.append("if not exist \"%TEMP%\\sharp_driver.exe\" (")
    lines.append("    echo WARNING: Driver download failed.")
    lines.append("    goto ADD_PRINTER")
    lines.append(")")

    lines.append("start /wait \"\" \"%TEMP%\\sharp_driver.exe\" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART")
    lines.append("")

    # ADD PRINTER
    lines.append(":ADD_PRINTER")
    lines.append("echo.")
    lines.append("echo Configuring printer...")

    lines.append(
        f"powershell -Command \"$portName = 'IP_{ip}'; "
        f"if (-not (Get-PrinterPort -Name $portName -ErrorAction SilentlyContinue)) "
        f"{{ Add-PrinterPort -Name $portName -PrinterHostAddress '{ip}' }}\""
    )
    lines.append("echo Printer port ready")

    lines.append(
        "powershell -Command \"$d = (Get-PrinterDriver | "
        "Where-Object { $_.Name -like '*Sharp*' } | "
        "Select-Object -First 1).Name; "
        "if (-not $d) { echo 'ERROR: Sharp driver not found'; exit 1 }; "
        "echo $d\" > \"%TEMP%\\driver_name.txt\""
    )
    lines.append("set /p DRIVER_NAME=<\"%TEMP%\\driver_name.txt\"")
    lines.append("echo Found driver: %DRIVER_NAME%")

    lines.append(
        f"powershell -Command \"if (-not (Get-Printer -Name '{name}' -ErrorAction SilentlyContinue)) "
        f"{{ Add-Printer -Name '{name}' -DriverName '%DRIVER_NAME%' -PortName 'IP_{ip}' }}\""
    )
    lines.append("echo Printer added")

    lines.append(
        f"powershell -Command \"(Get-WmiObject -Query "
        f"\\\"SELECT * FROM Win32_Printer WHERE Name='{name}'\\\").SetDefaultPrinter() | Out-Null\""
    )
    lines.append("echo Default printer set")

    # CONFIGURE PREFERENCES (Python)
    lines.append("echo.")
    lines.append("echo Configuring printer preferences...")

    lines.append("if not exist \"%TEMP%\\printer_config.py\" (")
    lines.append(
        f"    powershell -Command \"Invoke-WebRequest -Uri '{SERVER_BASE_URL}/printer_config.py' "
        "-OutFile '%TEMP%\\printer_config.py'\""
    )
    lines.append(") else (")
    lines.append("    echo Config script already cached")
    lines.append(")")

    lines.append("if not exist \"%TEMP%\\printer_config.py\" (")
    lines.append("    echo ERROR: Could not download printer_config.py")
    lines.append("    goto MANUAL")
    lines.append(")")

    lines.append("python -c \"import pywinauto\" >nul 2>&1")
    lines.append("if %errorlevel% NEQ 0 (")
    lines.append("    echo Installing required dependencies...")
    lines.append("    python -m pip install pywinauto >nul 2>&1")
    lines.append(") else (")
    lines.append("    echo pywinauto already installed")
    lines.append(")")

    lines.append("echo Running configuration script...")
    lines.append(f"python \"%TEMP%\\printer_config.py\" \"{name}\" \"{user}\" \"{code}\"")

    lines.append("if %errorlevel%==0 (")
    lines.append("    echo Preferences configured automatically")
    lines.append("    goto DONE")
    lines.append(")")

    # MANUAL FALLBACK
    lines.append(":MANUAL")
    lines.append("echo.")
    lines.append("echo ============================================")
    lines.append("echo   AUTO-CONFIG FAILED - Manual Setup Needed")
    lines.append("echo ============================================")
    lines.append("echo.")
    lines.append(f"echo Enter Name: {user}")
    lines.append("pause")
    lines.append(f"rundll32 printui.dll,PrintUIEntry /e /n \"{name}\"")

    # DONE
    lines.append(":DONE")
    lines.append("echo.")
    lines.append("echo ============================================")
    lines.append("echo INSTALLATION COMPLETE")
    lines.append("echo ============================================")
    lines.append("echo.")
    lines.append(f"echo Printer: {name}")
    lines.append(f"echo IP: {ip}")
    lines.append(f"echo User: {user}")
    lines.append(f"echo Code: {code}")
    lines.append("echo.")
    lines.append("pause")

    return "\r\n".join(lines)


# ================================
# STATIC FILES
# ================================
app.mount("/drivers", StaticFiles(directory="static/drivers"), name="drivers")
app.mount("/static", StaticFiles(directory="static"), name="static")
