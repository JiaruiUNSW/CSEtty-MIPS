# Public mipsy operand-overload audit — 2026-08-19

## Scope and method

The public [COMP1521 mipsy web](https://cgi.cse.unsw.edu.au/~cs1521/mipsy/)
was used as a black-box interoperability oracle after
`add $a1, $a2, 1` failed in `csetty-mips 0.1.2`. No upstream source, JavaScript,
WebAssembly, source map, diagnostic text, or asset was inspected or copied.

Six locally authored probe groups plus a symmetry follow-up executed 338
assemblies covering 330 unique integer operand forms. The public UI accepted
152 unique forms. Duplicate executions were retained only to cross-check
overlapping categories. The independent architecture/semantic tests remain
authoritative; the web result defines only the compatibility surface described
below.

## Confirmed overload families

| Family | Confirmed accepted forms |
|---|---|
| Three-source arithmetic/logical/compare | `add addu sub subu and or xor nor slt sltu mul`: either source may be one immediate; two immediate sources are rejected |
| Two-operand self arithmetic | The same family accepts `op $d, $r` and `op $d, immediate`, using `$d` as the left source |
| Immediate-instruction self shorthand | `addi addiu andi ori xori slti sltiu $d, immediate` |
| HI/LO arithmetic | `mult multu div divu` accept one immediate on either side; `mthi mtlo` accept an immediate |
| Real traps | `tge tgeu tlt tltu teq tne` accept one immediate on either side |
| Branch comparisons | `beq bne` and `blt ble bgt bge bltu bleu bgtu bgeu` accept one immediate on either side |
| Relational sets | `seq sne sge sgt sle sgeu sgtu sleu` accept one immediate on either side |
| Shift value source | `sll srl sra sllv srlv srav rotrv` accept an immediate value source; shift-count operand types remain unchanged |
| Shift self shorthand | `sll srl sra rotr sllv srlv srav rotrv` accept two operands, using `$d` as the shifted value |
| Unary self shorthand | `abs neg negu not clz clo seb seh $d`; `not` also accepts an immediate source |
| Result division/remainder | Three-operand `div` accepts one immediate on either side; `rem/remu` accept one immediate on either side |
| Remainder/rotate self shorthand | `rem remu rol ror` accept two operands, using `$d` as the first source |

## Confirmed boundaries

- Two immediate source values in one register-register operation were rejected.
- Variable shift counts still require a register; immediate shift instructions
  still require an immediate count.
- `movz`, `movn`, `clz`, `clo`, `seb`, and `seh` did not accept an immediate
  source; only the latter four accepted a one-operand self form.
- `madd`, `maddu`, `msub`, and `msubu` did not accept immediate sources.
- `jr`, `jalr`, CPU/FPU transfer operands, store values, and branch-on-zero
  sources did not accept immediate replacements.
- `ulw`, `usw`, `ulh`, `ulhu`, `ush`, `subi`, and `subiu` were rejected.
- Three-operand result-form `divu` rejected an immediate dividend or divisor;
  its all-register form remains supported.
- `tgt`, `tgtu`, `tle`, and `tleu` did not overload an operand with an
  immediate; their explicit `*i` aliases remain the supported immediate forms.

## Local safety and deliberate differences

`csetty-mips` materializes a single 32-bit expression through `$at` and rejects
source collisions instead of silently destroying an input. `.set noat` and
`.set nomacro` are enforced for every new overload. The implementation accepts
both three-operand `divu $d, $r, immediate` and `divu $d, immediate, $r` even
though the audited public UI rejected them; these are intentional regularity
extensions, not a claim of byte-identical compatibility.
