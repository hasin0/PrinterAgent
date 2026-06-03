from playwright.sync_api import sync_playwright
import time
import json

def discover_user_settings(printer_ip, admin_password):
    print(f"\n{'='*60}")
    print(f"  EXPLORING USER SETTINGS: http://{printer_ip}")
    print(f"{'='*60}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--ignore-certificate-errors']
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
        print(f"   ✅ Logged in!")

        # STEP 2: Click User Control tab
        print("\n2. Clicking User Control tab...")
        page.click("text=User Control")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        # STEP 3: Click "User Settings"
        print("\n3. Clicking 'User Settings'...")
        page.click("text=User Settings")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        print(f"   URL: {page.url}")
        print(f"   Title: {page.title()}")
        page.screenshot(path="discover/10_user_settings.png", full_page=True)
        print("   Screenshot: discover/10_user_settings.png")

        # STEP 4: Scan the User Settings page
        print("\n4. User Settings page content:")

        # Left menu links
        print("\n   LEFT MENU:")
        for frame in page.frames:
            links = frame.query_selector_all("a")
            for link in links:
                text = link.inner_text().strip()
                href = link.get_attribute("href") or ""
                if text and len(text) < 100:
                    tag = link.evaluate("el => el.tagName")
                    print(f"   [{text}] -> {href}")

        # All buttons
        print("\n   BUTTONS:")
        for frame in page.frames:
            buttons = frame.query_selector_all("input[type='button'], input[type='submit'], button")
            for btn in buttons:
                name = btn.get_attribute("name") or ""
                val = btn.get_attribute("value") or ""
                print(f"   name='{name}' value='{val}'")

        # All form fields
        print("\n   FORM FIELDS:")
        for frame in page.frames:
            inputs = frame.query_selector_all("input, select, textarea")
            for inp in inputs:
                name = inp.get_attribute("name") or ""
                fid = inp.get_attribute("id") or ""
                ftype = inp.get_attribute("type") or ""
                val = inp.get_attribute("value") or ""
                if name or fid:
                    print(f"   name='{name}' id='{fid}' type='{ftype}' value='{val}'")

        # All visible text
        print("\n   KEY LABELS:")
        for frame in page.frames:
            elements = frame.query_selector_all("td, th, span, label, h1, h2, h3")
            seen = set()
            for el in elements:
                text = el.inner_text().strip()
                if text and len(text) < 80 and text not in seen:
                    seen.add(text)
                    keywords = ["user", "add", "register", "list", "name",
                               "number", "group", "edit", "delete", "new",
                               "store", "page", "count", "total", "search"]
                    if any(kw in text.lower() for kw in keywords):
                        print(f"   '{text}'")

        # STEP 5: Try to find and click "Add" button
        print("\n5. Looking for Add/Register button...")
        add_found = False
        for frame in page.frames:
            for selector in [
                "input[value*='Add']",
                "input[value*='Register']",
                "input[value*='New']",
                "a:has-text('Add')",
                "a:has-text('Register')",
                "button:has-text('Add')"
            ]:
                try:
                    btn = frame.query_selector(selector)
                    if btn:
                        tag = btn.evaluate("el => el.tagName")
                        val = btn.get_attribute("value") or btn.inner_text()
                        print(f"   FOUND: <{tag}> '{val}'")

                        btn.click()
                        page.wait_for_load_state("networkidle")
                        time.sleep(2)
                        page.screenshot(path="discover/11_add_user_form.png", full_page=True)
                        print(f"   URL: {page.url}")
                        print("   Screenshot: discover/11_add_user_form.png")

                        # Scan the Add User form
                        print("\n   ADD USER FORM - ALL FIELDS:")
                        for f2 in page.frames:
                            inputs = f2.query_selector_all("input, select, textarea")
                            for inp in inputs:
                                name = inp.get_attribute("name") or ""
                                fid = inp.get_attribute("id") or ""
                                ftype = inp.get_attribute("type") or ""
                                val = inp.get_attribute("value") or ""
                                if name and ftype != "hidden":
                                    print(f"   name='{name}' id='{fid}' type='{ftype}' value='{val}'")

                        print("\n   ADD USER FORM - ALL LABELS:")
                        for f2 in page.frames:
                            tds = f2.query_selector_all("td, th, label, span")
                            seen2 = set()
                            for td in tds:
                                text = td.inner_text().strip()
                                if text and len(text) < 60 and text not in seen2:
                                    seen2.add(text)
                                    print(f"   '{text}'")

                        add_found = True
                        break
                except Exception:
                    continue
            if add_found:
                break

        if not add_found:
            print("   ❌ Add button not found - check screenshot manually")

        # KEEP OPEN
        print(f"\n{'='*60}")
        print("  BROWSER IS OPEN!")
        print("  If Add form is showing, note all the field names")
        print("  We need: User Name, User Number, Authority Group")
        print(f"{'='*60}")
        input("\nPress ENTER when done...")

        browser.close()

    print("\n✅ Done! Check discover/ folder")


# RUN
discover_user_settings("172.16.16.31", "admin")