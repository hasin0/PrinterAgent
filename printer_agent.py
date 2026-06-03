import os
import subprocess
import glob
import ctypes
import sys
import time

def is_admin():
    """Checks if the script has full Admin rights."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    """Restarts the script with Administrator privileges."""
    print("🚀 AGENT: Attempting to elevate privileges...")
    # This triggers the UAC prompt automatically
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(sys.argv), None, 1
    )

# --- STEP 1: GET LOCATION ---
def get_user_location():
    print("\n-------------------------------------------")
    print("🤖 AGENT: Printer Pro (Auto-Admin Edition)")
    print("-------------------------------------------")
    
    valid_locations = ["19B", "LONDON", "REMOTE"]
    while True:
        try:
            user_input = input("📍 Which office are you in? (19B, London): ").strip().upper()
            if user_input in valid_locations:
                print(f"✅ AGENT: Location set to: {user_input}")
                return user_input
            print(f"❌ AGENT: I don't know '{user_input}'. Try again.")
        except EOFError:
            return "19B"

# --- STEP 2: SELECT PRINTER ---
def select_printer(location):
    # DATABASE: "driver_name" must match the .inf file EXACTLY
    printer_db = {
        "19B": [
            {"name": "Sharp_MX3061_Main", "ip": "172.20.102.115", "driver_name": "SHARP MX-3061 PCL6"},
            {"name": "Reception_HP", "ip": "192.168.1.10", "driver_name": "HP Universal Printing PCL 6"}
        ],
        "LONDON": [
             # Example placeholder
            {"name": "London_Main_Canon", "ip": "10.0.0.50", "driver_name": "Canon Generic Plus PCL6"}
        ]
    }
    
    if location not in printer_db:
        print("❌ AGENT: No printers configured for this location.")
        return None

    print(f"\n🔎 AGENT: Scanning available printers in {location}...")
    options = printer_db[location]
    
    for i, p in enumerate(options):
        print(f"   {i+1}. {p['name']} (IP: {p['ip']})")
        
    try:
        choice = int(input("\n🖨️  Select a printer (Number): ")) - 1
        if 0 <= choice < len(options):
            return options[choice]
    except ValueError:
        pass
    print("❌ AGENT: Invalid selection.")
    return None

# --- STEP 3: INSTALL DRIVER ---
def install_driver_native(driver_folder_path):
    print(f"\n💿 AGENT: Searching for drivers in: {driver_folder_path}")
    
    if not os.path.exists(driver_folder_path):
        print("❌ AGENT: Driver folder not found! Is it in the same folder as this app?")
        return False

    # Locate the .inf file
    inf_file = None
    for root, dirs, files in os.walk(driver_folder_path):
        for file in files:
            # Look for .inf files. Refine this check if multiple INFs exist.
            if file.lower().endswith(".inf") and "pcl6" in file.lower():
                inf_file = os.path.join(root, file)
                break
        if inf_file: break
    
    if not inf_file:
        # Fallback: grab any .inf
        inf_files = glob.glob(os.path.join(driver_folder_path, "**", "*.inf"), recursive=True)
        if inf_files: 
            inf_file = inf_files[0]
        else:
            print(f"❌ AGENT: No .inf file found inside the driver folder.")
            return False

    print(f"   -> Found INF: {os.path.basename(inf_file)}")
    print("⚙️  AGENT: Installing driver via PnPUtil...")
    
    try:
        # Install using pnputil
        result = subprocess.run(
            ["pnputil.exe", "/add-driver", inf_file, "/install"],
            capture_output=True, text=True
        )
        
        # Check output for success keywords
        if "successfully added" in result.stdout.lower():
            print("✅ AGENT: Driver successfully added to Driver Store.")
            return True
        else:
            print(f"❌ AGENT: Driver install failed.\nDetails:\n{result.stdout}")
            return False
    except Exception as e:
        print(f"❌ AGENT: Critical Error during install: {e}")
        return False

# --- STEP 4: MAP PRINTER ---
def map_printer(printer_info):
    name = printer_info['name']
    ip = printer_info['ip']
    driver = printer_info['driver_name']
    
    print(f"\n🛠️  AGENT: Finalizing '{name}'...")
    
    # 1. Create Port (ignore error if it already exists)
    ps_port = f"Add-PrinterPort -Name 'IP_{ip}' -PrinterHostAddress '{ip}' -ErrorAction SilentlyContinue"
    subprocess.run(["powershell", "-Command", ps_port], check=False)

    # 2. Add Printer
    ps_add = f"Add-Printer -Name '{name}' -DriverName '{driver}' -PortName 'IP_{ip}'"

    try:
        # Capture output to diagnose issues
        result = subprocess.run(["powershell", "-Command", ps_add], capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"\n🎉 AGENT: SUCCESS! Printer '{name}' is ready.")
            return True
        else:
            print("❌ AGENT: Mapping failed.")
            print(f"   STDERR: {result.stderr.strip()}")
            print("   (Check if 'driver_name' matches the .inf file exactly)")
            return False

    except Exception as e:
        print(f"❌ AGENT: Python Error: {e}")
        return False

# ==========================================
#              MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    
    # --- AUTO-ELEVATION LOGIC ---
    if not is_admin():
        run_as_admin()
        sys.exit() # Close the non-admin version
    # ----------------------------

    # --- PATH DETECTION (Fixes .exe issue) ---
    if getattr(sys, 'frozen', False):
        # Running as compiled .exe
        application_path = os.path.dirname(sys.executable)
    else:
        # Running as .py script
        application_path = os.path.dirname(os.path.abspath(__file__))

    # Assumes "19B Printer-SharpMX3061" folder is NEXT TO the script/exe
    local_driver_path = os.path.join(application_path, "19B Printer-SharpMX3061")

    # --- RUN SEQUENCE ---
    loc = get_user_location()
    target = select_printer(loc)
    
    if target:
        # Only attempt mapping if driver install succeeds (or if driver already exists)
        if install_driver_native(local_driver_path):
            map_printer(target)
            
    # Keep window open
    input("\nPress Enter to exit...")