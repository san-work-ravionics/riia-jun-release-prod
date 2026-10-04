"""F40 Phase 3 — QA additions for GET /api/v1/experience/fno/position-value.

Edge cases beyond the engineer suite: fractional/odd shares, whitespace instrument, months
bounds, override validation, duplicate holdings, partial months, stale price, mixed currency
(no conversion), user isolation, auth, and the JS<->schema contract (programmatic).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from rita.auth import get_current_user
from rita.main import app
from rita.models.market_data import MarketDataCacheModel
from rita.models.user import UserModel
from rita.models.user_portfolio import UserPortfolioModel
from rita.models.user_portfolio_key import UserPortfolioKeyModel
from rita.schemas.position_value import (
    PositionValueBands,
    PositionValueDaily,
    PositionValueItem,
)

URL = "/api/v1/experience/fno/position-value"
END = date(2026, 9, 30)
_ROOT = Path(__file__).resolve().parents[2]
_FNO = _ROOT / "dashboard" / "js" / "fno"


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _as(user_id="u1"):
    app.dependency_overrides[get_current_user] = lambda: UserModel(id=user_id, can_access_ops=False)


def _seed_closes(db, und, n_days=420, end=END, last_close=50.0, step=1):
    """n_days calendar days ending at ``end`` (every ``step``-th day kept)."""
    for i in range(n_days):
        if (n_days - 1 - i) % step:
            continue
        d = end - timedelta(days=n_days - 1 - i)
        close = last_close + (0.0 if i == n_days - 1 else (1.0 if i % 2 else -1.0) + (i % 7) * 0.1)
        db.add(MarketDataCacheModel(
            cache_id=f"{und}-{i}", date=d, underlying=und, open=close, high=close, low=close,
            close=close, recorded_at=datetime(2026, 9, 30),
        ))
    db.commit()


def _seed_portfolio(db, holdings, key_id="k1", user_id="u1"):
    db.add(UserPortfolioKeyModel(key_id=key_id, user_id=user_id))
    db.add(UserPortfolioModel(
        portfolio_id="p-" + key_id, key_id=key_id, name="t", is_active=True,
        total_value_eur=10000.0, holdings=holdings,
    ))
    db.commit()


def _one(client, **params):
    r = client.get(URL, params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def _hold(shares, iid="ASML"):
    return [{"instrument_id": iid, "allocation_pct": 100.0, "shares": shares}]


# (a) shares edge cases ------------------------------------------------------
class TestSharesEdges:
    @pytest.mark.parametrize("shares,status", [
        (0, "no_shares"), (-3, "no_shares"), (None, "no_shares"),
        ("10", "no_shares"), ("abc", "no_shares"), (True, "no_shares"),
    ])
    def test_non_numeric_or_non_positive(self, client, db_session, shares, status):
        _seed_portfolio(db_session, _hold(shares))
        _seed_closes(db_session, "ASML")
        _as()
        it = _one(client, instrument="ASML")
        assert it["status"] == status and it["candles"] == [] and it["daily"] == []

    @pytest.mark.xfail(strict=True, reason="F40P3-QA-1: fractional shares truncate to 0 and return ok")
    def test_fractional_half_share_should_be_no_shares(self, client, db_session):
        _seed_portfolio(db_session, _hold(0.5))
        _seed_closes(db_session, "ASML")
        _as()
        it = _one(client, instrument="ASML")
        # Expected per design (null/<=0 -> no_shares); actual: int(0.5)=0 -> ok, all-zero series.
        assert it["status"] == "no_shares"

    def test_fractional_above_one_truncates(self, client, db_session):
        """Documented behaviour: 2.7 shares are truncated to 2 (advisory, not asserted as correct)."""
        _seed_portfolio(db_session, _hold(2.7))
        _seed_closes(db_session, "ASML", last_close=50.0)
        _as()
        it = _one(client, instrument="ASML")
        assert it["status"] == "ok" and it["shares"] == 2 and it["last_value"] == 100.0


# (b) whitespace instrument --------------------------------------------------
def test_whitespace_instrument_pinned(client, db_session):
    """Pinned (advisory 2): '  ' is not treated as omitted; returns one no_holding item, empty id."""
    _seed_portfolio(db_session, _hold(5))
    _as()
    items = client.get(URL, params={"instrument": "  "}).json()["items"]
    assert len(items) == 1 and items[0]["status"] == "no_holding" and items[0]["instrument_id"] == ""


# (c)(d) bounds --------------------------------------------------------------
class TestBounds:
    @pytest.mark.parametrize("m,code", [(0, 422), (1, 200), (36, 200), (37, 422)])
    def test_months_bounds(self, client, db_session, m, code):
        _seed_portfolio(db_session, _hold(5))
        _seed_closes(db_session, "ASML", n_days=1100)
        _as()
        assert client.get(URL, params={"instrument": "ASML", "months": m}).status_code == code

    def test_months_1_is_insufficient_data(self, client, db_session):
        _seed_portfolio(db_session, _hold(5))
        _seed_closes(db_session, "ASML")
        _as()
        assert _one(client, instrument="ASML", months=1)["status"] == "insufficient_data"

    def test_months_36_yields_up_to_36_candles(self, client, db_session):
        _seed_portfolio(db_session, _hold(5))
        _seed_closes(db_session, "ASML", n_days=1200)
        _as()
        it = _one(client, instrument="ASML", months=36)
        assert it["status"] == "ok" and len(it["candles"]) == 36

    @pytest.mark.parametrize("v", [0, -0.1, -50])
    def test_override_non_positive_422(self, client, v):
        _as()
        assert client.get(URL, params={"ann_vol_pct": v}).status_code == 422

    def test_override_non_numeric_422(self, client):
        _as()
        assert client.get(URL, params={"ann_vol_pct": "abc"}).status_code == 422


# (e) duplicates -------------------------------------------------------------
class TestDuplicates:
    def test_first_row_wins_even_if_first_has_no_shares(self, client, db_session):
        _seed_portfolio(db_session, [
            {"instrument_id": "ASML", "allocation_pct": 50.0, "shares": None},
            {"instrument_id": "ASML", "allocation_pct": 50.0, "shares": 40},
        ])
        _seed_closes(db_session, "ASML")
        _as()
        assert _one(client, instrument="ASML")["status"] == "no_shares"

    def test_all_holdings_dedupes_ids_and_case(self, client, db_session):
        _seed_portfolio(db_session, [
            {"instrument_id": "ASML", "allocation_pct": 50.0, "shares": 10},
            {"instrument_id": "asml", "allocation_pct": 50.0, "shares": 99},
        ])
        _seed_closes(db_session, "ASML")
        _as()
        items = client.get(URL).json()["items"]
        assert len(items) == 1 and items[0]["shares"] == 10


# (f) partial months / stale price ------------------------------------------
class TestPartialAndStale:
    def test_partial_first_and_last_month(self, client, db_session):
        _seed_portfolio(db_session, _hold(10))
        # data only on 2026-01-20 .. 2026-03-05 (partial Jan, full Feb, partial Mar)
        end = date(2026, 3, 5)
        n = (end - date(2026, 1, 20)).days + 1
        _seed_closes(db_session, "ASML", n_days=n, end=end, last_close=60.0)
        _as()
        it = _one(client, instrument="ASML", months=12)
        assert it["status"] == "ok"
        assert [c["month"] for c in it["candles"]] == ["2026-01", "2026-02", "2026-03"]
        assert it["daily"][0]["date"] == "2026-01-20" and it["daily"][-1]["date"] == "2026-03-05"
        assert it["candles"][-1]["close"] == 600.0
        assert it["bands"] is not None  # 45 closes >= 30 -> bands computed
        assert it["bands"]["anchor_value"] == 600.0 and it["bands"]["anchor_date"] == "2026-03-05"

    def test_stale_latest_price_window_anchored_to_latest_row(self, client, db_session):
        _seed_portfolio(db_session, _hold(3))
        _seed_closes(db_session, "ASML", n_days=200, end=date(2025, 6, 30), last_close=70.0)
        _as()
        it = _one(client, instrument="ASML", months=3)
        assert it["status"] == "ok"
        assert it["daily"][0]["date"] >= "2025-04-01" and it["daily"][-1]["date"] == "2025-06-30"
        assert it["bands"]["anchor_date"] == "2025-06-30"
        assert [c["month"] for c in it["candles"]] == ["2025-04", "2025-05", "2025-06"]


# (g) mixed currency ---------------------------------------------------------
def test_mixed_currency_no_conversion(client, db_session):
    _seed_portfolio(db_session, [
        {"instrument_id": "ASML", "allocation_pct": 50.0, "shares": 10},
        {"instrument_id": "RELIANCE", "allocation_pct": 50.0, "shares": 10},
    ])
    _seed_closes(db_session, "ASML", last_close=100.0)
    _seed_closes(db_session, "RELIANCE", last_close=100.0)
    _as()
    by = {i["instrument_id"]: i for i in client.get(URL).json()["items"]}
    assert (by["ASML"]["currency"], by["ASML"]["currency_symbol"]) == ("EUR", "€")
    assert (by["RELIANCE"]["currency"], by["RELIANCE"]["currency_symbol"]) == ("INR", "₹")
    # identical shares x close -> identical values; no FX applied to either
    assert by["ASML"]["last_value"] == by["RELIANCE"]["last_value"] == 1000.0
    assert by["ASML"]["daily"] == by["RELIANCE"]["daily"]


# (h)(i) isolation / auth ----------------------------------------------------
class TestIsolationAuth:
    def test_other_users_portfolio_not_visible(self, client, db_session):
        _seed_portfolio(db_session, _hold(10, "ASML"), key_id="k1", user_id="u1")
        _seed_portfolio(db_session, _hold(7, "RELIANCE"), key_id="k2", user_id="u2")
        _seed_closes(db_session, "ASML")
        _seed_closes(db_session, "RELIANCE", last_close=2500.0)
        _as("u2")
        items = client.get(URL).json()["items"]
        assert [i["instrument_id"] for i in items] == ["RELIANCE"]
        assert _one(client, instrument="ASML")["status"] == "no_holding"
        _as("u1")
        assert [i["instrument_id"] for i in client.get(URL).json()["items"]] == ["ASML"]

    def test_unauthenticated_401(self, client):
        assert client.get(URL).status_code == 401


# (j) JS contract ------------------------------------------------------------
_JS_SRC = (_FNO / "hedge-position-value.js").read_text(encoding="utf-8")
_JS_SRC_NOCOMMENT = re.sub(r"//.*", "", _JS_SRC)


class TestJsContract:
    def test_every_field_js_reads_exists_in_schema(self):
        item_fields = set(PositionValueItem.model_fields)
        band_fields = set(PositionValueBands.model_fields)
        daily_fields = set(PositionValueDaily.model_fields)
        # header comment enumerates the contract; code reads are checked via regexes
        read_item = set(re.findall(r"\bitem\??\.([a-z_0-9]+)", _JS_SRC_NOCOMMENT))
        read_bands = set(re.findall(r"\bb\.([a-z_0-9]+)", _JS_SRC_NOCOMMENT))
        read_daily = set(re.findall(r"\bd\.([a-z_0-9]+)", _JS_SRC_NOCOMMENT))
        # `item.daily.map`/`.length` etc. are JS builtins, not fields
        read_item -= {"length"}
        assert read_item and read_item <= item_fields, read_item - item_fields
        assert read_bands and read_bands <= band_fields, read_bands - band_fields
        assert read_daily <= daily_fields | {"toLocaleString"}, read_daily
        assert {"date", "value"} <= read_daily
        # header documents the same bands fields
        for f in ("plus_1sigma_value", "minus_1sigma_value", "plus_1sigma_pct", "minus_1sigma_pct"):
            assert f in band_fields and f in _JS_SRC

    @pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
    def test_node_build_monthly_candles_equals_server_candles(self, client, db_session, tmp_path):
        _seed_portfolio(db_session, _hold(13))
        _seed_closes(db_session, "ASML", n_days=500, last_close=88.0)
        _as()
        item = _one(client, instrument="ASML", ann_vol_pct=24)
        assert item["status"] == "ok" and len(item["candles"]) >= 12
        js = tmp_path / "js"
        shutil.copytree(_ROOT / "dashboard" / "js", js)
        (js / "package.json").write_text('{"type":"module"}', encoding="utf-8")
        (tmp_path / "item.json").write_text(json.dumps(item), encoding="utf-8")
        script = tmp_path / "run.mjs"
        script.write_text(
            "import fs from 'node:fs'; import { pathToFileURL } from 'node:url';\n"
            "const hc = await import(pathToFileURL(process.argv[2] + '/fno/hedge-charts.js').href);\n"
            "const it = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));\n"
            "const b = hc.buildMonthlyCandles(it.daily.map((d) => ({ date: d.date, price: d.value })));\n"
            "console.log(JSON.stringify({ keys: b.monthKeys, candles: b.candles }));\n",
            encoding="utf-8")
        out = subprocess.run(["node", str(script), str(js), str(tmp_path / "item.json")],
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr[-2000:]
        got = json.loads(out.stdout.strip().splitlines()[-1])
        assert got["keys"] == [c["month"] for c in item["candles"]]
        for g, s in zip(got["candles"], item["candles"]):
            assert (g["o"], g["h"], g["l"], g["c"]) == pytest.approx((s["open"], s["high"], s["low"], s["close"]), abs=0.01)

    def test_failure_message_string_in_js_and_workflow(self):
        assert "Position value unavailable for ${id}." in _JS_SRC
        wf = (_FNO / "hedge-workflow.js").read_text(encoding="utf-8")
        assert re.search(r"Position value unavailable for \$\{id\}\.", wf)
