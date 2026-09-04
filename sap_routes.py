# sap_routes.py
"""
SAP Config Agent API routes.

This file supports two models:

1. Server-side status routes:
   /sap/status, /sap/precheck, /sap/logs, etc.

2. Client-side PowerShell deployment:
   /sap/download-script downloads configure_sap.ps1
   /sap/client-report receives the result from the user's PC
"""

from fastapi import APIRouter, Query, Response, Request
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
import json
import os

from agents.sap_config_agent import SAPConfigAgent


router = APIRouter(prefix="/sap", tags=["SAP Config Agent"])


class SAPClientReport(BaseModel):
    success: bool
    user: str | None = None
    computer: str | None = None
    message: str | None = None
    systems: list[str] = []
    details: dict = {}


def agent() -> SAPConfigAgent:
    return SAPConfigAgent()


# ----------------------------------------------------------------------
# STATUS / PRECHECK
# ----------------------------------------------------------------------
@router.get("/status")
def sap_status(check_connectivity: bool = Query(False)):
    """Single call that powers the SAP card on the dashboard."""
    return agent().get_status(check_connectivity=check_connectivity)


@router.get("/precheck")
def sap_precheck():
    """SAP GUI installation + profile folder + SAP Logon process state."""
    return agent().run_precheck()


@router.get("/configured-systems")
def sap_configured_systems():
    """Read the deployed landscape file and report which SIDs exist."""
    return agent().get_configured_systems()


# ----------------------------------------------------------------------
# SERVER-SIDE DEPLOYMENT ROUTES
# Keep these for local testing only. For real users, use download-script.
# ----------------------------------------------------------------------
@router.post("/create-common-folder")
def sap_create_common_folder():
    return agent().create_sap_common_folder()


@router.post("/deploy")
def sap_deploy(force: bool = Query(False)):
    return agent().deploy_landscape(force=force)


@router.get("/preview-xml")
def sap_preview_xml():
    return {"xml": agent().build_landscape_xml()}


# ----------------------------------------------------------------------
# CONNECTIVITY
# ----------------------------------------------------------------------
@router.get("/connectivity")
def sap_connectivity():
    return agent().verify_all_systems()


# ----------------------------------------------------------------------
# LAUNCH
# ----------------------------------------------------------------------
@router.post("/launch")
def sap_launch():
    return agent().launch_sap()


@router.post("/close")
def sap_close():
    return agent().close_saplogon()


# ----------------------------------------------------------------------
# ONE-CLICK SERVER-SIDE CONFIGURE
# Keep this for local testing only.
# ----------------------------------------------------------------------
@router.post("/configure")
def sap_configure(
    launch: bool = Query(True),
    force: bool = Query(False),
):
    return agent().configure_sap(launch=launch, force=force)


# ----------------------------------------------------------------------
# AUDIT LOG
# ----------------------------------------------------------------------
@router.get("/logs")
def sap_logs(limit: int = Query(20, ge=1, le=500)):
    return agent().get_logs(limit=limit)


# ----------------------------------------------------------------------
# DOWNLOADABLE LOCAL SAP CONFIGURATION SCRIPT
# ----------------------------------------------------------------------
@router.get("/download-script")
def download_sap_script(request: Request):
    base_url = str(request.base_url).rstrip("/")
    report_url = f"{base_url}/sap/client-report"

    script = build_sap_bat_script(report_url)

    return Response(
        content=script,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename=configure_sap.bat"
        },
    )

@router.post("/client-report")
def sap_client_report(report: SAPClientReport):
    """
    Receives success/failure result from configure_sap.ps1 running
    on the user's workstation.
    """

    log_file = Path("data/sap_config_log.json")
    log_file.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": report.user or os.getenv("USERNAME"),
        "computer": report.computer or os.getenv("COMPUTERNAME"),
        "success": report.success,
        "message": report.message,
        "systems": report.systems,
        "details": report.details,
        "source": "client_powershell_script",
    }

    history = []
    if log_file.exists():
        try:
            history = json.loads(log_file.read_text(encoding="utf-8"))
        except Exception:
            history = []

    history.append(entry)
    history = history[-1000:]

    log_file.write_text(json.dumps(history, indent=2), encoding="utf-8")

    # Optional FreshService hook
    try:
        from tools.sap_freshservice import handle_report

        fs_report = {
            "success": report.success,
            "started_at": entry["timestamp"],
            "completed_at": entry["timestamp"],
            "message": report.message,
            "steps": {
                "configured_systems": {
                    "systems": {
                        "RSQ": "RSQ" in report.systems,
                        "RSP": "RSP" in report.systems,
                    }
                },
                "client_details": report.details,
            },
        }

        entry["freshservice"] = handle_report(
            fs_report,
            username=entry["user"],
            computer=entry["computer"],
            email=None,
        )

        # Rewrite log with FreshService result included
        history[-1] = entry
        log_file.write_text(json.dumps(history, indent=2), encoding="utf-8")

    except Exception as exc:
        entry["freshservice_error"] = str(exc)

    return {
        "success": True,
        "message": "Client report received.",
        "logged": entry,
    }







def build_sap_bat_script(report_url: str) -> str:
    """
    Generates a self-contained Windows .bat file that configures SAP Logon
    on the user's own workstation. Pure batch - no PowerShell, no GUID
    generation. Uses fixed UUIDs (valid for a local landscape file).
    """

    bat = r'''@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   SAP Configuration Agent
echo   Dangote Refinery IT Self-Service Portal
echo ============================================
echo.

REM --- 1. Detect SAP GUI ---
set "SAPLOGON="
if exist "C:\Program Files (x86)\SAP\FrontEnd\SAPgui\saplogon.exe" set "SAPLOGON=C:\Program Files (x86)\SAP\FrontEnd\SAPgui\saplogon.exe"
if exist "C:\Program Files\SAP\FrontEnd\SAPgui\saplogon.exe" set "SAPLOGON=C:\Program Files\SAP\FrontEnd\SAPgui\saplogon.exe"

if "%SAPLOGON%"=="" (
    echo SAP GUI is not installed on this computer.
    curl -s -X POST "__REPORT_URL__" -H "Content-Type: application/json" -d "{\"success\":false,\"user\":\"%USERNAME%\",\"computer\":\"%COMPUTERNAME%\",\"systems\":[],\"message\":\"SAP GUI not installed\"}" >nul 2>&1
    echo.
    pause
    exit /b 1
)
echo SAP GUI found: %SAPLOGON%

REM --- 2. Close SAP Logon if running ---
tasklist /FI "IMAGENAME eq saplogon.exe" 2>nul | find /I "saplogon.exe" >nul
if not errorlevel 1 (
    echo Closing SAP Logon before configuration...
    taskkill /F /IM saplogon.exe >nul 2>&1
    timeout /t 2 >nul
)

REM --- 3. Prepare SAP Common folder ---
set "SAPDIR=%APPDATA%\SAP\Common"
if not exist "%SAPDIR%" mkdir "%SAPDIR%"
echo SAP Common folder: %SAPDIR%

REM --- 4. Backup existing landscape file ---
set "LANDSCAPE=%SAPDIR%\SAPUILandscape.xml"
if exist "%LANDSCAPE%" (
    set "STAMP=%DATE:/=-%_%TIME::=-%"
    set "STAMP=!STAMP: =_!"
    copy "%LANDSCAPE%" "%SAPDIR%\SAPUILandscape.backup_!STAMP!.xml" >nul
    echo Backup created.
)

REM --- 5. Write new SAPUILandscape.xml ---
echo ^<?xml version="1.0" encoding="UTF-8"?^> > "%LANDSCAPE%"
echo ^<Landscape version="1" generator="SAPConfigAgent-BAT"^> >> "%LANDSCAPE%"
echo     ^<Workspaces^> >> "%LANDSCAPE%"
echo         ^<Workspace uuid="11111111-1111-1111-1111-111111111111" name="Local" expanded="1"^> >> "%LANDSCAPE%"
echo             ^<Item uuid="22222222-2222-2222-2222-222222222222" serviceid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" /^> >> "%LANDSCAPE%"
echo             ^<Item uuid="33333333-3333-3333-3333-333333333333" serviceid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" /^> >> "%LANDSCAPE%"
echo         ^</Workspace^> >> "%LANDSCAPE%"
echo     ^</Workspaces^> >> "%LANDSCAPE%"
echo     ^<Services^> >> "%LANDSCAPE%"
echo         ^<Service type="SAPGUI" uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" name="QUALITY RSQ 420" systemid="RSQ" mode="1" server="172.31.102.60:3200" sapcpg="1100" dcpg="2" /^> >> "%LANDSCAPE%"
echo         ^<Service type="SAPGUI" uuid="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" name="Refinery and Fertilizers - PRD - on premise" systemid="RSP" mode="1" server="ikjdcprdpha02.dangote-group.com:3200" sapcpg="1100" dcpg="2" /^> >> "%LANDSCAPE%"
echo     ^</Services^> >> "%LANDSCAPE%"
echo ^</Landscape^> >> "%LANDSCAPE%"

echo SAP landscape deployed successfully.

REM --- 6. Verify RSQ and RSP are present ---
find "RSQ" "%LANDSCAPE%" >nul
if errorlevel 1 goto FAIL
find "RSP" "%LANDSCAPE%" >nul
if errorlevel 1 goto FAIL

echo Configured systems: RSQ, RSP

REM --- 7. Report success to server ---
curl -s -X POST "__REPORT_URL__" -H "Content-Type: application/json" -d "{\"success\":true,\"user\":\"%USERNAME%\",\"computer\":\"%COMPUTERNAME%\",\"systems\":[\"RSQ\",\"RSP\"],\"message\":\"SAP configured successfully\"}" >nul 2>&1



REM --- Standardize SAP GUI theme (SAP Signature) ---
reg add "HKCU\Software\SAP\General\Appearance" /v SelectedTheme /t REG_DWORD /d 1 /f >nul 2>&1
echo SAP GUI theme set to SAP Signature.


REM --- 8. Launch SAP Logon ---
start "" "%SAPLOGON%"

echo.
echo ============================================
echo   SAP configuration completed successfully.
echo   RSQ and RSP are now available in SAP Logon.
echo ============================================
echo.
pause
exit /b 0

:FAIL
echo ERROR: RSQ/RSP could not be verified in the landscape file.
curl -s -X POST "__REPORT_URL__" -H "Content-Type: application/json" -d "{\"success\":false,\"user\":\"%USERNAME%\",\"computer\":\"%COMPUTERNAME%\",\"systems\":[],\"message\":\"Verification failed\"}" >nul 2>&1
echo.
pause
exit /b 1
'''

    return bat.replace("__REPORT_URL__", report_url)