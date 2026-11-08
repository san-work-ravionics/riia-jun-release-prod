"""Jarvis Chat page (RITA Market Analysis layout: key highlights, question groups, voice) and the Concepts page
built from the saved plan + saved portfolio of every region (no chat data).  Same node harness as
``test_f44_p4_js.py``: JS runs under node (skipped when node is missing); no network, no browser.
"""
from __future__ import annotations

import json
import re

import pytest

from .test_f44_p4_js import _FIXTURE, _HTML, _PRELUDE, HOSTILE, _needs_node, _node, _src

_COPY = _src("copy.js")


# ── static: the sources keep the two features apart ────────────────────────────────────────────

def test_concepts_does_not_read_chat_or_the_journey_live_view():
    s = _src("concepts.js")
    assert "messages" not in s and "live_holdings" not in s and "state.messages" not in s


def test_concepts_empty_texts_do_not_mention_chat():
    for key in ("cx.empty", "cx.empty.model", "cx.empty.engines", "cx.empty.mcp", "cx.empty.inst"):
        m = re.search(rf"'{re.escape(key)}':\s*'((?:[^'\\]|\\.)*)'", _COPY)
        assert m, key
        assert not re.search(r"chat|ask jarvis|say ", m.group(1), re.I), (key, m.group(1))


@pytest.mark.parametrize("module", ["concepts.js", "chat.js"])
def test_every_literal_copy_key_used_exists(module):
    """A missing key renders as the key itself; check the literals (several keys share a line in copy.js)."""
    used = set(re.findall(r"\bt\('([A-Za-z0-9_.]+)'", _src(module)))
    missing = sorted(k for k in used if not re.search(rf"'{re.escape(k)}'\s*:", _COPY))
    assert missing == []


def test_concepts_html_has_no_flow_intro_card_and_keeps_its_view_ids():
    html = _HTML.read_text(encoding="utf-8")
    assert "cx.flow.title" not in html and 'data-copy="cx.flow.p1"' not in html
    view = html[html.index('id="jv-view-concepts"'):html.index('id="jv-view-whatineed"')]
    assert view.index('id="jv-cx-tabs"') < view.index('id="jv-cx-panel"')
    for i in ("jv-cx-status", "jv-cx-tabs", "jv-cx-panel"):
        assert view.count(f'id="{i}"') == 1, i


# ── static: the chat page structure ────────────────────────────────────────────────────────────

def _chat_view() -> str:
    html = _HTML.read_text(encoding="utf-8")
    return html[html.index('id="jv-view-chat"'):html.index("PORTFOLIO (F44 P4c")]


def test_chat_page_order_is_highlights_then_questions_then_chat():
    v = _chat_view()
    pos = [v.index(x) for x in ('id="jv-chat-highlights"', 'id="sec-jv-questions"', 'id="sec-jv-chat"')]
    assert pos == sorted(pos)
    assert v.index('id="jv-chat-groups"') > v.index('id="sec-jv-questions"')
    assert v.index('id="jv-chat-groups"') < v.index('id="sec-jv-chat"')            # groups sit in the left panel


def test_chat_page_voice_controls_sit_in_the_chat_panel():
    v = _chat_view()
    chat_panel = v[v.index('id="sec-jv-chat"'):]
    form = chat_panel[chat_panel.index('<form id="jv-chat-form"'):chat_panel.index("</form>")]
    assert 'id="jv-chat-mic"' in form and 'type="button"' in form[form.index('id="jv-chat-mic"'):][:80]   # not a submit
    assert form.index('id="jv-chat-mic"') < form.index('id="jv-chat-send"')
    for i in ("jv-chat-speak", "jv-chat-voice-status"):
        assert i in chat_panel, i


def test_plan_panel_elements_are_kept_in_a_hidden_block_for_plan_js():
    """plan.js still writes into these; the chat page just no longer shows them."""
    v = _chat_view()
    block = v[v.index('<div hidden style="display:none">'):]
    for i in ("sec-jv-plan", "jv-plan-goal", "jv-plan-selection", "jv-plan-tracking", "jv-plan-proposal",
              "jv-plan-excluded", "jv-plan-method", "jv-plan-empty"):
        assert f'id="{i}"' in block, i
        assert v.count(f'id="{i}"') == 1, i


def test_chat_question_groups_offer_exactly_the_eight_questions():
    """The left panel offers exactly the eight saved-data questions, each with a copy text."""
    keys = re.findall(r"qs:\s*\[([^\]]*)\]", _src("chat.js"))
    questions = {q.strip().strip("'") for grp in keys for q in grp.split(",") if q.strip()}
    assert questions == {"goal", "build", "why", "closest", "track", "doing", "stop", "protect"}
    for q in questions:
        assert re.search(rf"'chat\.q\.{q}'\s*:", _COPY), q


# ── key highlights ─────────────────────────────────────────────────────────────────────────────

@_needs_node
def test_highlights_show_the_saved_plan_and_this_years_return():
    fx = json.dumps(_FIXTURE)
    r = _node(_PRELUDE + f"""
const FX = {fx};
const chat = await import(base + 'jarvis/chat.js?v=3');
const fmt = await import(base + 'jarvis/format.js?v=3');
const {{ COPY }} = await import(base + 'jarvis/copy.js?v=3');
const clone = o => JSON.parse(JSON.stringify(o));
const pf = clone(FX.A5_portfolio);
const up = clone(pf); up.perf.ytd_return = 0.031;
const down = clone(pf); down.perf.ytd_return = -0.02;
const none = clone(pf); none.perf.ytd_return = null; none.perf.target_to_date = null;
const g = FX.A4_state.goal;
const noPlan = clone(FX.A4_state); noPlan.journey = null; noPlan.goal = {{ ...noPlan.goal, saved: false, goal_return: null }};
const hostile = clone(FX.A4_state); hostile.journey.currency = {json.dumps(HOSTILE)};
const count = h => (h.match(/class="kpi kpi-sm"/g) || []).length;
console.log(JSON.stringify({{
  up: chat.highlightsHtml(FX.A4_state, up, 'europe'), down: chat.highlightsHtml(FX.A4_state, down, 'europe'),
  none: chat.highlightsHtml(FX.A4_state, none, 'europe'), noPf: chat.highlightsHtml(FX.A4_state, null, 'india'),
  noPlan: chat.highlightsHtml(noPlan, null, 'us'), nothing: chat.highlightsHtml(null, null, 'europe'),
  hostile: chat.highlightsHtml(hostile, up, 'europe'),
  rate: fmt.fmtRate(g.goal_return), ytd: fmt.fmtRate(0.031), years: fmt.fmtYears(g.horizon_years),
  money: fmt.fmtMoney(g.goal_value, g.currency), noPlanText: COPY['hl.no_plan'],
  counts: [chat.highlightsHtml(FX.A4_state, up, 'europe'), chat.highlightsHtml(null, null, 'us')].map(count) }}));""")
    up = r["up"]
    assert r["counts"] == [8, 8]                                         # the strip never changes shape
    assert "Europe" in up and r["rate"] in up and r["years"] in up and r["money"] in up and r["ytd"] in up
    assert 'kpi-value pos' in up and 'kpi-value neg' in r["down"]        # sign colouring of this year's return
    assert "kpi-value pos" not in r["none"] and "kpi-value neg" not in r["none"]   # unknown return: neutral dash
    assert "India" in r["noPf"] and r["rate"] in r["noPf"]               # plan shown even before A5 has loaded
    assert r["noPlanText"] in r["noPlan"] and "US" in r["noPlan"]        # no saved plan: said plainly
    assert "<img" not in r["hostile"]                                    # server strings go through esc()


# ── question groups ────────────────────────────────────────────────────────────────────────────

@_needs_node
def test_question_groups_render_every_group_and_question():
    r = _node(_PRELUDE + """
const chat = await import(base + 'jarvis/chat.js?v=3');
const { COPY } = await import(base + 'jarvis/copy.js?v=3');
const html = chat.groupsHtml();
console.log(JSON.stringify({
  groups: (html.match(/class="phase-group"/g) || []).length,
  qs: [...html.matchAll(/data-q="([a-z]+)"/g)].map(m => m[1]),
  titles: chat.QUESTION_GROUPS.map(g => COPY[`chat.${g.key}`]),
  texts: chat.QUESTION_GROUPS.flatMap(g => g.qs).map(q => COPY[`chat.q.${q}`]),
  html }));""")
    assert r["groups"] == 4
    assert r["qs"] == ["goal", "build", "why", "closest", "track", "doing", "stop", "protect"]
    assert all(r["titles"]) and all(r["texts"])
    assert all(t in r["html"] for t in r["titles"] + r["texts"])


# ── voice ──────────────────────────────────────────────────────────────────────────────────────

_VOICE_STUB = """
const els = {};
const mk = () => ({ listeners: {}, attrs: {}, value: '', checked: false, disabled: false, title: '', textContent: '',
  classList: { set: new Set(), toggle(n, on) { on ? this.set.add(n) : this.set.delete(n); } },
  setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(ev, fn) { (this.listeners[ev] ||= []).push(fn); } });
document.getElementById = id => (els[id] ||= mk());
Object.defineProperty(globalThis, 'navigator', { value: { language: 'en-GB' }, configurable: true });
"""


@_needs_node
def test_voice_is_disabled_with_a_reason_when_the_browser_has_no_speech_recognition():
    r = _node(_PRELUDE + _VOICE_STUB + """
const chat = await import(base + 'jarvis/chat.js?v=3');
const { COPY } = await import(base + 'jarvis/copy.js?v=3');
chat.initVoice(() => {});
console.log(JSON.stringify({ disabled: els['jv-chat-mic'].disabled,
  title: els['jv-chat-mic'].title === COPY['voice.unsupported'], clicks: (els['jv-chat-mic'].listeners.click || []).length }));""")
    assert r == {"disabled": True, "title": True, "clicks": 0}


@_needs_node
def test_voice_talk_flow_listens_shows_interim_text_and_sends_only_the_final_transcript():
    r = _node(_PRELUDE + _VOICE_STUB + """
let rec;
globalThis.SpeechRecognition = class { constructor() { rec = this; this.started = 0; this.stopped = 0; }
  start() { this.started += 1; } stop() { this.stopped += 1; } };
const chat = await import(base + 'jarvis/chat.js?v=3');
const { COPY } = await import(base + 'jarvis/copy.js?v=3');
const sent = [];
chat.initVoice(t => sent.push(t));
const mic = els['jv-chat-mic'], inp = els['jv-chat-input'], status = els['jv-chat-voice-status'];
const click = () => mic.listeners.click[0]();
const result = (text, isFinal) => rec.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: text }], { isFinal })] });
const log = {};
log.lang = rec.lang; log.interim = rec.interimResults; log.continuous = rec.continuous;
click();
log.listening = [mic.classList.set.has('is-listening'), mic.attrs['aria-pressed'], status.textContent === COPY['voice.listening'], rec.started];
result('use my', false);
log.interimShown = [inp.value, sent.length];
result('use my goal', true);
log.final = [inp.value, sent.slice()];
rec.onend();
log.ended = [mic.classList.set.has('is-listening'), mic.attrs['aria-pressed'], status.textContent];
click(); click();                                                     // start, then stop while listening
log.stopped = rec.stopped;
rec.onerror({ error: 'no-speech' });
log.noSpeech = status.textContent;
rec.onerror({ error: 'aborted' });
log.aborted = status.textContent;
rec.onerror({ error: 'not-allowed' });
log.denied = status.textContent;
log.deniedClass = mic.classList.set.has('is-listening');
console.log(JSON.stringify(log));""")
    assert r["lang"] == "en-GB" and r["interim"] is True and r["continuous"] is False
    assert r["listening"] == [True, "true", True, 1]
    assert r["interimShown"] == ["use my", 0]                           # interim text goes in the box, nothing sent
    assert r["final"] == ["", ["use my goal"]]                          # final: box cleared, sent exactly once
    assert r["ended"] == [False, "false", ""]
    assert r["stopped"] == 1
    assert r["noSpeech"] == "" and r["aborted"] == ""                   # silence / cancel are not errors
    assert "not-allowed" in r["denied"] and r["deniedClass"] is False


@_needs_node
def test_spoken_replies_follow_the_checkbox_and_cancel_earlier_speech():
    r = _node(_PRELUDE + _VOICE_STUB + """
globalThis.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
const spoken = []; let cancelled = 0;
globalThis.speechSynthesis = { cancel() { cancelled += 1; }, speak(u) { spoken.push([u.text, u.lang]); } };
const chat = await import(base + 'jarvis/chat.js?v=3');
chat.initVoice(() => {});
const spk = els['jv-chat-speak'];
const log = {};
chat.speakReply('off by default');
log.offByDefault = spoken.length;
spk.checked = true; spk.listeners.change[0]();
chat.speakReply('hello');
log.on = [spoken.slice(), cancelled >= 1];
chat.speakReply('');                                                  // nothing to say
log.empty = spoken.length;
const before = cancelled;
spk.checked = false; spk.listeners.change[0]();
chat.speakReply('muted');
log.off = [spoken.length, cancelled > before];                        // turning it off also stops current speech
console.log(JSON.stringify(log));""")
    assert r["offByDefault"] == 0
    assert r["on"] == [[["hello", "en-GB"]], True]
    assert r["empty"] == 1
    assert r["off"] == [1, True]


@_needs_node
def test_speak_reply_is_a_no_op_without_speech_synthesis():
    r = _node(_PRELUDE + """
const chat = await import(base + 'jarvis/chat.js?v=3');
chat.speakReply('hello');
console.log(JSON.stringify({ ok: true }));""")
    assert r == {"ok": True}


# ── Concepts: saved plan + saved portfolio of every region ─────────────────────────────────────

_CX_PRELUDE = _PRELUDE + """
const cx = await import(base + 'jarvis/concepts.js?v=3');
const { COPY } = await import(base + 'jarvis/copy.js?v=3');
const clone = o => JSON.parse(JSON.stringify(o));
"""


@_needs_node
def test_concepts_panels_use_every_regions_saved_portfolio_not_just_the_current_one():
    fx = json.dumps(_FIXTURE)
    r = _node(_CX_PRELUDE + f"""
const FX = {fx};
const row = (id, extra = {{}}) => ({{ ...clone(FX.A5_portfolio.instruments[0]), instrument_id: id, ...extra }});
const pfFor = (loc, ids) => ({{ ...clone(FX.A5_portfolio), location: loc, instruments: ids.map(i => row(i)) }});
const state = clone(FX.A4_state);
const has = (step, data) => (cx.panelHtml(step, data).match(/<canvas/g) || []).length;
const onlyOtherRegions = {{ state, pf: null, pfs: {{ india: pfFor('india', ['NIFTY']), us: pfFor('us', ['DJI']) }} }};
const nothing = {{ state, pf: null, pfs: {{}} }};
const unheld = {{ state, pf: null, pfs: {{ europe: {{ ...clone(FX.A5_portfolio), perf: null, instruments: [row('E1', {{ held: false, selected: false }})] }} }} }};
console.log(JSON.stringify({{
  s4Other: has('s4', onlyOtherRegions), s3bOther: has('s3', onlyOtherRegions),
  s4None: has('s4', nothing), s4Unheld: has('s4', unheld),
  fallbackToPf: has('s4', {{ state, pf: clone(FX.A5_portfolio) }}) }}));""")
    assert r["s4Other"] == 2                  # allocation chart (India + US rows) and the per-region return chart
    assert r["s3bOther"] == 1                 # invested-now bar comes from those rows too (no instrument opened)
    assert r["s4None"] == 0 and r["s4Unheld"] == 0                       # rows that are neither held nor picked don't count
    assert r["fallbackToPf"] == 2                                        # a lone pf (no pfs map) feeds both charts


@_needs_node
def test_concepts_say_why_a_model_panel_is_empty_instead_of_telling_the_user_to_use_chat():
    fx = json.dumps(_FIXTURE)
    r = _node(_CX_PRELUDE + f"""
const FX = {fx};
const noModel = clone(FX.A5_portfolio);
noModel.instruments = noModel.instruments.map(i => ({{ ...i, invested_fraction: null, sl_distance: null, sl_hit: null,
                                                      model_action: null, engines_available: ['fno'] }}));
noModel.engines = noModel.engines.map(e => ({{ ...e, return_since: null }}));                  // coverage stays
const noRita = clone(FX.A6_instrument); noRita.engines = noRita.engines.filter(e => e.engine !== 'rita');
const data = {{ state: FX.A4_state, pf: noModel, pfs: {{ europe: noModel }}, inst: noRita }};
const notes = h => [...h.matchAll(/<div class="cx-empty">([^<]*)</g)].map(m => m[1]);   // text up to the closing tag
const empties = Object.fromEntries(['s3', 's5', 's7'].map(s => [s, notes(cx.panelHtml(s, data))]));
console.log(JSON.stringify({{ empties, model: COPY['cx.empty.model'], engines: COPY['cx.empty.engines'], inst: COPY['cx.empty.inst'],
  noInst: notes(cx.panelHtml('s3', {{ state: FX.A4_state, pf: noModel, pfs: {{ europe: noModel }} }})) }}));""")
    assert r["empties"]["s3"] == [r["model"], r["model"]]               # sleeve chart (instrument opened) + invested-now
    assert r["empties"]["s5"] == [r["model"]]                           # price chart; the stop-loss panel falls back to returns
    assert r["empties"]["s7"] == [r["engines"]]                         # return chart empty; the coverage chart still draws
    assert r["inst"] in r["noInst"]                                     # nothing opened yet: say so
    for notes in r["empties"].values():                                 # the empty notes never send the user to the chat
        assert not any(re.search(r"ask jarvis|use my goal|track it|chat", n, re.I) for n in notes)


@_needs_node
def test_concepts_stop_loss_panel_falls_back_to_return_since_saved_and_says_so():
    fx = json.dumps(_FIXTURE)
    r = _node(_CX_PRELUDE + f"""
const FX = {fx};
const withSl = clone(FX.A5_portfolio);
const noSl = clone(FX.A5_portfolio);
noSl.instruments = noSl.instruments.map(i => ({{ ...i, sl_distance: null, sl_hit: null }}));
const empty = clone(FX.A5_portfolio);
empty.instruments = empty.instruments.map(i => ({{ ...i, sl_distance: null, ret: null }}));
const title = pf => {{ const h = cx.panelHtml('s5', {{ state: FX.A4_state, pf, pfs: {{ europe: pf }}, inst: FX.A6_instrument }});
                      return [h.includes(COPY['cx.s5.c1']), h.includes(COPY['cx.s5.c1alt']), (h.match(/jv-cx-s5a/g) || []).length]; }};
console.log(JSON.stringify({{ withSl: title(withSl), noSl: title(noSl), empty: title(empty) }}));""")
    assert r["withSl"] == [True, False, 1]          # stop-loss distance when a model view exists
    assert r["noSl"] == [False, True, 1]            # else the return since saved, titled as such
    assert r["empty"][2] == 0                       # neither: empty note, no canvas


@_needs_node
def test_concepts_mcp_stage_loading_empty_and_rows():
    """Stage 8 (modules and MCP): a chart of calls by tool and the most recent calls, from the MCP call log."""
    fx = json.dumps(_FIXTURE)
    r = _node(_CX_PRELUDE + f"""
const FX = {fx};
const base_ = {{ state: FX.A4_state, pf: FX.A5_portfolio, pfs: {{ europe: FX.A5_portfolio }}, inst: FX.A6_instrument }};
const rows = Array.from({{ length: 15 }}, (_, i) => ({{ timestamp: `2026-11-08T10:00:${{String(i).padStart(2, '0')}}.123456`, tool_name: `tool.${{i}}`, status: 'ok' }}));
const p = mcp => cx.panelHtml('s8', {{ ...base_, mcp }});
const canvases = h => (h.match(/<canvas/g) || []).length;
console.log(JSON.stringify({{
  loading: p(null), none: p([]), rows: p(rows), canvasRows: canvases(p(rows)), canvasLoading: canvases(p(null)),
  loadingText: COPY['cx.loading'], emptyText: COPY['cx.empty.mcp'], wraps: (p(rows).match(/chart-wrap/g) || []).length }}));""")
    assert r["loadingText"] in r["loading"] and r["emptyText"] in r["none"]
    assert r["loading"].count(r["loadingText"]) == 2 and r["none"].count(r["emptyText"]) == 2   # chart + table panels
    assert r["wraps"] == 3
    assert r["canvasRows"] == 1 and r["canvasLoading"] == 0                 # the chart needs rows
    rows = r["rows"]
    assert len(re.findall(r"tool\.\d+", rows)) == 12                     # the 12 most recent calls, no more
    assert "tool.0" in rows and "tool.11" in rows and "tool.12" not in rows
    assert "2026-11-08T10:00:00" in rows and ".123456" not in rows         # timestamp trimmed to the second
    assert "whatineed.get_goal" in rows and "portfolio.pnl" in rows        # the module table is always there


@_needs_node
def test_concepts_data_stage_lists_the_pipeline_and_the_users_latest_data():
    fx = json.dumps(_FIXTURE)
    r = _node(_CX_PRELUDE + f"""
const FX = {fx};
const fmt = await import(base + 'jarvis/format.js?v=3');
const row = (id, loc, close) => ({{ ...clone(FX.A5_portfolio.instruments[0]), instrument_id: id, last_close: close }});
const pf = (loc, asOf, rows) => ({{ ...clone(FX.A5_portfolio), location: loc, as_of: asOf, instruments: rows }});
const pfs = {{ europe: pf('europe', '2026-11-06', [row('ASML', 'europe', 1283.6)]), india: pf('india', '2026-11-08', [row('NIFTY', 'india', 24986.4)]) }};
const hostile = {{ europe: pf('europe', '2026-11-06', [row({json.dumps(HOSTILE)}, 'europe', 1)]) }};
const noClose = {{ europe: pf('europe', '2026-11-06', [row('X', 'europe', null)]) }};
const html = d => cx.panelHtml('s2', {{ state: FX.A4_state, ...d }});
console.log(JSON.stringify({{ two: html({{ pf: null, pfs }}), single: html({{ pf: pf('us', '2026-11-06', [row('DJI', 'us', 51285.73)]) }}),
  empty: html({{ pf: null, pfs: {{}} }}), hostile: html({{ pf: null, pfs: hostile }}), noClose: html({{ pf: null, pfs: noClose }}),
  asml: fmt.fmtNum(1283.6), nifty: fmt.fmtNum(24986.4), dji: fmt.fmtNum(51285.73), d1: fmt.fmtDate('2026-11-06'), d2: fmt.fmtDate('2026-11-08'),
  stage: COPY['cx.s2.col.stage'], empties: COPY['cx.empty'] }}));""")
    two = r["two"]
    for stage in ("Daily prices", "Returns", "Indicators", "Regions", "FX rates"):
        assert stage in two, stage                                           # the pipeline table is always shown
    assert "ASML" in two and "Europe" in two and r["asml"] in two and r["d1"] in two
    assert "NIFTY" in two and "India" in two and r["nifty"] in two and r["d2"] in two   # every region, not just one
    assert "DJI" in r["single"] and "US" in r["single"] and r["dji"] in r["single"]      # a lone portfolio still works
    assert r["empties"] in r["empty"] and "<td" not in r["empty"].split("cx-empty")[-1]    # no rows → the empty note
    assert "<img" not in r["hostile"]
    assert r["empties"] in r["noClose"] and "<td>X</td>" not in r["noClose"]            # no price → no row, the empty note
    assert "<canvas" not in two                                              # this stage is tables only


def test_concepts_text_is_about_the_flow_not_the_chat():
    """Concepts explains the data-science and AI concepts of the Jarvis flow; it is not the chat's help page."""
    assert "INTENT_TOOLS" not in _src("concepts.js") and "intent" not in _src("concepts.js").lower()
    cx_lines = [ln for ln in _COPY.splitlines() if re.match(r"\s*'cx\.", ln)]
    assert len(cx_lines) > 60
    for ln in cx_lines:
        assert not re.search(r"minilm|intent|\bchat\b|\bsay \"|track it|use my goal|you say", ln, re.I), ln


@_needs_node
def test_concepts_goal_step_draws_a_target_path_from_the_plan_alone():
    """Step 1 no longer waits for a price path: the saved plan's return gives the target through the year."""
    fx = json.dumps(_FIXTURE)
    r = _node(_CX_PRELUDE + f"""
const FX = {fx};
const state = clone(FX.A4_state);
state.journey = null;                                                  // plan only: no journey
const noPerf = {{ state, pf: null, pfs: {{}} }};
const noPlan = clone(state); noPlan.goal = {{ ...noPlan.goal, saved: false, goal_return: null }};
console.log(JSON.stringify({{ plan: (cx.panelHtml('s1', noPerf).match(/jv-cx-s1b/g) || []).length,
                              none: (cx.panelHtml('s1', {{ state: noPlan, pf: null, pfs: {{}} }}).match(/jv-cx-s1b/g) || []).length }}));""")
    assert r["plan"] == 1 and r["none"] == 0
