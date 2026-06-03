# Check if driver already installed
$DriverName = (Get-PrinterDriver | Where-Object {$_.Name -like "*Sharp*"} | Select-Object -First 1).Name

if (-not $DriverName) {
    # Driver NOT installed — download and install
    Write-Host "Downloading driver..."
    $DriverURL = "http://YOUR-SERVER:8000/drivers/SH_D20_PCL6_PS_2508a_EnglishUS_64bit.exe"
    $DriverPath = "$env:TEMP\sharp.exe"
    Invoke-WebRequest -Uri $DriverURL -OutFile $DriverPath
    Start-Process -FilePath $DriverPath -ArgumentList "/s" -Wait
    
    $DriverName = (Get-PrinterDriver | Where-Object {$_.Name -like "*Sharp*"} | Select-Object -First 1).Name
} else {
    Write-Host "Driver already installed"
}

# Add printer
$PrinterIP = "172.16.16.31"
$PrinterName = "Sharp BP-50C36"
$PortName = "IP_$PrinterIP"

if (-not (Get-PrinterPort -Name $PortName -ErrorAction SilentlyContinue)) {
    Add-PrinterPort -Name $PortName -PrinterHostAddress $PrinterIP
}

Add-Printer -Name $PrinterName -DriverName $DriverName -PortName $PortName
Set-Printer -Name $PrinterName -IsDefault $true

Write-Host "SUCCESS"


















# # ================================
# # Sharp Printer Auto Installer
# # ================================

# $ErrorActionPreference = "Stop"

# # ================================
# # CONFIG
# # ================================
# $PrinterIP   = "172.16.16.31"
# $PrinterName = "Sharp BP-50C36"
# $PortName    = "IP_$PrinterIP"

# # ✅ UPDATE THIS — SERVE YOUR EXE VIA WEB
# $DriverURL = "http://YOUR-SERVER/drivers/SH_D20_PCL6_PS_2508a_EnglishUS_64bit.exe"

# $DriverPath = "$env:TEMP\sharp_driver.exe"

# Write-Host "Starting printer setup..."

# # ================================
# # STEP 1 — DOWNLOAD DRIVER
# # ================================
# Write-Host "Downloading driver..."

# Invoke-WebRequest -Uri $DriverURL -OutFile $DriverPath

# if (!(Test-Path $DriverPath)) {
#     Write-Host "❌ Driver download failed"
#     exit 1
# }

# Write-Host "✅ Driver downloaded"

# # ================================
# # STEP 2 — INSTALL DRIVER (SILENT)
# # ================================
# Write-Host "Installing driver silently..."

# Start-Process -FilePath $DriverPath -ArgumentList "/s" -Wait

# Write-Host "✅ Driver installation completed"

# # ================================
# # STEP 3 — CREATE PORT
# # ================================
# Write-Host "Creating printer port..."

# if (-not (Get-PrinterPort -Name $PortName -ErrorAction SilentlyContinue)) {
#     Add-PrinterPort -Name $PortName -PrinterHostAddress $PrinterIP
# }

# Write-Host "✅ Port created"

# # ================================
# # STEP 4 — ADD PRINTER
# # ================================
# Write-Host "Adding printer..."

# $DriverName = (Get-PrinterDriver | Where-Object {$_.Name -like "*Sharp*"} | Select-Object -First 1).Name

# if (-not $DriverName) {
#     Write-Host "❌ Driver not found after install"
#     exit 1
# }

# if (-not (Get-Printer -Name $PrinterName -ErrorAction SilentlyContinue)) {
#     Add-Printer -Name $PrinterName -DriverName $DriverName -PortName $PortName
# }

# Write-Host "✅ Printer added"

# # ================================
# # STEP 5 — SET DEFAULT
# # ================================
# Set-Printer -Name $PrinterName -IsDefault $true

# Write-Host "✅ Printer set as default"

# # ================================
# # DONE
# # ================================
# Write-Host "🚀 SUCCESS: Printer installed and ready"
# ``