#!/usr/bin/env python3
"""
End-to-End Smoke Test
Run this against the live appliance after deployment to validate the full pipeline.

Usage:
    python execution/smoke_test.py --host http://mybrain.local --token <your-token>
    python execution/smoke_test.py --host http://192.168.1.100 --token <your-token>

Exit codes:
    0 — all checks passed
    1 — one or more checks failed
"""

import argparse
import sys
import time
import io

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx")
    sys.exit(1)


# ── Test audio helpers ────────────────────────────────────────────────────────

def make_test_wav() -> bytes:
    """Return a minimal but valid WAV file (silence, 1s, 44100Hz mono 16-bit)."""
    import struct
    sample_rate = 44100
    num_channels = 1
    bits_per_sample = 16
    num_samples = sample_rate  # 1 second
    data_size = num_samples * num_channels * (bits_per_sample // 8)
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,           # PCM chunk size
        1,            # PCM format
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    audio_data = b"\x00" * data_size  # silence
    return header + audio_data


# ── Check runners ─────────────────────────────────────────────────────────────

PASS = "  [PASS]"
FAIL = "  [FAIL]"
INFO = "  [INFO]"


def check_ingest(host: str, token: str, timeout: float = 10.0) -> tuple[bool, str, float]:
    """POST a WAV file and return (success, job_id, elapsed_ms)."""
    headers = {"Authorization": f"Bearer {token}"}
    wav_bytes = make_test_wav()
    t0 = time.monotonic()
    try:
        resp = httpx.post(
            f"{host}/api/ingest",
            headers=headers,
            files={"audio": ("smoke_test.wav", io.BytesIO(wav_bytes), "audio/wav")},
            data={"source": "smoke_test"},
            timeout=timeout,
        )
    except httpx.ConnectError as e:
        return False, "", 0
    elapsed_ms = (time.monotonic() - t0) * 1000
    if resp.status_code != 202:
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}", elapsed_ms
    job_id = resp.json().get("job_id", "")
    return True, job_id, elapsed_ms


def poll_job(host: str, job_id: str, timeout_s: float = 60.0) -> tuple[bool, str, float]:
    """Poll /api/jobs/{job_id} until complete or failed. Returns (success, status, elapsed_s)."""
    t0 = time.monotonic()
    deadline = t0 + timeout_s
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{host}/api/jobs/{job_id}", timeout=5)
        except httpx.ConnectError:
            time.sleep(2)
            continue
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}", time.monotonic() - t0
        data = resp.json()
        status = data.get("status", "unknown")
        if status == "complete":
            return True, status, time.monotonic() - t0
        if status == "failed":
            return False, f"failed: {data.get('error_message', 'unknown')}", time.monotonic() - t0
        time.sleep(2)
    return False, "timeout", time.monotonic() - t0


def check_note_exists(host: str, job_id: str) -> tuple[bool, str]:
    """Verify the job has an associated note in GET /api/notes."""
    resp = httpx.get(f"{host}/api/jobs/{job_id}", timeout=5)
    if resp.status_code != 200:
        return False, f"Job status HTTP {resp.status_code}"
    note_id = resp.json().get("note_id")
    if not note_id:
        return False, "note_id is null on completed job"
    return True, note_id


def check_web_ui(host: str) -> tuple[bool, float]:
    """GET / and measure load time."""
    t0 = time.monotonic()
    resp = httpx.get(f"{host}/", timeout=10)
    elapsed = time.monotonic() - t0
    return resp.status_code == 200, elapsed


def check_setup_page(host: str) -> bool:
    """GET /setup and verify it loads."""
    resp = httpx.get(f"{host}/setup", timeout=5)
    return resp.status_code == 200


def check_search(host: str) -> bool:
    """GET /api/notes?q=smoke_test returns at least one result."""
    resp = httpx.get(f"{host}/api/notes?q=smoke", timeout=5)
    if resp.status_code != 200:
        return False
    return resp.json().get("total", 0) > 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Second Brain smoke test")
    parser.add_argument("--host", default="http://mybrain.local", help="Appliance base URL")
    parser.add_argument("--token", required=True, help="Ingest Bearer token")
    parser.add_argument("--pipeline-timeout", type=float, default=60.0,
                        help="Max seconds to wait for pipeline completion (default: 60)")
    args = parser.parse_args()

    host = args.host.rstrip("/")
    failures = []

    print(f"\nSecond Brain Smoke Test")
    print(f"  Target : {host}")
    print(f"  Timeout: {args.pipeline_timeout}s pipeline")
    print("─" * 50)

    # ── Check 1: Web UI reachable ────────────────────────────────────────────
    print("\n[1] Web UI availability")
    ok, ui_ms = check_web_ui(host)
    if ok:
        print(f"{PASS} GET / returned 200 in {ui_ms*1000:.0f}ms")
        if ui_ms > 1.0:
            print(f"{INFO} WARNING: load time {ui_ms:.2f}s exceeds 1s NFR target")
    else:
        print(f"{FAIL} GET / failed — is the service running at {host}?")
        failures.append("Web UI unreachable")

    # ── Check 2: Setup page ──────────────────────────────────────────────────
    print("\n[2] Setup wizard")
    if check_setup_page(host):
        print(f"{PASS} GET /setup returned 200")
    else:
        print(f"{FAIL} GET /setup failed")
        failures.append("Setup wizard unavailable")

    # ── Check 3: Ingest endpoint ─────────────────────────────────────────────
    print("\n[3] Ingest endpoint (POST /api/ingest)")
    ok, job_id_or_err, ingest_ms = check_ingest(host, args.token)
    if ok:
        job_id = job_id_or_err
        print(f"{PASS} 202 Accepted in {ingest_ms:.0f}ms — job_id={job_id}")
        if ingest_ms > 500:
            print(f"{INFO} WARNING: ingest latency {ingest_ms:.0f}ms exceeds 500ms NFR target")
    else:
        print(f"{FAIL} Ingest failed — {job_id_or_err}")
        failures.append("Ingest endpoint failed")
        print("\n" + "─" * 50)
        print(f"RESULT: {len(failures)} check(s) FAILED — cannot continue without a successful ingest.")
        sys.exit(1)

    # ── Check 4: Pipeline completion ─────────────────────────────────────────
    print(f"\n[4] Pipeline completion (polling up to {args.pipeline_timeout:.0f}s)")
    ok, status, elapsed_s = poll_job(host, job_id, timeout_s=args.pipeline_timeout)
    if ok:
        print(f"{PASS} Job complete in {elapsed_s:.1f}s")
        if elapsed_s > 10:
            print(f"{INFO} WARNING: pipeline took {elapsed_s:.1f}s — PRD target is <10s for a 30s note")
    else:
        print(f"{FAIL} Pipeline did not complete — status={status}")
        failures.append(f"Pipeline failure: {status}")

    # ── Check 5: Note created ────────────────────────────────────────────────
    print("\n[5] Note creation")
    ok, note_id_or_err = check_note_exists(host, job_id)
    if ok:
        print(f"{PASS} Note created — note_id={note_id_or_err}")
    else:
        print(f"{FAIL} Note not found — {note_id_or_err}")
        failures.append("Note not created after pipeline")

    # ── Check 6: JSON notes API ──────────────────────────────────────────────
    print("\n[6] JSON notes API (GET /api/notes)")
    resp = httpx.get(f"{host}/api/notes", timeout=5)
    if resp.status_code == 200 and resp.json().get("total", 0) >= 1:
        print(f"{PASS} /api/notes returned {resp.json()['total']} note(s)")
    else:
        print(f"{FAIL} /api/notes returned unexpected response: {resp.status_code} {resp.text[:100]}")
        failures.append("Notes API failed")

    # ── Check 7: Full-text search ────────────────────────────────────────────
    print("\n[7] Full-text search")
    if check_search(host):
        print(f"{PASS} FTS search returned results")
    else:
        print(f"{INFO} FTS search returned no results for 'smoke' — may be OK if transcript differs")

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "─" * 50)
    if not failures:
        print(f"RESULT: ALL CHECKS PASSED ✓")
        print(f"\nPRD Success Metrics:")
        print(f"  Ingest latency : {ingest_ms:.0f}ms  (target <500ms)")
        print(f"  Pipeline time  : {elapsed_s:.1f}s   (target <10s for 30s note)")
        print(f"  Web UI load    : {ui_ms*1000:.0f}ms  (target <1000ms)")
        sys.exit(0)
    else:
        print(f"RESULT: {len(failures)} check(s) FAILED:")
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
