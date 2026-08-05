from __future__ import annotations

import difflib
import re

from .errors import AssemblyError, SourceRef

REGISTER_NAMES: tuple[str, ...] = (
    "zero",
    "at",
    "v0",
    "v1",
    "a0",
    "a1",
    "a2",
    "a3",
    "t0",
    "t1",
    "t2",
    "t3",
    "t4",
    "t5",
    "t6",
    "t7",
    "s0",
    "s1",
    "s2",
    "s3",
    "s4",
    "s5",
    "s6",
    "s7",
    "t8",
    "t9",
    "k0",
    "k1",
    "gp",
    "sp",
    "fp",
    "ra",
)

REGISTER_ALIASES: dict[str, int] = {name: index for index, name in enumerate(REGISTER_NAMES)}
REGISTER_ALIASES["s8"] = 30
for _index in range(32):
    REGISTER_ALIASES[str(_index)] = _index
    REGISTER_ALIASES[f"r{_index}"] = _index

R3_FUNCTS: dict[str, int] = {
    "add": 0x20,
    "addu": 0x21,
    "sub": 0x22,
    "subu": 0x23,
    "and": 0x24,
    "or": 0x25,
    "xor": 0x26,
    "nor": 0x27,
    "slt": 0x2A,
    "sltu": 0x2B,
}

SHIFT_IMMEDIATE_FUNCTS: dict[str, int] = {"sll": 0x00, "srl": 0x02, "sra": 0x03}
SHIFT_VARIABLE_FUNCTS: dict[str, int] = {"sllv": 0x04, "srlv": 0x06, "srav": 0x07}
SPECIAL2_ACCUM_FUNCTS: dict[str, int] = {
    "madd": 0x00,
    "maddu": 0x01,
    "msub": 0x04,
    "msubu": 0x05,
}
TRAP_R_FUNCTS: dict[str, int] = {
    "tge": 0x30,
    "tgeu": 0x31,
    "tlt": 0x32,
    "tltu": 0x33,
    "teq": 0x34,
    "tne": 0x36,
}

I_SIGNED_OPCODES: dict[str, int] = {
    "addi": 0x08,
    "addiu": 0x09,
    "slti": 0x0A,
    "sltiu": 0x0B,
}
I_UNSIGNED_OPCODES: dict[str, int] = {"andi": 0x0C, "ori": 0x0D, "xori": 0x0E}
BRANCH2_OPCODES: dict[str, int] = {"beq": 0x04, "bne": 0x05}
BRANCH1_OPCODES: dict[str, int] = {"blez": 0x06, "bgtz": 0x07}
REGIMM_RT: dict[str, int] = {"bltz": 0x00, "bgez": 0x01, "bltzal": 0x10, "bgezal": 0x11}
TRAP_I_RT: dict[str, int] = {
    "tgei": 0x08,
    "tgeiu": 0x09,
    "tlti": 0x0A,
    "tltiu": 0x0B,
    "teqi": 0x0C,
    "tnei": 0x0E,
}
MEMORY_OPCODES: dict[str, int] = {
    "lb": 0x20,
    "lh": 0x21,
    "lwl": 0x22,
    "lw": 0x23,
    "lbu": 0x24,
    "lhu": 0x25,
    "lwr": 0x26,
    "sb": 0x28,
    "sh": 0x29,
    "swl": 0x2A,
    "sw": 0x2B,
    "swr": 0x2E,
    "ll": 0x30,
    "sc": 0x38,
}
FPU_MEMORY_OPCODES: dict[str, int] = {
    "lwc1": 0x31,
    "ldc1": 0x35,
    "swc1": 0x39,
    "sdc1": 0x3D,
}

ALL_REAL_INSTRUCTIONS = frozenset(
    {
        *R3_FUNCTS,
        *SHIFT_IMMEDIATE_FUNCTS,
        *SHIFT_VARIABLE_FUNCTS,
        *SPECIAL2_ACCUM_FUNCTS,
        *TRAP_R_FUNCTS,
        *I_SIGNED_OPCODES,
        *I_UNSIGNED_OPCODES,
        *BRANCH2_OPCODES,
        *BRANCH1_OPCODES,
        *REGIMM_RT,
        *TRAP_I_RT,
        *MEMORY_OPCODES,
        *FPU_MEMORY_OPCODES,
        "j",
        "jal",
        "jr",
        "jalr",
        "movz",
        "movn",
        "syscall",
        "break",
        "mfhi",
        "mthi",
        "mflo",
        "mtlo",
        "mult",
        "multu",
        "div",
        "divu",
        "mul",
        "clz",
        "clo",
        "seb",
        "seh",
        "rotr",
        "rotrv",
        "lui",
        "mfc1",
        "mtc1",
    }
)

_REGISTER = re.compile(r"\$([A-Za-z0-9]+)\Z")
_FPU_REGISTER = re.compile(r"\$f([0-9]|[12][0-9]|3[01])\Z", re.IGNORECASE)


def parse_register(text: str, source: SourceRef) -> int:
    match = _REGISTER.fullmatch(text.strip())
    if match is None:
        raise AssemblyError("A200", f"expected a register, got {text!r}", source)
    name = match.group(1).lower()
    try:
        return REGISTER_ALIASES[name]
    except KeyError as error:
        choices = difflib.get_close_matches(name, REGISTER_ALIASES, n=1, cutoff=0.65)
        notes = (f"did you mean ${choices[0]}?",) if choices else ()
        raise AssemblyError("A201", f"unknown register ${name}", source, notes=notes) from error


def register_name(index: int) -> str:
    return f"${REGISTER_NAMES[index]}"


def parse_fpu_register(text: str, source: SourceRef) -> int:
    match = _FPU_REGISTER.fullmatch(text.strip())
    if match is None:
        raise AssemblyError("A231", f"expected a floating-point register, got {text!r}", source)
    return int(match.group(1))


def encode_r(rs: int, rt: int, rd: int, shamt: int, funct: int) -> int:
    return (rs << 21) | (rt << 16) | (rd << 11) | (shamt << 6) | funct


def encode_i(opcode: int, rs: int, rt: int, immediate: int) -> int:
    return (opcode << 26) | (rs << 21) | (rt << 16) | (immediate & 0xFFFF)


def encode_j(opcode: int, target: int) -> int:
    return (opcode << 26) | (target & 0x03FF_FFFF)


def is_supported_encoding(word: int) -> bool:
    """Return whether *word* is a canonical encoding understood by the runtime."""

    word &= 0xFFFF_FFFF
    opcode = word >> 26
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    rd = (word >> 11) & 0x1F
    shamt = (word >> 6) & 0x1F
    funct = word & 0x3F
    if opcode == 0:
        if funct == 0x00:
            return rs == 0
        if funct == 0x02:
            return rs in {0, 1}
        if funct == 0x03:
            return rs == 0
        if funct == 0x04:
            return shamt == 0
        if funct == 0x06:
            return shamt in {0, 1}
        if funct == 0x07:
            return shamt == 0
        if funct == 0x08:
            return rt == 0 and rd == 0 and shamt == 0
        if funct == 0x09:
            return rt == 0 and shamt == 0
        if funct in {0x0A, 0x0B}:
            return shamt == 0
        if funct in {0x0C, 0x0D}:
            return True
        if funct in {0x10, 0x12}:
            return rs == 0 and rt == 0 and shamt == 0
        if funct in {0x11, 0x13}:
            return rt == 0 and rd == 0 and shamt == 0
        if funct in {0x18, 0x19, 0x1A, 0x1B}:
            return rd == 0 and shamt == 0
        if funct in R3_FUNCTS.values():
            return shamt == 0
        return funct in TRAP_R_FUNCTS.values()
    if opcode == 0x01:
        return rt in {*REGIMM_RT.values(), *TRAP_I_RT.values()}
    if opcode in {0x02, 0x03, 0x04, 0x05}:
        return True
    if opcode in {0x06, 0x07}:
        return rt == 0
    if opcode in {*I_SIGNED_OPCODES.values(), *I_UNSIGNED_OPCODES.values()}:
        return True
    if opcode == 0x0F:
        return rs == 0
    if opcode == 0x11:
        return rs in {0, 4} and word & 0x7FF == 0
    if opcode == 0x1C:
        if funct in SPECIAL2_ACCUM_FUNCTS.values():
            return rd == 0 and shamt == 0
        if funct == 0x02:
            return shamt == 0
        if funct in {0x20, 0x21}:
            return rt == 0 and shamt == 0
        return False
    if opcode == 0x1F:
        return funct == 0x20 and rs == 0 and shamt in {0x10, 0x18}
    return opcode in {*MEMORY_OPCODES.values(), *FPU_MEMORY_OPCODES.values()}
