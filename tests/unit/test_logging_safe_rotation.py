"""Log rotation on Windows: a rollover that cannot rename the file (another process still has it open,
WinError 32) must not flood stderr with a traceback per record — the handler keeps writing to the current
file and retries after a back-off.  And ``configure_logging`` must not attach a second handler for a file
it already logs to (the old check compared a relative path with the handler's absolute ``baseFilename``).
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from types import SimpleNamespace

import pytest

from rita import logging_config as lc

_LINE = "x" * 80          # longer than maxBytes below, so every record wants a rollover


def _handler(tmp_path, **kw):
    h = lc._SafeRotatingFileHandler(str(tmp_path / "app.log"), maxBytes=50, backupCount=2, encoding="utf-8", **kw)
    h.setFormatter(logging.Formatter("%(message)s"))
    return h


def _logger(name: str, handler: logging.Handler) -> logging.Logger:
    log = logging.getLogger(name)
    log.handlers = [handler]
    log.propagate = False
    log.setLevel(logging.INFO)
    return log


@pytest.fixture
def errors(monkeypatch):
    """Records every call to ``Handler.handleError`` (what prints the "--- Logging error ---" traceback)."""
    seen: list = []
    monkeypatch.setattr(logging.Handler, "handleError", lambda self, record: seen.append(record))
    return seen


class _Rename:
    """Stands in for ``os.rename`` inside logging.handlers: counts calls, fails like Windows does."""

    def __init__(self, fail: bool):
        self.fail, self.calls = fail, 0

    def __call__(self, src, dst):
        self.calls += 1
        if self.fail:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        os.replace(src, dst)


def test_failed_rollover_keeps_writing_and_raises_nothing(tmp_path, monkeypatch, errors):
    rename = _Rename(fail=True)
    monkeypatch.setattr(logging.handlers.os, "rename", rename)
    h = _handler(tmp_path)
    log = _logger("t.rotation.fail", h)
    for i in range(5):
        log.info("%s-%d", _LINE, i)
    h.close()
    assert errors == []                                              # no "Logging error" per record
    text = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert all(f"{_LINE}-{i}" in text for i in range(5))             # every record still reached the file


def test_failed_rollover_is_retried_only_after_the_back_off(tmp_path, monkeypatch, errors):
    rename = _Rename(fail=True)
    monkeypatch.setattr(logging.handlers.os, "rename", rename)
    clock = {"t": 1000.0}
    monkeypatch.setattr(lc, "time", SimpleNamespace(monotonic=lambda: clock["t"]))
    h = _handler(tmp_path)
    log = _logger("t.rotation.backoff", h)
    log.info("%s-a", _LINE)                                          # longer than maxBytes → one rollover attempt
    assert rename.calls == 1
    for i in range(10):                                              # inside the back-off: no further attempts
        log.info("%s-c%d", _LINE, i)
    assert rename.calls == 1
    clock["t"] += lc._SafeRotatingFileHandler._RETRY_AFTER_S + 1     # back-off over
    log.info("%s-d", _LINE)
    assert rename.calls == 2
    h.close()
    assert errors == []


def test_rollover_succeeds_normally_once_the_file_is_free(tmp_path, monkeypatch, errors):
    rename = _Rename(fail=False)
    monkeypatch.setattr(logging.handlers.os, "rename", rename)
    h = _handler(tmp_path)
    log = _logger("t.rotation.ok", h)
    log.info("%s-first", _LINE)
    log.info("%s-second", _LINE)                                     # rolls app.log → app.log.1
    h.close()
    assert errors == []
    assert (tmp_path / "app.log.1").exists()
    assert f"{_LINE}-first" in (tmp_path / "app.log.1").read_text(encoding="utf-8")
    assert f"{_LINE}-second" in (tmp_path / "app.log").read_text(encoding="utf-8")


def test_a_later_rollover_works_after_an_earlier_one_was_blocked(tmp_path, monkeypatch, errors):
    rename = _Rename(fail=True)
    monkeypatch.setattr(logging.handlers.os, "rename", rename)
    clock = {"t": 50.0}
    monkeypatch.setattr(lc, "time", SimpleNamespace(monotonic=lambda: clock["t"]))
    h = _handler(tmp_path)
    log = _logger("t.rotation.recover", h)
    log.info("%s-a", _LINE)                                          # rollover attempt, blocked
    log.info("%s-b", _LINE)                                          # inside the back-off: written, no attempt
    assert rename.calls == 1
    rename.fail = False                                              # the other process let go
    clock["t"] += lc._SafeRotatingFileHandler._RETRY_AFTER_S + 1
    log.info("%s-c", _LINE)                                          # retried → rotates
    h.close()
    assert errors == []
    assert rename.calls == 2 and (tmp_path / "app.log.1").exists()


@pytest.fixture
def clean_root():
    root = logging.getLogger()
    saved, level = list(root.handlers), root.level
    for h in saved:
        root.removeHandler(h)
    yield root
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    for h in saved:
        root.addHandler(h)
    root.setLevel(level)


def test_configure_logging_adds_each_file_handler_once_with_a_relative_log_dir(tmp_path, monkeypatch, clean_root):
    """Regression: the dedupe compared ``logs/app.jsonl`` (relative) with ``baseFilename`` (absolute), never
    matched, and every call attached another handler on the same file — whose rollover then could not rename
    a file its sibling still held open."""
    monkeypatch.chdir(tmp_path)
    lc.configure_logging("info")
    lc.configure_logging("info")
    lc.configure_logging("debug")
    files = [getattr(h, "baseFilename", None) for h in clean_root.handlers if hasattr(h, "baseFilename")]
    assert sorted(os.path.basename(f) for f in files) == ["app.jsonl", "client-errors.jsonl", "experience.jsonl",
                                                          "jobs.jsonl"]
    assert len(files) == len(set(files))
    assert all(os.path.isabs(f) for f in files)
    assert all(isinstance(h, lc._SafeRotatingFileHandler) for h in clean_root.handlers if hasattr(h, "baseFilename"))


def test_configure_logging_keeps_the_prefix_routing(tmp_path, monkeypatch, clean_root):
    monkeypatch.chdir(tmp_path)
    lc.configure_logging("info")
    log = logging.getLogger("rita.events")
    log.info('{"event": "experience.view"}', extra={"rita_event": "experience.view"})
    log.info('{"event": "training.done"}', extra={"rita_event": "training.done"})
    for h in clean_root.handlers:
        h.flush()
    read = lambda n: (tmp_path / "logs" / n).read_text(encoding="utf-8")   # noqa: E731
    assert "experience.view" in read("experience.jsonl") and "training.done" not in read("experience.jsonl")
    assert "training.done" in read("jobs.jsonl") and "experience.view" not in read("jobs.jsonl")
