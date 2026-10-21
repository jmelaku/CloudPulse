#!/usr/bin/env python3
"""Measure POST-to-terminal-state latency, not merely API acceptance latency."""
import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import uuid4


def request_json(url, method="GET", body=None, headers=None):
    request = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, json.load(response)


def percentile(values, fraction):
    values = sorted(values)
    return values[max(0, min(len(values) - 1, int((len(values) - 1) * fraction)))]


def transaction(base_url, number, poll_interval, timeout):
    start = time.monotonic()
    body = json.dumps({"amount_cents": 100, "description": "e2e benchmark"}).encode()
    try:
        _, created = request_json(
            base_url + "/transactions", method="POST", body=body,
            headers={"Content-Type": "application/json", "Idempotency-Key": f"e2e-{number}-{uuid4()}"},
        )
        transaction_id = created["id"]
        deadline = start + timeout
        while time.monotonic() < deadline:
            _, state = request_json(base_url + "/transactions/" + transaction_id)
            if state["status"] == "completed":
                return "completed", time.monotonic() - start
            if state["status"] in ("failed", "cancelled"):
                return "failed", time.monotonic() - start
            time.sleep(poll_interval)
        return "timed_out", time.monotonic() - start
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, ValueError) as exc:
        return "failed", time.monotonic() - start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--poll-interval", type=float, default=0.05)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    started = time.monotonic()
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(transaction, args.url, n, args.poll_interval, args.timeout)
                   for n in range(args.requests)]
        for future in as_completed(futures):
            results.append(future.result())
    elapsed = time.monotonic() - started
    completed = [latency for status, latency in results if status == "completed"]
    output = {"submitted": args.requests, "completed": len(completed),
              "failed": sum(status == "failed" for status, _ in results),
              "timed_out": sum(status == "timed_out" for status, _ in results),
              "duration_seconds": round(elapsed, 4),
              "completed_throughput_rps": round(len(completed) / elapsed, 2)}
    if completed:
        output.update({"mean_ms": round(statistics.mean(completed) * 1000, 2),
                       "p50_ms": round(percentile(completed, .50) * 1000, 2),
                       "p95_ms": round(percentile(completed, .95) * 1000, 2),
                       "p99_ms": round(percentile(completed, .99) * 1000, 2)})
    print(json.dumps(output))


if __name__ == "__main__":
    main()
