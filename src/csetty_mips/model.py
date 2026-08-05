from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from .errors import SourceRef

TEXT_BASE = 0x0040_0000
DATA_BASE = 0x1000_0000
KTEXT_BASE = 0x8000_0000
KDATA_BASE = 0x9000_0000
STACK_TOP = 0x7FFF_EFFC
TEXT_INITIAL_BYTES = 256 * 1024
DATA_INITIAL_BYTES = 256 * 1024
DATA_MAX_BYTES = 1024 * 1024
KTEXT_INITIAL_BYTES = 64 * 1024
KDATA_MAX_BYTES = 1024 * 1024
STACK_MAX_BYTES = 256 * 1024


class Section(Enum):
    TEXT = "text"
    DATA = "data"
    KTEXT = "ktext"
    KDATA = "kdata"


@dataclass(frozen=True, slots=True)
class SourceUnit:
    filename: str
    text: str


@dataclass(frozen=True, slots=True)
class ParsedStatement:
    labels: tuple[str, ...]
    operation: str | None
    operands: tuple[str, ...]
    source: SourceRef


@dataclass(frozen=True, slots=True)
class SourceMapEntry:
    source: SourceRef
    rendered: str


@dataclass(frozen=True, slots=True)
class Program:
    text_base: int
    text_words: tuple[int, ...]
    data_base: int
    data: bytes
    data_initialized: bytes
    ktext_base: int
    ktext_words: tuple[int, ...]
    kdata_base: int
    kdata: bytes
    kdata_initialized: bytes
    symbols: Mapping[str, int]
    source_map: Mapping[int, SourceMapEntry]
    entry: int
    source_files: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        text_words: list[int],
        data: bytearray,
        data_initialized: bytearray,
        ktext_words: list[int],
        kdata: bytearray,
        kdata_initialized: bytearray,
        symbols: dict[str, int],
        source_map: dict[int, SourceMapEntry],
        entry: int,
        source_files: dict[str, str],
    ) -> Program:
        return cls(
            text_base=TEXT_BASE,
            text_words=tuple(word & 0xFFFF_FFFF for word in text_words),
            data_base=DATA_BASE,
            data=bytes(data),
            data_initialized=bytes(data_initialized),
            ktext_base=KTEXT_BASE,
            ktext_words=tuple(word & 0xFFFF_FFFF for word in ktext_words),
            kdata_base=KDATA_BASE,
            kdata=bytes(kdata),
            kdata_initialized=bytes(kdata_initialized),
            symbols=MappingProxyType(dict(symbols)),
            source_map=MappingProxyType(dict(source_map)),
            entry=entry,
            source_files=MappingProxyType(dict(source_files)),
        )
