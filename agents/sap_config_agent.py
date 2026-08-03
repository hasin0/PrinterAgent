# agents/sap_config_agent.py
"""
SAPConfigAgent - IT Self-Service Automation
Dangote Petroleum Refinery | PrinterAgent Platform

Capabilities:
    1. Detect SAP GUI installation
    2. Generate a VALID SAPUILandscape.xml (RSQ + RSP)
    3. Deploy configuration to the logged-in user's profile
    4. Verify application server connectivity (parallel)
    5. Launch SAP Logon
    6. Write an audit log / success report for the dashboard
"""

import os
import json
import socket
import shutil
import subprocess
import xml.etree.ElementTree as ET
from uuid import uuid4
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor


class SAPConfigAgent:

    # ------------------------------------------------------------------
    # SAP systems managed by this agent
    # ------------------------------------------------------------------
    SAP_SYSTEMS = {
        "RSQ": {
            "description": "QUALITY RSQ 420",
            "host": "172.31.102.60",
            "instance": "00",
        },
        "RSP": {
            "description": "Refinery and Fertilizers - PRD - on premise",
            "host": "ikjdcprdpha02.dangote-group.com",
            "instance": "00",
        },
    }

    WORKSPACE_NAME = "Local"
    LOG_FILE = Path("data/sap_config_log.json")

    def __init__(self):
        self.common_sap_paths = [
            r"C:\Program Files (x86)\SAP\FrontEnd\SAPgui\saplogon.exe",
            r"C:\Program Files\SAP\FrontEnd\SAPgui\saplogon.exe",
        ]

    # ==================================================================
    # HELPERS
    # ==================================================================
    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _dispatcher_port(instance: str) -> int:
        """SAP dispatcher port = 32<instance>  (instance 00 -> 3200)."""
        return int(f"32{str(instance).zfill(2)}")

    def landscape_path(self) -> Path:
        """Full path to the user's SAPUILandscape.xml."""
        appdata = os.getenv("APPDATA")
        return Path(appdata) / "SAP" / "Common" / "SAPUILandscape.xml"

    # ==================================================================
    # STEP 1 - DETECTION
    # ==================================================================
    def detect_sap_gui(self):
        """Detect if SAP GUI / SAP Logon is installed on this PC."""

        result = {"installed": False, "saplogon_path": None, "message": ""}

        for path in self.common_sap_paths:
            if os.path.exists(path):
                result.update(
                    installed=True,
                    saplogon_path=path,
                    message="SAP GUI is installed.",
                )
                return result

        try:
            process = subprocess.run(
                ["where", "saplogon.exe"],
                capture_output=True,
                text=True,
                shell=True,
            )

            if process.returncode == 0 and process.stdout.strip():
                result.update(
                    installed=True,
                    saplogon_path=process.stdout.strip().splitlines()[0],
                    message="SAP GUI is installed.",
                )
                return result

        except Exception as e:
            result["message"] = f"Unable to check SAP GUI from PATH: {e}"
            return result

        result["message"] = "SAP GUI is not installed on this PC."
        return result

    def get_sap_common_folder(self):
        """Return SAP Common folder status for the current user."""

        appdata = os.getenv("APPDATA")

        if not appdata:
            return {
                "exists": False,
                "path": None,
                "message": "APPDATA environment variable was not found.",
            }

        sap_common_path = Path(appdata) / "SAP" / "Common"

        return {
            "exists": sap_common_path.exists(),
            "path": str(sap_common_path),
            "message": "SAP Common folder found."
            if sap_common_path.exists()
            else "SAP Common folder does not exist yet.",
        }

    def create_sap_common_folder(self):
        """Create SAP Common folder if missing."""

        appdata = os.getenv("APPDATA")

        if not appdata:
            return {
                "success": False,
                "path": None,
                "message": "APPDATA environment variable was not found.",
            }

        sap_common_path = Path(appdata) / "SAP" / "Common"

        try:
            sap_common_path.mkdir(parents=True, exist_ok=True)
            return {
                "success": True,
                "path": str(sap_common_path),
                "message": "SAP Common folder is ready.",
            }
        except Exception as e:
            return {
                "success": False,
                "path": str(sap_common_path),
                "message": f"Failed to create SAP Common folder: {e}",
            }

    def is_saplogon_running(self):
        """
        SAP Logon rewrites SAPUILandscape.xml when it closes.
        Deploying while it is open will silently lose the configuration.
        """
        try:
            process = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq saplogon.exe"],
                capture_output=True,
                text=True,
                shell=True,
            )
            running = "saplogon.exe" in process.stdout.lower()

            return {
                "running": running,
                "message": "SAP Logon is currently running. Close it before deploying."
                if running
                else "SAP Logon is not running.",
            }
        except Exception as e:
            return {"running": False, "message": f"Could not check process list: {e}"}

    def close_saplogon(self):
        """Force close SAP Logon (used only when the user approves it)."""
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "saplogon.exe"],
                capture_output=True,
                text=True,
                shell=True,
            )
            return {"success": True, "message": "SAP Logon closed."}
        except Exception as e:
            return {"success": False, "message": f"Failed to close SAP Logon: {e}"}

    def run_precheck(self):
        """Full SAP configuration precheck."""
        return {
            "sap_gui": self.detect_sap_gui(),
            "sap_common_folder": self.get_sap_common_folder(),
            "saplogon_process": self.is_saplogon_running(),
        }

    # ==================================================================
    # STEP 2 - BUILD A VALID SAPUILandscape.xml
    # ==================================================================
    def build_landscape_xml(self) -> str:
        """
        Generate a SAP Logon compatible landscape file.

        Required structure:
            <Landscape>
                <Workspaces><Workspace><Item serviceid=.../></Workspace></Workspaces>
                <Services><Service type="SAPGUI" .../></Services>
            </Landscape>
        """

        landscape = ET.Element(
            "Landscape",
            {
                "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "version": "1",
                "generator": "SAPConfigAgent",
            },
        )

        workspaces = ET.SubElement(landscape, "Workspaces")
        workspace = ET.SubElement(
            workspaces,
            "Workspace",
            {
                "uuid": str(uuid4()),
                "name": self.WORKSPACE_NAME,
                "expanded": "1",
            },
        )

        services = ET.SubElement(landscape, "Services")

        for sid, cfg in self.SAP_SYSTEMS.items():
            service_uuid = str(uuid4())
            port = self._dispatcher_port(cfg["instance"])

            ET.SubElement(
                services,
                "Service",
                {
                    "type": "SAPGUI",
                    "uuid": service_uuid,
                    "name": cfg["description"],
                    "systemid": sid,
                    "mode": "1",  # 1 = custom application server
                    "server": f"{cfg['host']}:{port}",
                    "sapcpg": "1100",
                    "dcpg": "2",
                },
            )

            ET.SubElement(
                workspace,
                "Item",
                {"uuid": str(uuid4()), "serviceid": service_uuid},
            )

        ET.indent(landscape, space="    ")

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(landscape, encoding="unicode")
        )

    # ==================================================================
    # STEP 3 - DEPLOY
    # ==================================================================
    def deploy_landscape(self, force: bool = False):
        """Write the generated landscape file into the user's SAP profile."""

        destination = self.landscape_path()

        # Guard: SAP Logon must be closed
        process_state = self.is_saplogon_running()
        if process_state["running"] and not force:
            return {
                "success": False,
                "requires_close": True,
                "destination": str(destination),
                "message": "SAP Logon is open. Close SAP Logon and try again "
                           "(or deploy with force=true to close it automatically).",
            }

        if process_state["running"] and force:
            self.close_saplogon()

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)

            # Backup existing configuration for rollback safety
            backup_path = None
            if destination.exists():
                backup_path = destination.with_name(
                    f"SAPUILandscape.backup_{datetime.now():%Y%m%d_%H%M%S}.xml"
                )
                shutil.copy2(destination, backup_path)

            destination.write_text(self.build_landscape_xml(), encoding="utf-8")

            return {
                "success": True,
                "destination": str(destination),
                "backup": str(backup_path) if backup_path else None,
                "systems_deployed": list(self.SAP_SYSTEMS.keys()),
                "message": "SAP Landscape deployed successfully.",
            }

        except Exception as e:
            return {"success": False, "message": f"Deployment failed: {e}"}

    def get_configured_systems(self):
        """Read the deployed landscape file and report which systems exist."""

        destination = self.landscape_path()

        result = {
            "file_exists": destination.exists(),
            "path": str(destination),
            "systems": {sid: False for sid in self.SAP_SYSTEMS},
            "message": "",
        }

        if not destination.exists():
            result["message"] = "No SAP landscape file found for this user."
            return result

        try:
            tree = ET.parse(destination)
            found = {
                (service.get("systemid") or "").upper()
                for service in tree.iter("Service")
            }

            for sid in self.SAP_SYSTEMS:
                result["systems"][sid] = sid in found

            configured = [s for s, ok in result["systems"].items() if ok]
            result["message"] = (
                f"Configured systems: {', '.join(configured)}"
                if configured
                else "Landscape file exists but RSQ/RSP were not found."
            )

        except Exception as e:
            result["message"] = f"Could not read landscape file: {e}"

        return result

    # ==================================================================
    # STEP 4 - CONNECTIVITY (PARALLEL)
    # ==================================================================
    def verify_connection(self, host, instance="00", timeout=4):
        """TCP check against the SAP dispatcher port (32<instance>)."""

        port = self._dispatcher_port(instance)
        started = datetime.now()

        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
            reachable, message = True, "Application server is reachable."
        except socket.timeout:
            reachable, message = False, "Timed out - host not reachable on this network."
        except socket.gaierror:
            reachable, message = False, "Hostname could not be resolved (DNS)."
        except Exception as e:
            reachable, message = False, f"Not reachable: {e}"

        return {
            "reachable": reachable,
            "host": host,
            "port": port,
            "response_time_ms": round(
                (datetime.now() - started).total_seconds() * 1000
            ),
            "message": message,
        }

    def verify_all_systems(self):
        """Check every SAP system concurrently so the UI never stalls."""

        results = {}

        def check(item):
            sid, cfg = item
            return sid, {
                "description": cfg["description"],
                **self.verify_connection(cfg["host"], cfg["instance"]),
            }

        with ThreadPoolExecutor(max_workers=len(self.SAP_SYSTEMS)) as pool:
            for sid, data in pool.map(check, self.SAP_SYSTEMS.items()):
                results[sid] = data

        results["checked_at"] = self._now()
        return results

    # ==================================================================
    # STEP 5 - LAUNCH
    # ==================================================================
    def launch_sap(self):
        """Launch SAP Logon after configuration is deployed."""

        check = self.detect_sap_gui()

        if not check["installed"]:
            return {"success": False, "message": "SAP GUI is not installed on this PC."}

        try:
            subprocess.Popen([check["saplogon_path"]])
            return {
                "success": True,
                "saplogon_path": check["saplogon_path"],
                "message": "SAP Logon launched successfully.",
            }
        except Exception as e:
            return {"success": False, "message": f"Failed to launch SAP Logon: {e}"}

    # ==================================================================
    # STEP 6 - AUDIT LOG / SUCCESS REPORT
    # ==================================================================
    def _write_audit_log(self, report):
        """Append the configuration result to data/sap_config_log.json."""

        try:
            self.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

            history = []
            if self.LOG_FILE.exists():
                try:
                    history = json.loads(self.LOG_FILE.read_text(encoding="utf-8"))
                except Exception:
                    history = []

            history.append(
                {
                    "timestamp": report.get("started_at"),
                    "user": os.getenv("USERNAME"),
                    "computer": os.getenv("COMPUTERNAME"),
                    "success": report.get("success"),
                    "message": report.get("message"),
                    "systems": list(self.SAP_SYSTEMS.keys()),
                }
            )

            # Keep the most recent 500 entries
            history = history[-500:]

            self.LOG_FILE.write_text(
                json.dumps(history, indent=2), encoding="utf-8"
            )
        except Exception:
            pass  # never let logging break the workflow

    def get_logs(self, limit: int = 20):
        """Return the most recent configuration events for the dashboard."""

        if not self.LOG_FILE.exists():
            return {"count": 0, "logs": []}

        try:
            history = json.loads(self.LOG_FILE.read_text(encoding="utf-8"))
            return {"count": len(history), "logs": history[-limit:][::-1]}
        except Exception as e:
            return {"count": 0, "logs": [], "error": str(e)}

    # ==================================================================
    # DASHBOARD STATUS (single call for the SAP card)
    # ==================================================================
    def get_status(self, check_connectivity: bool = False):
        """Lightweight status snapshot used by the dashboard card."""

        gui = self.detect_sap_gui()
        configured = self.get_configured_systems()

        status = {
            "sap_gui_installed": gui["installed"],
            "saplogon_path": gui["saplogon_path"],
            "saplogon_running": self.is_saplogon_running()["running"],
            "landscape_deployed": configured["file_exists"],
            "landscape_path": configured["path"],
            "systems": {
                sid: {
                    "description": cfg["description"],
                    "host": cfg["host"],
                    "instance": cfg["instance"],
                    "configured": configured["systems"].get(sid, False),
                }
                for sid, cfg in self.SAP_SYSTEMS.items()
            },
            "user": os.getenv("USERNAME"),
            "computer": os.getenv("COMPUTERNAME"),
            "checked_at": self._now(),
        }

        if check_connectivity:
            connectivity = self.verify_all_systems()
            for sid in self.SAP_SYSTEMS:
                status["systems"][sid]["reachable"] = connectivity[sid]["reachable"]
                status["systems"][sid]["connectivity_message"] = connectivity[sid]["message"]

        ready = status["sap_gui_installed"] and all(
            s["configured"] for s in status["systems"].values()
        )
        status["ready"] = ready
        status["summary"] = (
            "SAP is configured and ready."
            if ready
            else "SAP configuration is required on this PC."
        )

        return status

    # ==================================================================
    # ONE-CLICK ORCHESTRATION
    # ==================================================================
    def configure_sap(self, launch: bool = True, force: bool = False):
        """Full workflow: precheck -> deploy -> verify -> launch -> report."""

        report = {"started_at": self._now(), "steps": {}}

        # 1. Precheck
        precheck = self.run_precheck()
        report["steps"]["precheck"] = precheck

        if not precheck["sap_gui"]["installed"]:
            report.update(
                success=False,
                message="SAP GUI is not installed. Install SAP GUI first.",
                completed_at=self._now(),
            )
            self._write_audit_log(report)
            return report

        # 2. Ensure folder exists
        if not precheck["sap_common_folder"]["exists"]:
            report["steps"]["create_folder"] = self.create_sap_common_folder()

        # 3. Deploy landscape
        deploy = self.deploy_landscape(force=force)
        report["steps"]["deploy"] = deploy

        if not deploy["success"]:
            report.update(
                success=False,
                message=deploy["message"],
                completed_at=self._now(),
            )
            self._write_audit_log(report)
            return report

        # 4. Confirm systems written
        report["steps"]["configured_systems"] = self.get_configured_systems()

        # 5. Connectivity
        report["steps"]["connectivity"] = self.verify_all_systems()

        # 6. Launch SAP Logon
        if launch:
            report["steps"]["launch"] = self.launch_sap()

        report.update(
            success=True,
            message="SAP configuration completed successfully.",
            completed_at=self._now(),
        )

        self._write_audit_log(report)
        return report
