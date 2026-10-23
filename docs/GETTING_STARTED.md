# Getting started

You can use csetty-mips in your browser or from a terminal. Both run the same
Python engine; MIPS Studio adds a visual debugger and control-flow map.

## In your browser

Open [MIPS Studio](https://mips.jiarui.academy/). There is nothing to install.

1. Choose **Sum a loop** from **Examples**, or use **Open .s** to open a local
   assembly file.
2. Click **Assemble**, then **Step** to follow execution or **Run** to finish.
   Click the editor gutter beside an instruction to set a breakpoint.
3. Watch the registers and logic map as the program runs. **Back** undoes a step;
   **Reset** starts the program over.

For programs that read input, type in **Terminal** and press Enter. If execution
is waiting for input, it continues automatically. Shift+Enter adds a newline
without sending yet.

For a large program, use the function selector or search to find a function.
Fold a branch or loop group to hide its body, then expand it when you need the
details. The map is inferred from assembly control flow, so unusual jumps may
not form a simple if/else or loop.

Programs run locally in the browser. The server serves the application files;
it does not execute your assembly.

## From a terminal

Install the package in a Python 3.11+ virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install csetty-mips
```

On Windows PowerShell, use `.venv\Scripts\Activate.ps1` to activate it instead.

Save this as `sum.s`:

```asm
.text
.globl main
main:
    li   $t0, 1
    li   $s0, 0

loop:
    add  $s0, $s0, $t0
    addi $t0, $t0, 1
    ble  $t0, 5, loop

    move $a0, $s0
    li   $v0, 1
    syscall
    li   $a0, '\n'
    li   $v0, 11
    syscall
    li   $v0, 10
    syscall
```

Run it:

```sh
csetty-mips sum.s
```

It prints `15`. To check the assembly without running it, use
`csetty-mips --check sum.s`.

## Step forward, then back

Open the same program in the command-line debugger:

```sh
csetty-mips --interactive sum.s
```

At the `(csetty-mips)` prompt, enter:

```text
break loop
run
step
print $s0
back
print $s0
delete all
continue
quit
```

`run` starts from the beginning and stops before the first instruction at
`loop`. After `step`, `$s0` is `1`. After `back`, it is `0` again. `delete all`
removes the breakpoint, and `continue` finishes the sum.

Use `continue` when you want to resume: `run` restarts the program. Command-line
`step` advances one machine instruction, so a pseudo-instruction may take more
than one step. The web debugger also offers source-level stepping.

## When a program stops with an error

The diagnostic names the file, line, and instruction that failed.

- **Uninitialized register or memory:** write a value before reading it.
  `.space` reserves bytes but does not initialize them; use `.word 0` for an
  initialized zero word.
- **Unaligned address (R204):** word loads and stores need an address divisible
  by four. Check both the label and the offset. `.word` aligns automatically;
  use `.align 2` when reserving a word buffer with `.space`.
- **Instruction limit:** first check for an unintended loop. For a longer
  command-line run, raise the limit with `--max-steps`, for example
  `csetty-mips --max-steps 20000000 sum.s`.

In the debugger, inspect the registers and source before retrying. `back` can
undo an earlier successful instruction; it does not change your source file.

See the [reference](SPEC.md) for instructions, syscalls, memory layout, and
debugger commands. The [README](../README.md#python-api) has a Python API example.
