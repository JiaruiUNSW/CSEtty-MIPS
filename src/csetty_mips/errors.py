from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceRef:
    filename: str
    line: int
    column: int
    text: str

    def shifted(self, offset: int) -> SourceRef:
        return SourceRef(self.filename, self.line, max(1, self.column + offset), self.text)


class CsettyMipsError(Exception):
    """Base class for stable, source-aware user errors."""

    def __init__(
        self,
        code: str,
        message: str,
        source: SourceRef | None = None,
        *,
        notes: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.source = source
        self.notes = notes

    def render(self) -> str:
        prefix = f"csetty-mips[{self.code}]"
        if self.source is None:
            lines = [f"{prefix}: {self.message}"]
        else:
            location = f"{self.source.filename}:{self.source.line}:{self.source.column}"
            caret_width = max(0, self.source.column - 1)
            lines = [
                f"{location}: {prefix}: {self.message}",
                f"  {self.source.text}",
                f"  {' ' * caret_width}^",
            ]
        lines.extend(f"  note: {note}" for note in self.notes)
        return "\n".join(lines)


class ParseError(CsettyMipsError):
    pass


class AssemblyError(CsettyMipsError):
    pass


class RuntimeFault(CsettyMipsError):
    def __init__(
        self,
        code: str,
        message: str,
        source: SourceRef | None = None,
        *,
        pc: int | None = None,
        notes: tuple[str, ...] = (),
    ) -> None:
        super().__init__(code, message, source, notes=notes)
        self.pc = pc

    def render(self) -> str:
        rendered = super().render()
        if self.pc is None:
            return rendered
        first, *rest = rendered.splitlines()
        return "\n".join([f"{first} (pc=0x{self.pc:08x})", *rest])
