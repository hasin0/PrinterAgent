# sap_routes.py
"""SAP Config Agent API routes."""

from fastapi import APIRouter, Query, Response, Request
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
import json
import os
from agents.sap_config_agent import SAPConfigAgent


class SAPClientReport(BaseModel):
    success: bool
    user: str | None = None
    computer: str | None = None
    message: str | None = None
    systems: list[str] = []
    details: dict = {}





router = APIRouter(prefix="/sap", tags=["SAP Config Agent"])


def agent() -> SAPConfigAgent:
    return SAPConfigAgent()


# ---------------- STATUS / PRECHECK ----------------
@router.get("/status")
def sap_status(check_connectivity: bool = Query(False)):
    """Single call that powers the SAP card on the dashboard."""
    return agent().get_status(check_connectivity=check_connectivity)


@router.get("/precheck")
def sap_precheck():
    return agent().run_precheck()


@router.get("/configured-systems")
def sap_configured_systems():
    return agent().get_configured_systems()


# ---------------- DEPLOYMENT ----------------
@router.post("/create-common-folder")
def sap_create_common_folder():
    return agent().create_sap_common_folder()


@router.post("/deploy")
def sap_deploy(force: bool = Query(False)):
    return agent().deploy_landscape(force=force)


@router.get("/preview-xml")
def sap_preview_xml():
    return {"xml": agent().build_landscape_xml()}


# ---------------- CONNECTIVITY ----------------
@router.get("/connectivity")
def sap_connectivity():
    return agent().verify_all_systems()


# ---------------- LAUNCH ----------------
@router.post("/launch")
def sap_launch():
    return agent().launch_sap()


@router.post("/close")
def sap_close():
    return agent().close_saplogon()


# ---------------- ONE-CLICK ----------------
@router.post("/configure")
def sap_configure(launch: bool = Query(True), force: bool = Query(False)):
    return agent().configure_sap(launch=launch, force=force)


# ---------------- AUDIT LOG ----------------
@router.get("/logs")
def sap_logs(limit: int = Query(20, ge=1, le=500)):
    return agent().get_logs(limit=limit)











def build_sap_powershell_script(report_url: str) -> str:
    """
    Generates a self-contained PowerShell script that configures SAP Logon
    locally on the user's workstation.
    """

    return f'''# configure_sap.ps1
# SAPConfigAgent - Local Workstation Configuration
# Dangote Petroleum Refinery | Hermes IT Self-Service Portal

$ErrorActionPreference = "Stop"

$ReportUrl = "{report_url}"

$Systems = @(
    @{{
        SID = "RSQ"
        Name = "QUALITY RSQ 420"
        Host = "172.31.102.60"
        Instance = "00"
        Port = "3200"
    }},
    @{{
        SID = "RSP"
        Name = "Refinery and Fertilizers - PRD - on premise"
        Host = "ikjdcprdpha02.dangote-group.com"
        Instance = "00"
        Port = "3200"
    }}
)

function Send-Report {{
    param(
        [bool]$Success,
        [string]$Message,
        [string[]]$SystemsConfigured,
        [hashtable]$Details
    )

    try {{
        $body = @{{
            success  = $Success
            user     = $env:USERNAME
            computer = $env:COMPUTERNAME
            message  = $Message
            systems  = $SystemsConfigured
            details  = $Details
        }} | ConvertTo-Json -Depth 6

        Invoke-RestMethod -Method Post -Uri $ReportUrl -Body $body -ContentType "application/json" | Out-Null
    }}
    catch {{
        Write-Host "Could not send report to server: $($_.Exception.Message)" -ForegroundColor Yellow
    }}
}}

function Find-SapLogon {{
    $paths = @(
        "C:\\Program Files (x86)\\SAP\\FrontEnd\\SAPgui\\saplogon.exe",
        "C:\\Program Files\\SAP\\FrontEnd\\SAPgui\\saplogon.exe"
    )

    foreach ($p in $paths) {{
        if (Test-Path $p) {{
            return $p
        }}
    }}

    return $null
}}

function New-GuidString {{
    return :NewGuid().ToString()
}}

function Build-LandscapeXml {{
    $workspaceId = New-GuidString

    $rsqServiceId = New-GuidString
    $rspServiceId = New-GuidString

    $rsqItemId = New-GuidString
    $rspItemId = New-GuidString

    $now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

    $xml = @"
<?xml version="1.0" encoding="UTF-8"?>
<Landscape updated="$now" version="1" generator="SAPConfigAgent-PowerShell">
    <Workspaces>
        <Workspace uuid="$workspaceId" name="Local" expanded="1">
            <Item uuid="$rsqItemId" serviceid="$rsqServiceId" />
            <Item uuid="$rspItemId" serviceid="$rspServiceId" />
        </Workspace>
    </Workspaces>
    <Services>
        <Service type="SAPGUI" uuid="$rsqServiceId" name="QUALITY RSQ 420" systemid="RSQ" mode="1" server="172.31.102.60:3200" sapcpg="1100" dcpg="2" />
        <Service type="SAPGUI" uuid="$rspServiceId" name="Refinery and Fertilizers - PRD - on premise" systemid="RSP" mode="1" server="ikjdcprdpha02.dangote-group.com:3200" sapcpg="1100" dcpg="2" />
    </Services>
</Landscape>
"@

    return $xml
}}

try {{
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host " SAP Configuration Agent" -ForegroundColor Cyan
    Write-Host " Dangote Refinery IT Self-Service Portal" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""

    # 1. Detect SAP GUI
    $sapLogon = Find-SapLogon

    if (-not $sapLogon) {{
        $msg = "SAP GUI is not installed on this computer."
        Write-Host $msg -ForegroundColor Red

        Send-Report -Success $false -Message $msg -SystemsConfigured @() -Details @{{
            sap_gui_installed = $false
        }}

        Read-Host "Press Enter to exit"
        exit 1
    }}

    Write-Host "SAP GUI found: $sapLogon" -ForegroundColor Green

    # 2. Close SAP Logon if running
    $running = Get-Process saplogon -ErrorAction SilentlyContinue
    if ($running) {{
        Write-Host "SAP Logon is currently running. Closing it before configuration..." -ForegroundColor Yellow
        Stop-Process -Name saplogon -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }}

    # 3. Prepare SAP Common folder
    $sapCommonPath = Join-Path $env:APPDATA "SAP\\Common"

    if (-not (Test-Path $sapCommonPath)) {{
        New-Item -Path $sapCommonPath -ItemType Directory -Force | Out-Null
    }}

    Write-Host "SAP Common folder: $sapCommonPath" -ForegroundColor Green

    # 4. Backup existing landscape
    $landscapePath = Join-Path $sapCommonPath "SAPUILandscape.xml"
    $backupPath = $null

    if (Test-Path $landscapePath) {{
        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $backupPath = Join-Path $sapCommonPath "SAPUILandscape.backup_$stamp.xml"
        Copy-Item $landscapePath $backupPath -Force
        Write-Host "Backup created: $backupPath" -ForegroundColor Green
    }}

    # 5. Write new SAPUILandscape.xml
    $xml = Build-LandscapeXml
    Set-Content -Path $landscapePath -Value $xml -Encoding UTF8

    Write-Host "SAP landscape deployed successfully." -ForegroundColor Green

    # 6. Verify configured systems inside the XML
    [xml]$checkXml = Get-Content $landscapePath -Raw
    $configured = @($checkXml.Landscape.Services.Service | ForEach-Object {{ $_.systemid }})

    $rsqOk = $configured -contains "RSQ"
    $rspOk = $configured -contains "RSP"

    if (-not ($rsqOk -and $rspOk)) {{
        throw "SAP landscape file was written, but RSQ/RSP could not be verified."
    }}

    Write-Host "Configured systems: $($configured -join ', ')" -ForegroundColor Green

    # 7. Optional connectivity check
    $connectivity = @{{}}

    foreach ($s in $Systems) {{
        $tcp = New-Object System.Net.Sockets.TcpClient
        $reachable = $false

        try {{
            $reachable = $tcp.ConnectAsync($s.Host, [int]$s.Port).Wait(4000)
        }}
        catch {{
            $reachable = $false
        }}
        finally {{
            $tcp.Close()
        }}

        $connectivity[$s.SID] = @{{
            host = $s.Host
            port = $s.Port
            reachable = $reachable
        }}

        if ($reachable) {{
            Write-Host "$($s.SID) server reachable." -ForegroundColor Green
        }}
        else {{
            Write-Host "$($s.SID) server not reachable. This is expected if you are outside the refinery network." -ForegroundColor Yellow
        }}
    }}

    # 8. Launch SAP Logon
    Start-Process $sapLogon

    $msg = "SAP configuration completed successfully. RSQ and RSP are now available in SAP Logon."

    Send-Report -Success $true -Message $msg -SystemsConfigured @("RSQ", "RSP") -Details @{{
        sap_gui_installed = $true
        saplogon_path = $sapLogon
        landscape_path = $landscapePath
        backup_path = $backupPath
        connectivity = $connectivity
    }}

    Write-Host ""
    Write-Host $msg -ForegroundColor Green
    Write-Host ""

    Read-Host "Press Enter to close"

}}
catch {{
    $err = $_.Exception.Message

    Write-Host ""
    Write-Host "SAP configuration failed: $err" -ForegroundColor Red
    Write-Host ""

    Send-Report -Success $false -Message $err -SystemsConfigured @() -Details @{{
        error = $err
    }}

    Read-Host "Press Enter to exit"
    exit 1
}}
'''


















# ----------------------------------------------------------------------
# DOWNLOADABLE LOCAL SAP CONFIGURATION SCRIPT
# ----------------------------------------------------------------------
@router.get("/download-script")
def download_sap_script(request: Request):
    """
    Downloads a PowerShell script that runs on the user's PC.
    This is the correct model for configuring %APPDATA% on the endpoint.
    """

    base_url = str(request.base_url).rstrip("/")
    report_url = f"{base_url}/sap/client-report"

    script = build_sap_powershell_script(report_url)

    return Response(
        content=script,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename=configure_sap.ps1"
        }
    )


@router.post("/client-report")
def sap_client_report(report: SAPClientReport):
    """
    Receives success/failure result from the PowerShell script running
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
        "source": "client_powershell_script"
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
                        "RSP": "RSP" in report.systems
                    }
                },
                "client_details": report.details
            }
        }

        entry["freshservice"] = handle_report(
            fs_report,
            username=entry["user"],
            computer=entry["computer"],
            email=None
        )

    except Exception as exc:
        entry["freshservice_error"] = str(exc)

    return {
        "success": True,
        "message": "Client report received.",
        "logged": entry     
    }