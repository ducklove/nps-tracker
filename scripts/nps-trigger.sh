#!/usr/bin/env bash
# nps-tracker daily batch on-time trigger (crontab: weekdays 15:45 KST).
# GitHub cron lags 2-3h in practice; this always-on server owns on-time delivery.
# GitHub crons (16:22/21:37 KST) remain as backup. Duplicate runs are harmless
# (workflow concurrency serializes; no-change runs skip the data commit).
LOG=$HOME/log/nps-trigger.log
{
  echo "[$(date '+%F %T')] dispatching pages.yml"
  if /usr/bin/gh workflow run pages.yml -R ducklove/nps-tracker -f refresh_data=true 2>&1; then
    echo "[$(date '+%F %T')] dispatch OK"
  else
    echo "[$(date '+%F %T')] dispatch FAILED - check gh auth/network"
  fi
} >> "$LOG" 2>&1
