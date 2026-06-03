from playwright.sync_api import sync_playwright
import json

def discover_sharp(printer_ip):
    print(f"\n{'='*60}")
    print(f"  DISCOVERING SHARP PRINTER AT: http://{printer_ip}")
    print(f"{'='*60}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--ignore-certificate-errors']
        )
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.set_default_timeout(30000)

        # STEP 1: Load printer page
        print("1. Loading printer page...")
        try:
            page.goto(f"http://{printer_ip}", wait_until="networkidle")
        except Exception:
            page.goto(f"https://{printer_ip}", wait_until="networkidle")

        title = page.title()
        print(f"   Page title: '{title}'")
        page.screenshot(path="discover/01_home.png", full_page=True)
        print("   Screenshot: discover/01_home.png")

        # STEP 2: Scan all links
        print("\n2. All links found:")
        all_links = []
        for frame in page.frames:
            links = frame.query_selector_all("a")
            for link in links:
                text = link.inner_text().strip()
                href = link.get_attribute("href")
                if text and len(text) < 100:
                    all_links.append({"text": text, "href": href})
                    print(f"   [{text}] -> {href}")

        # STEP 3: Scan all form fields
        print("\n3. Form fields found:")
        all_fields = []
        for frame in page.frames:
            inputs = frame.query_selector_all("input, select, textarea, button")
            for inp in inputs:
                info = {
                    "tag": inp.evaluate("el => el.tagName"),
                    "name": inp.get_attribute("name") or "",
                    "id": inp.get_attribute("id") or "",
                    "type": inp.get_attribute("type") or "",
                    "value": inp.get_attribute("value") or "",
                }
                if info["name"] or info["id"]:
                    all_fields.append(info)
                    print(f"   <{info['tag']}> name='{info['name']}' id='{info['id']}' type='{info['type']}'")

        # STEP 4: Check for frames
        print(f"\n4. Frames found: {len(page.frames)}")
        for i, frame in enumerate(page.frames):
            print(f"   Frame {i}: {frame.url}")

        # STEP 5: Save page source
        print("\n5. Saving page source...")
        html = page.content()
        with open("discover/page_source.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("   Saved: discover/page_source.html")

        # Save report
        report = {
            "printer_ip": printer_ip,
            "title": title,
            "frames": len(page.frames),
            "links": all_links,
            "fields": all_fields,
        }
        with open("discover/report.json", "w") as f:
            json.dump(report, f, indent=2)
        print("   Saved: discover/report.json")

        # KEEP OPEN
        print(f"\n{'='*60}")
        print("  BROWSER IS OPEN - Explore manually!")
        print("  Try clicking: User Control, Address Book, etc.")
        print(f"{'='*60}")
        input("\nPress ENTER when done exploring...")

        browser.close()

    print("\n Done! Check the discover/ folder")

# RUN
printer_ip = input("Enter Sharp printer IP: ")
discover_sharp(printer_ip)