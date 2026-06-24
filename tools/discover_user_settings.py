from playwright.sync_api import sync_playwright
import time
import os
import argparse

import sys
import os

# Add project root folder to Python import path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from printer_list import PRINTERS
except Exception as e:
    print("ERROR: Could not import printer_list.py")
    print("Reason:", e)
    PRINTERS = {}
def resolve_printer_ip(printer_key=None, direct_ip=None):
    """
    Resolve printer IP either from:
    1. --ip direct IP address
    2. --printer key from printer_list.py
    """

    if direct_ip:
        return direct_ip, direct_ip, "DIRECT IP"

    if not printer_key:
        raise ValueError("You must provide either --printer or --ip")

    if not PRINTERS:
        raise ValueError(
            "No printers loaded from printer_list.py. "
            "Check that printer_list.py exists in the project root and can be imported."
        )

    printer = PRINTERS.get(printer_key)

    if not printer:
        available = "\n".join([f" - {key}" for key in PRINTERS.keys()])
        raise ValueError(
            f"Printer key '{printer_key}' not found in printer_list.py.\n\n"
            f"Available printers:\n{available}"
        )

    printer_ip = printer["ip"]
    printer_name = printer.get("display_name", printer_key)
    printer_location = printer.get("location", "")

    return printer_ip, printer_name, printer_location


def discover_user_settings(printer_ip, admin_password, printer_name="UNKNOWN", printer_location="UNKNOWN"):
    os.makedirs("discover", exist_ok=True)

    print(f"\n{'=' * 60}")
    print(f"  EXPLORING USER SETTINGS")
    print(f"  Printer: {printer_name}")
    print(f"  Location: {printer_location}")
    print(f"  URL: http://{printer_ip}")
    print(f"{'=' * 60}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--ignore-certificate-errors"]
        )

        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.set_default_timeout(30000)

        # STEP 1: Login as admin
        print("1. Logging in as admin...")

        page.goto(f"http://{printer_ip}", wait_until="networkidle")

        page.click("text=Administrator Login(C)")
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        page.fill("input[name='ggt_textbox(10006)']", admin_password)
        page.click("input[name='loginbtn']")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        print("   ✅ Logged in!")

        # STEP 2: Click User Control tab
        print("\n2. Clicking User Control tab...")

        page.click("text=User Control")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        # STEP 3: Click User Settings
        print("\n3. Clicking 'User Settings'...")

        page.click("text=User Settings")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        print(f"   URL: {page.url}")
        print(f"   Title: {page.title()}")

        screenshot_1 = f"discover/{printer_name.replace(' ', '_')}_user_settings.png"
        page.screenshot(path=screenshot_1, full_page=True)

        print(f"   Screenshot: {screenshot_1}")

        # STEP 4: Scan the User Settings page
        print("\n4. User Settings page content:")

        # Left menu links
        print("\n   LEFT MENU:")

        for frame in page.frames:
            links = frame.query_selector_all("a")

            for link in links:
                try:
                    text = link.inner_text().strip()
                    href = link.get_attribute("href") or ""

                    if text and len(text) < 100:
                        print(f"   [{text}] -> {href}")
                except Exception:
                    continue

        # All buttons
        print("\n   BUTTONS:")

        for frame in page.frames:
            buttons = frame.query_selector_all(
                "input[type='button'], input[type='submit'], button"
            )

            for btn in buttons:
                try:
                    name = btn.get_attribute("name") or ""
                    val = btn.get_attribute("value") or ""
                    text = btn.inner_text().strip() if btn.inner_text() else ""

                    print(f"   name='{name}' value='{val}' text='{text}'")
                except Exception:
                    continue

        # All form fields
        print("\n   FORM FIELDS:")

        for frame in page.frames:
            inputs = frame.query_selector_all("input, select, textarea")

            for inp in inputs:
                try:
                    name = inp.get_attribute("name") or ""
                    fid = inp.get_attribute("id") or ""
                    ftype = inp.get_attribute("type") or ""
                    val = inp.get_attribute("value") or ""

                    if name or fid:
                        print(
                            f"   name='{name}' id='{fid}' "
                            f"type='{ftype}' value='{val}'"
                        )
                except Exception:
                    continue

        # All key visible labels
        print("\n   KEY LABELS:")

        keywords = [
            "user", "add", "register", "list", "name",
            "number", "group", "edit", "delete", "new",
            "store", "page", "count", "total", "search"
        ]

        for frame in page.frames:
            elements = frame.query_selector_all("td, th, span, label, h1, h2, h3")
            seen = set()

            for el in elements:
                try:
                    text = el.inner_text().strip()

                    if text and len(text) < 80 and text not in seen:
                        seen.add(text)

                        if any(kw in text.lower() for kw in keywords):
                            print(f"   '{text}'")
                except Exception:
                    continue

        # STEP 5: Try to find and click Add/Register button
        print("\n5. Looking for Add/Register button...")

        add_found = False

        possible_selectors = [
            "input[value*='Add']",
            "input[value*='Register']",
            "input[value*='New']",
            "a:has-text('Add')",
            "a:has-text('Register')",
            "button:has-text('Add')",
            "button:has-text('Register')"
        ]

        for frame in page.frames:
            for selector in possible_selectors:
                try:
                    btn = frame.query_selector(selector)

                    if btn:
                        tag = btn.evaluate("el => el.tagName")
                        val = btn.get_attribute("value") or btn.inner_text()

                        print(f"   FOUND: <{tag}> '{val}'")

                        btn.click()
                        page.wait_for_load_state("networkidle")
                        time.sleep(2)

                        screenshot_2 = f"discover/{printer_name.replace(' ', '_')}_add_user_form.png"
                        page.screenshot(path=screenshot_2, full_page=True)

                        print(f"   URL: {page.url}")
                        print(f"   Screenshot: {screenshot_2}")

                        # Scan Add User form
                        print("\n   ADD USER FORM - ALL FIELDS:")

                        for f2 in page.frames:
                            inputs = f2.query_selector_all("input, select, textarea")

                            for inp in inputs:
                                try:
                                    name = inp.get_attribute("name") or ""
                                    fid = inp.get_attribute("id") or ""
                                    ftype = inp.get_attribute("type") or ""
                                    val = inp.get_attribute("value") or ""

                                    if name and ftype != "hidden":
                                        print(
                                            f"   name='{name}' id='{fid}' "
                                            f"type='{ftype}' value='{val}'"
                                        )
                                except Exception:
                                    continue

                        print("\n   ADD USER FORM - ALL LABELS:")

                        for f2 in page.frames:
                            labels = f2.query_selector_all("td, th, label, span")
                            seen2 = set()

                            for label in labels:
                                try:
                                    text = label.inner_text().strip()

                                    if text and len(text) < 60 and text not in seen2:
                                        seen2.add(text)
                                        print(f"   '{text}'")
                                except Exception:
                                    continue

                        add_found = True
                        break

                except Exception:
                    continue

            if add_found:
                break

        if not add_found:
            print("   ❌ Add button not found - check screenshot manually")

        # KEEP OPEN
        print(f"\n{'=' * 60}")
        print("  BROWSER IS OPEN!")
        print("  If Add form is showing, note all field names.")
        print("  We need:")
        print("  - User Name")
        print("  - User Number")
        print("  - Authority Group")
        print(f"{'=' * 60}")

        input("\nPress ENTER when done...")

        browser.close()

    print("\n✅ Done! Check discover/ folder")


def main():
    parser = argparse.ArgumentParser(
        description="Discover Sharp printer User Settings page dynamically."
    )

    parser.add_argument(
        "--printer",
        help="Printer key from printer_list.py, e.g. 19A_PRINTER"
    )

    parser.add_argument(
        "--ip",
        help="Direct printer IP address, e.g. 172.16.16.31"
    )

    parser.add_argument(
        "--password",
        required=True,
        help="Sharp printer administrator password"
    )

    args = parser.parse_args()

    printer_ip, printer_name, printer_location = resolve_printer_ip(
        printer_key=args.printer,
        direct_ip=args.ip
    )

    discover_user_settings(
        printer_ip=printer_ip,
        admin_password=args.password,
        printer_name=printer_name,
        printer_location=printer_location
    )


if __name__ == "__main__":
    main()