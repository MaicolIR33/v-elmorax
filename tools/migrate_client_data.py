#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from app.core.database import init_db
from app.services.client_migration import migrate_client_bundle

parser = argparse.ArgumentParser(description="Valida o importa un paquete inicial de cliente en Velmorax.")
parser.add_argument("bundle", type=Path, help="Carpeta con manifest.json y archivos CSV")
parser.add_argument("--apply", action="store_true", help="Aplica la importación; sin esta opción solo valida")
args = parser.parse_args()
init_db()
result = migrate_client_bundle(args.bundle, apply=args.apply)
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result["valid"] else 2)
