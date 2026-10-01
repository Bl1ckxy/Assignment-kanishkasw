# Disk guard for large MySQL imports.
# Polls C: free space; if < ThresholdGB kills the mysql.exe IMPORT CLIENT
# (not mysqld), writes a stop marker, exits 2.
# Exits 0 when the sentinel file appears (import finished), 3 on timeout.
param(
    [int]$ThresholdGB = 8,
    [string]$Sentinel  = "H:\kanishka\project\logs\import_done.flag",
    [string]$OutDir    = "H:\kanishka\project\logs",
    [int]$IntervalSec  = 15,
    [int]$MaxMinutes   = 240
)
$csv = Join-Path $OutDir "disk_monitor.csv"
$stopMarker = Join-Path $OutDir "disk_monitor_stop.txt"
$doneMarker = Join-Path $OutDir "disk_monitor_done.txt"
Remove-Item $stopMarker, $doneMarker -ErrorAction SilentlyContinue
if (-not (Test-Path $csv)) { "ts,free_gb" | Out-File $csv -Encoding ascii }

$t0 = Get-Date
while ($true) {
    $free = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
    "$(Get-Date -Format o),$free" | Add-Content $csv
    if ($free -lt $ThresholdGB) {
        Get-Process mysql -ErrorAction SilentlyContinue | Stop-Process -Force
        "STOPPED_DISK_LOW free=${free}GB threshold=${ThresholdGB}GB at $(Get-Date -Format o)" |
            Out-File $stopMarker -Encoding ascii
        exit 2
    }
    if (Test-Path $Sentinel) {
        "OK_DONE free=${free}GB at $(Get-Date -Format o)" | Out-File $doneMarker -Encoding ascii
        exit 0
    }
    if (((Get-Date) - $t0).TotalMinutes -gt $MaxMinutes) {
        "TIMEOUT after $MaxMinutes min free=${free}GB (monitor only; import may still run)" |
            Out-File (Join-Path $OutDir "disk_monitor_timeout.txt") -Encoding ascii
        exit 3
    }
    Start-Sleep -Seconds $IntervalSec
}
