from playwright.sync_api import sync_playwright
import json

def discover_admin(printer_ip, admin_password):
    print(f"\n{'='*60}")
    print(f"  ADMIN DISCOVERY: http://{printer_ip}")
    print(f"  Model: Sharp BP-50C36")
    print(f"{'='*60}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--ignore-certificate-errors']
        )
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.set_default_timeout(30000)

        # STEP 1: Load login page
        print("1. Loading login page...")
        page.goto(f"http://{printer_ip}", wait_until="networkidle")
        print(f"   Title: {page.title()}")

        # STEP 2: Click "Administrator Login(C)"
        print("\n2. Clicking 'Administrator Login(C)'...")
        try:
            page.click("text=Administrator Login(C)")
        except Exception:
            try:
                page.click("input[value='Administrator Login(C)']")
            except Exception:
                # Try clicking by index - second button
                buttons = page.query_selector_all("input[type='submit'], button")
                for btn in buttons:
                    val = btn.get_attribute("value") or btn.inner_text()
                    print(f"   Found button: '{val}'")
                    if "Administrator" in val or "Admin" in val:
                        btn.click()
                        break

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        page.screenshot(path="discover/02_admin_login.png", full_page=True)
        print("   Screenshot: discover/02_admin_login.png")

        # STEP 3: Scan what's on the admin login page
        print("\n3. Admin login page fields:")
        for frame in page.frames:
            inputs = frame.query_selector_all("input, select, textarea")
            for inp in inputs:
                name = inp.get_attribute("name") or ""
                fid = inp.get_attribute("id") or ""
                ftype = inp.get_attribute("type") or ""
                placeholder = inp.get_attribute("placeholder") or ""
                print(f"   name='{name}' id='{fid}' type='{ftype}' placeholder='{placeholder}'")

        # STEP 4: Try to enter admin password
        print(f"\n4. Entering admin password: {admin_password}")
        password_entered = False

        for frame in page.frames:
            # Try password fields
            pw_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                'input[name="passwd"]',
                'input[name="admin_password"]',
                'input[name="iPassword"]',
                'input[id="password"]',
            ]
            for selector in pw_selectors:
                try:
                    field = frame.query_selector(selector)
                    if field:
                        field.fill(admin_password)
                        print(f"   Filled password in: {selector}")
                        password_entered = True
                        break
                except Exception:
                    continue

            # Also try regular text fields (Sharp sometimes uses text for passwords)
            if not password_entered:
                text_fields = frame.query_selector_all('input[type="text"]')
                for field in text_fields:
                    name = field.get_attribute("name") or ""
                    if any(kw in name.lower() for kw in ["pass", "pwd", "auth", "pin"]):
                        field.fill(admin_password)
                        print(f"   Filled password in text field: name='{name}'")
                        password_entered = True
                        break

            if password_entered:
                break

        if not password_entered:
            print("   Could not find password field - check screenshot")

        page.screenshot(path="discover/03_password_filled.png", full_page=True)

        # STEP 5: Click Login/Submit
        print("\n5. Clicking login button...")
        login_clicked = False
        for frame in page.frames:
            btn_selectors = [
                "text=Login",
                "text=OK",
                "input[type='submit']",
                "button[type='submit']",
                "text=Enter",
                "input[value='Login']",
                "input[value='OK']",
            ]
            for selector in btn_selectors:
                try:
                    btn = frame.query_selector(selector)
                    if btn:
                        val = btn.get_attribute("value") or btn.inner_text()
                        btn.click()
                        print(f"   Clicked: '{val}'")
                        login_clicked = True
                        break
                except Exception:
                    continue
            if login_clicked:
                break

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)
        page.screenshot(path="discover/04_admin_panel.png", full_page=True)
        print("   Screenshot: discover/04_admin_panel.png")

        # STEP 6: Check if login succeeded - scan the admin panel
        print(f"\n6. Current URL: {page.url}")
        print(f"   Page title: {page.title()}")

        print("\n7. Admin panel menu links:")
        all_links = []
        for frame in page.frames:
            links = frame.query_selector_all("a")
            for link in links:
                text = link.inner_text().strip()
                href = link.get_attribute("href")
                if text and len(text) < 100:
                    all_links.append({"text": text, "href": href})
                    print(f"   [{text}] -> {href}")

        # STEP 7: Look for User Control / User List
        print("\n8. Searching for User Control / User List...")
        user_keywords = [
            "User Control", "User List", "User Management",
            "User Registration", "Address Book", "User Settings",
            "Authentication", "Access Control", "Security"
        ]

        for keyword in user_keywords:
            for frame in page.frames:
                try:
                    link = frame.query_selector(f"a:has-text('{keyword}')")
                    if link:
                        text = link.inner_text().strip()
                        print(f"   FOUND: [{text}]")
                except Exception:
                    continue

        # Save report
        report = {
            "printer_ip": printer_ip,
            "model": "Sharp BP-50C36",
            "admin_password_used": admin_password,
            "login_succeeded": login_clicked,
            "current_url": page.url,
            "admin_links": all_links,
        }
        with open("discover/admin_report.json", "w") as f:
            json.dump(report, f, indent=2)

        # KEEP OPEN
        print(f"\n{'='*60}")
        print("  BROWSER IS OPEN!")
        print("  Manually explore: User Control, Address Book, etc.")
        print("  Look for where to ADD USERS")
        print(f"{'='*60}")
        input("\nPress ENTER when done exploring...")

        browser.close()

    print("\n Done! Check discover/ folder for screenshots")


# RUN
printer_ip = "172.16.16.31"

# Try first password
print("Trying password: admin")
discover_admin(printer_ip, "admin")