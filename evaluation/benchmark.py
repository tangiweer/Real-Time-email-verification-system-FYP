import asyncio
import time
import httpx
import numpy as np
import json
from datetime import datetime

import os

# Load test emails from an external file — no hardcoded PII
base_dir = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(base_dir, "data", "benchmark_emails.txt"), "r") as f:
    TEST_EMAILS = [line.strip() for line in f if line.strip()]

# Sweep across concurrency levels to answer: "does the system fall over under load?"
# (Addresses research gap (b): scalability and real-time latency)
CONCURRENCY_LEVELS = [1, 5, 10, 25, 50]
REQUESTS_PER_LEVEL = 50


async def verify_email(client: httpx.AsyncClient, email: str) -> dict:
    start = time.perf_counter()
    try:
        response = await client.post(
            "http://127.0.0.1:8000/verify-email",
            json={"email": email},
            timeout=30.0
        )
        latency = (time.perf_counter() - start) * 1000
        return {"status": response.status_code, "latency": latency, "data": response.json()}
    except Exception as e:
        return {"status": 500, "latency": (time.perf_counter() - start) * 1000, "error": str(e)}


async def worker(queue: asyncio.Queue, client: httpx.AsyncClient, results: list):
    while True:
        try:
            email = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        res = await verify_email(client, email)
        results.append(res)
        queue.task_done()


async def run_level(concurrency: int, total_requests: int) -> dict:
    print(f"\n[bench] Concurrency={concurrency}, requests={total_requests} ...")
    queue = asyncio.Queue()
    for i in range(total_requests):
        queue.put_nowait(TEST_EMAILS[i % len(TEST_EMAILS)])

    results = []
    async with httpx.AsyncClient() as client:
        start_time = time.perf_counter()
        tasks = [asyncio.create_task(worker(queue, client, results)) for _ in range(concurrency)]
        await asyncio.gather(*tasks)
        total_time = time.perf_counter() - start_time

    latencies = [r["latency"] for r in results if r["status"] == 200]
    errors = [r for r in results if r["status"] != 200]

    if not latencies:
        print(f"[bench]   All {total_requests} requests failed at concurrency={concurrency}!")
        return {
            "concurrency": concurrency,
            "total_requests": total_requests,
            "success_count": 0,
            "errors": len(errors),
            "total_time_s": total_time,
            "throughput_per_s": 0.0,
            "latency_ms": {"mean": None, "p50": None, "p95": None, "p99": None},
            "layer_breakdown_ms": {},
        }

    p50 = float(np.percentile(latencies, 50))
    p95 = float(np.percentile(latencies, 95))
    p99 = float(np.percentile(latencies, 99))
    throughput = len(latencies) / total_time

    # Average layer times across ALL successful requests at this concurrency
    # level, not just the first one — gives a realistic picture
    layer_totals: dict[str, list[float]] = {}
    for r in results:
        if r["status"] == 200:
            for layer, t in r["data"].get("execution_times", {}).items():
                layer_totals.setdefault(layer, []).append(t)
    layer_avg = {layer: round(float(np.mean(v)), 1) for layer, v in layer_totals.items()}

    print(f"[bench]   Throughput: {throughput:.2f} req/s | "
          f"p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms | "
          f"errors={len(errors)}/{total_requests}")
    if layer_avg:
        print(f"[bench]   Avg layer times: {layer_avg}")

    return {
        "concurrency": concurrency,
        "total_requests": total_requests,
        "success_count": len(latencies),
        "errors": len(errors),
        "total_time_s": round(total_time, 2),
        "throughput_per_s": round(throughput, 2),
        "latency_ms": {
            "mean": round(float(np.mean(latencies)), 2),
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
        },
        "layer_breakdown_ms": layer_avg,
        "raw_results": results,
    }


async def run_benchmark():
    print(f"Starting Benchmark sweep: concurrency levels {CONCURRENCY_LEVELS}, "
          f"{REQUESTS_PER_LEVEL} requests per level.")

    level_results = []
    for concurrency in CONCURRENCY_LEVELS:
        result = await run_level(concurrency, REQUESTS_PER_LEVEL)
        level_results.append(result)
        await asyncio.sleep(2)  # let the server cool down between levels

    print("\n" + "=" * 70)
    print("  BENCHMARK SUMMARY (concurrency sweep)")
    print("=" * 70)
    print(f"{'Concurrency':>12}{'Throughput':>14}{'p50 (ms)':>12}{'p95 (ms)':>12}{'p99 (ms)':>12}{'Errors':>10}")
    for r in level_results:
        p = r["latency_ms"]
        print(f"{r['concurrency']:>12}{r['throughput_per_s']:>14}"
              f"{p['p50'] if p['p50'] is not None else 'N/A':>12}"
              f"{p['p95'] if p['p95'] is not None else 'N/A':>12}"
              f"{p['p99'] if p['p99'] is not None else 'N/A':>12}"
              f"{r['errors']:>10}")

    summary = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "concurrency_levels": CONCURRENCY_LEVELS,
        "requests_per_level": REQUESTS_PER_LEVEL,
        "results_by_concurrency": level_results,
    }

    # Append to history so successive runs accumulate, not overwrite
    out_path = os.path.join(base_dir, "evaluation", "evaluation_results.json")
    try:
        with open(out_path, "r") as f:
            existing = json.load(f)
            if not isinstance(existing, list):
                existing = [existing]
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    existing.append(summary)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(existing, f, indent=2)

    print(f"\n[bench] Full sweep results appended to {out_path}")


if __name__ == "__main__":
    asyncio.run(run_benchmark())