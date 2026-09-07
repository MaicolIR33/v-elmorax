#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Uso: ./deploy/check-production.sh https://app.tu-dominio.com" >&2
  exit 2
fi

base_url="${1%/}"
case "$base_url" in
  https://*) ;;
  *) echo "La comprobación exige una dirección HTTPS." >&2; exit 2 ;;
esac

response="$(curl --fail --silent --show-error --max-time 10 "$base_url/health")"
printf '%s' "$response" | python -c '
import json, sys
payload = json.load(sys.stdin)
if payload.get("status") != "ok" or payload.get("database") != "postgres" or payload.get("database_status") != "ok":
    raise SystemExit("Velmorax respondió, pero no está listo sobre PostgreSQL")
print("Velmorax está disponible por HTTPS y conectado a PostgreSQL.")
'
