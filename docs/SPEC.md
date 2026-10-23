# MIPS and debugger reference

This page covers the command-line tool, assembly syntax, supported instructions,
and runtime behavior. For a first program and a debugging walkthrough, see
[Getting started](GETTING_STARTED.md).

- [Command line](#command-line)
- [Registers and memory](#registers-and-memory)
- [Assembly syntax](#assembly-syntax)
- [Instructions](#instructions)
- [Syscalls and files](#syscalls-and-files)
- [Debugger](#debugger)
- [Limits](#limits)
- [Unsupported features](#unsupported-features)

## Command line

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

With no filename, `csetty-mips` opens the debugger; use `load FILE...` there to
load a program. Pass several filenames to assemble them together.

| Option | Use it to |
|---|---|
| `--check` / `--compile` | Assemble without running the program |
| `--check-no-main` | Check a file that has no `main`, such as a data-only file |
| `--hex`, `--hex-pad-zero` | Print encoded instruction words, optionally padded to eight hex digits |
| `--trace` | Follow executed instructions in a normal command-line run |
| `--max-steps N` | Set the instruction limit |
| `--history N` | Set how many steps can be reversed |
| `--fs-root DIR` | Allow file syscalls inside an existing directory |
| `--relaxed` / `--spim` | Read uninitialized registers and memory as zero |
| `--move-label OLD=NEW` | Resolve references to `OLD` through `NEW` |

Program output goes to stdout; diagnostics go to stderr. Output already printed
is kept if the program later fails. Exit codes are `0` for success, `1` for an
assembly or runtime error, `2` for invalid command usage, and `130` for an
interrupted run. A status supplied to syscall 17 is returned modulo 256.

For Python use, the package exports `assemble`, `SourceUnit`, `Program`,
`Machine`, `Debugger`, `Limits`, `DEFAULT_LIMITS`, and error classes. Type hints
are included. See the [Python example](../README.md#python-api).

## Registers and memory

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

| Segment | Base | Size and access |
|---|---:|---|
| user text | `0x00400000` | initial 256 KiB, writable and executable |
| user data/heap | `0x10000000` | initial 256 KiB, grows to at most 1 MiB |
| stack | below `0x7fffeffc` | sparse, bounded to 256 KiB |
| kernel text | `0x80000000` | emitted by assembler but protected in user execution |
| kernel data | `0x90000000` | emitted by assembler but protected in user execution |

Memory is allocated as needed. Reading uninitialized bytes, using a misaligned
address, or accessing protected memory raises an error. A failed write leaves
memory unchanged. Stepping backward restores the old bytes and initialization
state, and releases pages created by that instruction.

`--relaxed`/`--spim` reads uninitialized registers, `HI`/`LO`, floating-point
registers, and memory as zero. It does not turn off alignment, access, or
resource-limit checks.

## Assembly syntax

Source files use UTF-8. You can use `#` or `;` comments, named or numeric
registers, multiple labels at one address, escaped strings and characters, and
binary, octal, decimal, or hexadecimal integers. Constants and operands accept
C-like unary, arithmetic, shift, comparison, bitwise, and short-circuit logical
expressions, plus `%hi(...)` and `%lo(...)`. Each source file needs a unique name
when passed to the Python API.

Symbols are local to a source file unless declared with `.globl`/`.global`.
If another file needs to call a function or access a label, export that symbol.
Duplicate definitions, unknown symbols, invalid operands, and unsafe uses of
`$at` are reported at the relevant source line.

Define constants with `NAME = EXPR`, `.eqv`, or `.equ`:

```asm
COUNT = 5
.eqv STEP, 1
.equ BYTES, COUNT * 4
```

### Directives

The supported directives are:

```text
.text .data .ktext .kdata
.globl .global .set .eqv .equ
.align .balign
.ascii .asciiz .byte .half .word .float .double .space
```

`.space` reserves uninitialized bytes. Use a data directive such as `.word 0`
when you need an initialized value. `.half`, `.word`, `.float`, and `.double`
automatically align their data.

### Alignment

`.align N` advances to a multiple of `2**N` bytes. A label immediately before
the directive points to the aligned storage, not the padding:

```asm
.data
prefix: .byte 1, 2, 3
buffer:
    .align 2
    .space 4
```

Here `buffer` is word-aligned, but still needs a store before a load. Putting
the label on the `.align` line has the same effect. Multiple labels for the
same storage move together, including exported labels.

An alignment can move a label until that section emits a nonempty object or
instruction. Consecutive alignments, empty strings, `.space 0`, metadata, and
switching away from a section and back within one file do not end that group.
An explicit change of section origin or the end of a source file does. Already
emitted data never moves. Constants keep the value calculated when they were
defined, even if a label used in that calculation moves later.

`.align 0` adds no padding; it does not disable automatic typed-data alignment.
`.balign` takes a power-of-two byte count instead of an exponent, so
`.balign 4` aligns like `.align 2`. It is a csetty-mips extension.

Padding is uninitialized and counts toward the section limit. Ordinary
`lw`/`sw` still require four-byte alignment; `lh`/`sh` require two-byte alignment.

`.set at/noat`, `.set macro/nomacro`, and `.set push/pop` are enforced per
source file. `.set reorder/noreorder` are accepted; the assembler itself never
reorders instructions.

## Instructions

The following 91 instructions are supported:

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

### Pseudo-instructions

These expand into one or more machine instructions:

```text
nop move clear not neg negu li la
b bal beqz bnez
blt ble bgt bge bltu bleu bgtu bgeu
seq sne sge sgt sle sgeu sgtu sleu
seqi snei sgei sgti slei sequi sneui sgeui sgtui sleui
abs rem remu rol ror
push pop begin end tgt tgtu tgti tgtiu tle tleu tlei tleiu
```

The assembler also accepts immediate operands, shorter operand lists, and
symbolic or full-width memory addresses where described below. For example:

```asm
add  $t0, $t1, 1     # Add an immediate value
addi $t0, 1          # Equivalent to addi $t0, $t0, 1
div  $t2, $t1, 2     # Store the quotient in $t2
```

For `add`, `addu`, `sub`, `subu`, `and`, `or`, `xor`, `nor`, `slt`, `sltu`, and
`mul`, either source may be one 32-bit immediate expression. A two-operand form
uses the destination as the left source. At most one source may be immediate;
it is materialized through `$at`, preserving the selected real instruction's
overflow and wrapping semantics.

The same single-immediate rule applies to the two-source `mult`, `multu`,
`div`, `divu`, `tge`, `tgeu`, `tlt`, `tltu`, `teq`, and `tne` forms. `mthi` and
`mtlo` accept an immediate source. `addi`, `addiu`, `andi`, `ori`, `xori`,
`slti`, and `sltiu` accept `op $d, immediate` as `op $d, $d, immediate`.

Integer shifts accept two-operand self forms. `sll`, `srl`, `sra`, `sllv`,
`srlv`, `srav`, and `rotrv` also accept one immediate value source. `clz`,
`clo`, `seb`, and `seh` accept one-operand self forms. `abs`, `neg`, `negu`, and
`not` accept one-operand self forms, and `not` additionally accepts an immediate
source.

Either compared value in `beq`, `bne`, the relational branch family, or the
relational set family may be the single immediate source. The dividend or
divisor in three-operand `div`, `divu`, `rem`, and `remu` may likewise be the
single immediate. Two-operand `rem`/`remu` and `rol`/`ror` use the destination as
the first source. All expansions honor `.set noat`, `.set nomacro`, and `$at`
input-collision checks.

Pseudo-instructions execute as their expanded machine instructions. In the
command-line debugger, `step` advances one of those instructions, not
necessarily a whole source line. The disassembler shows the expanded form.

## Syscalls and files

Set `$v0` to the service number, supply its arguments, then execute `syscall`.
The supported services are:

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

### File access

File operations use a virtual filesystem. To allow access to host files, pass
an existing directory with `--fs-root DIR`. Paths must stay within that
directory: absolute paths, parent traversal, backslashes, NULs, and symlinks
are rejected.

Writes are staged while the program runs. A successful normal CLI run commits
changed files; in the debugger, use `commit-files` to save them explicitly.
Each file is replaced atomically, but the files are saved one at a time. If a
later save fails, earlier files stay changed.

`commit-files` clears step history even when a save fails. Changes already
saved to the host filesystem cannot be undone with `back`.

## Debugger

Start with `csetty-mips --interactive program.s`, or run `csetty-mips` without
arguments and enter `load program.s` at the prompt.

```text
run                       restart from the beginning and run
continue                  resume from the current instruction
step [N]                  execute N machine instructions (default 1)
back [N]                  undo N recorded instructions (default 1)
break TARGET              stop before a label, address, or file:line
delete TARGET|all         remove breakpoints
breaks                    list breakpoints
watch $REG|$fN|ADDRESS     stop when a register or memory byte changes
unwatch TARGET|all        remove watchpoints
print EXPR                inspect a register, symbol, or expression
registers                 show integer registers
fregisters                show raw floating-point registers
examine ADDRESS [COUNT]   show memory words (default 1)
disassemble [ADDR] [N]    show decoded instructions (default 10)
context                   show the current source and instruction
labels                    list labels and addresses
output                    show buffered program output
commit-files              save staged files under --fs-root
reset                     restore the initial machine state
help                      list commands
quit                      leave the debugger
```

For example, `break loop` stops before the instruction at `loop`, `print $t0`
shows a register, and `watch $s0` stops when `$s0` changes. Breakpoint targets
may also be numeric addresses or locations such as `sum.s:9`.

`back` restores registers, `HI`/`LO`, memory, input position, buffered output,
exit state, and virtual files. It also restores initialization state, heap
boundaries, allocated pages, descriptors, and the `ll`/`sc` reservation. It
cannot erase text that has already appeared in your terminal; use `output` to
see the program's current output buffer.

Normal non-debug CLI execution records no history unless `--history` is given.
The API and debugger keep a bounded history; see [Limits](#limits) below.

### Errors

Execution stops on uninitialized reads, signed overflow in trapping arithmetic,
division by zero, true trap conditions, invalid encodings, misaligned or
protected addresses, and exceeded limits. The diagnostic points to the source
line where available. A failed instruction leaves the simulator at its
pre-instruction state, so you can inspect it in the debugger.

## Limits

The Python package uses the defaults below. Pass a `Limits` object to the
Python API to change them; the CLI exposes `--max-steps` and `--history`.
MIPS Studio uses separate limits for interactive browser sessions.

| Resource | Default |
|---|---:|
| Source text | 1 MiB |
| Statements / symbols | 250,000 / 100,000 |
| User / kernel text | 64K / 16K instruction words |
| User / kernel data | 1 MiB each |
| Stack | 256 KiB |
| Allocated memory pages | 8,192 |
| Executed instructions | 10 million |
| Recorded history | 10,000 steps in the API/debugger; none in a normal CLI run |
| Input / output | 16 MiB / 4 MiB |
| Input tokens / strings | 1 MiB each |
| Open files | 64 |
| File path | 4,096 bytes |
| One virtual file / all virtual files | 16 MiB / 64 MiB |

The CLI accepts at most 100,000 history records.

## Unsupported features

- big-endian execution, branch delay slots, branch-likely instructions;
- privileged/kernel execution, exceptions/interrupts, MMU/TLB behavior;
- floating-point arithmetic, comparison, rounding modes, or FP exceptions
  (raw COP1 transfers, memory operations, and I/O syscalls are supported);
- instructions outside the list above.

Unsupported instructions and syscalls produce an error; they are not treated
as no-ops. For tests and past compatibility comparisons, see
[Test coverage](ACCEPTANCE_MATRIX.md).
