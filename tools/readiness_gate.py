#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import httpx


async def run(base_url: str, requests: int, concurrency: int) -> dict:
    timeout = httpx.Timeout(10.0)
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, follow_redirects=False) as client:
        ready = await client.get("/health/ready")
        login = await client.get("/login")
        forged = await client.post("/logout", headers={"Origin": "https://malicious.invalid", "Sec-Fetch-Site": "cross-site"})
        semaphore = asyncio.Semaphore(concurrency)
        async def hit():
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get("/login")
                    return response.status_code, (time.perf_counter() - started) * 1000
                except Exception:
                    return 0, (time.perf_counter() - started) * 1000
        results = await asyncio.gather(*(hit() for _ in range(requests)))
    latencies = [latency for _, latency in results]
    errors = sum(status != 200 for status, _ in results)
    p95 = sorted(latencies)[max(0, int(len(latencies) * .95) - 1)]
    required_headers = ("content-security-policy", "x-content-type-options", "x-frame-options", "referrer-policy", "permissions-policy")
    checks = {
        "ready": ready.status_code == 200,
        "security_headers": all(header in login.headers for header in required_headers),
        "cross_site_post_blocked": forged.status_code == 403,
        "error_rate_below_1_percent": (errors / max(requests, 1)) < .01,
        "p95_below_1500_ms": p95 < 1500,
    }
    return {"passed": all(checks.values()), "checks": checks, "requests": requests, "concurrency": concurrency, "errors": errors, "p95_ms": round(p95, 2), "median_ms": round(statistics.median(latencies), 2)}


parser = argparse.ArgumentParser(description="Puerta de carga y seguridad de Velmorax")
parser.add_argument("--url", default="http://127.0.0.1:8000")
parser.add_argument("--requests", type=int, default=200)
parser.add_argument("--concurrency", type=int, default=20)
args = parser.parse_args()
report = asyncio.run(run(args.url, max(1, args.requests), max(1, args.concurrency)))
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report["passed"] else 2)
