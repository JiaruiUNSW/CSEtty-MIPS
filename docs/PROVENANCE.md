# csetty-mips provenance record

Baseline date: 2026-08-06
Covered implementation: `src/csetty_mips`

## Independence rule

`csetty-mips` is a new implementation. It is not a fork, translation, port, or
refactoring of `insou22/mipsy`. No upstream source file, test, table, generated
artifact, asset, diagnostic string, or documentation prose is included in or
used to derive the implementation.

The upstream repository was inspected at its public project page only to:

1. confirm that the reviewed tree did not present an explicit redistribution
   licence; and
2. identify public product-level claims such as educational focus, diagnostics,
   initialization checks, debugging, reverse execution, and stated non-goals.

Those public claims are a compatibility target, not an implementation source.

## Reference ledger

| Reference | Permitted use in this implementation |
|---|---|
| [Public mipsy project page](https://github.com/insou22/mipsy) | Product-level feature/non-goal inventory and licensing decision only |
| [COMP1521 26T2 public MIPS guide](https://cgi.cse.unsw.edu.au/~cs1521/26T2/resources/mips-guide.html) | Public instruction, pseudo, directive, memory, expression, and syscall contract |
| [MIPS32 Instruction Set, revision 5.04](https://cgi.cse.unsw.edu.au/~cs1521/26T2/resources/MIPS32-II-r5.04.pdf) | Architectural encodings and integer operation semantics |
| Independently installed SPIM 8.0 executable | Optional black-box input/output comparison for overlapping behavior only |
| Original CSEExamTTY MIPS programs and expected output | Independent end-to-end acceptance corpus |
| Preserved pinned upstream executable | One-time post-implementation black-box integration comparison on the already-authored local corpus only |
| Python standard-library documentation | Parser, integer, binary packing, filesystem, and CLI behavior |

The MIPS32 document is used for functional and architectural facts only; its
text and diagrams are not copied. SPIM source is not consulted or incorporated.

## Prohibited material

- Source, tests, tables, generated files, error strings, UI prose, or assets
  from `insou22/mipsy`.
- Course-assignment solutions whose redistribution rights are not established,
  including earlier student implementations.
- Copied fixtures, reference solutions, or diagnostics from university
  infrastructure.
- Reverse engineering of a private or term-specific binary to reproduce
  undocumented details.

## Independent design ledger

- The scanner/parser, expression parser, two-pass section assembler, pseudo
  expansion, encoders, decoder, disassembler, sparse memory, runtime, syscall
  layer, virtual filesystem, debugger, and reversible step record are original
  Python modules under `src/csetty_mips`.
- Error namespaces and wording (`P`, `A`, `R`, `D`, `I`) are locally designed.
- The instruction encoding matrix states expected words directly from
  architectural field definitions and covers every declared real instruction.
- Semantic tests use ordinary Python integer/byte calculations as independent
  oracles and fixed random seeds; unaligned operations cover every byte offset.
- The SPIM fixture is locally authored and compares only stdout for a small
  documented overlap. It is not imported from SPIM or mipsy.
- The question-bank acceptance set consists of local original programs and
  expected outputs.

## Post-implementation integration comparison

After the independent implementation and its original expected-output corpus
were complete, the project owner requested a consistency check before course
integration. A preserved private executable at commit
`61f96b38626c30c2ead7925486304f163ec56b2b` was treated only as a black box and
run against 92 already-authored local reference cases. Exit status and successful
program stdout matched in all 92 cases. A separate boundary check found and
corrected the public `argc`/`argv` convention; assembly/runtime diagnostic text
and output channel were deliberately not copied or normalized.

This comparison happened after implementation, introduced no upstream fixture,
table, diagnostic string, or asset, and is not an automated dependency or a
persistent regression corpus. The independent local expected outputs remain the
authoritative tests.

## Distribution record

The `csetty_mips` modules contain no runtime dependency on, executable from, or
vendored content belonging to mipsy. They are distributed under the repository
MPL-2.0 `LICENSE`; a component-specific 2026 copyright `NOTICE` and `py.typed`
are included as package data. The independently usable console entry point is
`csetty-mips`, avoiding an assertion that this package is the upstream program.

CSEExamTTY consumes this package as a separately versioned dependency. Any
compatibility launcher or container integration belongs to that downstream
project and does not add upstream mipsy source or binary to this repository.

## Maintenance rule

When the supported surface changes:

1. add the operation to `docs/SPEC.md` and `docs/ACCEPTANCE_MATRIX.md`;
2. add independently authored encoding, semantic, boundary, and negative tests;
3. record any new public architectural reference here; and
4. do not use an unlicensed implementation as an implementation input, shortcut,
   fixture source, or persistent regression corpus.
