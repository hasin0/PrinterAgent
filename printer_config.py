import time
import subprocess
import sys
from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys


def configure_printer_preferences(printer_name, user_name, user_code):

    print("")
    print("============================================")
    print("  Configuring Printer Preferences")
    print("  Printer: " + printer_name)
    print("  User: " + user_name)
    print("  Code: " + user_code)
    print("============================================")
    print("")

    print("Step 1: Opening printer preferences...")

    subprocess.Popen([
        "rundll32", "printui.dll,PrintUIEntry",
        "/e", "/n", printer_name
    ])

    time.sleep(5)

    try:
        print("Step 2: Finding preferences window...")

        windows = Desktop(backend="uia").windows()
        target_title = None

        for w in windows:
            title = w.window_text()
            if "Printing Preferences" in title:
                target_title = title
                print("   Found: " + title)
                break

        if not target_title:
            print("   ERROR: No Printing Preferences window found")
            return False

        app = Application(backend="uia").connect(title=target_title)
        dlg = app.window(title=target_title)
        dlg.wait("visible", timeout=10)
        print("   Window connected")

        # ================================
        # ================================
        #   PART 1: MAIN TAB
        # ================================
        # ================================
        print("")
        print("========== MAIN TAB ==========")
        print("")

        print("Step 3: Clicking Main BUTTON...")
        buttons = dlg.descendants(control_type="Button")
        for btn in buttons:
            if btn.window_text() == "Main":
                btn.click_input()
                print("   CLICKED: Main")
                break
        time.sleep(3)

        print("")
        print("Step 4: Scanning Main tab combos WITH INDEX...")
        combos = dlg.descendants(control_type="ComboBox")
        doc_filing_idx = -1
        color_mode_idx = -1
        nup_idx = -1

        for i, combo in enumerate(combos):
            try:
                name = combo.window_text()
                selected = combo.selected_text()
                print("   [" + str(i) + "] '" + name + "' = '" + selected + "'")
                if "Document Filing" in name:
                    doc_filing_idx = i
                if "Color" in name:
                    color_mode_idx = i
                if "N-Up" in name:
                    nup_idx = i
            except Exception:
                pass

        print("   Doc Filing idx=" + str(doc_filing_idx) + " Color idx=" + str(color_mode_idx) + " N-Up idx=" + str(nup_idx))

        # ================================
        # Step 5 — Set Document Filing
        # ================================
        print("")
        print("Step 5: Setting Document Filing...")
        if doc_filing_idx >= 0:
            combo = combos[doc_filing_idx]
            try:
                selected = combo.selected_text()
                if selected == "Hold Only":
                    print("   Already Hold Only")
                else:
                    combo.click_input()
                    time.sleep(1)
                    send_keys("H")
                    time.sleep(0.5)
                    send_keys("{ENTER}")
                    time.sleep(1)
                    print("   Set to Hold Only")
            except Exception as e:
                print("   WARNING: " + str(e))
        else:
            print("   WARNING: Document Filing not found")

        time.sleep(2)

        # ================================
        # Step 6 — Set Color Mode
        # ================================
        print("")
        print("Step 6: Setting Color Mode...")
        if color_mode_idx >= 0:
            combo = combos[color_mode_idx]
            try:
                selected = combo.selected_text()
                if "Black" in selected:
                    print("   Already Black and White")
                else:
                    combo.click_input()
                    time.sleep(1)
                    send_keys("B")
                    time.sleep(0.5)
                    send_keys("{ENTER}")
                    time.sleep(1)
                    print("   Set to Black and White")
            except Exception as e:
                print("   WARNING: " + str(e))
        else:
            print("   WARNING: Color Mode not found")

        time.sleep(2)

        # ================================
        # Step 6b — Reset N-Up to None (safety)
        # ================================
        print("")
        print("Step 6b: Ensuring N-Up is set to None...")
        if nup_idx >= 0:
            combo = combos[nup_idx]
            try:
                selected = combo.selected_text()
                if selected == "None":
                    print("   N-Up already None")
                else:
                    combo.click_input()
                    time.sleep(1)
                    send_keys("N")
                    time.sleep(0.5)
                    send_keys("{ENTER}")
                    time.sleep(1)
                    print("   N-Up reset to None")
            except Exception as e:
                print("   WARNING: " + str(e))
        else:
            print("   N-Up combo not found (skip)")

        time.sleep(1)

        # ================================
        # ================================
        #   PART 2: JOB HANDLING TAB
        # ================================
        # ================================
        print("")
        print("========== JOB HANDLING TAB ==========")
        print("")

        # ================================
        # Step 7 — Click Job Handling
        # ================================
        print("Step 7: Clicking Job Handling BUTTON...")
        buttons = dlg.descendants(control_type="Button")
        for btn in buttons:
            if btn.window_text() == "Job Handling":
                btn.click_input()
                print("   CLICKED: Job Handling")
                break
        time.sleep(3)

        # ================================
        # Step 8 — Scan Job Handling combos
        # ================================
        print("")
        print("Step 8: Scanning Job Handling combos WITH INDEX...")
        combos = dlg.descendants(control_type="ComboBox")
        auth_idx = -1

        for i, combo in enumerate(combos):
            try:
                name = combo.window_text()
                selected = combo.selected_text()
                print("   [" + str(i) + "] '" + name + "' = '" + selected + "'")
                if "Authentication" in name:
                    auth_idx = i
            except Exception:
                pass

        print("   Auth idx=" + str(auth_idx))

        # ================================
        # Step 9 — Set Authentication
        # ================================
        print("")
        print("Step 9: Setting Authentication...")
        if auth_idx >= 0:
            combo = combos[auth_idx]
            try:
                selected = combo.selected_text()
                print("   Current: '" + selected + "'")
                if "User Number" in selected:
                    print("   Already User Number")
                else:
                    combo.click_input()
                    time.sleep(1)
                    send_keys("U")
                    time.sleep(0.5)
                    send_keys("{ENTER}")
                    time.sleep(1)
                    print("   Set to User Number")
            except Exception as e:
                print("   WARNING: " + str(e))
        else:
            print("   WARNING: Auth combo not found")

        # CRITICAL: Wait for new controls to appear
        time.sleep(4)

        # ================================
        # Step 10 — Rescan after Auth change
        # ================================
        print("")
        print("Step 10: Rescanning after Auth change...")
        print("   CheckBoxes:")
        checks = dlg.descendants(control_type="CheckBox")
        for cb in checks:
            try:
                print("   - '" + cb.window_text() + "' = " + str(cb.get_toggle_state()))
            except Exception:
                pass

        print("   Edits:")
        edits = dlg.descendants(control_type="Edit")
        for i, edit in enumerate(edits):
            try:
                val = edit.get_value()
                enabled = edit.is_enabled()
                visible = edit.is_visible()
                print("   - [" + str(i) + "] value='" + str(val) + "' enabled=" + str(enabled) + " visible=" + str(visible))
            except Exception:
                pass

        # ================================
        # Step 11 — Check User Name checkbox
        # ================================
        print("")
        print("Step 11: Enabling User Name checkbox...")
        checkbox_found = False
        checks = dlg.descendants(control_type="CheckBox")
        for cb in checks:
            try:
                text = cb.window_text()
                if "User Name" in text:
                    if not cb.get_toggle_state():
                        cb.toggle()
                    checkbox_found = True
                    print("   Checked: '" + text + "'")
                    break
            except Exception:
                continue
        if not checkbox_found:
            print("   WARNING: User Name checkbox not found")

        time.sleep(2)

        # ================================
        # Step 12 — Rescan edits after checkbox
        # ================================
        print("")
        print("Step 12: Rescanning edits after checkbox...")
        edits = dlg.descendants(control_type="Edit")
        enabled_fields = []
        for i, edit in enumerate(edits):
            try:
                val = edit.get_value()
                enabled = edit.is_enabled()
                visible = edit.is_visible()
                print("   [" + str(i) + "] value='" + str(val) + "' enabled=" + str(enabled) + " visible=" + str(visible))
                if enabled and visible:
                    enabled_fields.append({"index": i, "edit": edit, "value": val})
            except Exception:
                pass
        print("   Enabled fields: " + str(len(enabled_fields)))

        # ================================
        # Step 13 — Enter User Name
        # ================================
        print("")
        print("Step 13: Entering User Name: " + user_name)
        name_entered = False

        # First: find field with old text (replace it)
        for field in enabled_fields:
            val = field["value"]
            if val == "1":
                continue
            if val != "" and val != "1":
                field["edit"].set_text("")
                time.sleep(0.5)
                field["edit"].set_text(user_name)
                name_entered = True
                print("   Entered in [" + str(field["index"]) + "] replaced '" + val + "'")
                break

        # Second: if no old text, use empty fields
        if not name_entered:
            empty = [f for f in enabled_fields if f["value"] == ""]
            if len(empty) >= 2:
                empty[1]["edit"].set_text(user_name)
                name_entered = True
                print("   Entered in second empty field")
            elif len(empty) == 1:
                empty[0]["edit"].set_text(user_name)
                name_entered = True
                print("   Entered in only empty field")

        if not name_entered:
            print("   WARNING: Could not enter User Name")

        time.sleep(1)

        # ================================
        # Step 14 — Enter User Number
        # ================================
        print("")
        print("Step 14: Entering User Number: " + user_code)
        code_entered = False
        edits = dlg.descendants(control_type="Edit")
        for i, edit in enumerate(edits):
            try:
                if edit.is_enabled() and edit.is_visible():
                    val = edit.get_value()
                    if val == "1":
                        continue
                    if val == user_name:
                        continue
                    if val == "" or val is None:
                        edit.set_text(user_code)
                        code_entered = True
                        print("   Entered in [" + str(i) + "]")
                        break
            except Exception:
                continue
        if not code_entered:
            print("   WARNING: Could not enter User Number")

        time.sleep(1)

        # ================================
        # Step 15 — Verify
        # ================================
        print("")
        print("Step 15: Verifying...")
        edits = dlg.descendants(control_type="Edit")
        for i, edit in enumerate(edits):
            try:
                val = edit.get_value()
                if edit.is_enabled():
                    print("   [" + str(i) + "] = '" + str(val) + "'")
            except Exception:
                pass

        # ================================
        # Step 16 — Click Apply
        # ================================
        print("")
        print("Step 16: Clicking Apply...")
        try:
            apply_btn = dlg.child_window(title="Apply", control_type="Button")
            apply_btn.click_input()
            print("   Apply clicked")
            time.sleep(3)
        except Exception as e:
            print("   WARNING: " + str(e))

        # ================================
        # Step 17 — Handle popup
        # ================================
        print("Step 17: Checking popup...")
        time.sleep(2)
        try:
            popup_windows = Desktop(backend="uia").windows()
            for pw in popup_windows:
                pw_title = pw.window_text()
                if "Information" in pw_title or "Warning" in pw_title:
                    print("   Popup: " + pw_title)
                    popup_app = Application(backend="uia").connect(title=pw_title)
                    popup_dlg = popup_app.window(title=pw_title)
                    popup_ok = popup_dlg.child_window(title="OK", control_type="Button")
                    popup_ok.click_input()
                    print("   Popup OK clicked")
                    time.sleep(1)
                    break
        except Exception:
            print("   No popup")

        # ================================
        # Step 18 — Click OK
        # ================================
        print("Step 18: Clicking OK...")
        try:
            app = Application(backend="uia").connect(title=target_title)
            dlg = app.window(title=target_title)
            ok_buttons = dlg.descendants(title="OK", control_type="Button")
            if ok_buttons:
                ok_buttons[-1].click_input()
                print("   OK clicked")
        except Exception as e:
            print("   WARNING: " + str(e))

        # ================================
        # Result
        # ================================
        print("")
        print("============================================")
        print("  ALL PREFERENCES CONFIGURED!")
        print("")
        print("  Printer: " + printer_name)
        print("  User: " + user_name)
        print("  Code: " + user_code)
        print("  Document Filing: Hold Only")
        print("  Color Mode: Black & White")
        print("  N-Up: None")
        print("============================================")

        return True

    except Exception as e:
        print("")
        print("ERROR: " + str(e))
        return False


# ================================
# RUN
# ================================
if __name__ == "__main__":

    if len(sys.argv) >= 4:
        printer_name = sys.argv[1]
        user_name = sys.argv[2]
        user_code = sys.argv[3]
    else:
        printer_name = "Sharp BP-50C36"
        user_name = "Test User"
        user_code = "12345"

    success = configure_printer_preferences(printer_name, user_name, user_code)

    if success:
        print("\nDONE")
        sys.exit(0)
    else:
        print("\nFAILED")
        sys.exit(1)