from __future__ import annotations

import ast
import difflib
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .errors import AssemblyError, SourceRef
from .expression import evaluate, is_constant
from .integers import (
    fits_signed,
    fits_unsigned,
    require_signed,
    require_signed_or_bit_pattern,
    require_unsigned,
    u32,
)
from .isa import (
    ALL_REAL_INSTRUCTIONS,
    BRANCH1_OPCODES,
    BRANCH2_OPCODES,
    FPU_MEMORY_OPCODES,
    I_SIGNED_OPCODES,
    I_UNSIGNED_OPCODES,
    MEMORY_OPCODES,
    R3_FUNCTS,
    REGIMM_RT,
    SHIFT_IMMEDIATE_FUNCTS,
    SHIFT_VARIABLE_FUNCTS,
    SPECIAL2_ACCUM_FUNCTS,
    TRAP_I_RT,
    TRAP_R_FUNCTS,
    encode_i,
    encode_j,
    encode_r,
    parse_fpu_register,
    parse_register,
)
from .limits import DEFAULT_LIMITS, Limits
from .model import (
    DATA_BASE,
    KDATA_BASE,
    KTEXT_BASE,
    TEXT_BASE,
    ParsedStatement,
    Program,
    Section,
    SourceMapEntry,
    SourceUnit,
)
from .parser import parse_sources

_MEMORY_OPERAND = re.compile(r"(.*?)\(\s*(\$[A-Za-z0-9]+)\s*\)\Z")
_SYMBOL_NAME = re.compile(r"[A-Za-z_.$][A-Za-z0-9_.$]*\Z")
_TEXT_SECTIONS = frozenset({Section.TEXT, Section.KTEXT})
_DATA_SECTIONS = frozenset({Section.DATA, Section.KDATA})
_SECTION_BASES = {
    Section.TEXT: TEXT_BASE,
    Section.DATA: DATA_BASE,
    Section.KTEXT: KTEXT_BASE,
    Section.KDATA: KDATA_BASE,
}

_PSEUDO_INSTRUCTIONS = frozenset(
    {
        "nop",
        "move",
        "clear",
        "not",
        "neg",
        "negu",
        "li",
        "la",
        "mul",
        "b",
        "bal",
        "beq",
        "bne",
        "beqz",
        "bnez",
        "blt",
        "ble",
        "bgt",
        "bge",
        "bltu",
        "bleu",
        "bgtu",
        "bgeu",
        "seq",
        "sne",
        "sge",
        "sgt",
        "sle",
        "sgeu",
        "sgtu",
        "sleu",
        "seqi",
        "snei",
        "sgei",
        "sgti",
        "slei",
        "sequi",
        "sneui",
        "sgeui",
        "sgtui",
        "sleui",
        "abs",
        "rem",
        "remu",
        "rol",
        "ror",
        "push",
        "pop",
        "begin",
        "end",
        "tgt",
        "tgtu",
        "tgti",
        "tgtiu",
        "tle",
        "tleu",
        "tlei",
        "tleiu",
        *MEMORY_OPCODES,
        *FPU_MEMORY_OPCODES,
    }
)


@dataclass(frozen=True, slots=True)
class _LocatedStatement:
    statement: ParsedStatement
    section: Section
    address: int
    size: int


@dataclass(frozen=True, slots=True)
class _FirstPassResult:
    located: list[_LocatedStatement]
    local_symbols: dict[str, dict[str, int]]
    global_symbols: dict[str, int]
    text_end: int
    data_end: int
    ktext_end: int
    kdata_end: int


def _looks_like_register(text: str) -> bool:
    return text.strip().startswith("$")


def _load_word_count(expression: str, source: SourceRef) -> int:
    if is_constant(expression):
        value = evaluate(expression, {}, source)
        if fits_signed(value, 16) or fits_unsigned(value, 16):
            return 1
    return 2


def _memory_parts(operand: str) -> tuple[str, str | None]:
    match = _MEMORY_OPERAND.fullmatch(operand.strip())
    if match is None:
        return operand.strip(), None
    return match.group(1).strip() or "0", match.group(2)


def _memory_word_count(statement: ParsedStatement) -> int:
    operation = statement.operation
    assert operation is not None
    _operand_count(operation, statement.operands, 2, statement.source)
    expression, base = _memory_parts(statement.operands[1])
    if is_constant(expression):
        value = evaluate(expression, {}, statement.source)
        if fits_signed(value, 16) or (base is not None and fits_unsigned(value, 16)):
            return 1
    return _load_word_count(expression, statement.source) + (2 if base is not None else 1)


def _uses_macro(statement: ParsedStatement, words: int) -> bool:
    operation = statement.operation
    assert operation is not None
    if operation in MEMORY_OPCODES or operation in FPU_MEMORY_OPCODES:
        _, base = _memory_parts(statement.operands[1])
        return base is None or words != 1
    if operation in {"beq", "bne"}:
        return not _looks_like_register(statement.operands[1])
    if operation == "mul":
        return not _looks_like_register(statement.operands[2])
    if operation in {"div", "divu"} and len(statement.operands) == 3:
        return True
    return operation in _PSEUDO_INSTRUCTIONS


def _uses_assembler_temporary(statement: ParsedStatement, words: int) -> bool:
    operation = statement.operation
    assert operation is not None
    if operation in MEMORY_OPCODES or operation in FPU_MEMORY_OPCODES:
        return words != 1
    if operation == "mul":
        return not _looks_like_register(statement.operands[2])
    if operation in {"beq", "bne"}:
        return not _looks_like_register(statement.operands[1])
    if operation in {"blt", "ble", "bgt", "bge", "bltu", "bleu", "bgtu", "bgeu"}:
        return True
    if operation in {"seq", "sne"}:
        return True
    if operation in {
        "sge",
        "sgt",
        "sle",
        "sgeu",
        "sgtu",
        "sleu",
        "seqi",
        "snei",
        "sgei",
        "sgti",
        "slei",
        "sequi",
        "sneui",
        "sgeui",
        "sgtui",
        "sleui",
    }:
        return not _looks_like_register(statement.operands[2]) or operation.endswith("i")
    if operation == "rol":
        return _looks_like_register(statement.operands[2])
    return operation in {"tgti", "tgtiu", "tlei", "tleiu"}


def _operand_count(
    operation: str,
    operands: Sequence[str],
    expected: int | tuple[int, ...],
    source: SourceRef,
) -> None:
    accepted = (expected,) if isinstance(expected, int) else expected
    if len(operands) in accepted:
        return
    rendered = " or ".join(str(value) for value in accepted)
    raise AssemblyError(
        "A202",
        f"{operation} expects {rendered} operand(s), got {len(operands)}",
        source,
    )


def _decode_string(text: str, source: SourceRef) -> bytes:
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError) as error:
        raise AssemblyError("A106", "invalid string literal", source) from error
    if not isinstance(value, str):
        raise AssemblyError("A106", "expected a quoted string literal", source)
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise AssemblyError("A107", "string cannot be encoded as UTF-8", source) from error


def _align(address: int, alignment: int) -> int:
    return (address + alignment - 1) & -alignment


def _pseudo_word_count(statement: ParsedStatement) -> int:
    operation = statement.operation
    assert operation is not None
    operands = statement.operands
    if operation in MEMORY_OPCODES or operation in FPU_MEMORY_OPCODES:
        return _memory_word_count(statement)
    if operation == "li":
        _operand_count(operation, operands, 2, statement.source)
        return _load_word_count(operands[1], statement.source)
    if operation == "la":
        _operand_count(operation, operands, 2, statement.source)
        return 2
    if operation in {"beq", "bne"}:
        _operand_count(operation, operands, 3, statement.source)
        return (
            1
            if _looks_like_register(operands[1])
            else _load_word_count(operands[1], statement.source) + 1
        )
    if operation == "mul":
        _operand_count(operation, operands, 3, statement.source)
        return (
            1
            if _looks_like_register(operands[2])
            else _load_word_count(operands[2], statement.source) + 1
        )
    if operation in {"blt", "ble", "bgt", "bge", "bltu", "bleu", "bgtu", "bgeu"}:
        _operand_count(operation, operands, 3, statement.source)
        return (
            2
            if _looks_like_register(operands[1])
            else _load_word_count(operands[1], statement.source) + 2
        )
    if operation in {"seq", "sne", "sge", "sle", "sgeu", "sleu", "sgt", "sgtu"}:
        _operand_count(operation, operands, 3, statement.source)
        remaining = 1 if operation in {"sgt", "sgtu"} else 2
        return (
            remaining
            if _looks_like_register(operands[2])
            else _load_word_count(operands[2], statement.source) + remaining
        )
    immediate_sets = {
        "seqi",
        "snei",
        "sgei",
        "sgti",
        "slei",
        "sequi",
        "sneui",
        "sgeui",
        "sgtui",
        "sleui",
    }
    if operation in immediate_sets:
        _operand_count(operation, operands, 3, statement.source)
        remaining = 1 if operation in {"sgti", "sgtui"} else 2
        return _load_word_count(operands[2], statement.source) + remaining
    if operation == "abs":
        _operand_count(operation, operands, 2, statement.source)
        return 3
    if operation in {"rem", "remu"}:
        _operand_count(operation, operands, 3, statement.source)
        return 2
    if operation in {"rol", "ror"}:
        _operand_count(operation, operands, 3, statement.source)
        if not _looks_like_register(operands[2]):
            return 1
        return 1 if operation == "ror" else 2
    if operation in {"push", "pop"}:
        _operand_count(operation, operands, 1, statement.source)
        return 2
    if operation == "begin":
        _operand_count(operation, operands, 0, statement.source)
        return 3
    if operation == "end":
        _operand_count(operation, operands, 0, statement.source)
        return 2
    if operation in {"tgt", "tgtu", "tle", "tleu"}:
        _operand_count(operation, operands, 2, statement.source)
        return 1
    if operation in {"tgti", "tgtiu", "tlei", "tleiu"}:
        _operand_count(operation, operands, 2, statement.source)
        return _load_word_count(operands[1], statement.source) + 1
    counts: dict[str, int] = {
        "nop": 0,
        "move": 2,
        "clear": 1,
        "not": 2,
        "neg": 2,
        "negu": 2,
        "b": 1,
        "bal": 1,
        "beqz": 2,
        "bnez": 2,
    }
    _operand_count(operation, operands, counts[operation], statement.source)
    return 1


def _instruction_word_count(statement: ParsedStatement) -> int:
    operation = statement.operation
    assert operation is not None
    if operation in _PSEUDO_INSTRUCTIONS:
        return _pseudo_word_count(statement)
    if operation in {"div", "divu"} and len(statement.operands) == 3:
        return 2
    if operation in ALL_REAL_INSTRUCTIONS:
        return 1
    inventory = sorted(ALL_REAL_INSTRUCTIONS | _PSEUDO_INSTRUCTIONS)
    prefix_choices = sorted(
        (candidate for candidate in inventory if candidate.startswith(operation)),
        key=lambda candidate: (len(candidate), candidate),
    )
    choices = prefix_choices[:1] or difflib.get_close_matches(
        operation, inventory, n=1, cutoff=0.65
    )
    notes = (f"did you mean {choices[0]!r}?",) if choices else ()
    raise AssemblyError("A203", f"unknown instruction {operation!r}", statement.source, notes=notes)


def _directive_size(
    statement: ParsedStatement,
    section: Section,
    address: int,
    symbols: Mapping[str, int],
) -> tuple[int, int]:
    operation = statement.operation
    assert operation is not None
    operands = statement.operands
    if operation in {".globl", ".global", ".eqv", ".equ"}:
        return address, 0
    if operation in {".align", ".balign"}:
        _operand_count(operation, operands, 1, statement.source)
        amount = evaluate(operands[0], symbols, statement.source)
        if operation == ".align" and not 0 <= amount <= 20:
            raise AssemblyError(
                "A204", ".align exponent must be between 0 and 20", statement.source
            )
        alignment = (1 << amount) if operation == ".align" else amount
        if alignment <= 0 or alignment > 1 << 20 or alignment & (alignment - 1):
            raise AssemblyError(
                "A204", "alignment must be a positive power of two", statement.source
            )
        aligned = _align(address, alignment)
        return aligned, 0
    if operation in {".ascii", ".asciiz"}:
        if section not in _DATA_SECTIONS:
            raise AssemblyError(
                "A205", f"{operation} is only valid in a data section", statement.source
            )
        if not operands:
            raise AssemblyError(
                "A206", f"{operation} requires at least one string", statement.source
            )
        size = sum(len(_decode_string(item, statement.source)) for item in operands)
        if operation == ".asciiz":
            size += len(operands)
        return address, size
    widths = {".byte": 1, ".half": 2, ".word": 4, ".float": 4, ".double": 8}
    if operation in widths:
        if not operands:
            raise AssemblyError(
                "A207", f"{operation} requires at least one value", statement.source
            )
        if section in _TEXT_SECTIONS and operation != ".word":
            raise AssemblyError(
                "A205", f"{operation} is only valid in a data section", statement.source
            )
        width = widths[operation]
        return _align(address, width), width * len(operands)
    if operation == ".space":
        if section not in _DATA_SECTIONS:
            raise AssemblyError("A205", ".space is only valid in a data section", statement.source)
        _operand_count(operation, operands, 1, statement.source)
        size = evaluate(operands[0], symbols, statement.source)
        if size < 0:
            raise AssemblyError("A208", ".space size cannot be negative", statement.source)
        return address, size
    raise AssemblyError("A209", f"unknown directive {operation!r}", statement.source)


def _split_constant_operands(statement: ParsedStatement) -> tuple[str, str]:
    if len(statement.operands) == 2:
        return statement.operands[0], statement.operands[1]
    if len(statement.operands) == 1:
        pieces = statement.operands[0].split(None, 1)
        if len(pieces) == 2:
            return pieces[0], pieces[1]
    raise AssemblyError(
        "A210", f"{statement.operation} expects a name and an expression", statement.source
    )


def _global_declarations(
    statements: Sequence[ParsedStatement],
) -> dict[str, set[str]]:
    declarations: dict[str, set[str]] = {}
    for statement in statements:
        if statement.operation not in {".globl", ".global"}:
            continue
        if not statement.operands:
            raise AssemblyError(
                "A233", f"{statement.operation} requires at least one symbol", statement.source
            )
        selected = declarations.setdefault(statement.source.filename, set())
        for name in statement.operands:
            if _SYMBOL_NAME.fullmatch(name) is None:
                raise AssemblyError("A234", f"invalid global symbol {name!r}", statement.source)
            selected.add(name)
    return declarations


def _first_pass(statements: Sequence[ParsedStatement], limits: Limits) -> _FirstPassResult:
    section = Section.TEXT
    addresses = dict(_SECTION_BASES)
    declarations = _global_declarations(statements)
    local_symbols: dict[str, dict[str, int]] = {}
    global_symbols: dict[str, int] = {}
    located: list[_LocatedStatement] = []
    symbol_count = 0
    allow_at = True
    allow_macros = True
    setting_stack: list[tuple[bool, bool]] = []
    active_filename: str | None = None

    def define(name: str, value: int, source: SourceRef) -> None:
        nonlocal symbol_count
        local = local_symbols.setdefault(source.filename, {})
        if name in local:
            raise AssemblyError("A211", f"symbol {name!r} is defined more than once", source)
        if symbol_count >= limits.max_symbols:
            raise AssemblyError("A212", f"symbol count exceeds limit {limits.max_symbols}", source)
        local[name] = value
        symbol_count += 1
        if name in declarations.get(source.filename, set()):
            if name in global_symbols:
                raise AssemblyError(
                    "A235", f"global symbol {name!r} is defined in more than one file", source
                )
            global_symbols[name] = value

    def visible_symbols(filename: str) -> dict[str, int]:
        result = dict(global_symbols)
        result.update(local_symbols.get(filename, {}))
        return result

    for statement in statements:
        if statement.source.filename != active_filename:
            active_filename = statement.source.filename
            section = Section.TEXT
            allow_at = True
            allow_macros = True
            setting_stack = []
        current = addresses[section]
        operation = statement.operation
        if operation is None:
            for label in statement.labels:
                define(label, current, statement.source)
            continue
        if operation in {".text", ".data", ".ktext", ".kdata"}:
            for label in statement.labels:
                define(label, current, statement.source)
            _operand_count(operation, statement.operands, (0, 1), statement.source)
            section = {
                ".text": Section.TEXT,
                ".data": Section.DATA,
                ".ktext": Section.KTEXT,
                ".kdata": Section.KDATA,
            }[operation]
            if statement.operands:
                requested = evaluate(
                    statement.operands[0],
                    visible_symbols(statement.source.filename),
                    statement.source,
                )
                base = _SECTION_BASES[section]
                if requested < addresses[section] or requested < base:
                    raise AssemblyError(
                        "A213", f"{operation} address cannot move backwards", statement.source
                    )
                maximum = {
                    Section.TEXT: TEXT_BASE + limits.max_text_words * 4,
                    Section.DATA: DATA_BASE + limits.max_data_bytes,
                    Section.KTEXT: KTEXT_BASE + limits.max_kernel_text_words * 4,
                    Section.KDATA: KDATA_BASE + limits.max_kernel_data_bytes,
                }[section]
                if requested > maximum:
                    raise AssemblyError(
                        "A216" if section in _TEXT_SECTIONS else "A217",
                        f"{operation} address exceeds the configured section limit",
                        statement.source,
                    )
                if section in _TEXT_SECTIONS and requested & 3:
                    raise AssemblyError(
                        "A213", f"{operation} address must be word aligned", statement.source
                    )
                addresses[section] = requested
            continue
        if operation in {".eqv", ".equ"}:
            for label in statement.labels:
                define(label, current, statement.source)
            name, expression = _split_constant_operands(statement)
            if _SYMBOL_NAME.fullmatch(name) is None:
                raise AssemblyError("A214", f"invalid constant name {name!r}", statement.source)
            define(
                name,
                evaluate(expression, visible_symbols(statement.source.filename), statement.source),
                statement.source,
            )
            continue
        if operation == ".set":
            for label in statement.labels:
                define(label, current, statement.source)
            _operand_count(operation, statement.operands, 1, statement.source)
            setting = statement.operands[0].strip().lower()
            if setting == "at":
                allow_at = True
            elif setting == "noat":
                allow_at = False
            elif setting == "macro":
                allow_macros = True
            elif setting == "nomacro":
                allow_macros = False
            elif setting in {"reorder", "noreorder"}:
                pass
            elif setting == "push":
                setting_stack.append((allow_at, allow_macros))
            elif setting == "pop":
                if not setting_stack:
                    raise AssemblyError(
                        "A238", ".set pop has no matching .set push", statement.source
                    )
                allow_at, allow_macros = setting_stack.pop()
            else:
                raise AssemblyError(
                    "A239", f"unsupported .set option {setting!r}", statement.source
                )
            continue
        address = addresses[section]
        if operation.startswith("."):
            effective_address, size = _directive_size(
                statement,
                section,
                address,
                visible_symbols(statement.source.filename),
            )
            label_address = address if operation in {".align", ".balign"} else effective_address
            for label in statement.labels:
                define(label, label_address, statement.source)
            address = effective_address
            located.append(_LocatedStatement(statement, section, address, size))
            addresses[section] = address + size
        else:
            for label in statement.labels:
                define(label, address, statement.source)
            if section not in _TEXT_SECTIONS:
                raise AssemblyError(
                    "A215", "instructions may only appear in a text section", statement.source
                )
            words = _instruction_word_count(statement)
            if not allow_macros and _uses_macro(statement, words):
                raise AssemblyError(
                    "A240",
                    f"{operation} requires macro expansion while .set nomacro is active",
                    statement.source,
                )
            if not allow_at and _uses_assembler_temporary(statement, words):
                raise AssemblyError(
                    "A241", f"{operation} requires $at while .set noat is active", statement.source
                )
            size = words * 4
            located.append(_LocatedStatement(statement, section, address, size))
            addresses[section] += size
        if addresses[Section.TEXT] - TEXT_BASE > limits.max_text_words * 4:
            raise AssemblyError(
                "A216", f"text exceeds {limits.max_text_words} words", statement.source
            )
        if addresses[Section.DATA] - DATA_BASE > limits.max_data_bytes:
            raise AssemblyError(
                "A217", f"data exceeds {limits.max_data_bytes} bytes", statement.source
            )
        if addresses[Section.KTEXT] - KTEXT_BASE > limits.max_kernel_text_words * 4:
            raise AssemblyError(
                "A216",
                f"kernel text exceeds {limits.max_kernel_text_words} words",
                statement.source,
            )
        if addresses[Section.KDATA] - KDATA_BASE > limits.max_kernel_data_bytes:
            raise AssemblyError(
                "A217",
                f"kernel data exceeds {limits.max_kernel_data_bytes} bytes",
                statement.source,
            )
    return _FirstPassResult(
        located,
        local_symbols,
        global_symbols,
        addresses[Section.TEXT],
        addresses[Section.DATA],
        addresses[Section.KTEXT],
        addresses[Section.KDATA],
    )


def _public_symbols(result: _FirstPassResult) -> dict[str, int]:
    symbols = dict(result.global_symbols)
    occurrences: dict[str, int] = {}
    for local in result.local_symbols.values():
        for name in local:
            occurrences[name] = occurrences.get(name, 0) + 1
    for filename, local in result.local_symbols.items():
        for name, value in local.items():
            if name not in symbols and occurrences[name] == 1:
                symbols[name] = value
            elif name not in result.global_symbols:
                symbols[f"{filename}::{name}"] = value
    return symbols


def _expand_load(
    destination: str,
    expression: str,
    *,
    symbols: Mapping[str, int],
    source: SourceRef,
    expected_words: int,
) -> list[tuple[str, tuple[str, ...]]]:
    value = evaluate(expression, symbols, source)
    if not -(1 << 31) <= value <= 0xFFFF_FFFF:
        raise AssemblyError("A218", f"32-bit literal out of range: {value}", source)
    if expected_words == 1 and fits_signed(value, 16):
        return [("addiu", (destination, "$zero", str(value)))]
    if expected_words == 1 and fits_unsigned(value, 16):
        return [("ori", (destination, "$zero", str(value)))]
    if expected_words != 2:
        raise AssertionError(f"invalid load expansion size {expected_words}")
    word = u32(value)
    return [
        ("lui", (destination, str((word >> 16) & 0xFFFF))),
        ("ori", (destination, destination, str(word & 0xFFFF))),
    ]


def _expand_pseudo(
    operation: str,
    operands: Sequence[str],
    *,
    address: int,
    symbols: Mapping[str, int],
    source: SourceRef,
    expected_words: int,
) -> list[tuple[str, tuple[str, ...]]]:
    if operation == "nop":
        return [("sll", ("$zero", "$zero", "0"))]
    if operation == "move":
        return [("addu", (operands[0], operands[1], "$zero"))]
    if operation == "clear":
        return [("addu", (operands[0], "$zero", "$zero"))]
    if operation == "not":
        return [("nor", (operands[0], operands[1], "$zero"))]
    if operation in {"neg", "negu"}:
        return [("sub" if operation == "neg" else "subu", (operands[0], "$zero", operands[1]))]
    if operation == "li":
        return _expand_load(
            operands[0],
            operands[1],
            symbols=symbols,
            source=source,
            expected_words=expected_words,
        )
    if operation == "la":
        value = u32(evaluate(operands[1], symbols, source))
        return [
            ("lui", (operands[0], str((value >> 16) & 0xFFFF))),
            ("ori", (operands[0], operands[0], str(value & 0xFFFF))),
        ]
    if operation == "mul":
        if _looks_like_register(operands[2]):
            return [("mul", tuple(operands))]
        if parse_register(operands[1], source) == 1:
            raise AssemblyError(
                "A230", "$at cannot be an input when an immediate needs expansion", source
            )
        loaded = _expand_load(
            "$at",
            operands[2],
            symbols=symbols,
            source=source,
            expected_words=expected_words - 1,
        )
        return [*loaded, ("mul", (operands[0], operands[1], "$at"))]
    if operation in MEMORY_OPCODES or operation in FPU_MEMORY_OPCODES:
        expression, base = _memory_parts(operands[1])
        value = evaluate(expression, symbols, source)
        if expected_words == 1:
            selected_base = "$zero" if base is None else base
            return [(operation, (operands[0], f"{value}({selected_base})"))]
        stores = {"sb", "sh", "sw", "swl", "swr", "sc"}
        base_is_at = base is not None and parse_register(base, source) == 1
        value_is_at = operation in stores and parse_register(operands[0], source) == 1
        if base_is_at or value_is_at:
            raise AssemblyError(
                "A230",
                "$at cannot hold a value or base when an address needs expansion",
                source,
            )
        remaining = 2 if base is not None else 1
        address_load = _expand_load(
            "$at",
            expression,
            symbols=symbols,
            source=source,
            expected_words=expected_words - remaining,
        )
        if base is None:
            return [*address_load, (operation, (operands[0], "0($at)"))]
        return [
            *address_load,
            ("addu", ("$at", "$at", base)),
            (operation, (operands[0], "0($at)")),
        ]
    if operation == "b":
        return [("beq", ("$zero", "$zero", operands[0]))]
    if operation == "bal":
        return [("bgezal", ("$zero", operands[0]))]
    if operation in {"beq", "bne"}:
        if _looks_like_register(operands[1]):
            return [(operation, tuple(operands))]
        if parse_register(operands[0], source) == 1:
            raise AssemblyError(
                "A230", "$at cannot be compared when an immediate needs expansion", source
            )
        loaded = _expand_load(
            "$at",
            operands[1],
            symbols=symbols,
            source=source,
            expected_words=expected_words - 1,
        )
        return [*loaded, (operation, (operands[0], "$at", operands[2]))]
    if operation == "beqz":
        return [("beq", (operands[0], "$zero", operands[1]))]
    if operation == "bnez":
        return [("bne", (operands[0], "$zero", operands[1]))]
    relational_branches = {"blt", "bge", "bgt", "ble", "bltu", "bgeu", "bgtu", "bleu"}
    if operation in relational_branches:
        branch_relations = {
            "blt": ("slt", operands[0], operands[1], "bne"),
            "bge": ("slt", operands[0], operands[1], "beq"),
            "bgt": ("slt", operands[1], operands[0], "bne"),
            "ble": ("slt", operands[1], operands[0], "beq"),
            "bltu": ("sltu", operands[0], operands[1], "bne"),
            "bgeu": ("sltu", operands[0], operands[1], "beq"),
            "bgtu": ("sltu", operands[1], operands[0], "bne"),
            "bleu": ("sltu", operands[1], operands[0], "beq"),
        }
        compare, left, right, branch = branch_relations[operation]
        if _looks_like_register(operands[1]):
            branch_loaded: list[tuple[str, tuple[str, ...]]] = []
        else:
            if parse_register(operands[0], source) == 1:
                raise AssemblyError(
                    "A230", "$at cannot be compared when an immediate needs expansion", source
                )
            branch_loaded = _expand_load(
                "$at",
                operands[1],
                symbols=symbols,
                source=source,
                expected_words=expected_words - 2,
            )
            if operation in {"blt", "bge", "bltu", "bgeu"}:
                left, right = operands[0], "$at"
            else:
                left, right = "$at", operands[0]
        return [
            *branch_loaded,
            (compare, ("$at", left, right)),
            (branch, ("$at", "$zero", operands[2])),
        ]

    immediate_set_aliases = {
        "seqi": "seq",
        "snei": "sne",
        "sgei": "sge",
        "sgti": "sgt",
        "slei": "sle",
        "sequi": "seq",
        "sneui": "sne",
        "sgeui": "sgeu",
        "sgtui": "sgtu",
        "sleui": "sleu",
    }
    set_operation = immediate_set_aliases.get(operation, operation)
    set_operations = {"seq", "sne", "sge", "sgt", "sle", "sgeu", "sgtu", "sleu"}
    if set_operation in set_operations:
        immediate = operation in immediate_set_aliases or not _looks_like_register(operands[2])
        set_loaded: list[tuple[str, tuple[str, ...]]] = []
        right = operands[2]
        remaining = 1 if set_operation in {"sgt", "sgtu"} else 2
        if immediate:
            if parse_register(operands[1], source) == 1:
                raise AssemblyError(
                    "A230", "$at cannot be an input when an immediate needs expansion", source
                )
            set_loaded = _expand_load(
                "$at",
                operands[2],
                symbols=symbols,
                source=source,
                expected_words=expected_words - remaining,
            )
            right = "$at"
        if set_operation in {"seq", "sne"}:
            finish = "sltiu" if set_operation == "seq" else "sltu"
            final_operands = (
                (operands[0], "$at", "1")
                if set_operation == "seq"
                else (operands[0], "$zero", "$at")
            )
            return [
                *set_loaded,
                ("xor", ("$at", operands[1], right)),
                (finish, final_operands),
            ]
        unsigned = set_operation.endswith("u")
        compare = "sltu" if unsigned else "slt"
        if set_operation in {"sgt", "sgtu"}:
            return [*set_loaded, (compare, (operands[0], right, operands[1]))]
        reverse = set_operation.startswith("sle")
        left = right if reverse else operands[1]
        compare_right = operands[1] if reverse else right
        return [
            *set_loaded,
            (compare, (operands[0], left, compare_right)),
            ("xori", (operands[0], operands[0], "1")),
        ]
    if operation == "abs":
        return [
            ("addu", (operands[0], operands[1], "$zero")),
            ("bgez", (operands[1], str(address + 12))),
            ("sub", (operands[0], "$zero", operands[1])),
        ]
    if operation in {"rem", "remu"}:
        divide = "divu" if operation == "remu" else "div"
        return [(divide, (operands[1], operands[2])), ("mfhi", (operands[0],))]
    if operation in {"rol", "ror"}:
        if _looks_like_register(operands[2]):
            if operation == "ror":
                return [("rotrv", (operands[0], operands[1], operands[2]))]
            if parse_register(operands[1], source) == 1:
                raise AssemblyError(
                    "A230", "$at cannot hold the rotate input when a temporary is needed", source
                )
            return [
                ("subu", ("$at", "$zero", operands[2])),
                ("rotrv", (operands[0], operands[1], "$at")),
            ]
        amount = evaluate(operands[2], symbols, source)
        if not 0 <= amount <= 31:
            raise AssemblyError("A219", "rotate amount must be between 0 and 31", source)
        selected = (-amount) & 31 if operation == "rol" else amount
        return [("rotr", (operands[0], operands[1], str(selected)))]
    if operation == "push":
        return [
            ("addiu", ("$sp", "$sp", "-4")),
            ("sw", (operands[0], "0($sp)")),
        ]
    if operation == "pop":
        return [
            ("lw", (operands[0], "0($sp)")),
            ("addiu", ("$sp", "$sp", "4")),
        ]
    if operation == "begin":
        return [
            ("addiu", ("$sp", "$sp", "-4")),
            ("sw", ("$fp", "0($sp)")),
            ("addu", ("$fp", "$sp", "$zero")),
        ]
    if operation == "end":
        return [
            ("addiu", ("$sp", "$fp", "4")),
            ("lw", ("$fp", "0($fp)")),
        ]
    trap_aliases = {
        "tgt": "tlt",
        "tgtu": "tltu",
        "tle": "tge",
        "tleu": "tgeu",
    }
    if operation in trap_aliases:
        return [(trap_aliases[operation], (operands[1], operands[0]))]
    immediate_trap_aliases = {
        "tgti": "tlt",
        "tgtiu": "tltu",
        "tlei": "tge",
        "tleiu": "tgeu",
    }
    if operation in immediate_trap_aliases:
        if parse_register(operands[0], source) == 1:
            raise AssemblyError(
                "A230", "$at cannot be compared when an immediate needs expansion", source
            )
        loaded = _expand_load(
            "$at",
            operands[1],
            symbols=symbols,
            source=source,
            expected_words=expected_words - 1,
        )
        return [*loaded, (immediate_trap_aliases[operation], ("$at", operands[0]))]
    raise AssertionError(f"unhandled pseudo instruction {operation}")


def _branch_immediate(
    target_text: str, address: int, symbols: Mapping[str, int], source: SourceRef
) -> int:
    target = evaluate(target_text, symbols, source)
    if target & 3:
        raise AssemblyError("A220", f"branch target 0x{target:x} is not word aligned", source)
    offset = (target - (address + 4)) // 4
    return require_signed(offset, 16, source, "branch offset")


def _encode_real(
    operation: str,
    operands: Sequence[str],
    *,
    address: int,
    symbols: Mapping[str, int],
    source: SourceRef,
) -> int:
    def register(text: str) -> int:
        return parse_register(text, source)

    def expression(text: str) -> int:
        return evaluate(text, symbols, source)

    if operation in R3_FUNCTS:
        _operand_count(operation, operands, 3, source)
        rd, rs, rt = map(register, operands)
        return encode_r(rs, rt, rd, 0, R3_FUNCTS[operation])
    if operation in SHIFT_IMMEDIATE_FUNCTS:
        _operand_count(operation, operands, 3, source)
        rd, rt = register(operands[0]), register(operands[1])
        shamt = require_unsigned(expression(operands[2]), 5, source, "shift amount")
        return encode_r(0, rt, rd, shamt, SHIFT_IMMEDIATE_FUNCTS[operation])
    if operation in SHIFT_VARIABLE_FUNCTS:
        _operand_count(operation, operands, 3, source)
        rd, rt, rs = map(register, operands)
        return encode_r(rs, rt, rd, 0, SHIFT_VARIABLE_FUNCTS[operation])
    if operation == "rotr":
        _operand_count(operation, operands, 3, source)
        rd, rt = register(operands[0]), register(operands[1])
        shamt = require_unsigned(expression(operands[2]), 5, source, "rotate amount")
        return encode_r(1, rt, rd, shamt, 0x02)
    if operation == "rotrv":
        _operand_count(operation, operands, 3, source)
        rd, rt, rs = map(register, operands)
        return encode_r(rs, rt, rd, 1, 0x06)
    if operation in I_SIGNED_OPCODES:
        _operand_count(operation, operands, 3, source)
        rt, rs = register(operands[0]), register(operands[1])
        immediate = require_signed_or_bit_pattern(expression(operands[2]), 16, source, "immediate")
        return encode_i(I_SIGNED_OPCODES[operation], rs, rt, immediate)
    if operation in I_UNSIGNED_OPCODES:
        _operand_count(operation, operands, 3, source)
        rt, rs = register(operands[0]), register(operands[1])
        immediate = require_unsigned(expression(operands[2]), 16, source, "immediate")
        return encode_i(I_UNSIGNED_OPCODES[operation], rs, rt, immediate)
    if operation == "lui":
        _operand_count(operation, operands, 2, source)
        rt = register(operands[0])
        immediate = require_unsigned(expression(operands[1]), 16, source, "immediate")
        return encode_i(0x0F, 0, rt, immediate)
    if operation in BRANCH2_OPCODES:
        _operand_count(operation, operands, 3, source)
        rs, rt = register(operands[0]), register(operands[1])
        return encode_i(
            BRANCH2_OPCODES[operation],
            rs,
            rt,
            _branch_immediate(operands[2], address, symbols, source),
        )
    if operation in BRANCH1_OPCODES:
        _operand_count(operation, operands, 2, source)
        rs = register(operands[0])
        return encode_i(
            BRANCH1_OPCODES[operation],
            rs,
            0,
            _branch_immediate(operands[1], address, symbols, source),
        )
    if operation in REGIMM_RT:
        _operand_count(operation, operands, 2, source)
        rs = register(operands[0])
        return encode_i(
            0x01,
            rs,
            REGIMM_RT[operation],
            _branch_immediate(operands[1], address, symbols, source),
        )
    if operation in TRAP_I_RT:
        _operand_count(operation, operands, 2, source)
        rs = register(operands[0])
        immediate = require_signed_or_bit_pattern(
            expression(operands[1]), 16, source, "trap immediate"
        )
        return encode_i(0x01, rs, TRAP_I_RT[operation], immediate)
    if operation in {"j", "jal"}:
        _operand_count(operation, operands, 1, source)
        target = expression(operands[0])
        if target & 3:
            raise AssemblyError("A221", f"jump target 0x{target:x} is not word aligned", source)
        if (target & 0xF000_0000) != ((address + 4) & 0xF000_0000):
            raise AssemblyError("A222", "jump target is outside the current 256 MiB region", source)
        return encode_j(0x02 if operation == "j" else 0x03, target >> 2)
    if operation == "jr":
        _operand_count(operation, operands, 1, source)
        return encode_r(register(operands[0]), 0, 0, 0, 0x08)
    if operation == "jalr":
        _operand_count(operation, operands, (1, 2), source)
        rd, rs = (
            (31, register(operands[0]))
            if len(operands) == 1
            else (
                register(operands[0]),
                register(operands[1]),
            )
        )
        return encode_r(rs, 0, rd, 0, 0x09)
    if operation in {"movz", "movn"}:
        _operand_count(operation, operands, 3, source)
        rd, rs, rt = map(register, operands)
        return encode_r(rs, rt, rd, 0, 0x0A if operation == "movz" else 0x0B)
    if operation in {"syscall", "break"}:
        _operand_count(operation, operands, (0, 1), source)
        code = 0 if not operands else require_unsigned(expression(operands[0]), 20, source, "code")
        funct = 0x0C if operation == "syscall" else 0x0D
        return (code << 6) | funct
    if operation in {"mfhi", "mflo"}:
        _operand_count(operation, operands, 1, source)
        return encode_r(0, 0, register(operands[0]), 0, 0x10 if operation == "mfhi" else 0x12)
    if operation in {"mthi", "mtlo"}:
        _operand_count(operation, operands, 1, source)
        return encode_r(register(operands[0]), 0, 0, 0, 0x11 if operation == "mthi" else 0x13)
    if operation in {"mult", "multu", "div", "divu"}:
        _operand_count(operation, operands, 2, source)
        rs, rt = map(register, operands)
        funct = {"mult": 0x18, "multu": 0x19, "div": 0x1A, "divu": 0x1B}[operation]
        return encode_r(rs, rt, 0, 0, funct)
    if operation in TRAP_R_FUNCTS:
        _operand_count(operation, operands, (2, 3), source)
        rs, rt = register(operands[0]), register(operands[1])
        code = (
            0
            if len(operands) == 2
            else require_unsigned(expression(operands[2]), 10, source, "trap code")
        )
        return encode_r(rs, rt, 0, 0, TRAP_R_FUNCTS[operation]) | (code << 6)
    if operation in SPECIAL2_ACCUM_FUNCTS:
        _operand_count(operation, operands, 2, source)
        rs, rt = map(register, operands)
        return (0x1C << 26) | encode_r(rs, rt, 0, 0, SPECIAL2_ACCUM_FUNCTS[operation])
    if operation in {"mul", "clz", "clo"}:
        _operand_count(operation, operands, 3 if operation == "mul" else 2, source)
        rd = register(operands[0])
        rs = register(operands[1])
        rt = register(operands[2]) if operation == "mul" else 0
        funct = {"mul": 0x02, "clz": 0x20, "clo": 0x21}[operation]
        return (0x1C << 26) | encode_r(rs, rt, rd, 0, funct)
    if operation in {"seb", "seh"}:
        _operand_count(operation, operands, 2, source)
        rd, rt = map(register, operands)
        shamt = 0x10 if operation == "seb" else 0x18
        return (0x1F << 26) | encode_r(0, rt, rd, shamt, 0x20)
    if operation in {"mfc1", "mtc1"}:
        _operand_count(operation, operands, 2, source)
        rt = register(operands[0])
        fs = parse_fpu_register(operands[1], source)
        selector = 0 if operation == "mfc1" else 4
        return (0x11 << 26) | (selector << 21) | (rt << 16) | (fs << 11)
    if operation in MEMORY_OPCODES or operation in FPU_MEMORY_OPCODES:
        _operand_count(operation, operands, 2, source)
        rt = (
            register(operands[0])
            if operation in MEMORY_OPCODES
            else parse_fpu_register(operands[0], source)
        )
        if operation in {"ldc1", "sdc1"} and (rt & 1 or rt == 31):
            raise AssemblyError(
                "A232",
                f"{operation} requires an even floating-point register from $f0 to $f30",
                source,
            )
        match = _MEMORY_OPERAND.fullmatch(operands[1].strip())
        if match is None:
            raise AssemblyError(
                "A223", f"expected offset(base) memory operand, got {operands[1]!r}", source
            )
        offset_text = match.group(1).strip() or "0"
        rs = register(match.group(2))
        offset = require_signed_or_bit_pattern(expression(offset_text), 16, source, "memory offset")
        opcode = (
            MEMORY_OPCODES[operation]
            if operation in MEMORY_OPCODES
            else FPU_MEMORY_OPCODES[operation]
        )
        return encode_i(opcode, rs, rt, offset)
    raise AssertionError(f"unhandled real instruction {operation}")


def _emit_directive(
    item: _LocatedStatement,
    *,
    symbols: Mapping[str, int],
    text_words: list[int],
    data: bytearray,
    data_initialized: bytearray,
    ktext_words: list[int],
    kdata: bytearray,
    kdata_initialized: bytearray,
    source_map: dict[int, SourceMapEntry],
) -> None:
    statement = item.statement
    operation = statement.operation
    assert operation is not None
    operands = statement.operands
    if operation in {".globl", ".global", ".eqv", ".equ", ".align", ".balign"}:
        return
    if item.section is Section.DATA:
        selected_data = data
        selected_initialized = data_initialized
        selected_data_base = DATA_BASE
    elif item.section is Section.KDATA:
        selected_data = kdata
        selected_initialized = kdata_initialized
        selected_data_base = KDATA_BASE
    else:
        selected_data = bytearray()
        selected_initialized = bytearray()
        selected_data_base = 0
    if operation in {".ascii", ".asciiz"}:
        offset = item.address - selected_data_base
        for operand in operands:
            payload = _decode_string(operand, statement.source)
            selected_data[offset : offset + len(payload)] = payload
            selected_initialized[offset : offset + len(payload)] = b"\x01" * len(payload)
            offset += len(payload)
            if operation == ".asciiz":
                selected_data[offset] = 0
                selected_initialized[offset] = 1
                offset += 1
        return
    if operation == ".space":
        return
    if operation in {".float", ".double"}:
        offset = item.address - selected_data_base
        fmt = "<f" if operation == ".float" else "<d"
        width = struct.calcsize(fmt)
        for operand in operands:
            try:
                payload = struct.pack(fmt, float(operand))
            except (OverflowError, ValueError) as error:
                raise AssemblyError(
                    "A224", f"invalid floating-point literal {operand!r}", statement.source
                ) from error
            selected_data[offset : offset + width] = payload
            selected_initialized[offset : offset + width] = b"\x01" * width
            offset += width
        return
    widths = {".byte": 1, ".half": 2, ".word": 4}
    if operation not in widths:
        raise AssertionError(f"unhandled directive {operation}")
    width = widths[operation]
    for index, operand in enumerate(operands):
        value = evaluate(operand, symbols, statement.source)
        minimum = -(1 << (width * 8 - 1))
        maximum = (1 << (width * 8)) - 1
        if not minimum <= value <= maximum:
            raise AssemblyError(
                "A225",
                f"{operation} value {value} does not fit in {width} byte(s)",
                statement.source,
            )
        payload = int(value & ((1 << (width * 8)) - 1)).to_bytes(width, "little")
        address = item.address + index * width
        if item.section in _DATA_SECTIONS:
            offset = address - selected_data_base
            selected_data[offset : offset + width] = payload
            selected_initialized[offset : offset + width] = b"\x01" * width
        else:
            if width != 4:
                raise AssemblyError(
                    "A226", f"{operation} is not word-sized in .text", statement.source
                )
            selected_text = text_words if item.section is Section.TEXT else ktext_words
            selected_text_base = TEXT_BASE if item.section is Section.TEXT else KTEXT_BASE
            word_index = (address - selected_text_base) // 4
            selected_text[word_index] = int.from_bytes(payload, "little")
            source_map[address] = SourceMapEntry(statement.source, statement.source.text.strip())


def assemble(
    sources: Sequence[SourceUnit],
    *,
    require_main: bool = True,
    move_labels: Mapping[str, str] | None = None,
    limits: Limits = DEFAULT_LIMITS,
) -> Program:
    filenames = [unit.filename for unit in sources]
    if len(filenames) != len(set(filenames)):
        raise AssemblyError("A236", "assembly source filenames must be unique")
    statements = parse_sources(tuple(sources), limits=limits)
    first_pass = _first_pass(statements, limits)
    symbols = _public_symbols(first_pass)
    symbol_views = {
        filename: {**first_pass.global_symbols, **first_pass.local_symbols.get(filename, {})}
        for filename in filenames
    }
    for old, new in (move_labels or {}).items():
        if new not in symbols:
            raise AssemblyError("A227", f"cannot move {old!r}: target symbol {new!r} is unknown")
        symbols[old] = symbols[new]
        for view in symbol_views.values():
            view[old] = symbols[new]
    if require_main and "main" not in symbols:
        candidates = [
            local["main"] for local in first_pass.local_symbols.values() if "main" in local
        ]
        if len(candidates) > 1:
            raise AssemblyError("A237", "multiple files define a non-global main label")
        raise AssemblyError("A228", "program has no main label")
    entry = symbols.get("main", TEXT_BASE)
    if (require_main or "main" in symbols) and (
        entry < TEXT_BASE or entry >= first_pass.text_end or entry & 3
    ):
        raise AssemblyError("A229", f"entry address 0x{entry:08x} is not executable text")

    text_words = [0] * ((first_pass.text_end - TEXT_BASE + 3) // 4)
    data = bytearray(first_pass.data_end - DATA_BASE)
    data_initialized = bytearray(first_pass.data_end - DATA_BASE)
    ktext_words = [0] * ((first_pass.ktext_end - KTEXT_BASE + 3) // 4)
    kdata = bytearray(first_pass.kdata_end - KDATA_BASE)
    kdata_initialized = bytearray(first_pass.kdata_end - KDATA_BASE)
    source_map: dict[int, SourceMapEntry] = {}

    for item in first_pass.located:
        statement = item.statement
        operation = statement.operation
        assert operation is not None
        visible_symbols = symbol_views[statement.source.filename]
        if operation.startswith("."):
            _emit_directive(
                item,
                symbols=visible_symbols,
                text_words=text_words,
                data=data,
                data_initialized=data_initialized,
                ktext_words=ktext_words,
                kdata=kdata,
                kdata_initialized=kdata_initialized,
                source_map=source_map,
            )
            continue
        expanded: list[tuple[str, tuple[str, ...]]]
        if operation in _PSEUDO_INSTRUCTIONS:
            expanded = _expand_pseudo(
                operation,
                statement.operands,
                address=item.address,
                symbols=visible_symbols,
                source=statement.source,
                expected_words=item.size // 4,
            )
        elif operation in {"div", "divu"} and len(statement.operands) == 3:
            expanded = [
                (operation, (statement.operands[1], statement.operands[2])),
                ("mflo", (statement.operands[0],)),
            ]
        else:
            expanded = [(operation, statement.operands)]
        if len(expanded) * 4 != item.size:
            raise AssertionError(
                f"pass size mismatch for {operation}: expected {item.size // 4}, "
                f"got {len(expanded)}"
            )
        for offset, (real_operation, operands) in enumerate(expanded):
            address = item.address + offset * 4
            word = _encode_real(
                real_operation,
                operands,
                address=address,
                symbols=visible_symbols,
                source=statement.source,
            )
            if item.section is Section.TEXT:
                selected_words = text_words
                selected_base = TEXT_BASE
            else:
                selected_words = ktext_words
                selected_base = KTEXT_BASE
            selected_words[(address - selected_base) // 4] = word
            rendered = f"{real_operation} {', '.join(operands)}".rstrip()
            source_map[address] = SourceMapEntry(statement.source, rendered)

    source_files = {unit.filename: unit.text for unit in sources}
    return Program.create(
        text_words=text_words,
        data=data,
        data_initialized=data_initialized,
        ktext_words=ktext_words,
        kdata=kdata,
        kdata_initialized=kdata_initialized,
        symbols=symbols,
        source_map=source_map,
        entry=entry,
        source_files=source_files,
    )
