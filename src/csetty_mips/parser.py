from __future__ import annotations

import re

from .errors import ParseError, SourceRef
from .limits import DEFAULT_LIMITS, Limits
from .model import ParsedStatement, SourceUnit

_LABEL = re.compile(r"[A-Za-z_.$][A-Za-z0-9_.$]*")
_OPERATION = re.compile(r"\.?[A-Za-z_][A-Za-z0-9_.]*")


def _strip_comment(line: str, source: SourceRef) -> str:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if quote is not None:
            if character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character in {"#", ";"}:
            return line[:index]
    if quote is not None:
        raise ParseError("P101", "unterminated quoted literal", source.shifted(len(line) - 1))
    return line


def _split_operands(text: str, source: SourceRef, start_column: int) -> tuple[str, ...]:
    if not text.strip():
        return ()
    result: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    escaped = False
    for index, character in enumerate(text):
        if escaped:
            escaped = False
            continue
        if quote is not None:
            if character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise ParseError(
                    "P102",
                    "unexpected closing parenthesis",
                    source.shifted(start_column + index - 1),
                )
        elif character == "," and depth == 0:
            operand = text[start:index].strip()
            if not operand:
                raise ParseError(
                    "P103",
                    "empty operand",
                    source.shifted(start_column + index - 1),
                )
            result.append(operand)
            start = index + 1
    if quote is not None:
        raise ParseError("P101", "unterminated quoted literal", source)
    if depth != 0:
        raise ParseError("P104", "unclosed parenthesis", source.shifted(start_column - 1))
    operand = text[start:].strip()
    if not operand:
        raise ParseError("P103", "trailing comma creates an empty operand", source)
    result.append(operand)
    return tuple(result)


def parse_sources(
    sources: list[SourceUnit] | tuple[SourceUnit, ...],
    *,
    limits: Limits = DEFAULT_LIMITS,
) -> tuple[ParsedStatement, ...]:
    total_bytes = 0
    for unit in sources:
        try:
            total_bytes += len(unit.text.encode("utf-8"))
        except UnicodeEncodeError as error:
            raise ParseError(
                "P110", f"{unit.filename}: source text is not valid UTF-8: {error}"
            ) from error
    if total_bytes > limits.max_source_bytes:
        raise ParseError(
            "P100",
            f"source input is {total_bytes} bytes; limit is {limits.max_source_bytes}",
        )

    statements: list[ParsedStatement] = []
    for unit in sources:
        for line_number, original in enumerate(unit.text.splitlines(), start=1):
            base = SourceRef(unit.filename, line_number, 1, original)
            line = _strip_comment(original, base)
            position = 0
            while position < len(line) and line[position].isspace():
                position += 1
            if position == len(line):
                continue

            labels: list[str] = []
            while True:
                match = _LABEL.match(line, position)
                if match is None:
                    break
                after = match.end()
                while after < len(line) and line[after].isspace():
                    after += 1
                if after >= len(line) or line[after] != ":":
                    break
                labels.append(match.group(0))
                position = after + 1
                while position < len(line) and line[position].isspace():
                    position += 1

            if position == len(line):
                statements.append(
                    ParsedStatement(
                        tuple(labels), None, (), SourceRef(unit.filename, line_number, 1, original)
                    )
                )
                if len(statements) > limits.max_statements:
                    raise ParseError(
                        "P107",
                        f"statement count exceeds limit {limits.max_statements}",
                        statements[-1].source,
                    )
                continue

            constant_match = _LABEL.match(line, position)
            if constant_match is not None:
                after_name = constant_match.end()
                while after_name < len(line) and line[after_name].isspace():
                    after_name += 1
                if after_name < len(line) and line[after_name] == "=":
                    if labels:
                        raise ParseError(
                            "P108",
                            "a constant assignment cannot also define a label",
                            SourceRef(unit.filename, line_number, position + 1, original),
                        )
                    expression = line[after_name + 1 :].strip()
                    if not expression:
                        raise ParseError(
                            "P109",
                            "constant assignment requires an expression",
                            SourceRef(unit.filename, line_number, after_name + 2, original),
                        )
                    statements.append(
                        ParsedStatement(
                            (),
                            ".equ",
                            (constant_match.group(0), expression),
                            SourceRef(unit.filename, line_number, position + 1, original),
                        )
                    )
                    if len(statements) > limits.max_statements:
                        raise ParseError(
                            "P107",
                            f"statement count exceeds limit {limits.max_statements}",
                            statements[-1].source,
                        )
                    continue

            operation_match = _OPERATION.match(line, position)
            if operation_match is None:
                raise ParseError(
                    "P105",
                    "expected an instruction or directive",
                    SourceRef(unit.filename, line_number, position + 1, original),
                )
            operation = operation_match.group(0).lower()
            operation_column = position + 1
            position = operation_match.end()
            if position < len(line) and not line[position].isspace():
                raise ParseError(
                    "P106",
                    "unexpected character after operation name",
                    SourceRef(unit.filename, line_number, position + 1, original),
                )
            while position < len(line) and line[position].isspace():
                position += 1
            operands = _split_operands(line[position:], base, position + 1)
            statements.append(
                ParsedStatement(
                    tuple(labels),
                    operation,
                    operands,
                    SourceRef(unit.filename, line_number, operation_column, original),
                )
            )
            if len(statements) > limits.max_statements:
                raise ParseError(
                    "P107",
                    f"statement count exceeds limit {limits.max_statements}",
                    statements[-1].source,
                )
    return tuple(statements)
