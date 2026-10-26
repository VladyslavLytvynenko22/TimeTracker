# Installs TimeTracker: adds a Startup shortcut (runs at Windows login) and starts it now.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { $pythonw = "C:\Python314\pythonw.exe" }
if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found. Install Python 3 and try again." }

$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "TimeTracker.lnk"
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = $pythonw
$sc.Arguments = "`"$root\tracker.py`""
$sc.WorkingDirectory = $root
$sc.Description = "TimeTracker - personal work time tracker"
$icon = Join-Path $root "data\tracker.ico"
if (Test-Path $icon) { $sc.IconLocation = $icon }
$sc.Save()
Write-Host "Startup shortcut created: $lnk"

$running = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*TimeTracker\tracker.py*" }
if ($running) {
    Write-Host "TimeTracker is already running (PID $($running.ProcessId -join ', '))."
} else {
    Start-Process -FilePath $pythonw -ArgumentList "`"$root\tracker.py`"" -WorkingDirectory $root
    Write-Host "TimeTracker started."
}
Start-Sleep -Seconds 2
$port = 48411
$settingsFile = Join-Path $root "data\tracker.db"
Start-Process "http://127.0.0.1:$port/"
Write-Host "Dashboard: http://127.0.0.1:$port/  (look for the blue clock icon in the tray)"
