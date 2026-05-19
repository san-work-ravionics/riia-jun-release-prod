"""System router for infrastructure / data-prep checks and static data.

ADR-001 Tier 1: file-system checks, JUnit XML reader, static SHAP data,
data-understanding computation. No DB writes.
URLs preserved from observability.py (Option A migration).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter

from rita.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["system:data-prep"])

_E2E_SUITE_NAMES = ["rita", "fno", "ops"]
_RELEASE_ROOT = Path(__file__).parent.parent.parent.parent.parent.parent


# ── JUnit XML helpers ─────────────────────────────────────────────────────────

def _latest_xml(folder: Path) -> Optional[Path]:
    if not folder.exists():
        return None
    xmls = sorted(folder.glob("*.xml"), reverse=True)
    return xmls[0] if xmls else None


def _history_runs(folder: Path) -> list[dict[str, Any]]:
    if not folder.exists():
        return []
    result = []
    for xml in sorted(folder.glob("*.xml"), reverse=True):
        data = _parse_junit(xml)
        data["run_id"] = xml.stem
        result.append(data)
    return result


def _parse_junit(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"total": 0, "passed": 0, "failed": 0, "cases": [], "run_at": None}
    tree = ET.parse(path)
    root = tree.getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return {"total": 0, "passed": 0, "failed": 0, "cases": [], "run_at": None}
    total    = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0))
    errors   = int(suite.get("errors", 0))
    failed   = failures + errors
    passed   = total - failed
    cases = []
    for tc in suite.findall("testcase"):
        name    = tc.get("name", "")
        failure = tc.find("failure")
        status  = "passed" if failure is None else "failed"
        message = ""
        if failure is not None:
            raw = failure.get("message", "") or (failure.text or "")
            message = raw.split("\n")[0][:80]
        cases.append({"name": name, "status": status, "message": message})
    return {"total": total, "passed": passed, "failed": failed, "cases": cases, "run_at": suite.get("timestamp")}


def _extract_module_name(classname: str) -> str:
    if not classname:
        return "unknown"
    return classname.split(".")[-1]


def _parse_junit_grouped(path: Path) -> dict[str, Any]:
    base = _parse_junit(path)
    if not path.exists():
        return {**base, "modules": {}}
    tree = ET.parse(path)
    root = tree.getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return {**base, "modules": {}}
    modules: dict[str, dict] = {}
    for tc in suite.findall("testcase"):
        name      = tc.get("name", "")
        classname = tc.get("classname", "")
        mod       = _extract_module_name(classname)
        failure   = tc.find("failure")
        status    = "passed" if failure is None else "failed"
        message   = ""
        if failure is not None:
            raw     = failure.get("message", "") or (failure.text or "")
            message = raw.split("\n")[0][:80]
        if mod not in modules:
            modules[mod] = {"total": 0, "passed": 0, "failed": 0, "cases": []}
        modules[mod]["total"] += 1
        modules[mod]["passed" if status == "passed" else "failed"] += 1
        modules[mod]["cases"].append({"name": name, "status": status, "message": message})
    return {**base, "modules": modules}


# ── GET /api/v1/data-prep/status ──────────────────────────────────────────────

@router.get("/data-prep/status", summary="Data preparation pipeline status")
def data_prep_status() -> dict[str, Any]:
    cfg = get_settings()
    stages: list[dict[str, Any]] = []
    overall = "ok"

    raw_csv = Path("data/raw/NIFTY/merged.csv")
    if raw_csv.exists():
        try:
            with open(raw_csv, encoding="utf-8", errors="ignore") as f:
                row_count = sum(1 for _ in f) - 1
            stages.append({"name": "Raw CSV", "status": "ok", "detail": f"merged.csv found ({row_count} rows)"})
        except Exception:
            stages.append({"name": "Raw CSV", "status": "ok", "detail": "merged.csv found"})
    else:
        stages.append({"name": "Raw CSV", "status": "warn", "detail": "merged.csv not found — market signals will use nifty_manual.csv"})
        overall = "warn"

    manual_csv = Path(cfg.data.input_dir) / "DAILY-DATA" / "nifty_manual.csv"
    if manual_csv.exists():
        stages.append({"name": "Manual Daily Data", "status": "ok", "detail": "nifty_manual.csv found"})
    else:
        stages.append({"name": "Manual Daily Data", "status": "warn", "detail": "nifty_manual.csv not found — 2026 data unavailable"})
        if overall != "error":
            overall = "warn"

    model_dir = Path(cfg.model.path)
    zips = sorted(model_dir.rglob("*.zip")) if model_dir.exists() else []
    if zips:
        stages.append({"name": "Model Files", "status": "ok", "detail": f"{len(zips)} model file(s) found"})
    else:
        stages.append({"name": "Model Files", "status": "warn", "detail": "No trained model files found — run pipeline to train"})
        if overall != "error":
            overall = "warn"

    return {"status": overall, "stages": stages}


# ── GET /api/v1/test-results ──────────────────────────────────────────────────

@router.get("/test-results", summary="Latest test results — e2e, integration, unit")
def test_results() -> dict[str, Any]:
    all_modules: list[dict] = []
    suite_summary: dict[str, dict] = {}
    suites: list[dict] = []
    any_file_found = False

    e2e_total = e2e_passed = e2e_failed = 0
    e2e_run_at: Optional[str] = None

    for name in _E2E_SUITE_NAMES:
        suite_dir  = _RELEASE_ROOT / "test-results" / "e2e" / name
        latest_xml = _latest_xml(suite_dir)
        has_runs   = latest_xml is not None

        if has_runs:
            latest = _parse_junit(latest_xml)
            any_file_found = True
        else:
            latest = {"total": 0, "passed": 0, "failed": 0, "cases": [], "run_at": None}

        runs = _history_runs(suite_dir)
        suites.append({
            "name": name, "file_exists": has_runs,
            "total": latest["total"], "passed": latest["passed"], "failed": latest["failed"],
            "cases": latest["cases"], "run_at": latest["run_at"],
            "runs": [{"run_id": r["run_id"], "total": r["total"], "passed": r["passed"],
                      "failed": r["failed"], "run_at": r["run_at"]} for r in runs],
        })
        all_modules.append({
            "module": name, "suite_type": "e2e", "file_exists": has_runs,
            "total": latest["total"], "passed": latest["passed"], "failed": latest["failed"],
            "cases": latest["cases"], "run_at": latest["run_at"],
        })
        e2e_total  += latest["total"]
        e2e_passed += latest["passed"]
        e2e_failed += latest["failed"]
        if latest["run_at"] and (e2e_run_at is None or latest["run_at"] > e2e_run_at):
            e2e_run_at = latest["run_at"]

    suite_summary["e2e"] = {
        "total": e2e_total, "passed": e2e_passed, "failed": e2e_failed,
        "run_at": e2e_run_at, "module_count": len(_E2E_SUITE_NAMES),
        "file_exists": e2e_total > 0,
    }

    for suite_type in ("unit", "integration", "chrome-extension"):
        st_dir     = _RELEASE_ROOT / "test-results" / suite_type
        latest_xml = _latest_xml(st_dir)
        has_runs   = latest_xml is not None

        if has_runs:
            latest = _parse_junit_grouped(latest_xml)
            any_file_found = True
        else:
            latest = {"total": 0, "passed": 0, "failed": 0, "modules": {}, "run_at": None}

        runs = _history_runs(st_dir)
        for mod_name, mod_data in latest.get("modules", {}).items():
            all_modules.append({
                "module": mod_name, "suite_type": suite_type, "file_exists": has_runs,
                "total": mod_data["total"], "passed": mod_data["passed"], "failed": mod_data["failed"],
                "cases": mod_data["cases"], "run_at": latest["run_at"],
            })
        suite_summary[suite_type] = {
            "total": latest["total"], "passed": latest["passed"], "failed": latest["failed"],
            "run_at": latest["run_at"], "module_count": len(latest.get("modules", {})),
            "file_exists": has_runs,
            "runs": [{"run_id": r["run_id"], "total": r["total"], "passed": r["passed"],
                      "failed": r["failed"], "run_at": r.get("run_at")} for r in runs],
        }

    total  = sum(s["total"]  for s in suite_summary.values())
    passed = sum(s["passed"] for s in suite_summary.values())
    failed = sum(s["failed"] for s in suite_summary.values())

    return {
        "data_available": any_file_found,
        "total": total, "passed": passed, "failed": failed,
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
        "suite_summary": suite_summary,
        "modules": all_modules,
        "suites": suites,
    }


# ── GET /api/v1/shap ──────────────────────────────────────────────────────────

@router.get("/shap", summary="SHAP feature importance for the active model")
def shap_values() -> list[dict[str, Any]]:
    """Static representative SHAP scores. Replace with live inference in v2."""
    return [
        {"feature": "RSI_14",         "Overall": 0.1820, "Cash (0%)": 0.0921, "Half (50%)": 0.0412, "Full (100%)": 0.0487},
        {"feature": "MACD",           "Overall": 0.1570, "Cash (0%)": 0.0334, "Half (50%)": 0.0498, "Full (100%)": 0.0738},
        {"feature": "EMA_13",         "Overall": 0.1430, "Cash (0%)": 0.0287, "Half (50%)": 0.0441, "Full (100%)": 0.0702},
        {"feature": "BB_PctB",        "Overall": 0.1280, "Cash (0%)": 0.0712, "Half (50%)": 0.0312, "Full (100%)": 0.0256},
        {"feature": "ATR_14",         "Overall": 0.1140, "Cash (0%)": 0.0634, "Half (50%)": 0.0298, "Full (100%)": 0.0208},
        {"feature": "EMA_5",          "Overall": 0.0980, "Cash (0%)": 0.0198, "Half (50%)": 0.0312, "Full (100%)": 0.0470},
        {"feature": "EMA_26",         "Overall": 0.0890, "Cash (0%)": 0.0178, "Half (50%)": 0.0289, "Full (100%)": 0.0423},
        {"feature": "Volume",         "Overall": 0.0530, "Cash (0%)": 0.0189, "Half (50%)": 0.0198, "Full (100%)": 0.0143},
        {"feature": "Price_Momentum", "Overall": 0.0360, "Cash (0%)": 0.0071, "Half (50%)": 0.0099, "Full (100%)": 0.0190},
    ]


# ── GET /api/v1/data-understanding ────────────────────────────────────────────

@router.get("/data-understanding", summary="Statistical analysis and clustering for an instrument")
def get_data_understanding(instrument_id: str) -> dict[str, Any]:
    """Full data understanding payload for the DS dashboard."""
    from rita.core.data_understanding import compute_understanding
    return compute_understanding(instrument_id)
