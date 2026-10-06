"""File-backed repository for the bundled F42 P5 sample Console files (ADR-002).

The three synthetic CSV files are committed under ``data/input/<sample_dir>/`` and shipped by the
deploy rsync of ``data/input/``; they are only READ at runtime (the production mount is read-only).
This class is the single owner of every filesystem access to those files: ``FnoSampleService`` and
``FnoImportReadService`` receive it by injection and never touch a path themselves.

Exemption note: project.md section 8 ("constructors take ``db: Session``") applies to the
SQLAlchemy repositories; a file-backed repository is constructed from a directory instead.

File names are server-side constants (the configured reserved prefix + a fixed suffix), never
client input; files are opened ``rb`` only and capped at ``import_max_file_bytes``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rita.config import get_settings

DEFAULT_PREFIX = "SAMPLE_"
SAMPLE_TRADE_ID_PREFIX = "SMP"             # every sample trade/order id starts with this
_SUFFIXES = {"tradebook": "tradebook.csv", "ledger": "ledger.csv", "pnl": "pnl.csv"}
IMPORT_ORDER = ("tradebook", "ledger", "pnl")


class SampleFilesMissing(Exception):
    """One or more bundled sample files are missing, empty, oversized or unreadable."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__("sample files unavailable: " + ", ".join(missing))
        self.missing = missing


@dataclass(frozen=True)
class SampleFilesStatus:
    ok: bool
    missing: list[str] = field(default_factory=list)
    sizes: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SampleFile:
    kind: str
    name: str
    data: bytes


class FnoSampleFileRepo:
    def __init__(self, directory: Path, prefix: str = DEFAULT_PREFIX,
                 max_file_bytes: Optional[int] = None) -> None:
        self._dir = Path(directory)
        self._prefix = prefix
        self._cap = max_file_bytes if max_file_bytes is not None \
            else get_settings().trade_analysis.import_max_file_bytes

    @classmethod
    def from_settings(cls) -> "FnoSampleFileRepo":
        """Directory = ``settings.data.input_dir`` / ``trade_analysis.sample_dir``."""
        s = get_settings()
        cfg = s.trade_analysis
        return cls(Path(s.data.input_dir) / cfg.sample_dir, cfg.sample_file_prefix,
                   cfg.import_max_file_bytes)

    @property
    def names(self) -> dict[str, str]:
        return {k: f"{self._prefix}{suffix}" for k, suffix in _SUFFIXES.items()}

    def readiness(self) -> SampleFilesStatus:
        """Do all three files exist, non-empty and within the size cap?  Never raises."""
        missing: list[str] = []
        sizes: dict[str, int] = {}
        for name in self.names.values():
            p = self._dir / name
            try:
                size = p.stat().st_size if p.is_file() else 0
            except OSError:
                size = 0
            if size <= 0 or size > self._cap:
                missing.append(name)
            else:
                sizes[name] = size
        return SampleFilesStatus(ok=not missing, missing=missing, sizes=sizes)

    def read_all(self) -> list[SampleFile]:
        """The three files in import order (tradebook, ledger, P&L); raises SampleFilesMissing."""
        out: list[SampleFile] = []
        missing: list[str] = []
        for kind in IMPORT_ORDER:
            name = self.names[kind]
            try:
                with (self._dir / name).open("rb") as fh:
                    data = fh.read(self._cap + 1)
            except OSError:
                missing.append(name)
                continue
            if not data or len(data) > self._cap:
                missing.append(name)
                continue
            out.append(SampleFile(kind, name, data))
        if missing:
            raise SampleFilesMissing(missing)
        return out
