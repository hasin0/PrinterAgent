# from langchain_core.tools import tool
from playwright.sync_api import sync_playwright
import time
import threading
import os



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

        try:

            with sync_playwright() as p:

                browser = p.chromium.launch(
                    headless=True,      # <-  False  after testing
                    args=["--ignore-certificate-errors"]
                )

                context = browser.new_context(
                    ignore_https_errors=True
                )

                page = context.new_page()
                page.set_default_timeout(20000)

                page.goto(
                    f"http://{printer_ip}",
                    wait_until="networkidle"
                )

                page.click("text=Administrator Login(C)")
                time.sleep(1)

                page.fill(
                    "input[name='ggt_textbox(10006)']",
                    admin_password
                )

                page.click("input[name='loginbtn']")
                time.sleep(2)

                page.click("text=User Control")
                time.sleep(1)

                page.click("text=User Settings")
                time.sleep(2)

                page.click("input[name='addbtn']")
                time.sleep(2)

                page.fill(
                    "input[name='ggt_textbox(1)']",
                    user_name
                )

                page.fill(
                    "input[name='ggt_textbox(3)']",
                    user_name[:10]
                )

                page.fill(
                    "input[name='ggt_textbox(5)']",
                    user_number
                )

                page.fill(
                    "input[name='ggt_textbox(8)']",
                    email
                )

                page.click("input[name='submitbtn']")
                time.sleep(2)

                os.makedirs("audit", exist_ok=True)

                page.screenshot(
                    path=f"audit/{user_name}_{printer_ip}.png"
                )

                result["output"] = (
                    f"SUCCESS\n"
                    f"User: {user_name}\n"
                    f"Code: {user_number}\n"
                    f"Email: {email}\n"
                    f"Printer: {printer_ip}"
                )

                browser.close()

        except Exception as e:
            result["output"] = f"ERROR: {str(e)}"

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join(timeout=60)

    if not result["output"]:
        return "ERROR: Registration timeout"

    return result["output"]