#!/bin/sh
set -eu

python -c "from app.core.config import get_settings; get_settings().validate_production()"
python -c "from app.core.database import init_db; init_db()"

exec python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers "${WEB_CONCURRENCY:-2}" \
  --proxy-headers \
  --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}"
