# csetty-mips implementation and acceptance matrix

Baseline: 2026-08-06
Scope: standalone `src/csetty_mips` package
Legend: `verified` means implemented and covered by executable local evidence.

Current verification snapshot:

- package suite: `282 passed, 1 skipped` (the skip is only the optional local
  SPIM executable check);
- Ruff: clean; strict mypy: clean for all 17 `csetty_mips` Python modules;
- fresh-wheel installation and execution: Python 3.12/macOS;
- independent SPIM 8.0 overlap output: `15|-128|14`, identical to
  `csetty-mips`;
- one-time post-implementation comparison on the original local corpus:
  92/92 expected exit/stdout cases matched the pinned private upstream runner.

## Product capabilities

| Capability | Status | Evidence |
|---|---|---|
| Multi-file UTF-8 parser and source diagnostics | verified | core, contract, CLI negative tests |
| Local symbols plus explicit cross-file globals | verified | duplicate, invisible, and successful linkage tests |
| Safe C-like expressions, constants, `%hi`/`%lo` | verified | precedence, legacy literal, short-circuit, depth/token/shift tests |
| Four-section two-pass assembler | verified | `.text/.data/.ktext/.kdata`, layout, alignment, pass-stability tests |
| Real word encoding and runtime decode | verified | 91-case exhaustive declared-instruction encoding table |
| Reserved-field validation and disassembly | verified | canonical encoding table and malformed-word runtime test |
| Bounded sparse segmented memory | verified | mapping, alignment, permissions, page-limit, atomic cross-page tests |
| Strict initialization and SPIM-relaxed mode | verified | register/FPR/`HI`/`LO`/memory and CLI-mode tests |
| Program `argc`/`argv` | verified | CLI argument end-to-end tests |
| Syscalls 1–17 | verified | integer/string/float/double/I/O/filesystem/exit tests |
| Sandboxed reversible filesystem | verified | flags, traversal, symlink, limits, reverse, stdio close, commit tests |
| Interactive debugger | verified | scripted load/run/inspect/control/error-recovery sessions |
| Breakpoints and integer/FPR/memory watchpoints | verified | scripted debugger and FPR expression tests |
| Reverse execution | verified | registers, memory/pages, input, output, heap, descriptors, files |
| Stable streaming CLI behavior | verified | subprocess, trace, hex, partial-output, UTF-8, usage tests |
| Typed public API and `py.typed` wheel data | verified | strict mypy and installed-wheel inspection |
| Independent SPIM overlap | verified | identical `15|-128|14` output in isolated SPIM 8.0 run |

## Real instructions

Every name below has an independent expected 32-bit encoding case. Semantic
tests exercise each family, edge values, taken/fallthrough control paths,
faulting atomicity, and all four offsets for unaligned word operations.

| Family | Instructions | Status |
|---|---|---|
| Trapping/wrapping arithmetic | `add addu addi addiu sub subu` | verified |
| Logical/immediate | `and andi or ori xor xori nor lui` | verified |
| Compare | `slt sltu slti sltiu` | verified |
| Shift/rotate | `sll sllv srl srlv sra srav rotr rotrv` | verified |
| Multiply/divide | `mult multu div divu mul` | verified |
| Accumulate | `madd maddu msub msubu` | verified |
| Special integer/move | `mfhi mthi mflo mtlo clz clo seb seh movz movn` | verified |
| Two-register branch | `beq bne` | verified |
| Sign branch/link | `blez bgtz bltz bgez bltzal bgezal` | verified |
| Jump/link | `j jal jr jalr` (one- and two-operand `jalr`) | verified |
| Aligned loads | `lb lbu lh lhu lw` | verified |
| Aligned stores | `sb sh sw` | verified |
| Unaligned word | `lwl lwr swl swr` | verified |
| Atomic | `ll sc` | verified |
| COP1 transfer/memory | `mfc1 mtc1 lwc1 ldc1 swc1 sdc1` | verified |
| Register traps | `tge tgeu tlt tltu teq tne` | verified |
| Immediate traps | `tgei tgeiu tlti tltiu teqi tnei` | verified |
| Control | `syscall break` | verified |

## Pseudo-instructions and overloads

| Family | Inventory | Status |
|---|---|---|
| Basic | `nop move clear not neg negu li la` | verified |
| Unconditional/zero branch | `b bal beqz bnez` | verified |
| Immediate branch overload | `beq bne` with a literal/expression | verified |
| Relational branch | `blt ble bgt bge bltu bleu bgtu bgeu` | verified |
| Relational set | `seq sne sge sgt sle sgeu sgtu sleu` | verified |
| Immediate set aliases | `seqi snei sgei sgti slei sequi sneui sgeui sgtui sleui` | verified |
| Arithmetic | `abs`, immediate `mul`, 3-operand `div/divu`, `rem/remu` | verified |
| Rotate | register/immediate `rol ror` | verified |
| Course stack frame | `push pop begin end` | verified |
| Trap aliases | `tgt tgtu tgti tgtiu tle tleu tlei tleiu` | verified |
| Address macros | label/expression, indirect, and combined symbolic memory forms | verified |
| Assembler temporary safety | `.set noat`, macro `$at` collision rejection | verified |

## Directives and source controls

| Inventory | Status | Notes |
|---|---|---|
| `.text .data .ktext .kdata` | verified | optional forward address, section limits, protected kernel ranges |
| `.globl .global` | verified | explicit multi-file export |
| `.eqv .equ` and `NAME = EXPR` | verified | source-scoped constants |
| `.align .balign` | verified | power-of-two and range validation |
| `.ascii .asciiz` | verified | multiple escaped UTF-8 strings |
| `.byte .half .word` | verified | range, endian, auto-alignment; `.word` also allowed in text |
| `.float .double` | verified | little-endian IEEE data emission |
| `.space` | verified | uninitialized allocation |
| `.set at/noat macro/nomacro push/pop reorder/noreorder` | verified | state resets per source file |

## Syscalls

| Services | Status | Evidence |
|---|---|---|
| `1, 2, 3, 4, 11` print values/strings/character | verified | exact format and output-limit atomicity |
| `5, 6, 7, 8, 12` read values/string/character | verified | prefix parsing, EOF, length edges, reversal |
| `9, 10, 17` allocation/exit | verified | alignment, mapping, bounds, status |
| `13, 14, 15, 16` file operations | verified | flags, limits, sandbox, stdio, reverse, commit |

## Safety and negative contracts

| Contract | Status |
|---|---|
| Source, statement, expression, symbol, section, page, step, history, input/output, string, path, file, and descriptor bounds | verified |
| Failed instructions restore all simulator-visible state | verified |
| Failed cross-page writes release partially allocated pages | verified |
| Reversed stores release pages created by the reversed instruction | verified |
| `SC` validates even a failed target and all writes invalidate reservation | verified |
| Kernel ranges cannot be read/written/executed in user mode | verified |
| Normal CLI has zero history unless requested; CLI history is capped | verified |
| Debugger `load` enforces aggregate source bytes and UTF-8 | verified |
| Host file writes are staged and require success/explicit commit | verified |

## Deliberate non-goals

| Capability | Status |
|---|---|
| Delay slots, big-endian mode, branch-likely instructions | intentionally unsupported |
| Privileged/kernel execution, MMU/TLB, interrupts | intentionally unsupported |
| COP1 arithmetic/comparison/rounding/exceptions | intentionally unsupported |
| Every instruction from every MIPS32 revision | intentionally unsupported |
| Undocumented or byte-identical upstream CLI/debugger behavior | intentionally unsupported |
| Upstream mipsy source or binary in this project | intentionally excluded |

## Acceptance commands

```sh
.venv/bin/ruff check src tests
.venv/bin/mypy src/csetty_mips
.venv/bin/pytest -q
python -m build --wheel
```

The wheel smoke gate installs into a fresh environment and checks the console
entry point, API execution, MPL licence file, component notice, and `py.typed`.
Downstream Docker, judge, question-bank, and VS Code acceptance belongs to
CSEExamTTY and is intentionally not part of this repository.
