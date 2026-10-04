"""Fetch the Zerodha put-option ladder for India F&O names and write the snapshot CSV.

Run LOCALLY with fno-margin-fetch running and authenticated (Kite token valid):

    ~/work/py-shared-env/dev/bin/python scripts/fetch_kite_put_premiums.py [INFY SBIN ...]

Writes data/input/kite/put_premiums.csv. Commit it and deploy: deploy.yaml rsyncs
data/input/ to EC2, where /portfolio-hedge reads it when no live Kite is reachable
(snapshots older than 10 days, or past expiry, are ignored -> model estimate).
Default instruments: every F&O-eligible India name plus NIFTY and BANKNIFTY.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rita.api.experience.portfolio_hedge import _FNO_ELIGIBLE  # noqa: E402
from rita.services.kite_middleware_client import (  # noqa: E402
    PUT_CSV_RELPATH,
    fetch_put_chain,
    warm_pe_cache,
    write_put_csv,
)


def main(argv: list[str]) -> int:
    instruments = [a.upper() for a in argv] or sorted(_FNO_ELIGIBLE) + ["NIFTY", "BANKNIFTY"]
    print("Loading the NFO option master (slow, ~30k contracts)...")
    if not warm_pe_cache():
        print("Could not load the NFO instrument list — is fno-margin-fetch running and the Kite token valid?")
        return 1
    rows, failed = [], []
    for inst in instruments:
        chain = fetch_put_chain(inst)
        if chain:
            rows.extend(chain)
            print(f"  {inst:<11} {len(chain)} strikes, expiry {chain[0]['expiry']}, spot {chain[0]['spot']:g}")
        else:
            failed.append(inst)
            print(f"  {inst:<11} no data")
    if not rows:
        print("No data fetched — is fno-margin-fetch running and the Kite token valid? CSV not written.")
        return 1
    out = ROOT / "data" / "input" / PUT_CSV_RELPATH
    write_put_csv(out, rows)
    print(f"Wrote {len(rows)} rows for {len(instruments) - len(failed)} instruments -> {out.relative_to(ROOT)}")
    if failed:
        print("No data for: " + ", ".join(failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
