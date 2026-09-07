#!/bin/sh
set -eu

: "${PGHOST:?Falta PGHOST}"
: "${PGDATABASE:?Falta PGDATABASE}"
: "${PGUSER:?Falta PGUSER}"

passphrase_file="/run/secrets/backup_passphrase"
if [ ! -s "$passphrase_file" ]; then
  echo "Falta el secreto cifrado de respaldo." >&2
  exit 2
fi
if [ "$(wc -c < "$passphrase_file" | tr -d ' ')" -lt 32 ]; then
  echo "La clave de cifrado del respaldo debe tener al menos 32 caracteres." >&2
  exit 2
fi

mkdir -p /backups
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_name="velmorax_${timestamp}.dump.enc"
encrypted_path="/backups/${backup_name}"
plain_path="$(mktemp /tmp/velmorax-backup.dump.XXXXXX)"
verify_path="$(mktemp /tmp/velmorax-verify.dump.XXXXXX)"
verify_db="velmorax_verify_${timestamp}"

cleanup() {
  rm -f "$plain_path" "$verify_path"
  dropdb --if-exists "$verify_db" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

pg_dump --format=custom --compress=6 --no-owner --no-acl --file="$plain_path" "$PGDATABASE"
pg_restore --list "$plain_path" >/dev/null

openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 \
  -in "$plain_path" -out="$encrypted_path" -pass "file:${passphrase_file}"
sha256sum "$encrypted_path" > "${encrypted_path}.sha256"

openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in "$encrypted_path" -out="$verify_path" -pass "file:${passphrase_file}"
createdb "$verify_db"
pg_restore --no-owner --no-acl --dbname="$verify_db" "$verify_path"

required_tables="organizations users inventory_items inventory_movements appointments patients alerts audit_events"
for table_name in $required_tables; do
  found="$(psql --dbname="$verify_db" --tuples-only --no-align -c "SELECT to_regclass('public.${table_name}') IS NOT NULL")"
  if [ "$found" != "t" ]; then
    echo "La restauración no contiene la tabla requerida: ${table_name}" >&2
    exit 1
  fi
done

retention_days="${BACKUP_RETENTION_DAYS:-30}"
case "$retention_days" in *[!0-9]*|'') echo "BACKUP_RETENTION_DAYS no es válido" >&2; exit 2;; esac
find /backups -type f \( -name 'velmorax_*.dump.enc' -o -name 'velmorax_*.dump.enc.sha256' \) \
  -mtime "+${retention_days}" -delete

if [ -n "${BACKUP_REMOTE:-}" ]; then
  if [ ! -s /run/secrets/rclone.conf ]; then
    echo "BACKUP_REMOTE está definido, pero falta .secrets/rclone.conf" >&2
    exit 1
  fi
  rclone --config /run/secrets/rclone.conf copy "$encrypted_path" "$BACKUP_REMOTE"
  rclone --config /run/secrets/rclone.conf copy "${encrypted_path}.sha256" "$BACKUP_REMOTE"
fi

printf '%s\n' "$timestamp" > /backups/last_success_at
date -u +%s > /backups/last_success_epoch
printf '%s\n' "$backup_name" > /backups/last_success_file
printf 'verified\n' > /backups/last_success_status
rm -f /backups/last_failure_epoch

echo "Respaldo cifrado y restauración de prueba completados: ${backup_name}"
