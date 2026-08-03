# sap_routes.py
"""SAP Config Agent API routes."""

from fastapi import APIRouter, Query
from agents.sap_config_agent import SAPConfigAgent

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