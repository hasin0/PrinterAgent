# from langchain_core.tools import tool
from playwright.sync_api import sync_playwright
import time
import threading
import os


# =============================================================
# HELPERS
# =============================================================

def open_printer(page, printer_ip, path=""):
    """
    Open the printer web UI. Tries HTTPS first (newer Sharp BP-series
    firmware uses a self-signed cert), then falls back to HTTP for
    older MX models. Returns the scheme that worked.
    """
    last_err = None
    for scheme in ("https", "http"):
        try:
            page.goto(f"{scheme}://{printer_ip}/{path}",
                      wait_until="networkidle", timeout=20000)
            return scheme
        except Exception as e:
            last_err = e
    raise last_err


def click_first(page, selectors, timeout=8000):
    """
    Click the first selector that exists. Lets one script handle small
    label differences between Sharp MX and BP firmware.
    """
    last_err = None
    for sel in selectors:
        try:
            page.click(sel, timeout=timeout)
            return sel
        except Exception as e:
            last_err = e
    raise last_err


def safe_name(text):
    """Make a string safe for use in a filename."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in text)


# =============================================================
# MAIN
# =============================================================

# @tool
def register_user_on_sharp(
    printer_ip: str,
    user_name: str,
    user_number: str,
    email: str,
    admin_password: str = "admin"
) -> str:
    """
    Register a user on a Sharp printer through the Sharp web interface.

    Parameters:
    - printer_ip: Printer IP Address
    - user_name: Full user name
    - user_number: User number (5-8 digits)
    - email: User email
    - admin_password: Sharp admin password

    Returns:
    - Success or failure message
    """

    if not user_name or len(user_name.strip()) < 2:
        return "ERROR: User Name is required"

    if not user_number.isdigit() or not (5 <= len(user_number) <= 8):
        return "ERROR: User Number must be 5–8 digits"

    if not email or "@" not in email:
        return "ERROR: Valid email is required"

    result = {"output": ""}

    def _run():
        browser = None
        page = None
        stage = "starting"

        try:
            with sync_playwright() as p:

                browser = p.chromium.launch(
                    headless=True,      # <- set False to watch it while testing
                    args=["--ignore-certificate-errors"]
                )

                # Accept the printer's self-signed HTTPS certificate
                context = browser.new_context(ignore_https_errors=True)

                page = context.new_page()
                page.set_default_timeout(20000)

                # ---- 1. Open printer (HTTPS first, then HTTP) ----
                stage = "opening printer"
                scheme = open_printer(page, printer_ip)

                # ---- 2. Administrator login ----
                stage = "admin login"
                click_first(page, [
                    "text=Administrator Login(C)",
                    "text=Administrator Login",
                    "text=Login",
                ])
                time.sleep(1)

                page.fill("input[name='ggt_textbox(10006)']", admin_password)
                page.click("input[name='loginbtn']")
                time.sleep(2)

                # ---- 3. Navigate to User Settings ----
                stage = "navigating user settings"
                try:
                    page.click("text=User Control")
                except Exception:
                    # Login likely failed (wrong password / still on login page)
                    raise RuntimeError("LOGIN_FAILED: could not reach User Control after login")
                time.sleep(1)

                page.click("text=User Settings")
                time.sleep(2)

                # ---- 4. Add user ----
                stage = "adding user"
                page.click("input[name='addbtn']")
                time.sleep(2)

                page.fill("input[name='ggt_textbox(1)']", user_name)
                page.fill("input[name='ggt_textbox(3)']", user_name[:10])
                page.fill("input[name='ggt_textbox(5)']", user_number)
                page.fill("input[name='ggt_textbox(8)']", email)

                stage = "submitting"
                page.click("input[name='submitbtn']")
                time.sleep(2)

                # ---- 5. Audit screenshot ----
                os.makedirs("audit", exist_ok=True)
                page.screenshot(
                    path=f"audit/{safe_name(user_name)}_{printer_ip}.png"
                )

                # Detect "already registered" message if the printer shows one
                body = (page.inner_text("body") or "").lower()
                if "already" in body and ("registered" in body or "exist" in body):
                    result["output"] = (
                        f"ALREADY_EXISTS\n"
                        f"User: {user_name}\n"
                        f"Code: {user_number}\n"
                        f"Printer: {printer_ip}"
                    )
                else:
                    result["output"] = (
                        f"SUCCESS\n"
                        f"User: {user_name}\n"
                        f"Code: {user_number}\n"
                        f"Email: {email}\n"
                        f"Printer: {printer_ip} ({scheme.upper()})"
                    )

                browser.close()

        except Exception as e:
            # Save a screenshot of where it failed - very useful for debugging
            try:
                if page is not None:
                    os.makedirs("audit", exist_ok=True)
                    page.screenshot(
                        path=f"audit/FAILED_{safe_name(user_name)}_{printer_ip}.png"
                    )
            except Exception:
                pass

            msg = str(e)
            if "LOGIN_FAILED" in msg:
                result["output"] = f"LOGIN_FAILED at {stage}: {msg}"
            elif "Timeout" in msg or "timeout" in msg:
                result["output"] = f"TIMEOUT at {stage}: {msg}"
            else:
                result["output"] = f"FAILED at {stage}: {msg}"

            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join(timeout=75)

    if not result["output"]:
        return "TIMEOUT: Registration did not finish within 75 seconds"

    return result["output"]
