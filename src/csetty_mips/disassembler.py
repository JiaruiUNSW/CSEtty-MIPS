from __future__ import annotations

from .integers import sign_extend
from .isa import is_supported_encoding, register_name

_R_NAMES = {
    0x00: "sll",
    0x02: "srl",
    0x03: "sra",
    0x04: "sllv",
    0x06: "srlv",
    0x07: "srav",
    0x08: "jr",
    0x09: "jalr",
    0x0A: "movz",
    0x0B: "movn",
    0x0C: "syscall",
    0x0D: "break",
    0x10: "mfhi",
    0x11: "mthi",
    0x12: "mflo",
    0x13: "mtlo",
    0x18: "mult",
    0x19: "multu",
    0x1A: "div",
    0x1B: "divu",
    0x20: "add",
    0x21: "addu",
    0x22: "sub",
    0x23: "subu",
    0x24: "and",
    0x25: "or",
    0x26: "xor",
    0x27: "nor",
    0x2A: "slt",
    0x2B: "sltu",
    0x30: "tge",
    0x31: "tgeu",
    0x32: "tlt",
    0x33: "tltu",
    0x34: "teq",
    0x36: "tne",
}

_I_NAMES = {
    0x08: "addi",
    0x09: "addiu",
    0x0A: "slti",
    0x0B: "sltiu",
    0x0C: "andi",
    0x0D: "ori",
    0x0E: "xori",
}

_MEMORY_NAMES = {
    0x20: "lb",
    0x21: "lh",
    0x22: "lwl",
    0x23: "lw",
    0x24: "lbu",
    0x25: "lhu",
    0x26: "lwr",
    0x28: "sb",
    0x29: "sh",
    0x2A: "swl",
    0x2B: "sw",
    0x2E: "swr",
    0x30: "ll",
    0x38: "sc",
}

_FPU_MEMORY_NAMES = {
    0x31: "lwc1",
    0x35: "ldc1",
    0x39: "swc1",
    0x3D: "sdc1",
}


def disassemble(word: int, pc: int) -> str:
    if not is_supported_encoding(word):
        return f".word 0x{word & 0xFFFF_FFFF:08x}"
    opcode = word >> 26
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    rd = (word >> 11) & 0x1F
    shamt = (word >> 6) & 0x1F
    funct = word & 0x3F
    immediate = word & 0xFFFF
    signed_immediate = sign_extend(immediate, 16)
    if opcode == 0:
        name = _R_NAMES.get(funct)
        if name is None:
            return f".word 0x{word:08x}"
        if name == "srl" and rs == 1:
            return f"rotr {register_name(rd)}, {register_name(rt)}, {shamt}"
        if name in {"sll", "srl", "sra"}:
            return f"{name} {register_name(rd)}, {register_name(rt)}, {shamt}"
        if name == "srlv" and shamt == 1:
            return f"rotrv {register_name(rd)}, {register_name(rt)}, {register_name(rs)}"
        if name in {"sllv", "srlv", "srav"}:
            return f"{name} {register_name(rd)}, {register_name(rt)}, {register_name(rs)}"
        if name == "jr":
            return f"jr {register_name(rs)}"
        if name == "jalr":
            return f"jalr {register_name(rd)}, {register_name(rs)}"
        if name in {"movz", "movn"}:
            return f"{name} {register_name(rd)}, {register_name(rs)}, {register_name(rt)}"
        if name in {"syscall", "break"}:
            code = (word >> 6) & 0xFFFFF
            return name if code == 0 else f"{name} {code}"
        if name in {"mfhi", "mflo"}:
            return f"{name} {register_name(rd)}"
        if name in {"mthi", "mtlo"}:
            return f"{name} {register_name(rs)}"
        if name in {"mult", "multu", "div", "divu"}:
            return f"{name} {register_name(rs)}, {register_name(rt)}"
        if name in {"tge", "tgeu", "tlt", "tltu", "teq", "tne"}:
            code = (word >> 6) & 0x3FF
            suffix = "" if code == 0 else f", {code}"
            return f"{name} {register_name(rs)}, {register_name(rt)}{suffix}"
        return f"{name} {register_name(rd)}, {register_name(rs)}, {register_name(rt)}"
    if opcode == 0x01:
        trap_name = {
            0x08: "tgei",
            0x09: "tgeiu",
            0x0A: "tlti",
            0x0B: "tltiu",
            0x0C: "teqi",
            0x0E: "tnei",
        }.get(rt)
        if trap_name is not None:
            return f"{trap_name} {register_name(rs)}, {signed_immediate}"
        name = {0x00: "bltz", 0x01: "bgez", 0x10: "bltzal", 0x11: "bgezal"}.get(rt)
        if name is None:
            return f".word 0x{word:08x}"
        target = (pc + 4 + signed_immediate * 4) & 0xFFFF_FFFF
        return f"{name} {register_name(rs)}, 0x{target:08x}"
    if opcode in {0x02, 0x03}:
        target = ((pc + 4) & 0xF000_0000) | ((word & 0x03FF_FFFF) << 2)
        return f"{'j' if opcode == 0x02 else 'jal'} 0x{target:08x}"
    if opcode in {0x04, 0x05}:
        target = (pc + 4 + signed_immediate * 4) & 0xFFFF_FFFF
        name = "beq" if opcode == 0x04 else "bne"
        return f"{name} {register_name(rs)}, {register_name(rt)}, 0x{target:08x}"
    if opcode in {0x06, 0x07}:
        target = (pc + 4 + signed_immediate * 4) & 0xFFFF_FFFF
        name = "blez" if opcode == 0x06 else "bgtz"
        return f"{name} {register_name(rs)}, 0x{target:08x}"
    if opcode in _I_NAMES:
        value = immediate if opcode in {0x0C, 0x0D, 0x0E} else signed_immediate
        return f"{_I_NAMES[opcode]} {register_name(rt)}, {register_name(rs)}, {value}"
    if opcode == 0x0F:
        return f"lui {register_name(rt)}, {immediate}"
    if opcode == 0x11:
        name = {0: "mfc1", 4: "mtc1"}.get(rs)
        if name is None or word & 0x7FF:
            return f".word 0x{word:08x}"
        return f"{name} {register_name(rt)}, $f{rd}"
    if opcode == 0x1C:
        name = {
            0x00: "madd",
            0x01: "maddu",
            0x02: "mul",
            0x04: "msub",
            0x05: "msubu",
            0x20: "clz",
            0x21: "clo",
        }.get(funct)
        if name is None:
            return f".word 0x{word:08x}"
        if name in {"madd", "maddu", "msub", "msubu"}:
            return f"{name} {register_name(rs)}, {register_name(rt)}"
        if name == "mul":
            return f"mul {register_name(rd)}, {register_name(rs)}, {register_name(rt)}"
        return f"{name} {register_name(rd)}, {register_name(rs)}"
    if opcode == 0x1F and funct == 0x20 and rs == 0 and shamt in {0x10, 0x18}:
        name = "seb" if shamt == 0x10 else "seh"
        return f"{name} {register_name(rd)}, {register_name(rt)}"
    if opcode in _MEMORY_NAMES:
        return (
            f"{_MEMORY_NAMES[opcode]} {register_name(rt)}, {signed_immediate}({register_name(rs)})"
        )
    if opcode in _FPU_MEMORY_NAMES:
        return f"{_FPU_MEMORY_NAMES[opcode]} $f{rt}, {signed_immediate}({register_name(rs)})"
    return f".word 0x{word:08x}"
