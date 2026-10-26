# Stops TimeTracker and removes the Startup shortcut. Data in .\data is kept.
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "TimeTracker.lnk"
if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "Removed $lnk" }
Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*TimeTracker\tracker.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Stopped PID $($_.ProcessId)" }
Write-Host "Done. Your data is still in $PSScriptRoot\data"
