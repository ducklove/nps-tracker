# Daily batch on-time trigger for nps-tracker.
# Windows Task Scheduler runs this on weekdays at 15:45 KST (right after market close).
# GitHub cron is delayed 2-3h in practice, so on-time delivery is owned by this local
# trigger; the GitHub crons (16:22/21:37 KST) remain as backup for days the PC is off.
# Duplicate runs are harmless: the workflow concurrency group serializes them and
# no-change runs skip the data commit.
$logDir = Join-Path $env:LOCALAPPDATA 'nps-tracker'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir 'trigger.log'
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$gh = 'C:\Program Files\GitHub CLI\gh.exe'
if (-not (Test-Path $gh)) { $gh = 'gh' }
Add-Content $log "[$stamp] dispatching pages.yml"
& $gh workflow run pages.yml -R ducklove/nps-tracker -f refresh_data=true 2>&1 |
    ForEach-Object { Add-Content $log "[$stamp] $_" }
if ($LASTEXITCODE -eq 0) {
    Add-Content $log "[$stamp] dispatch OK"
} else {
    Add-Content $log "[$stamp] dispatch FAILED (exit $LASTEXITCODE) - check network/gh auth"
}
