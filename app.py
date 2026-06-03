from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI()


class RequestModel(BaseModel):
    location: str
    name: str
    user_number: str
    email: str


@app.post("/api/register")
def register(req: RequestModel):

    printer_ip = "172.16.16.31"
    printer_name = "Sharp BP-50C36"

    result = (
        "SUCCESS\n\n"
        "User Registered:\n"
        "- Name: " + req.name + "\n"
        "- Code: " + req.user_number + "\n"
        "- Email: " + req.email + "\n\n"
        "Printer IP: " + printer_ip
    )

    return {
        "message": result,
        "download": "/api/installer?ip=" + printer_ip + "&name=" + printer_name + "&user=" + req.name + "&code=" + req.user_number
    }


@app.get("/api/installer")
def installer(ip: str, name: str, user: str = "", code: str = ""):

    script = get_installer_script(ip, name, user, code)

    headers = {"Content-Disposition": "attachment; filename=install_printer.bat"}

    return Response(content=script, media_type="application/octet-stream", headers=headers)


def get_installer_script(ip, name, user, code):

    lines = []

    # ================================
    # Header
    # ================================
    lines.append("@echo off")
    lines.append("echo ============================================")
    lines.append("echo   Sharp Printer Auto Installer")
    lines.append("echo   Printer: " + name)
    lines.append("echo   IP: " + ip)
    lines.append("echo   User: " + user)
    lines.append("echo   Code: " + code)
    lines.append("echo ============================================")
    lines.append("echo.")
    lines.append("")

    # ================================
    # Step 1 — Check if driver already installed
    # ================================
    lines.append(":: Step 1 - Check existing driver")
    lines.append("echo Checking if Sharp driver is already installed...")
    lines.append("powershell -Command \"$d = (Get-PrinterDriver | Where-Object { $_.Name -like '*Sharp*' } | Select-Object -First 1).Name; if ($d) { echo DRIVER_EXISTS } else { echo DRIVER_MISSING }\" > \"%TEMP%\\driver_check.txt\"")
    lines.append("findstr /C:\"DRIVER_EXISTS\" \"%TEMP%\\driver_check.txt\" >nul")
    lines.append("if %errorlevel%==0 (")
    lines.append("    echo Driver already installed - skipping download")
    lines.append("    goto ADD_PRINTER")
    lines.append(")")
    lines.append("echo Driver not found - will install now")
    lines.append("")

    # ================================
    # Step 2 — Download driver
    # ================================
    lines.append(":: Step 2 - Download driver")
    lines.append("echo Downloading driver...")
    lines.append("powershell -Command \"Invoke-WebRequest -Uri 'http://127.0.0.1:8000/drivers/SH_D20_PCL6_PS_2508a_EnglishUS_64bit.exe' -OutFile '%TEMP%\\sharp_driver.exe'\"")
    lines.append("")
    lines.append("if not exist \"%TEMP%\\sharp_driver.exe\" (")
    lines.append("    echo ERROR: Driver download failed")
    lines.append("    pause")
    lines.append("    exit /b 1")
    lines.append(")")
    lines.append("echo Driver downloaded OK")
    lines.append("")

    # ================================
    # Step 3 — Try silent extract + INF install
    # ================================
    lines.append(":: Step 3 - Try silent install first")
    lines.append("echo Attempting silent driver install...")
    lines.append("mkdir \"%TEMP%\\sharp_extracted\" 2>nul")
    lines.append("\"%TEMP%\\sharp_driver.exe\" /extract:\"%TEMP%\\sharp_extracted\"")
    lines.append("timeout /t 5 /nobreak >nul")
    lines.append("")
    lines.append("dir \"%TEMP%\\sharp_extracted\\*.inf\" >nul 2>&1")
    lines.append("if %errorlevel%==0 (")
    lines.append("    echo INF files found - installing silently...")
    lines.append("    powershell -Command \"pnputil /add-driver '%TEMP%\\sharp_extracted\\*.inf' /install\"")
    lines.append("    echo Driver installed silently OK")
    lines.append("    goto WAIT_SPOOLER")
    lines.append(")")
    lines.append("")

    # ================================
    # Step 4 — Fallback: guided wizard
    # ================================
    lines.append(":: Step 4 - Fallback: open wizard with instructions")
    lines.append("echo.")
    lines.append("echo ============================================")
    lines.append("echo   DRIVER WIZARD WILL OPEN")
    lines.append("echo.")
    lines.append("echo   Follow these steps:")
    lines.append("echo   1. Click 'Add a new Sharp printer'")
    lines.append("echo   2. Click 'Next'")
    lines.append("echo   3. Wait for installation to complete")
    lines.append("echo   4. Click 'Finish'")
    lines.append("echo   5. Come back to this window")
    lines.append("echo ============================================")
    lines.append("echo.")
    lines.append("pause")
    lines.append("start /wait \"\" \"%TEMP%\\sharp_driver.exe\"")
    lines.append("echo Driver installed via wizard OK")
    lines.append("")

    # ================================
    # Step 5 — Wait for Print Spooler
    # ================================
    lines.append(":WAIT_SPOOLER")
    lines.append("echo.")
    lines.append("echo Waiting for Print Spooler service...")
    lines.append("timeout /t 10 /nobreak >nul")
    lines.append("net stop spooler >nul 2>&1")
    lines.append("timeout /t 3 /nobreak >nul")
    lines.append("net start spooler >nul 2>&1")
    lines.append("timeout /t 5 /nobreak >nul")
    lines.append("echo Print Spooler is ready")
    lines.append("")

    # ================================
    # Step 6 — Add printer
    # ================================
    lines.append(":ADD_PRINTER")
    lines.append("echo.")
    lines.append("echo Configuring printer...")
    lines.append("")

    # Create port
    lines.append(":: Create printer port")
    lines.append("powershell -Command \"$portName = 'IP_" + ip + "'; if (-not (Get-PrinterPort -Name $portName -ErrorAction SilentlyContinue)) { Add-PrinterPort -Name $portName -PrinterHostAddress '" + ip + "' }\"")
    lines.append("echo Printer port ready")
    lines.append("")

    # Find driver name
    lines.append(":: Find installed Sharp driver name")
    lines.append("powershell -Command \"$d = (Get-PrinterDriver | Where-Object { $_.Name -like '*Sharp*' } | Select-Object -First 1).Name; if (-not $d) { echo 'ERROR: Sharp driver not found'; exit 1 }; echo $d\" > \"%TEMP%\\driver_name.txt\"")
    lines.append("set /p DRIVER_NAME=<\"%TEMP%\\driver_name.txt\"")
    lines.append("echo Found driver: %DRIVER_NAME%")
    lines.append("")

    # Add printer
    lines.append(":: Add printer")
    lines.append("powershell -Command \"if (-not (Get-Printer -Name '" + name + "' -ErrorAction SilentlyContinue)) { Add-Printer -Name '" + name + "' -DriverName '%DRIVER_NAME%' -PortName 'IP_" + ip + "' }\"")
    lines.append("echo Printer added")
    lines.append("")

    # Set as default printer
    lines.append(":: Set as default printer")
    lines.append("powershell -Command \"(Get-WmiObject -Query \\\"SELECT * FROM Win32_Printer WHERE Name='" + name + "'\\\").SetDefaultPrinter() | Out-Null\"")
    lines.append("echo Default printer set")
    lines.append("")

    # ================================
    # Step 7 — Configure preferences (pywinauto)
    # ================================
    lines.append(":: Step 7 - Auto-configure printer preferences")
    lines.append("echo.")
    lines.append("echo Configuring printer preferences...")
    lines.append("")
    lines.append("python printer_config.py \"" + name + "\" \"" + user + "\" \"" + code + "\"")
    lines.append("")
    lines.append("if %errorlevel%==0 (")
    lines.append("    echo Preferences configured automatically")
    lines.append("    goto DONE")
    lines.append(")")
    lines.append("")

    # ================================
    # Step 8 — Fallback: manual config (if pywinauto fails)
    # ================================
    lines.append(":: Step 8 - Fallback: manual configuration")
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
    lines.append("echo   3. Enter: " + user)
    lines.append("echo   4. Click 'Apply'")
    lines.append("echo   5. Click 'OK'")
    lines.append("echo.")
    lines.append("echo ============================================")
    lines.append("echo.")
    lines.append("echo Press any key to open Printer Preferences...")
    lines.append("pause >nul")
    lines.append("rundll32 printui.dll,PrintUIEntry /e /n \"" + name + "\"")
    lines.append("")

    # ================================
    # Done
    # ================================
    lines.append(":DONE")
    lines.append("echo.")
    lines.append("echo ============================================")
    lines.append("echo   INSTALLATION COMPLETE!")
    lines.append("echo.")
    lines.append("echo   Printer: " + name)
    lines.append("echo   IP: " + ip)
    lines.append("echo   User: " + user)
    lines.append("echo   Code: " + code)
    lines.append("echo   Status: Ready to print")
    lines.append("echo ============================================")
    lines.append("echo.")
    lines.append("pause")

    return "\r\n".join(lines)


# ================================
# Mount static - drivers FIRST then UI
# ================================
app.mount("/drivers", StaticFiles(directory="static/drivers"), name="drivers")
app.mount("/", StaticFiles(directory="static", html=True), name="static")