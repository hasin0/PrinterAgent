PrinterAgent — Deployment Checklist
Server folder (your REAL one, has venv + tools):
C:\Users\hassan.abdulmalik\PrinterAgent
Always start here:
cd C:\Users\hassan.abdulmalik\PrinterAgent
---
0. Back up first (30 seconds, saves hours)
```powershell
cd C:\Users\hassan.abdulmalik
Copy-Item PrinterAgent PrinterAgent_BACKUP_(Get-Date -Format yyyyMMdd) -Recurse
```
---
1. Confirm you are in the RIGHT folder
```powershell
cd C:\Users\hassan.abdulmalik\PrinterAgent
Test-Path .\venv          # must be True
Test-Path .\tools         # must be True
```
If either is False, you're in the wrong copy. The stray `C:\PrinterAgent`
(no venv/tools) has caused repeated errors — ignore it or rename it:
```powershell
Rename-Item C:\PrinterAgent C:\PrinterAgent_OLD -ErrorAction SilentlyContinue
```
---
2. Required Python modules (root of PrinterAgent, next to app.py)
Tick each — must exist in `C:\Users\hassan.abdulmalik\PrinterAgent\`:
[ ] `app.py`                (this new clean version)
[ ] `toner_service.py`      (this new version — DAILY scan)
[ ] `toner_monitor.py`      (v3 — shared+closed SnmpEngine, printers_store import)
[ ] `printers_store.py`     (fleet registry -> data/printers.json)
[ ] `toner_detail.py`       (categorisation + attention)
[ ] `toner_db.py`           (history / forecasts)
[ ] `reachability.py`       (Online vs SNMP-Disabled — optional but recommended)
[ ] `sap_routes.py`         (existing)
[ ] `tools\` folder         (printer_tool, logger_tool, sharp_web_register, etc.)
Quick check:
```powershell
Get-ChildItem *.py | Select-Object Name
```
---
3. Required static pages (in static)
[ ] `static\index.html`
[ ] `static\portal.html`
[ ] `static\dashboard.html`
[ ] `static\toner_center.html`      (Toner Center page)
[ ] `static\manage_printers.html`   (Add/edit/delete printer IPs)
[ ] `static\sap.html`
Quick check:
```powershell
Get-ChildItem static\*.html | Select-Object Name
```
---
4. Copy the two new files into place
If they downloaded to Downloads, copy them in (adjust names if suffixed):
```powershell
Copy-Item "$env:USERPROFILE\Downloads\app.py"           ".\app.py" -Force
Copy-Item "$env:USERPROFILE\Downloads\toner_service.py" ".\toner_service.py" -Force
```
---
5. Verify toner_monitor.py imports the store correctly
Open `toner_monitor.py` and confirm this line is NOT commented out
(near the PRINTERS section):
```python
from printers_store import load_printers
PRINTERS = load_printers()
```
If it shows `# from printers_store import ...`, remove the `#`.
Then confirm the store loads:
```powershell
.\venv\Scripts\python.exe -c "import printers_store; print(len(printers_store.load_printers()), 'printers')"
```
---
6. Compile-check everything (catches typos before launch)
```powershell
.\venv\Scripts\python.exe -m py_compile .\app.py .\toner_service.py .\toner_monitor.py .\printers_store.py .\toner_detail.py .\toner_db.py .\reachability.py
```
No output = all good. Any error names the exact file + line.
---
7. Launch  (IMPORTANT: no --reload, single worker)
```powershell
.\venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000
```
Do NOT use `--reload` or `--workers 2` — both re-introduce the
"too many file descriptors in select()" crash on Windows.
Expected startup log:
```
toner_db: ready at ...\data\toner_history.db
Toner cache warmed from snapshot: N printer(s)
Toner background scanner started (every 24 hour(s)).
INFO:     Application startup complete.
=== Toner fleet scan started ... ===
```
---
8. Smoke test (browser)
[ ] http://localhost:8000/                    -> home tiles
[ ] http://localhost:8000/portal              -> printer request form
[ ] http://localhost:8000/dashboard           -> ops dashboard
[ ] http://localhost:8000/toner               -> Toner Center loads
[ ] http://localhost:8000/manage-printers     -> printer registry UI
[ ] http://localhost:8000/api/toner-status-all -> JSON, success:true
[ ] http://localhost:8000/api/toner-check?ip=172.20.102.115 -> live detail
---
9. Fix the fleet registry (the data issue)
Your registered printers were on `172.16.x.x` (E-BLOCK); you're now testing
on `172.20.x.x`. Update the fleet so scans find live printers:
Open http://localhost:8000/manage-printers
ADD the printers that respond on THIS network (e.g. MCR1 = 172.20.102.115)
DELETE/EDIT the old E-BLOCK entries whose IPs no longer reachable
Trigger a scan to populate "Needs Attention":
```
POST http://localhost:8000/api/toner-refresh
```
(or click Refresh on the Dashboard)
Watch the console: printers that respond should print `= Healthy/Low/Critical`
instead of `= Offline`.
---
10. Confirm the daily cycle
The scanner runs once ~5s after boot, then every 24h.
On-demand LIVE checks work any time via the Toner Center "Check a Printer".
To change cadence, edit `toner_service.py`:
SCAN_INTERVAL_SECONDS = 24 * 60 * 60   # e.g. 126060 for twice daily
---
Rollback (if anything breaks)
```powershell
# stop uvicorn (Ctrl+C), then restore backup
Remove-Item .\app.py, .\toner_service.py
Copy-Item ..\PrinterAgent_BACKUP_YYYYMMDD\app.py .\app.py
Copy-Item ..\PrinterAgent_BACKUP_YYYYMMDD\toner_service.py .\toner_service.py
```
---
Common errors -> cause
Error	Cause	Fix
ModuleNotFoundError: printers_store	file missing / commented import	step 5
ModuleNotFoundError: tools	running from C:\PrinterAgent	step 1
can't open file app.py	wrong folder / file in Downloads	step 1/4
too many file descriptors in select()	ran with --reload	step 7
Internal Server Error on /toner	toner_center.html missing	step 3
Needs Attention empty / all Offline	fleet IPs on old subnet	step 9
