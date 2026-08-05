# csetty-mips specification

Status: implemented standalone package contract, revision 4
Baseline date: 2026-08-06

## 1. Scope and compatibility target

`csetty-mips` is an independently implemented educational MIPS32 assembler,
simulator, disassembler, and time-travel debugger. This revision covers the
standalone Python package in `src/csetty_mips` and the `csetty-mips` command.
CSEExamTTY consumes the released package as an external dependency; its course
command and container integration are outside this repository.

The compatibility target is the public COMP1521/mipsy teaching surface:

- the current public COMP1521 MIPS instruction, pseudo-instruction, directive,
  memory, and syscall guide;
- the public product properties claimed by mipsy: source-aware diagnostics,
  initialization checks, an interactive debugger, and reverse execution; and
- independently specified MIPS32 instruction encodings and integer semantics.

This is not a claim to implement every MIPS32 revision, privileged operation,
or undocumented behavior of a particular mipsy build. The exact supported
surface and deliberate non-goals are normative below.

## 2. Independence and licensing

This is not a fork, port, translation, or vendored copy of `insou22/mipsy`.
Upstream source, tests, tables, generated files, assets, and diagnostic wording
are not implementation inputs and are not distributed in the package. Public
upstream pages are used only to identify user-visible claims and an openly
published compatibility surface.

The implementation is covered by this repository's MPL-2.0 `LICENSE`.
Functional facts such as architectural register numbers, instruction names,
binary encodings, and syscall numbers are independently recorded in local code
and tests. See `docs/PROVENANCE.md` for the clean-room ledger.

## 3. Public interfaces

The installed command is:

```text
csetty-mips [OPTIONS] FILE... [-- PROGRAM_ARG...]
csetty-mips                         # interactive debugger without a program
csetty-mips --interactive FILE...
csetty-mips --check FILE...
csetty-mips --check-no-main FILE...
csetty-mips --compile FILE...
csetty-mips --hex [--hex-pad-zero] FILE...
csetty-mips --move-label OLD=NEW FILE...
csetty-mips --version
```

Execution options are `--trace`, `--max-steps`, `--history`, `--fs-root`, and
`--relaxed`/`--spim`. Diagnostics go to stderr, program output goes to stdout,
and already-produced output is retained if a later instruction faults. Exit
codes are 0 for success, 1 for assembly/runtime failure, 2 for invalid command
usage, and 130 for interruption. Syscall 17 is returned modulo 256 by the CLI.

The typed Python API exports `assemble`, `SourceUnit`, `Program`, `Machine`,
`Debugger`, `Limits`, `DEFAULT_LIMITS`, and the public error classes. A
`py.typed` marker is included in the wheel.

## 4. Architectural and memory model

- 32 general-purpose 32-bit registers, immutable `$zero`, `HI`, `LO`, and a
  32-bit `PC`; `$s0`–`$s7`, `$gp`, `$sp`, `$fp`, `$ra`, `argc`, and `argv` have
  defined entry values, while temporary registers remain initialization-checked.
- 32 raw 32-bit floating-point registers for transfer/load/store and syscalls;
  pairs use an even low register for 64-bit values.
- Little-endian byte order and real 32-bit encoded instruction fetch/decode.
- No branch delay slots. Link instructions therefore store `PC + 4`.
- Program arguments after `--` are installed verbatim as the complete simulated
  `argv` and exposed as `argc`/`argv` in `$a0`/`$a1`; assembler source filenames
  are not inserted as an implicit `argv[0]`.

| Segment | Base | Contract |
|---|---:|---|
| user text | `0x00400000` | initial 256 KiB, writable and executable |
| user data/heap | `0x10000000` | initial 256 KiB, grows to at most 1 MiB |
| stack | below `0x7fffeffc` | sparse, bounded to 256 KiB |
| kernel text | `0x80000000` | emitted by assembler but protected in user execution |
| kernel data | `0x90000000` | emitted by assembler but protected in user execution |

Memory is sparse, permission checked, alignment checked, initialization tracked,
and page bounded. Every simulated write is transactional, including page
allocation. Reverse execution restores byte values, initialized bits, and pages
created by the reversed instruction. `--relaxed`/`--spim` changes uninitialized
register, `HI`/`LO`, FPR, and memory reads to zero; all other safety checks remain.

## 5. Source language and assembler

The parser accepts multiple uniquely named UTF-8 files, `#`/`;` comments,
multiple labels, named/numeric registers, escaped string and character literals,
legacy octal plus binary/decimal/hex integers, memory operands, constant
assignments, and source expressions. Expressions are parsed without `eval` and
support C-like unary, arithmetic, shift, comparison, bitwise, and short-circuit
logical operators plus `%hi(...)` and `%lo(...)`.

Symbols are local to a source file unless declared with `.globl`/`.global`.
Duplicate local/global definitions, invisible cross-file references, invalid
entry points, pass-size disagreement, ranges, alignment, and reserved `$at`
collisions are diagnosed with stable source-linked codes.

Supported directives:

```text
.text .data .ktext .kdata
.globl .global .set .eqv .equ
.align .balign
.ascii .asciiz .byte .half .word .float .double .space
```

`.set at/noat`, `.set macro/nomacro`, and `.set push/pop` are enforced per
source file. `.set reorder/noreorder` are accepted; the assembler itself never
reorders instructions.

Supported real instructions (91 total):

```text
add addu addi addiu sub subu
and andi or ori xor xori nor lui
slt sltu slti sltiu
sll sllv srl srlv sra srav rotr rotrv
mult multu div divu madd maddu msub msubu mul
mfhi mthi mflo mtlo clz clo seb seh movz movn
beq bne blez bgtz bltz bgez bltzal bgezal
j jal jr jalr
lb lbu lh lhu lw lwl lwr sb sh sw swl swr ll sc
mfc1 mtc1 lwc1 ldc1 swc1 sdc1
tge tgeu tlt tltu teq tne tgei tgeiu tlti tltiu teqi tnei
syscall break
```

Supported pseudo-instructions and course overloads:

```text
nop move clear not neg negu li la
b bal beq-immediate bne-immediate beqz bnez
blt ble bgt bge bltu bleu bgtu bgeu
seq sne sge sgt sle sgeu sgtu sleu
seqi snei sgei sgti slei sequi sneui sgeui sgtui sleui
abs mul-immediate div-3-operand divu-3-operand rem remu rol ror
push pop begin end tgt tgtu tgti tgtiu tle tleu tlei tleiu
symbolic and full-width memory-address forms
```

Assembler passes assign all four sections, expand pseudos deterministically,
resolve local/global symbols and expressions, emit data plus real instruction
words, validate canonical reserved fields, and create a per-word source map.
The runtime executes emitted words rather than parser objects.

## 6. Runtime services

All public COMP1521 services 1–17 are implemented:

| Service | Operation |
|---:|---|
| 1 | print signed integer |
| 2 | print single precision (`%.8f`) |
| 3 | print double precision (`%.18g`) |
| 4 | print NUL-terminated byte string |
| 5 | read integer with `atol`-style prefix semantics |
| 6 | read single precision with `atof`-style prefix semantics |
| 7 | read double precision with `atof`-style prefix semantics |
| 8 | bounded, NUL-terminated line input |
| 9 | aligned and bounded `sbrk` |
| 10 | exit with status 0 |
| 11 | print low byte as a character |
| 12 | read a character, returning `-1` at EOF |
| 13 | open a sandboxed file |
| 14 | read from a file descriptor |
| 15 | write to a file descriptor |
| 16 | close a file descriptor, including standard descriptors |
| 17 | exit with the supplied status |

File services operate on a reversible virtual filesystem. Host access is
disabled unless an existing `--fs-root` is explicitly supplied. Absolute paths,
parent traversal, backslashes, NULs, symlink traversal, and paths outside the
root are rejected. Writes remain staged during simulation. A successful normal
CLI run commits dirty files using per-file atomic replacement; the debugger
requires `commit-files`, which clears history because host commits cannot be
reversed.

## 7. Diagnostics and debugger

Strict mode reports source-linked faults for uninitialized state, overflow on
trapping arithmetic, division by zero, true traps, reserved encodings,
misalignment, unmapped/protected memory, output/input limits, and instruction
limits. A failed instruction restores all simulator state before reporting.

The debugger supports:

```text
load run continue step back
break delete breaks watch unwatch
print registers fregisters examine disassemble
context labels output commit-files reset help quit
```

Targets may be labels, numeric addresses, or `file:line`. Watchpoints cover
integer registers, FPRs, and memory bytes. A bounded step record restores PC,
register/FPR initialization, `HI`/`LO`, reservation, heap/data boundary, sparse
pages, input position, buffered output, exit state, standard descriptors, and
virtual filesystem state.

Normal non-debug CLI execution records no history unless `--history` is given.
The API/debugger default is 10,000 records, and the CLI rejects values over
100,000.

## 8. Default resource limits

Defaults are configurable through `Limits` and include 1 MiB source, 250,000
statements, 100,000 symbols, 64K user-text words, 16K kernel-text words, 1 MiB
for each data section, 256 KiB stack, 8,192 allocated pages, 10 million executed
instructions, 16 MiB input, 4 MiB output, 1 MiB tokens/strings, 64 open files,
16 MiB per file, and 64 MiB total virtual-file data.

## 9. Deliberate non-goals

- big-endian execution, branch delay slots, branch-likely instructions;
- privileged/kernel execution, exceptions/interrupts, MMU/TLB behavior;
- floating-point arithmetic, comparison, rounding modes, or FP exceptions
  (raw COP1 transfers, memory operations, and I/O syscalls are supported);
- every instruction from every MIPS32 revision; and
- byte-for-byte reproduction of undocumented mipsy CLI/debugger wording.

Unsupported instructions and syscalls fail explicitly; they are never silently
treated as no-ops.

## 10. Package acceptance

Completion of this package requires:

- Ruff and strict mypy success for `src/csetty_mips`;
- exhaustive declared-instruction encoding coverage plus semantic family,
  boundary, atomicity, parser, directive, pseudo, syscall, filesystem,
  debugger, reverse-execution, CLI, and resource-limit tests;
- independently authored instruction, runtime, and SPIM-overlap fixtures passing;
- an optional SPIM black-box overlap fixture with identical output;
- a built wheel that installs, exposes `csetty-mips`, imports the typed API, and
  runs on supported Python 3.11+ environments.

Course integration is specified and verified separately by the downstream
CSEExamTTY project.
