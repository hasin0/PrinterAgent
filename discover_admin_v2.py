from playwright.sync_api import sync_playwright
import time

def try_admin_login(printer_ip, password):
    print(f"\n{'='*60}")
    print(f"  ADMIN LOGIN: http://{printer_ip}")
    print(f"  Trying password: {password}")
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

        # STEP 2: Click "Administrator Login(C)" tab/button
        print("\n2. Clicking 'Administrator Login(C)'...")
        # Use the exact button name we discovered
        for frame in page.frames:
            try:
                btn = frame.query_selector("input[name='loginbtn'][type='button']")
                if btn:
                    # There might be multiple loginbtn - find the admin one
                    buttons = frame.query_selector_all("input[name='loginbtn']")
                    for b in buttons:
                        val = b.get_attribute("value") or ""
                        print(f"   Found button: '{val}'")
                    
                # Click the Administrator Login(C) tab first
                admin_tab = frame.query_selector("text=Administrator Login(C)")
                if admin_tab:
                    admin_tab.click()
                    print("   Clicked 'Administrator Login(C)' tab")
                    break
            except Exception:
                continue

        page.wait_for_load_state("networkidle")
        time.sleep(2)

        # STEP 3: Fill password using exact field name from discovery
        print(f"\n3. Filling password: {password}")
        password_filled = False
        for frame in page.frames:
            try:
                # Use the EXACT field name we discovered
                pw_field = frame.query_selector("input[name='ggt_textbox(10006)']")
                if pw_field:
                    pw_field.fill(password)
                    print("   Filled: ggt_textbox(10006)")
                    password_filled = True
                    break
            except Exception:
                pass

            # Fallback to type=password
            if not password_filled:
                try:
                    pw_field = frame.query_selector("input[type='password']")
                    if pw_field:
                        pw_field.fill(password)
                        print("   Filled: input[type='password']")
                        password_filled = True
                        break
                except Exception:
                    pass

        # STEP 4: Click the Login(P) button (submit on admin page)
        print("\n4. Clicking Login(P) button...")
        for frame in page.frames:
            try:
                # Click the loginbtn (not the tab, the actual submit)
                login_btn = frame.query_selector("input[name='loginbtn']")
                if login_btn:
                    login_btn.click()
                    print("   Clicked loginbtn")
                    break
            except Exception:
                continue

        page.wait_for_load_state("networkidle")
        time.sleep(3)

        # STEP 5: Check if login succeeded
        new_url = page.url
        new_title = page.title()
        print(f"\n5. After login:")
        print(f"   URL: {new_url}")
        print(f"   Title: {new_title}")
        page.screenshot(path="discover/05_after_login.png", full_page=True)

        # Check if we're still on login page (login failed)
        if "login" in new_url.lower() or "Login" in new_title:
            print("\n   ❌ Login FAILED - still on login page")
            print(f"   Password '{password}' did not work")

            # Check for error messages
            for frame in page.frames:
                error_elements = frame.query_selector_all(".error, .alert, .warning, [class*='error']")
                for el in error_elements:
                    print(f"   Error message: {el.inner_text()}")

            # Check all visible text for error clues
            body_text = page.inner_text("body")
            if "incorrect" in body_text.lower() or "wrong" in body_text.lower() or "invalid" in body_text.lower():
                print(f"   Found error in page text")

            browser.close()
            return False

        # LOGIN SUCCEEDED!
        print("\n   ✅ LOGIN SUCCEEDED!")
        page.screenshot(path="discover/06_admin_panel.png", full_page=True)

        # STEP 6: Explore the admin panel
        print("\n6. Scanning admin panel...")

        # Get ALL links in ALL frames
        print("\n   MENU LINKS:")
        for i, frame in enumerate(page.frames):
            links = frame.query_selector_all("a")
            for link in links:
                text = link.inner_text().strip()
                href = link.get_attribute("href") or ""
                if text and len(text) < 100:
                    print(f"   [Frame {i}] [{text}] -> {href}")

        # Get ALL form fields
        print("\n   FORM FIELDS:")
        for i, frame in enumerate(page.frames):
            inputs = frame.query_selector_all("input, select, textarea, button")
            for inp in inputs:
                name = inp.get_attribute("name") or ""
                fid = inp.get_attribute("id") or ""
                ftype = inp.get_attribute("type") or ""
                val = inp.get_attribute("value") or ""
                if name or fid:
                    print(f"   [Frame {i}] name='{name}' id='{fid}' type='{ftype}' value='{val}'")

        # Look for user-related menus
        print("\n   SEARCHING FOR USER MANAGEMENT:")
        keywords = [
            "User", "Address", "Account", "Authentication",
            "Security", "System", "Setting", "Control",
            "Registration", "List", "Management"
        ]
        for frame in page.frames:
            all_text = frame.query_selector_all("a, span, td, div, li")
            for el in all_text:
                text = el.inner_text().strip()
                for kw in keywords:
                    if kw.lower() in text.lower() and len(text) < 80:
                        tag = el.evaluate("el => el.tagName")
                        print(f"   FOUND: <{tag}> '{text}'")
                        break

        # KEEP OPEN
        print(f"\n{'='*60}")
        print("  BROWSER IS OPEN!")
        print("  Manually navigate to find 'User Control' or 'User List'")
        print("  Take note of the menus you see on the left/top")
        print(f"{'='*60}")
        input("\nPress ENTER when done...")

        browser.close()
        return True


# ========================================
# TRY BOTH PASSWORDS
# ========================================
printer_ip = "172.16.16.31"

# Try password 1
if not try_admin_login(printer_ip, "admin"):
    print("\n\nTrying second password...")
    # Try password 2
    if not try_admin_login(printer_ip, "Ref@123"):
        print("\n❌ Both passwords failed!")
        print("Please try logging in manually in your browser")
        print(f"Go to: http://{printer_ip}")