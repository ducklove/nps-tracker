#!/usr/bin/env bash
# nps-tracker daily batch trigger (crontab: weekdays 15:45 KST, right after market close).
# This server is the single scheduler: GitHub cron was removed (its 2-3h delay made it
# useless, and if this server is down the parent service value-invest is down anyway).
# Transient dispatch failures are absorbed by 3 retries, 60s apart; persistent failures
# are visible in the log below.
LOG=$HOME/log/nps-trigger.log
{
  for i in 1 2 3; do
    echo "[$(date '+%F %T')] dispatching pages.yml (attempt $i)"
    if /usr/bin/gh workflow run pages.yml -R ducklove/nps-tracker -f refresh_data=true 2>&1; then
      echo "[$(date '+%F %T')] dispatch OK"
      exit 0
    fi
    sleep 60
  done
  echo "[$(date '+%F %T')] dispatch FAILED after 3 attempts - check gh auth/network"
} >> "$LOG" 2>&1
