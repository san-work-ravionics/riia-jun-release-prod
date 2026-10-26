"""RITA Core — price-series integrity check for model replay windows (F44 P3, A6).

A model may only be replayed on bars that look like the data it was trained on.  An unadjusted
split / reverse split in a stored CSV (e.g. ATO 2024-11-12 ×86, 2024-12-06 ×0.015) is a finite,
positive jump that ``bad_data`` (non-finite / ≤ 0) does not catch.

Rule (no hand-set threshold): a bar AFTER ``train_end`` fails when its absolute log close-to-close
return is larger than the largest absolute log return the same instrument had on or before
``train_end`` — that bound is also the edge of the model's training distribution.  It errs toward
exclusion (a genuine record move also trips it); the failing dates and values are reported.

Pure: takes an already-loaded close series, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

REASON = "data_integrity"


@dataclass(frozen=True)
class IntegrityResult:
    passed: bool
    threshold: float | None                 # max |ln r| on or before train_end
    failures: list[tuple[date, float]] = field(default_factory=list)  # (bar date, |ln r|)

    def detail(self, limit: int = 3) -> str | None:
        """Short human text for the exclusion detail (dates + values), None when passed."""
        if self.passed:
            return None
        if self.threshold is None:
            return "no history on or before train_end to bound the window"
        shown = ", ".join(f"{d.isoformat()} |ln r|={v:.3f}" for d, v in self.failures[:limit])
        more = f" (+{len(self.failures) - limit} more)" if len(self.failures) > limit else ""
        return f"{shown}{more} > pre-train_end max {self.threshold:.3f}"


def check_window(close: pd.Series, train_end: date | str) -> IntegrityResult:
    """Check the bars after ``train_end`` against the instrument's own pre-``train_end`` max.

    ``close`` is the instrument's close series on a DatetimeIndex (any order; sorted here).
    Non-positive / non-finite closes are left to the ``bad_data`` check (their log return is
    NaN here and is skipped).
    """
    s = pd.Series(close, dtype=float).sort_index()
    cutoff = pd.Timestamp(train_end)
    with np.errstate(divide="ignore", invalid="ignore"):
        lr = np.log(s / s.shift(1)).abs()
    lr = lr.replace([np.inf, -np.inf], np.nan)
    pre = lr[lr.index <= cutoff].dropna()
    post = lr[lr.index > cutoff].dropna()
    if pre.empty:
        return IntegrityResult(passed=False, threshold=None)
    threshold = float(pre.max())
    bad = post[post > threshold]
    failures = [(ts.date(), float(v)) for ts, v in bad.items()]
    return IntegrityResult(passed=not failures, threshold=threshold, failures=failures)
