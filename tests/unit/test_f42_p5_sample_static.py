"""F42 P5 - static contracts: ADR-001/002 compliance of the new modules, no file I/O in services,
config keys, delivery/deploy assumptions, DOM ids, window bindings, escaping and empty-state wiring."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from rita.config import TradeAnalysisSettings

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "rita"
SERVICE = (SRC / "services/fno_sample_service.py").read_text()
IMPORT_SVC = (SRC / "services/fno_import_service.py").read_text()
REPO_SRC = (SRC / "repositories/fno_sample_files.py").read_text()
ROUTER = (SRC / "api/v1/workflow/fno_console_import.py").read_text()
MAIN_PY = (SRC / "main.py").read_text()
JS = (ROOT / "dashboard/js/fno/trade-import.js").read_text()
JS_AN = (ROOT / "dashboard/js/fno/trade-analytics.js").read_text()
MAIN_JS = (ROOT / "dashboard/js/fno/main.js").read_text()
HTML = (ROOT / "dashboard/fno.html").read_text()

# actual file access primitives (string helpers such as os.path.basename are NOT file access)
_FILE_IO = re.compile(
    r"(?<![\w.])open\(|\bPath\(|\.read_bytes\(|\.read_text\(|\.write_(bytes|text)\(|\.is_file\(|\.exists\("
    r"|\.iterdir\(|\.glob\(|\bshutil\b|os\.(listdir|scandir|stat|walk|remove|unlink|path\.(exists|isfile|getsize))")


# ── ADR-002: no file I/O in services; the file-backed repository owns it ───────

@pytest.mark.parametrize("name,src", [("fno_sample_service.py", SERVICE), ("fno_import_service.py", IMPORT_SVC)])
def test_services_perform_no_file_io(name, src):
    assert not _FILE_IO.search(src), f"{name} must not touch the filesystem (ADR-002)"


def test_service_has_no_raw_sql_and_receives_the_repo_by_injection():
    assert "text(" not in SERVICE and "execute(" not in SERVICE and "select(" not in SERVICE
    assert re.search(r"def __init__\(self, db: Session, files: FnoSampleFileRepo\)", SERVICE)
    assert re.search(r"def __init__\(self, db: Session, sample_files: Optional\[FnoSampleFileRepo\] = None\)",
                     IMPORT_SVC)
    assert "FnoSampleService.from_settings(db)" in ROUTER
    assert "rita.repositories" not in ROUTER                          # routers never import repositories


def test_file_repo_reads_only_the_three_named_files_read_only():
    opens = re.findall(r"\.open\(([^)]*)\)", REPO_SRC)
    assert opens == ['"rb"'] or all('"rb"' in o for o in opens)
    assert not re.search(r"\.open\(\s*['\"][wa+x]", REPO_SRC)
    assert not re.search(r"write|unlink|mkdir|rename|remove", REPO_SRC)
    assert set(re.findall(r'"(tradebook|ledger|pnl)": "', REPO_SRC)) == {"tradebook", "ledger", "pnl"}
    assert "request" not in REPO_SRC.lower()                   # names are server constants, never client input


# ── ADR-001 / project rules ─────────────────────────────────────────────────────

def test_workflow_tier_second_router_without_content_length_route():
    assert re.search(r'sample_router = APIRouter\(prefix="/api/v1/workflow/fno"', ROUTER)
    block = ROUTER[ROUTER.index("sample_router = APIRouter"):ROUTER.index("\n\n", ROUTER.index("sample_router = APIRouter"))]
    assert "route_class" not in block
    assert '@sample_router.post("/console-import/sample", response_model=SampleLoadResponse)' in ROUTER
    assert re.search(r"\ndef load_sample_data\(", ROUTER)                # plain def: runs in the threadpool
    assert "Depends(get_current_user)" in ROUTER[ROUTER.index("def load_sample_data"):]
    assert "app.include_router(fno_console_import_sample_router)" in MAIN_PY
    assert "sample_files.ready" in MAIN_PY                                # startup readiness log


def test_real_upload_guard_is_before_parsing():
    up = ROUTER[ROUTER.index("async def upload_console_files"):ROUTER.index("@router.delete")]
    assert up.index("is_sample_data") < up.index("await f.read(")
    assert "status_code=409" in up and "Remove it before importing your own files." in up


def test_no_print_and_no_hardcoded_lot_sizes_in_new_modules():
    for src in (SERVICE, REPO_SRC):
        assert "print(" not in src
        assert not re.search(r"\b(75|30)\b", src)                          # lot sizes only from settings
    gen = (ROOT / "scripts/generate_fno_sample.py").read_text()
    assert "args.nifty_lot" not in gen and "required=True" in gen          # lot sizes are mandatory arguments


def test_sample_runs_cannot_be_created_through_the_upload_route():
    assert "allow_reserved" not in ROUTER
    assert "allow_reserved=True" in SERVICE


# ── config ──────────────────────────────────────────────────────────────────────

def test_config_keys_in_class_and_base_yaml():
    base = yaml.safe_load((ROOT / "config/base.yaml").read_text())["trade_analysis"]
    for k in ("sample_enabled", "sample_dir", "sample_file_prefix"):
        assert k in TradeAnalysisSettings.model_fields and k in base
    assert set(base) <= set(TradeAnalysisSettings.model_fields)           # extra="forbid"-safe
    t = TradeAnalysisSettings(**base)
    assert (t.sample_enabled, t.sample_dir, t.sample_file_prefix) == (True, "sample/fno", "SAMPLE_")


@pytest.mark.parametrize("kw", [
    {"sample_dir": ""}, {"sample_dir": "/etc"}, {"sample_dir": "../x"}, {"sample_dir": "a/../../b"},
    {"sample_dir": "C:\\x"}, {"sample_file_prefix": ""}, {"sample_file_prefix": "a/b_"},
    {"sample_file_prefix": " S_"}, {"sample_file_prefix": "x" * 40}])
def test_config_validators_reject_bad_values(kw):
    with pytest.raises(ValidationError):
        TradeAnalysisSettings(**kw)


# ── delivery assumptions (verified in the Engineer's first step) ───────────────

def test_deploy_rsync_ships_data_input_and_the_sample_is_tracked():
    wf = (ROOT / ".github/workflows/deploy.yaml").read_text()
    assert re.search(r"rsync -av --update[^\n]*\\\n(?:[^\n]*\\\n)*\s*data/input/\s*\\\n\s*ubuntu@[^\n]*:/opt/rita_input/input/", wf)
    ig = (ROOT / ".gitignore").read_text()
    assert "data/input/sample" not in ig and not re.search(r"^data/input/?\*?$", ig, re.M)
    prod = yaml.safe_load((ROOT / "config/production.yaml").read_text())
    assert prod["data"]["input_dir"] == "/app/data/input"


def test_single_process_assumption_for_the_in_process_lock():
    docker = (ROOT / "Dockerfile").read_text()
    assert "uvicorn rita.main:app" in docker and "--workers" not in docker
    assert "WEB_CONCURRENCY" not in docker


# ── frontend ────────────────────────────────────────────────────────────────────

def test_new_dom_ids_exist_in_fno_html():
    for i in ("ta-sample-banner", "ta-sample-banner-text", "ta-sample-remove-btn", "ta-sample-own-btn",
              "ta-imp-sample-card", "ta-imp-sample-btn", "ta-imp-sample-note", "ta-empty-cta", "ta-empty-cta-btn"):
        assert f'id="{i}"' in HTML, i
    ids_used = set(re.findall(r"""_(?:el|show)\('(ta-[a-z-]+)'""", JS)) | set(re.findall(r"setEl\('(ta-[a-z-]+)'", JS))
    for i in ids_used:
        assert f'id="{i}"' in HTML, i


def test_banner_is_page_level_above_the_tabs_and_not_tab_scoped():
    b = HTML.index('id="ta-sample-banner"')
    assert b < HTML.index('id="ta-tabs"')
    tag = HTML[HTML.rindex("<div", 0, b):HTML.index(">", b)]
    assert "data-ta-tab" not in tag                                        # visible on every tab
    assert HTML.index('id="ta-tabs"') - b < 1800                           # directly above the tab strip


def test_import_tab_card_precedes_the_console_card_and_cta_covers_analytics_tabs():
    imp = HTML.index('data-ta-tab="import"')
    assert imp < HTML.index('id="ta-imp-sample-card"') < HTML.index("Import Zerodha Console files")
    cta = HTML.index('id="ta-empty-cta"')
    wrapper = HTML[HTML.rindex('<div data-ta-tab=', 0, cta):cta]
    assert 'data-ta-tab="behaviour market suggestions"' in wrapper         # Behaviour + Market & P&L + Suggestions
    assert cta < HTML.index("Analytics (from your imported Console data)")
    assert "taSwitchTab('import')" in HTML[cta:cta + 700]
    assert "No data yet. Go to the Import tab to upload your Console files or load sample data." in HTML
    for panel, tab in (("ta-panel-margintrap", "behaviour"), ("ta-panel-spotpnl", "market"),
                       ("ta-panel-suggestions", "suggestions"), ("ta-panel-marketturn", "market")):
        assert re.search(rf'id="{panel}" data-ta-tab="{tab}"', HTML), panel


def test_functions_exported_bound_on_window_and_wired_in_html():
    for fn in ("taSampleLoad", "taSampleRemove"):
        assert re.search(rf"export async function {fn}\b", JS)
        assert f"window.{fn} = {fn}" in MAIN_JS
        assert fn in re.search(r"import \{[^}]*\} from './trade-import.js'", MAIN_JS).group(0)
    assert 'onclick="taSampleLoad()"' in HTML and 'onclick="taSampleRemove()"' in HTML
    own = re.search(r'id="ta-sample-own-btn" onclick="([^"]+)"', HTML).group(1)
    assert own.index("taSampleRemove()") < own.index("taSwitchTab('import')")      # remove first, then switch


def test_sample_endpoint_is_workflow_tier_and_no_system_paths():
    assert "const _SAMPLE = '/api/v1/workflow/fno/console-import/sample';" in JS
    for m in re.finditer(r"'(/api/[^']+)'", JS):
        p = m.group(1)
        assert p.startswith(("/api/v1/workflow/", "/api/v1/experience/")), p
    assert "api(_SAMPLE, 'POST')" in JS


def test_render_sample_is_null_safe_and_gates_uploads():
    fn = JS[JS.index("function _renderSample"):JS.index("function _renderStatus")]
    assert "(s && s.sample) || null" in fn and "(sm && sm.window) || null" in fn
    assert "_show('ta-sample-banner', _sampleLoaded)" in fn
    assert "_show('ta-imp-sample-card', !!(sm && sm.offer))" in fn
    assert "_show('ta-empty-cta', !(s && s.has_data))" in fn
    assert "file.disabled = _sampleLoaded" in fn
    assert "Remove the sample data to import your own files." in fn
    assert "_sampleLoaded" in JS[JS.index("function _setBusy"):JS.index("function _show")]    # upload button too
    assert "_renderSample(s);" in JS[JS.index("function _renderStatus"):JS.index("function _renderTrades")]


def test_server_text_is_escaped_before_innerhtml():
    fn = JS[JS.index("function _renderSample"):JS.index("function _renderStatus")]
    assert "_dash(w.from)" in fn and "_dash(w.to)" in fn
    assert "${w.from}" not in fn and "${w.to}" not in fn
    assert "note.textContent" in fn                                         # not innerHTML
    load = JS[JS.index("export async function taSampleLoad"):JS.index("export async function taSampleRemove")]
    assert "_esc(refused)" in load and "out.message" in load
    assert "innerHTML = res" not in JS


def test_sample_load_uses_busy_guard_and_refreshes_via_taRefresh():
    load = JS[JS.index("export async function taSampleLoad"):JS.index("export async function taSampleRemove")]
    assert "if (_busy) return;" in load and "_setBusy(true)" in load and "finally" in load and "_setBusy(false)" in load
    assert "await taRefresh()" in load
    assert "import { taRefresh } from './trade-analysis.js'" in JS
    rem = JS[JS.index("export async function taSampleRemove"):]
    assert "window.confirm('Remove the sample data?')" in rem
    assert "api(`${_UPLOAD}?confirm=true`, 'DELETE')" in rem and "return true" in rem and "return false" in rem


def test_no_data_copy_updated_in_js_and_service():
    copy = "Import your Console files on the Import tab, or load sample data there."
    assert copy in JS_AN
    svc = (SRC / "services/fno_trade_analytics_service.py").read_text()
    assert "Import your Console files on the Import tab" in svc and "load sample data there" in svc
    assert "Import panel first" not in svc and "Import panel first" not in JS_AN
