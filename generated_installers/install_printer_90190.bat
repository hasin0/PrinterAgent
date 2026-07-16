@echo off
echo ============================================
echo   Sharp Printer Auto Installer
echo   Printer: ASSET INTEGRITY PRINTER
echo   IP: 172.16.18.88
echo   User: Osama
echo   Code: 90190
echo ============================================
echo.
echo Checking if Sharp driver is already installed...
powershell -Command "$d = (Get-PrinterDriver | Where-Object { $_.Name -like '*Sharp*' } | Select-Object -First 1).Name; if ($d) { echo DRIVER_EXISTS } else { echo DRIVER_MISSING }" > "%TEMP%\driver_check.txt"
findstr /C:"DRIVER_EXISTS" "%TEMP%\driver_check.txt" >nul
if %errorlevel%==0 (
    echo Driver already installed - skipping download
    goto ADD_PRINTER
)
echo Driver not found - downloading...
powershell -Command "Invoke-WebRequest -Uri 'http://127.0.0.1:8000/drivers/sharp_driver.exe' -OutFile '%TEMP%\sharp_driver.exe'"
if not exist "%TEMP%\sharp_driver.exe" (
    echo WARNING: Driver download failed.
    goto ADD_PRINTER
)
start /wait "" "%TEMP%\sharp_driver.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART

:ADD_PRINTER
echo.
echo Configuring printer...
powershell -Command "$portName = 'IP_172.16.18.88'; if (-not (Get-PrinterPort -Name $portName -ErrorAction SilentlyContinue)) { Add-PrinterPort -Name $portName -PrinterHostAddress '172.16.18.88' }"
echo Printer port ready
powershell -Command "$d = (Get-PrinterDriver | Where-Object { $_.Name -like '*Sharp*' } | Select-Object -First 1).Name; if (-not $d) { echo 'ERROR: Sharp driver not found'; exit 1 }; echo $d" > "%TEMP%\driver_name.txt"
set /p DRIVER_NAME=<"%TEMP%\driver_name.txt"
echo Found driver: %DRIVER_NAME%
powershell -Command "if (-not (Get-Printer -Name 'ASSET INTEGRITY PRINTER' -ErrorAction SilentlyContinue)) { Add-Printer -Name 'ASSET INTEGRITY PRINTER' -DriverName '%DRIVER_NAME%' -PortName 'IP_172.16.18.88' }"
echo Printer added
powershell -Command "(Get-WmiObject -Query \"SELECT * FROM Win32_Printer WHERE Name='ASSET INTEGRITY PRINTER'\").SetDefaultPrinter() | Out-Null"
echo Default printer set
echo.
echo Configuring printer preferences...
if not exist "%TEMP%\printer_config.py" (
    powershell -Command "Invoke-WebRequest -Uri 'http://127.0.0.1:8000/printer_config.py' -OutFile '%TEMP%\printer_config.py'"
) else (
    echo Config script already cached
)
if not exist "%TEMP%\printer_config.py" (
    echo ERROR: Could not download printer_config.py
    goto MANUAL
)
python -c "import pywinauto" >nul 2>&1
if %errorlevel% NEQ 0 (
    echo Installing required dependencies...
    python -m pip install pywinauto >nul 2>&1
) else (
    echo pywinauto already installed
)
echo Running configuration script...
python "%TEMP%\printer_config.py" "ASSET INTEGRITY PRINTER" "Osama" "90190"
if %errorlevel%==0 (
    echo Preferences configured automatically
    goto DONE
)
:MANUAL
echo.
echo ============================================
echo   AUTO-CONFIG FAILED - Manual Setup Needed
echo ============================================
echo.
echo Enter Name: Osama
pause
rundll32 printui.dll,PrintUIEntry /e /n "ASSET INTEGRITY PRINTER"
:DONE
echo.
echo ============================================
echo INSTALLATION COMPLETE
echo ============================================
echo.
echo Printer: ASSET INTEGRITY PRINTER
echo IP: 172.16.18.88
echo User: Osama
echo Code: 90190
echo.
pause