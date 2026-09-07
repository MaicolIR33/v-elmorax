#!/bin/sh
set -u

interval="${BACKUP_INTERVAL_SECONDS:-21600}"
case "$interval" in *[!0-9]*|'') echo "BACKUP_INTERVAL_SECONDS no es válido" >&2; exit 2;; esac

while true; do
  if ! /usr/local/bin/backup-cycle; then
    date -u +%s > /backups/last_failure_epoch
  fi
  sleep "$interval"
done
