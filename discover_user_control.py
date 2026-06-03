from playwright.sync_api import sync_playwright
import time
import json

def discover_user_control(printer_ip, admin_password):
    print(f"\n{'='*60}")
    print(f"  EXPLORING USER CONTROL: http://{printer_ip}")
    print(f"{'='*60}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--ignore-certificate-errors']
        )
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.set_default_timeout(30000)

        # ============================
        # STEP 1: Login as admin
        # ============================
        print("1. Logging in as admin...")
        page.goto(f"http://{printer_ip}", wait_until="networkidle")

        # Click Administrator Login(C) tab
        page.click("text=Administrator Login(C)")
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # Fill password
        page.fill("input[name='ggt_textbox(10006)']", admin_password)

        # Click Login(P) button
        page.click("input[name='loginbtn']")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        print(f"   ✅ Logged in! Title: {page.title()}")

        # ============================
        # STEP 2: Click "User Control" tab
        # ============================
        print("\n2. Navigating to User Control...")
        page.click("text=User Control")
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        print(f"   URL: {page.url}")
        print(f"   Title: {page.title()}")
        page.screenshot(path="discover/07_user_control.png", full_page=True)
        print("   Screenshot: discover/07_user_control.png")

        # ============================
        # STEP 3: Scan User Control page
        # ============================
        print("\n3. User Control page content:")

        # All links (left menu + main content)
        print("\n   LINKS:")
        for frame in page.frames:
            links = frame.query_selector_all("a")
            for link in links:
                text = link.inner_text().strip()
                href = link.get_attribute("href") or ""
                if text and len(text) < 100:
                    print(f"   [{text}] -> {href}")

        # All form fields
        print("\n   FORM FIELDS:")
        for frame in page.frames:
            inputs = frame.query_selector_all("input, select, textarea, button")
            for inp in inputs:
                name = inp.get_attribute("name") or ""
                fid = inp.get_attribute("id") or ""
                ftype = inp.get_attribute("type") or ""
                val = inp.get_attribute("value") or ""
                if name or fid:
                    print(f"   name='{name}' id='{fid}' type='{ftype}' value='{val}'")

        # All visible text (to find sub-menus)
        print("\n   VISIBLE TEXT (menus & labels):")
        for frame in page.frames:
            elements = frame.query_selector_all("a, span, td, th, div.menu, li, h1, h2, h3, label")
            seen = set()
            for el in elements:
                text = el.inner_text().strip()
                if text and len(text) < 80 and text not in seen:
                    seen.add(text)
                    tag = el.evaluate("el => el.tagName")
                    # Filter for relevant items
                    keywords = ["user", "list", "add", "register", "group",
                               "control", "default", "setting", "auth",
                               "number", "name", "count", "page", "store",
                               "edit", "delete", "new"]
                    if any(kw in text.lower() for kw in keywords):
                        print(f"   <{tag}> '{text}'")

        # ============================
        # STEP 4: Look for sub-pages
        # ============================
        print("\n4. Exploring sub-pages under User Control...")

        # Try clicking common sub-menu items
        sub_pages = [
            "User List", "User Registration", "Default Settings",
            "User Count", "Authority Group", "Group List",
            "Add", "Register", "User Number List"
        ]

        for sub in sub_pages:
            for frame in page.frames:
                try:
                    link = frame.query_selector(f"a:has-text('{sub}')")
                    if link:
                        text = link.inner_text().strip()
                        href = link.get_attribute("href") or ""
                        print(f"   FOUND SUB-PAGE: [{text}] -> {href}")
                except Exception:
                    continue

        # ============================
        # STEP 5: Click into User List (if exists)
        # ============================
        print("\n5. Looking for User List...")
        user_list_found = False
        for frame in page.frames:
            for text in ["User List", "User Registration", "User Number List"]:
                try:
                    link = frame.query_selector(f"a:has-text('{text}')")
                    if link:
                        link.click()
                        page.wait_for_load_state("networkidle")
                        time.sleep(2)
                        print(f"   Clicked: '{text}'")
                        print(f"   URL: {page.url}")
                        page.screenshot(path="discover/08_user_list.png", full_page=True)
                        print("   Screenshot: discover/08_user_list.png")

                        # Scan user list page
                        print("\n   USER LIST PAGE FIELDS:")
                        for f2 in page.frames:
                            inputs = f2.query_selector_all("input, select, textarea, button")
                            for inp in inputs:
                                name = inp.get_attribute("name") or ""
                                fid = inp.get_attribute("id") or ""
                                ftype = inp.get_attribute("type") or ""
                                val = inp.get_attribute("value") or ""
                                if name or fid:
                                    print(f"   name='{name}' id='{fid}' type='{ftype}' value='{val}'")

                        print("\n   USER LIST PAGE LINKS:")
                        for f2 in page.frames:
                            links2 = f2.query_selector_all("a")
                            for l2 in links2:
                                t = l2.inner_text().strip()
                                h = l2.get_attribute("href") or ""
                                if t and len(t) < 100:
                                    print(f"   [{t}] -> {h}")

                        user_list_found = True
                        break
                except Exception:
                    continue
            if user_list_found:
                break

        # ============================
        # STEP 6: Try to find "Add" button on user list
        # ============================
        if user_list_found:
            print("\n6. Looking for 'Add' or 'Register' button...")
            for frame in page.frames:
                for btn_text in ["Add", "Register", "New", "Add User"]:
                    try:
                        btn = frame.query_selector(f"input[value='{btn_text}']")
                        if not btn:
                            btn = frame.query_selector(f"a:has-text('{btn_text}')")
                        if not btn:
                            btn = frame.query_selector(f"button:has-text('{btn_text}')")
                        if btn:
                            tag = btn.evaluate("el => el.tagName")
                            val = btn.get_attribute("value") or btn.inner_text()
                            print(f"   FOUND: <{tag}> '{val}'")

                            # Click it to see the Add User form
                            btn.click()
                            page.wait_for_load_state("networkidle")
                            time.sleep(2)
                            page.screenshot(path="discover/09_add_user.png", full_page=True)
                            print("   Screenshot: discover/09_add_user.png")

                            # Scan the Add User form
                            print("\n   ADD USER FORM FIELDS:")
                            for f3 in page.frames:
                                inputs = f3.query_selector_all("input, select, textarea")
                                for inp in inputs:
                                    name = inp.get_attribute("name") or ""
                                    fid = inp.get_attribute("id") or ""
                                    ftype = inp.get_attribute("type") or ""
                                    val = inp.get_attribute("value") or ""
                                    placeholder = inp.get_attribute("placeholder") or ""
                                    if name or fid:
                                        print(f"   name='{name}' id='{fid}' type='{ftype}' value='{val}' placeholder='{placeholder}'")

                            # Also get labels
                            print("\n   ADD USER FORM LABELS:")
                            for f3 in page.frames:
                                labels = f3.query_selector_all("td, th, label, span")
                                seen_labels = set()
                                for lbl in labels:
                                    t = lbl.inner_text().strip()
                                    if t and len(t) < 60 and t not in seen_labels:
                                        seen_labels.add(t)
                                        print(f"   '{t}'")

                            break
                    except Exception:
                        continue

        # KEEP OPEN
        print(f"\n{'='*60}")
        print("  BROWSER IS OPEN!")
        print("  Explore the User Control section manually")
        print("  Look for: User List -> Add -> form fields")
        print(f"{'='*60}")
        input("\nPress ENTER when done...")

        browser.close()

    print("\n✅ Done! Check discover/ folder")


# RUN
discover_user_control("172.16.16.31", "admin")