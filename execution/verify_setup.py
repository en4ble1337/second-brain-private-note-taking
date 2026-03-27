#!/usr/bin/env python3
"""
Post-install environment verification.
Called automatically by deployment/install.sh after installation.
Can also be run manually: python execution/verify_setup.py
"""

import sys
import subprocess
from pathlib import Path


PASS = "  [ ok ]"
FAIL = "  [FAIL]"


def check_python_version() -> tuple[bool, str]:
    required = (3, 11)
    current = sys.version_info[:2]
    if current < required:
        return False, f"Python {required[0]}.{required[1]}+ required, found {current[0]}.{current[1]}"
    return True, f"Python {current[0]}.{current[1]}"


def check_env_file() -> tuple[bool, str]:
    env_path = Path(".env")
    if not env_path.exists():
        return False, ".env not found — run deployment/install.sh"
    content = env_path.read_text()
    if "INGEST_TOKEN" not in content:
        return False, ".env is missing INGEST_TOKEN"
    token_line = next((l for l in content.splitlines() if l.startswith("INGEST_TOKEN=")), "")
    token_val = token_line.split("=", 1)[-1].strip()
    if not token_val:
        return False, "INGEST_TOKEN is empty"
    return True, ".env present with INGEST_TOKEN set"


def check_data_dirs() -> tuple[bool, str]:
    required = [Path("data/raw"), Path("data/db")]
    missing = [str(d) for d in required if not d.is_dir()]
    if missing:
        return False, f"Missing data directories: {', '.join(missing)}"
    return True, "data/raw and data/db exist"


def check_packages() -> tuple[bool, str]:
    required = [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("sqlalchemy", "sqlalchemy"),
        ("aiosqlite", "aiosqlite"),
        ("filetype", "filetype"),
        ("pydantic_settings", "pydantic-settings"),
        ("jinja2", "jinja2"),
        ("faster_whisper", "faster-whisper"),
        ("ollama", "ollama"),
        ("httpx", "httpx"),
    ]
    missing = []
    for import_name, pkg_name in required:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg_name)
    if missing:
        return False, f"Missing packages: {', '.join(missing)}"
    return True, "All required packages importable"


def check_ollama_running() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "ollama"],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip() == "active":
            return True, "ollama.service is active"
        return False, f"ollama.service is not active (state: {result.stdout.strip()})"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, "Could not check ollama.service status"


def check_ollama_model() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=10
        )
        if "llama3.2" in result.stdout:
            return True, "llama3.2 model present"
        return False, "llama3.2 model not found — run: ollama pull llama3.2:3b"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, "Could not run 'ollama list' — is Ollama installed?"


def check_src_importable() -> tuple[bool, str]:
    try:
        import src.core.config  # noqa: F401
        return True, "src.core.config importable"
    except Exception as e:
        return False, f"Failed to import src: {e}"


def main() -> int:
    checks = [
        ("Python version",     check_python_version),
        ("Environment file",   check_env_file),
        ("Data directories",   check_data_dirs),
        ("Python packages",    check_packages),
        ("Ollama service",     check_ollama_running),
        ("Ollama model",       check_ollama_model),
        ("App importable",     check_src_importable),
    ]

    print("=" * 50)
    print("Second Brain — Environment Verification")
    print("=" * 50)

    failures = []
    for name, fn in checks:
        ok, msg = fn()
        print(f"{'  [ ok ]' if ok else '  [FAIL]'} {name}: {msg}")
        if not ok:
            failures.append(name)

    print("=" * 50)
    if not failures:
        print("All checks passed.")
        return 0
    else:
        print(f"{len(failures)} check(s) failed — fix the issues above before proceeding.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
