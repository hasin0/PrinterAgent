"""
PrinterAgent — IT Self-Service Automation Platform
Dangote Petroleum Refinery

Agents:
    - PrinterAgent      : Sharp printer registration, driver deploy, toner monitoring
    - SAPConfigAgent    : SAP Logon landscape deployment (RSQ / RSP)

Toner monitoring pipeline (background, DAILY scan):
    toner_service  ->  toner_monitor (SNMP)  ->  reachability (Online/SNMP-Disabled)
                                              ->  toner_db (history / forecasts)

On-demand LIVE detail: /api/toner-check?ip=...  (toner, drum, developer,
fuser, transfer, charger, waste) via toner_detail.py
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
from urllib.parse import urlencode
import os

# ================================
# TOOLS / AGENTS
# ================================
from tools.printer_tool import get_all_printers, get_printer

from tools.logger_tool import (
    write_install_log,
    read_install_logs,
    find_open_ticket,
)
from tools.sharp_web_register import register_user_on_sharp
from tools.freshservice_tool import (
    create_freshservice_ticket,
    update_ticket_on_retry,
)
from tools.printer_monitor import get_printer_statuses

# SAP Config Agent routes
from sap_routes import router as sap_router

# ---- Toner subsystem ----
# Single-printer LIVE check (blocking) + async single check
from toner_monitor import check_toner_sync, get_toner_levels

# History / forecast DB
import toner_db
from toner_db import get_history, get_sparkline, get_forecast, get_all_forecasts

# Background scan service (instant cache + reachability + history)
from toner_service import (
    warm_cache_from_snapshot,
    start_background_scanner,
    stop_background_scanner,
    trigger_scan_background,
    get_cached_fleet,
    get_scan_status,
)

# Full-detail categorisation + attention ranking
from toner_detail import build_full_detail, attention_list

# Printer registry (web-UI managed via data/printers.json)
import printers_store


# ================================
# APP
# ================================
app = FastAPI(
    title="PrinterAgent — IT Self-Service Portal",
    description="Automation platform for printer onboarding, toner monitoring, and SAP configuration.",
    version="1.3.0",
)

# Register the SAP Config Agent (adds all /sap/* endpoints)
app.include_router(sap_router)


# ================================
# STARTUP / SHUTDOWN  (single handler each)
# ================================
@app.on_event("startup")
async def on_startup():
    toner_db.init_db()              # ensure history DB + table exist
    warm_cache_from_snapshot()      # instant dashboard from last snapshot
    start_background_scanner()      # daily fleet scan in the background


@app.on_event("shutdown")
async def on_shutdown():
    stop_background_scanner()


# ================================
# CONFIG
# ================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DRIVERS_DIR = os.path.join(STATIC_DIR, "drivers")
TOOLS_DIR = os.path.join(STATIC_DIR, "tools")
DRIVER_FILE_NAME = "sharp_driver.exe"
SERVER_BASE_URL = "http://172.20.228.49:8000"   # <-- your deployed server IP
INSTALLER_DIR = os.path.join(BASE_DIR, "generated_installers")

os.makedirs(INSTALLER_DIR, exist_ok=True)
os.makedirs(TOOLS_DIR, exist_ok=True)


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


class PrinterCreate(BaseModel):
    display_name: str
    ip: str
    location: str = ""


class PrinterUpdate(BaseModel):
    display_name: str | None = None
    ip: str | None = None
    location: str | None = None


# ================================
# HELPERS
# ================================
def map_status_to_freshservice(log_status):
    """2 = Open, 3 = Pending, 4 = Resolved"""
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
                      location, log_status, registration_result,
                      download_url=None):
    desc = (
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
    if download_url:
        desc += (
            "<br><br><b>Printer Installer:</b><br>"
            f'<a href="{download_url}">Download Printer Installer</a>'
        )
    return desc


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
# PRINTERS (registration dropdown source)
# ================================
@app.get("/api/printers")
def api_printers():
    return get_all_printers()


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

    try:
        registration_result = register_user_on_sharp(
            printer_ip=printer_ip,
            user_name=req.name,
            user_number=req.user_number,
            email=req.email,
        )
    except Exception as e:
        registration_result = f"FAILED: {str(e)}"

    log_status = classify_result(registration_result)

    installer_file_path = None
    if log_status == "REGISTRATION_SUCCESS":
        installer_file_path = generate_installer_file(
            printer_ip, printer_name, req.name, req.user_number
        )

    query_params = urlencode({
        "ip": printer_ip,
        "name": printer_name,
        "user": req.name,
        "code": req.user_number,
    })

    download_url = (
        f"{SERVER_BASE_URL}/api/installer?{query_params}"
        if log_status == "REGISTRATION_SUCCESS"
        else None
    )

    fs_status_code = map_status_to_freshservice(log_status)

    description = build_description(
        req.name, req.user_number, req.email,
        printer_name, printer_ip, printer_location,
        log_status, registration_result,
        download_url=download_url,
    )

    existing_ticket_id = find_open_ticket(
        user_code=req.user_number,
        printer_name=printer_name,
    )

    if existing_ticket_id:
        ticket_id = existing_ticket_id
        resolved = (log_status == "REGISTRATION_SUCCESS")
        try:
            update_ticket_on_retry(
                ticket_id=ticket_id,
                result_text=registration_result,
                resolved=resolved,
            )
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
                installer_path=installer_file_path,
            )
            ticket_id = ticket_response.get("ticket_id")
        except Exception as e:
            print("Ticket creation failed:", e)
            ticket_id = None

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
            ticket_id=ticket_id,
        )
    except Exception as e:
        print("Log Error:", e)

    portal_download = (
        "/api/installer?" + query_params
        if log_status == "REGISTRATION_SUCCESS"
        else None
    )

    return {
        "success": True,
        "message": registration_result,
        "status": log_status,
        "ticket_id": ticket_id,
        "download": portal_download,
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
            email=req.email,
        )
    except Exception as e:
        registration_result = f"FAILED: {str(e)}"

    log_status = classify_result(registration_result)
    success = (log_status == "REGISTRATION_SUCCESS")

    if success:
        generate_installer_file(printer_ip, printer_name, req.name, req.user_number)

    try:
        update_ticket_on_retry(
            ticket_id=req.ticket_id,
            result_text=registration_result,
            resolved=success,
        )
    except Exception as e:
        print("Retry ticket update failed:", e)

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
            ticket_id=req.ticket_id,
        )
    except Exception as e:
        print("Log Error:", e)

    query_params = urlencode({
        "ip": printer_ip,
        "name": printer_name,
        "user": req.name,
        "code": req.user_number,
    })
    download_url = "/api/installer?" + query_params if success else None

    return {
        "success": True,
        "status": log_status,
        "ticket_id": req.ticket_id,
        "message": registration_result,
        "download": download_url,
    }


# ================================
# CONFIG SCRIPT
# ================================
@app.get("/printer_config.py")
def get_config_script():
    return FileResponse("printer_config.py")


# ================================
# TONER STATUS API  (cache-backed, instant)
# ================================
@app.get("/api/toner-status/{printer_ip}")
def toner_status(printer_ip: str):
    """LIVE single-printer check (blocking). For troubleshooting one device."""
    try:
        result = check_toner_sync(printer_ip)
        return {"success": True, "data": result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/toner-status-all")
def toner_status_all():
    """FAST endpoint - returns the in-memory cache instantly (no live scan)."""
    try:
        fleet = get_cached_fleet()
        return {
            "success": True,
            "count": len(fleet),
            "scan": get_scan_status(),
            "data": fleet,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/toner-scan-status")
def toner_scan_status():
    try:
        return {"success": True, "scan": get_scan_status()}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.post("/api/toner-refresh")
async def toner_refresh():
    """Manual refresh - starts a background scan and returns immediately."""
    try:
        result = await trigger_scan_background()
        return {"success": True, **result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ================================
# TONER HISTORY / FORECAST API
# ================================
@app.get("/api/toner-forecast")
def toner_forecast(color: str = "Black"):
    try:
        data = get_all_forecasts(color)
        return {"success": True, "color": color, "data": data}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/toner-sparkline/{printer_key}")
def toner_sparkline(printer_key: str, color: str = "Black", points: int = 20):
    try:
        values = get_sparkline(printer_key, color, points)
        forecast = get_forecast(printer_key, color)
        return {
            "success": True,
            "printer_key": printer_key,
            "color": color,
            "values": values,
            "forecast": forecast,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/toner-history/{printer_key}")
def toner_history(printer_key: str, color: str = "Black", days: int = 14):
    try:
        return {
            "success": True,
            "printer_key": printer_key,
            "color": color,
            "data": get_history(printer_key, color, days),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ================================
# TONER CENTER  (attention + on-demand full detail)
# ================================
@app.get("/api/toner-attention")
def toner_attention(limit: int = 0):
    """Fleet ranked by lowest toner (most urgent first), from the cache."""
    try:
        fleet = get_cached_fleet()
        data = attention_list(fleet, limit=limit or None)
        return {
            "success": True,
            "scan": get_scan_status(),
            "count": len(data["attention"]),
            "offline_count": len(data["offline"]),
            "data": data,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/toner-check")
async def toner_check(ip: str, community: str = "public"):
    """LIVE full-detail check of ONE printer by IP (all consumables)."""
    try:
        result = await get_toner_levels(ip, community=community, key=None, meta={"ip": ip})
        return {"success": True, "data": build_full_detail(result)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.get("/api/toner-check-key/{printer_key}")
async def toner_check_key(printer_key: str, community: str = "public"):
    """LIVE full-detail check by registered printer key."""
    try:
        from toner_monitor import PRINTERS, reload_printers
        reload_printers()
        meta = PRINTERS.get(printer_key)
        if not meta:
            return {"success": False, "error": f"Unknown printer '{printer_key}'."}
        result = await get_toner_levels(
            meta["ip"], community=community, key=printer_key, meta=meta
        )
        return {"success": True, "data": build_full_detail(result)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ================================
# MANAGE PRINTERS  (web-UI CRUD -> data/printers.json)
# ================================
@app.get("/api/manage-printers")
def manage_printers_list():
    try:
        return {"success": True, "data": printers_store.load_printers()}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.post("/api/manage-printers")
def manage_printers_add(req: PrinterCreate):
    try:
        key, printer = printers_store.add_printer(req.display_name, req.ip, req.location)
        from toner_monitor import reload_printers
        reload_printers()
        return {"success": True, "key": key, "printer": printer}
    except ValueError as ve:
        return {"success": False, "error": str(ve)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.put("/api/manage-printers/{key}")
def manage_printers_update(key: str, req: PrinterUpdate):
    try:
        printer = printers_store.update_printer(
            key, display_name=req.display_name, ip=req.ip, location=req.location
        )
        from toner_monitor import reload_printers
        reload_printers()
        return {"success": True, "key": key, "printer": printer}
    except ValueError as ve:
        return {"success": False, "error": str(ve)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@app.delete("/api/manage-printers/{key}")
def manage_printers_delete(key: str):
    try:
        ok = printers_store.delete_printer(key)
        from toner_monitor import reload_printers
        reload_printers()
        if not ok:
            return {"success": False, "error": f"Printer '{key}' not found."}
        return {"success": True, "key": key}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ================================
# EPSON LQ-350 INSTALLER
# ================================
EPSON_PRINTER_NAME = "EPSON LQ-350"
EPSON_DRIVER_NAME = "EPSON LQ-350 ESC/P2"


def get_epson_installer_script():
    return r'''@echo off
setlocal EnableDelayedExpansion
set "PRINTER_NAME=''' + EPSON_PRINTER_NAME + r'''"
set "DRIVER_NAME=''' + EPSON_DRIVER_NAME + r'''"
echo.
echo ==============================================
echo   PrinterAgent - EPSON LQ-350 Setup
echo ==============================================
echo.
echo  Installing "%PRINTER_NAME%", please wait...
echo.
powershell -ExecutionPolicy Bypass -NoProfile -Command ^
  "$name='%PRINTER_NAME%';" ^
  "$driver='%DRIVER_NAME%';" ^
  "try {" ^
  "  if (Get-Printer -Name $name -ErrorAction SilentlyContinue) {" ^
  "    Write-Host '[OK] Printer already exists.' -ForegroundColor Green; exit 0 }" ^
  "  if (-not (Get-PrinterDriver -Name $driver -ErrorAction SilentlyContinue)) {" ^
  "    try { Add-PrinterDriver -Name $driver -ErrorAction Stop }" ^
  "    catch { Write-Host '[FAIL] Driver not available. Install LQ-350 driver first.' -ForegroundColor Red; exit 1 } }" ^
  "  $port='LPT1:';" ^
  "  if (Get-Printer ^| Where-Object { $_.PortName -eq 'LPT1:' }) {" ^
  "    if (-not (Get-Printer ^| Where-Object { $_.PortName -eq 'LPT2:' })) { $port='LPT2:' }" ^
  "    elseif (-not (Get-Printer ^| Where-Object { $_.PortName -eq 'LPT3:' })) { $port='LPT3:' } }" ^
  "  Add-Printer -Name $name -DriverName $driver -PortName $port -ErrorAction Stop;" ^
  "  $p=Get-Printer -Name $name;" ^
  "  Write-Host '[ OK ] SUCCESS - EPSON LQ-350 ready.' -ForegroundColor Green;" ^
  "  Write-Host ('        Port   : ' + $p.PortName);" ^
  "  Write-Host ('        Driver : ' + $p.DriverName) }" ^
  "catch { Write-Host ('[FAIL] ' + $_.Exception.Message) -ForegroundColor Red; exit 1 }"
echo.
pause
endlocal
'''


@app.get("/api/epson-installer")
def epson_installer():
    script = get_epson_installer_script()
    return Response(
        content=script,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=install_epson_lq350.bat"},
    )


# ================================
# INSTALLER ENDPOINT (Sharp)
# ================================
@app.get("/api/installer")
def installer(ip: str, name: str, user: str = "", code: str = ""):
    script = get_installer_script(ip, name, user, code)
    return Response(
        content=script,
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=install_printer.bat"},
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


@app.get("/toner")
def toner_center_page():
    path = os.path.join(STATIC_DIR, "toner_center.html")
    if not os.path.exists(path):
        return Response("toner_center.html not found in static/.",
                        media_type="text/plain", status_code=404)
    return FileResponse(path)


@app.get("/manage-printers")
def manage_printers_page():
    path = os.path.join(STATIC_DIR, "manage_printers.html")
    if not os.path.exists(path):
        return Response("manage_printers.html not found in static/.",
                        media_type="text/plain", status_code=404)
    return FileResponse(path)


@app.get("/sap-config")
def sap_config_page():
    return FileResponse("static/sap.html")


# ================================
# INSTALLER SCRIPT GENERATOR (Sharp, Python-based)
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

    # CONFIGURE PREFERENCES
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
# STATIC FILES  (keep LAST - mounts must come after routes)
# ================================
app.mount("/drivers", StaticFiles(directory=DRIVERS_DIR), name="drivers")
app.mount("/tools", StaticFiles(directory=TOOLS_DIR), name="tools")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
