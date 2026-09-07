#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Uso: restore-backup /backups/velmorax_FECHA.dump.enc" >&2
  exit 2
fi

encrypted_path="$1"
passphrase_file="/run/secrets/backup_passphrase"
if [ ! -f "$encrypted_path" ] || [ ! -s "$passphrase_file" ]; then
  echo "No se encontró la copia o su clave de cifrado." >&2
  exit 2
fi

checksum_file="${encrypted_path}.sha256"
if [ ! -f "$checksum_file" ]; then
  echo "La copia no tiene archivo de integridad." >&2
  exit 2
fi
(cd "$(dirname "$encrypted_path")" && sha256sum -c "$(basename "$checksum_file")")

plain_path="$(mktemp /tmp/velmorax-restore.dump.XXXXXX)"
restore_db="velmorax_manual_restore_$(date -u +%Y%m%dT%H%M%SZ)"
cleanup() { rm -f "$plain_path"; }
trap cleanup EXIT INT TERM

openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in "$encrypted_path" -out="$plain_path" -pass "file:${passphrase_file}"
createdb "$restore_db"
if ! pg_restore --no-owner --no-acl --dbname="$restore_db" "$plain_path"; then
  dropdb --if-exists "$restore_db" >/dev/null 2>&1 || true
  exit 1
fi

echo "Restauración comprobada en la base temporal: ${restore_db}"
echo "No se modificó la base de producción. Elimina la temporal cuando termines: dropdb ${restore_db}"
