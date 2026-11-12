"""Seed nse_option_bhav table from compressed DB file.

Idempotent: skips if table already has data or seed file is missing.
"""
import gzip
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

SEED_GZ = Path(os.environ.get("SEED_GZ_PATH", "nse_option_bhav.db.gz"))
DB_PATH = Path(os.environ.get("DB_PATH", "rita.db"))

if not SEED_GZ.exists():
    print(f"SKIP: {SEED_GZ} not found")
    raise SystemExit(0)

con = sqlite3.connect(str(DB_PATH))
cur = con.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nse_option_bhav'")
if not cur.fetchone():
    print("SKIP: nse_option_bhav table does not exist yet")
    con.close()
    raise SystemExit(0)

count = cur.execute("SELECT COUNT(*) FROM nse_option_bhav").fetchone()[0]
if count > 0:
    print(f"SKIP: nse_option_bhav already has {count} rows")
    con.close()
    raise SystemExit(0)

with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
    with gzip.open(str(SEED_GZ), "rb") as f_in:
        shutil.copyfileobj(f_in, tmp)
    tmp_path = tmp.name

try:
    cur.execute(f"ATTACH DATABASE '{tmp_path}' AS seed_db")
    cur.execute(
        "INSERT INTO nse_option_bhav "
        "(date, strike, option_type, expiry, open, high, low, close, settle_price, oi) "
        "SELECT date, strike, option_type, expiry, open, high, low, close, settle_price, oi "
        "FROM seed_db.nse_option_bhav"
    )
    con.commit()
    inserted = cur.execute("SELECT COUNT(*) FROM nse_option_bhav").fetchone()[0]
    cur.execute("DETACH DATABASE seed_db")
    print(f"Seeded {inserted} rows into nse_option_bhav")
finally:
    os.unlink(tmp_path)
    con.close()
