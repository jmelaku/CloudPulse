#!/usr/bin/env python3
"""Concurrent local HTTP benchmark; reports measured submit latency."""
import argparse
import json
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import uuid4


def post(base: str, n: int) -> float:
    request = urllib.request.Request(base + "/transactions", method="POST",
        data=json.dumps({"amount_cents": 100, "description": "benchmark"}).encode(),
        headers={"Content-Type": "application/json", "Idempotency-Key": f"load-{n}-{uuid4()}"})
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=20) as result:
        if result.status not in (200, 202):
            raise RuntimeError(result.status)
    return time.perf_counter() - start


def percentile(values, p):
    return sorted(values)[max(0, min(len(values) - 1, int((len(values) - 1) * p)))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        latencies = list(as_completed([pool.submit(post, args.url, n) for n in range(args.requests)]))
        values = [f.result() for f in latencies]
    elapsed = time.perf_counter() - start
    print(json.dumps({"requests": len(values), "concurrency": args.concurrency,
     "elapsed_seconds": round(elapsed, 4), "throughput_rps": round(len(values)/elapsed, 2),
     "mean_ms": round(statistics.mean(values)*1000, 2), "p50_ms": round(percentile(values,.50)*1000,2),
     "p95_ms": round(percentile(values,.95)*1000,2), "p99_ms": round(percentile(values,.99)*1000,2)}))


if __name__ == "__main__":
    main()
