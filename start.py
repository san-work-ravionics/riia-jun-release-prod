"""RITA development server startup — tees output to a dated log file."""
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

PORT = 8000


# ── Load .env file ────────────────────────────────────────────────────────────
# Reads KEY=VALUE pairs from .env (next to this script) and sets them as
# environment variables inherited by the uvicorn subprocess.
# Shell variables already set take precedence (setdefault behaviour).
# Lines starting with # and blank lines are ignored.
def _load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        print(f"[start] No .env file found at {env_path} — using shell environment only.")
        return
    with env_path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
    print(f"[start] Loaded env from {env_path}")


_load_dotenv(Path(__file__).parent / ".env")

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"rita-{date.today()}.log"

# Kill any process already holding the port
result = subprocess.run(
    ["netstat", "-ano"],
    capture_output=True, text=True
)
for line in result.stdout.splitlines():
    if f":{PORT}" in line and "LISTENING" in line:
        parts = line.split()
        pid = parts[-1]
        print(f"Killing existing process on port {PORT} (PID {pid})")
        subprocess.run(["taskkill", "/PID", pid, "/F"],
                       capture_output=True)
        break

# ── Chat feature pre-flight checks ───────────────────────────────────────────
# The RITA chat assistant is fully local — no API key required.
# It uses sentence-transformers/all-MiniLM-L6-v2 (lazy-loaded on first warmup).
_csv = Path(__file__).parent / "data" / "raw" / "NIFTY" / "merged.csv"
if not _csv.exists():
    print(f"WARNING: {_csv} not found — RITA chat dispatch will fail at runtime.")
    print("         Place the Nifty 50 OHLCV CSV at that path before using chat.\n")
else:
    print(f"[start] Market data CSV found: {_csv}")

print(f"Starting RITA  |  logs -> {log_file}\n")

proc = subprocess.Popen(
    [
        sys.executable, "-m", "uvicorn", "rita.main:app",
        "--host", "0.0.0.0", "--port", str(PORT), "--reload",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
)

try:
    with open(log_file, "a", buffering=1) as lf:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            lf.write(line)
except KeyboardInterrupt:
    proc.terminate()
    proc.wait()
