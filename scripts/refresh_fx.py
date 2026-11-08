"""Load daily EUR->INR / EUR->USD rates into market_data_cache (F44 P2 refresh_fx).

Run by the /refresh-all-instruments-data skill after the instrument refresh (org.md section 3: FX is
fetched only in a skill run, never from request code).  Usage: python scripts/refresh_fx.py
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "src")

from rita.database import SessionLocal  # noqa: E402
from rita.services.data_refresh import refresh_fx  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        results = refresh_fx(db)
    finally:
        db.close()
    print(json.dumps(results, indent=2))
    return 1 if any(r["status"] == "error" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
