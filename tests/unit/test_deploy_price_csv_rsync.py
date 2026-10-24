"""Deploy must not overwrite the price CSVs on EC2.

They are kept current by /refresh-all-instruments-data (POST /api/v1/instrument/refresh-all
on prod). A fresh CI checkout has new mtimes, so ``rsync --update`` would replace the
refreshed copies with the older git ones.
"""
from __future__ import annotations

import re
from pathlib import Path

WF = (Path(__file__).parent.parent.parent / ".github" / "workflows" / "deploy.yaml").read_text()


def _rsyncs_to(dest: str) -> list[str]:
    cmds = re.findall(r"rsync -av[^\n]*\\\n(?:[^\n]*\\\n)*[^\n]*", WF)
    return [c for c in cmds if dest in c]


def test_raw_price_csvs_are_only_seeded_never_overwritten():
    cmds = _rsyncs_to(":/opt/rita_input/raw/")
    assert cmds and all("--ignore-existing" in c and "--update" not in c for c in cmds)


def test_daily_input_csvs_are_only_seeded_never_overwritten():
    cmds = _rsyncs_to(":/opt/rita_input/input/")
    seed = [c for c in cmds if "--ignore-existing" in c]
    update = [c for c in cmds if "--update" in c]
    assert len(seed) == 1 and len(update) == 1
    assert "--exclude '*_daily.csv'" in update[0]
