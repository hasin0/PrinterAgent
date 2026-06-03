from langchain_core.tools import tool
from playwright.sync_api import sync_playwright
import time
import threading
import os


@tool
def register_user_on_sharp(
    printer_ip: str,
    user_name: str,
    user_number: str,
    email: str,
    admin_password: str = "admin"
) -> str:
    """
    Register a new user on Sharp BP-50C36 printer via web interface.

    Required Fields:
    - user_name: Full name of user (required)
    - user_number: 5–8 digit numeric code (required)
    - email: user email address (required)

    Returns:
    - Success or failure message with details
    """


    # ============================
    # VALIDATION
    # ============================
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
                    headless=True,
                    args=["--ignore-certificate-errors"]
                )
                context = browser.new_context(ignore_https_errors=True)
                page = context.new_page()
                page.set_default_timeout(20000)

                # ============================
                # STEP 1: LOGIN
                # ============================
                page.goto(f"http://{printer_ip}", wait_until="networkidle")

                page.click("text=Administrator Login(C)")
                time.sleep(1)

                page.fill("input[name='ggt_textbox(10006)']", admin_password)
                page.click("input[name='loginbtn']")
                time.sleep(2)

                if "login" in page.url.lower():
                    result["output"] = f"❌ Login failed on {printer_ip}"
                    browser.close()
                    return

                # ============================
                # STEP 2: NAVIGATION
                # ============================
                page.click("text=User Control")
                time.sleep(1)

                page.click("text=User Settings")
                time.sleep(2)

                # ============================
                # STEP 3: CHECK EXISTING USER
                # ============================
                body_text = page.inner_text("body")

                if user_name.lower() in body_text.lower():
                    result["output"] = f"⚠️ User '{user_name}' already exists"
                    browser.close()
                    return

                # ============================
                # STEP 4: CLICK ADD
                # ============================
                page.click("input[name='addbtn']")
                time.sleep(2)

                # ============================
                # STEP 5: FILL FORM
                # ============================
                page.fill("input[name='ggt_textbox(1)']", user_name)
                page.fill("input[name='ggt_textbox(3)']", user_name[:10])
                page.fill("input[name='ggt_textbox(5)']", user_number)
                page.fill("input[name='ggt_textbox(8)']", email)

                # ============================
                # STEP 6: SUBMIT
                # ============================
                page.click("input[name='submitbtn']")
                time.sleep(2)

                # ============================
                # STEP 7: DEBUG INFO
                # ============================
                print("DEBUG URL:", page.url)
                print("DEBUG TITLE:", page.title())

                page_text = page.inner_text("body")

                # ============================
                # STEP 8: ERROR CHECK ✅ (NEW)
                # ============================
                if "this number is already used" in page_text.lower():
                    result["output"] = f"""
❌ FAILED

User Number '{user_number}' already exists on printer.

👉 Choose another number (5–8 digits).
"""
                
                elif "error" in page_text.lower():
                    result["output"] = f"""
❌ FAILED: Printer returned error

Details:
{page_text[:400]}
"""

                # ============================
                # STEP 9: SUCCESS CHECK ✅ (IMPROVED)
                # ============================
                elif "user list" in page.url.lower() or "user list" in page.title().lower():
                    result["output"] = f"""
✅ SUCCESS

User Registered:
- Name: {user_name}
- Code: {user_number}
- Email: {email}

Printer IP: {printer_ip}
"""

                elif user_name.lower() in page_text.lower():
                    result["output"] = f"""
✅ SUCCESS (Verified by Name Match)

User '{user_name}' found on printer.
"""

                else:
                    result["output"] = """
⚠️ Submitted but verification unclear.
Check audit screenshot.
"""

                # ============================
                # STEP 10: SCREENSHOT
                # ============================
                os.makedirs("audit", exist_ok=True)
                page.screenshot(path=f"audit/{user_name}_{printer_ip}.png")

                # ============================
                # STEP 11: LOGOUT
                # ============================
                try:
                    page.click("text=Logout")
                except:
                    pass

                browser.close()

        except Exception as e:
            result["output"] = f"❌ ERROR: {str(e)}"

    # Run thread
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=60)

    if not result["output"]:
        return "ERROR: Operation timeout"

    return result["output"]


# ============================
# TEST RUNNER
# ============================
if __name__ == "__main__":
    result = register_user_on_sharp.invoke({
        "printer_ip": "172.16.16.31",
        "user_name": "Test User thursday",
        "user_number": "43576",
        "email": "test@dangote.com"
    })

    print(result)