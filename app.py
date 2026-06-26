from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
from urllib.parse import urlencode

from tools.printer_tool import get_all_printers, get_printer
from tools.logger_tool import write_install_log, read_install_logs
from tools.sharp_web_register import register_user_on_sharp
from fastapi.responses import Response, FileResponse

app = FastAPI()


# ================================
# CONFIG
# ================================
DRIVER_FILE_NAME = "sharp_driver.exe"
SERVER_BASE_URL = "http://127.0.0.1:8000"


# ================================
# MODEL
# ================================
class RequestModel(BaseModel):
    printer: str
    name: str
    user_number: str
    email: str


# ================================
# GET AVAILABLE PRINTERS
# ================================
@app.get("/api/printers")
def api_printers():
    return get_all_printers()


# ================================
# REGISTER API
# ================================
@app.post("/api/register")
def register(req: RequestModel):

    # ==========================================
    # GET PRINTER
    # ==========================================
    selected_printer = get_printer(req.printer)

    if not selected_printer:
        return {
            "success": False,
            "message": "Invalid printer selected."
        }

    printer_ip = selected_printer["ip"]
    printer_name = selected_printer["display_name"]
    printer_location = selected_printer["location"]

    # ==========================================
    # REGISTER USER ON SHARP
    # ==========================================
    try:
        registration_result = register_user_on_sharp(
            printer_ip=printer_ip,
            user_name=req.name,
            user_number=req.user_number,
            email=req.email
        )
    except Exception as e:
        registration_result = f"ERROR: {str(e)}"

    # ==========================================
    # DETERMINE STATUS
    # ==========================================
    registration_text = registration_result.lower()

    if "success" in registration_text:
        log_status = "SUCCESS"

    elif "already exists" in registration_text:
        log_status = "ALREADY_EXISTS"

    elif "timeout" in registration_text:
        log_status = "TIMEOUT"

    elif "login failed" in registration_text:
        log_status = "LOGIN_FAILED"

    elif "error" in registration_text:
        log_status = "FAILED"

    else:
        log_status = "UNKNOWN"

    # ==========================================
    # LOG REQUEST
    # ==========================================
    try:
        write_install_log(
            name=req.name,
            code=req.user_number,
            email=req.email,
            printer_name=printer_name,
            printer_ip=printer_ip,
            location=printer_location,
            status=log_status,
            details=registration_result
        )
    except Exception as e:
        print("Log Error:", e)

    # ==========================================
    # INSTALLER URL
    # ==========================================
    query_params = urlencode({
        "ip": printer_ip,
        "name": printer_name,
        "user": req.name,
        "code": req.user_number
    })

    return {
        "success": True,
        "message": registration_result,
        "status": log_status,
        "download": "/api/installer?" + query_params
    }

# ================================
# SERVE CONFIG SCRIPT
# ================================
@app.get("/printer_config.py")
def get_config_script():
    return FileResponse("printer_config.py")


# ================================
# INSTALLER API
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
# LOGS API
# ================================
@app.get("/api/logs")
def api_logs():
    return read_install_logs()


@app.get("/dashboard")
def dashboard():
    return FileResponse("static/dashboard.html")

# ================================
# dashboard API
# ================================

@app.get("/dashboard")
def dashboard():
    return FileResponse("static/dashboard.html")
# ================================
# INSTALLER SCRIPT GENERATOR
# ================================
def get_installer_script(ip, name, user, code):

    lines = []

    # HEADER
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
    lines.append("echo Driver not found - attempting driver download...")
    lines.append(
        f"powershell -Command \"Invoke-WebRequest -Uri '{SERVER_BASE_URL}/drivers/{DRIVER_FILE_NAME}' "
        "-OutFile '%TEMP%\\sharp_driver.exe'\""
    )

    lines.append("if not exist \"%TEMP%\\sharp_driver.exe\" (")
    lines.append("    echo WARNING: Driver download failed or driver file not found on server.")
    lines.append("    echo Please install Sharp driver manually if printer installation fails.")
    lines.append("    goto ADD_PRINTER")
    lines.append(")")

    lines.append("echo Driver downloaded OK")
    lines.append("echo Launching driver installer...")
    lines.append("start /wait \"\" \"%TEMP%\\sharp_driver.exe\"")
    lines.append("echo Driver installer completed")
    lines.append("")

    # ADD PRINTER
    lines.append(":ADD_PRINTER")
    lines.append("echo.")
    lines.append("echo Configuring printer...")

    lines.append("echo Creating printer port...")
    lines.append(
        f"powershell -Command \"$portName = 'IP_{ip}'; "
        f"if (-not (Get-PrinterPort -Name $portName -ErrorAction SilentlyContinue)) "
        f"{{ Add-PrinterPort -Name $portName -PrinterHostAddress '{ip}' }}\""
    )
    lines.append("echo Printer port ready")

    # Find driver
    lines.append("echo Finding Sharp printer driver...")
    lines.append(
        "powershell -Command \"$d = (Get-PrinterDriver | "
        "Where-Object { $_.Name -like '*Sharp*' } | "
        "Select-Object -First 1).Name; "
        "if (-not $d) { echo 'ERROR: Sharp driver not found'; exit 1 }; "
        "echo $d\" > \"%TEMP%\\driver_name.txt\""
    )

    lines.append("set /p DRIVER_NAME=<\"%TEMP%\\driver_name.txt\"")
    lines.append("echo Found driver: %DRIVER_NAME%")

    # Add printer
    lines.append("echo Adding printer...")
    lines.append(
        f"powershell -Command \"if (-not (Get-Printer -Name '{name}' -ErrorAction SilentlyContinue)) "
        f"{{ Add-Printer -Name '{name}' -DriverName '%DRIVER_NAME%' -PortName 'IP_{ip}' }}\""
    )
    lines.append("echo Printer added")

    # Set default
    lines.append("echo Setting printer as default...")
    lines.append(
        f"powershell -Command \"(Get-WmiObject -Query "
        f"\\\"SELECT * FROM Win32_Printer WHERE Name='{name}'\\\").SetDefaultPrinter() | Out-Null\""
    )
    lines.append("echo Default printer set")

    # CONFIG SCRIPT
    lines.append("echo.")
    lines.append("echo Configuring printer preferences...")

    lines.append("echo Downloading configuration script...")
    lines.append(
        f"powershell -Command \"Invoke-WebRequest -Uri '{SERVER_BASE_URL}/printer_config.py' "
        "-OutFile '%TEMP%\\printer_config.py'\""
    )

    lines.append("if not exist \"%TEMP%\\printer_config.py\" (")
    lines.append("    echo ERROR: Could not download printer_config.py")
    lines.append("    goto MANUAL")
    lines.append(")")

    lines.append("echo Checking Python installation...")
    lines.append("python --version >nul 2>&1")
    lines.append("if %errorlevel% NEQ 0 (")
    lines.append("    echo ERROR: Python is not installed or not in PATH.")
    lines.append("    goto MANUAL")
    lines.append(")")

    lines.append("echo Installing required dependencies...")
    lines.append("python -m pip install pywinauto >nul 2>&1")

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
    lines.append("echo   Printer Preferences will open now.")
    lines.append("echo   Go to the 'Job Handling' tab:")
    lines.append("echo.")
    lines.append("echo   1. Change Authentication to 'User Number'")
    lines.append("echo   2. Check 'User Name' checkbox")
    lines.append(f"echo   3. Enter: {user}")
    lines.append("echo   4. Click 'Apply'")
    lines.append("echo   5. Click 'OK'")
    lines.append("echo.")
    lines.append("pause")
    lines.append(f"rundll32 printui.dll,PrintUIEntry /e /n \"{name}\"")

    # DONE
    lines.append(":DONE")
    lines.append("echo.")
    lines.append("echo ============================================")
    lines.append("echo   INSTALLATION COMPLETE")
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
app.mount("/", StaticFiles(directory="static", html=True), name="static")