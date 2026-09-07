#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from app.services.pilot import evaluate_pilot

parser = argparse.ArgumentParser(description="Evalúa la evidencia de un piloto de Velmorax.")
parser.add_argument("report", type=Path)
args = parser.parse_args()
result = evaluate_pilot(json.loads(args.report.read_text(encoding="utf-8")))
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result["approved"] else 2)
