# Alignment-label maintenance audit

Version: `0.1.4`, based on commit
`ccede7ae84a0c6b5d2b85d19792dfd81bbdde7e9` (public engine 0.1.3).

## Cause and implementation

A standalone label was immediately assigned the pre-padding section cursor.
Later `.align` and typed-data alignment advanced storage without updating that
label. Inline `.align` labels also explicitly used the old cursor. Inline typed
data happened to work, so the existing data-layout tests did not expose this.

The first pass now tracks labels awaiting storage independently per section.
Padding moves only those labels and their exported bindings. Nonempty objects
and instructions commit the pending group. Constants are not labels and retain
their original evaluated values. File boundaries and explicit origin changes
end the relevant pending group. Parser, encoding, runtime alignment faults and
instruction semantics are unchanged.

## Black-box comparison

Only independently written, nonsensitive probes were entered into the public
[COMP1521 mipsy web UI](https://cgi.cse.unsw.edu.au/~cs1521/mipsy/).
No upstream source, JavaScript, WASM, assets or diagnostics were used as
implementation material. The [course guide](https://cgi.cse.unsw.edu.au/~cs1521/26T2/resources/mips-guide.html)
supplies the public directive contract. Absolute data bases differ between
environments, so probes compare offsets relative to an aligned base label.

Each combined case starts with three bytes. Observed offsets were:

| Case | Offset(s) |
|---|---|
| Standalone label before `.align 2` | 4 |
| Inline label on `.align 2` | 4 |
| Standalone label before `.word`, `.half`, `.float` | 4 each |
| Standalone label before `.double` | 8 |
| Two aliases before `.align 2` | 4, 4 |
| Aliases across `.align 2` then `.align 3` | 8, 8 |
| Label on `.space 0` / empty `.ascii`, then `.align 2` | 4 each |
| Label on a nonempty byte, followed by alignment | old object 3, new object 8 |
| `.space` without alignment | 3 |
| `.align 0` before a word | 4 |
| `.align 0`, positive alignment, then another unaligned word | automatically aligned |
| `.align 0` then `.data` and a word | 4 |
| Intervening `.globl`, repeated `.data`, or a text-section round trip | 4 each |

These are 18 case definitions in one original program. Four further probes
confirmed: a captured constant stays at offset 3 while its label moves to 4;
text labels move through padding; kernel-data labels move through padding;
and `.balign` is rejected by that UI. `.balign` remains a documented local
extension, not an asserted mipsy-compatible directive. Multi-file boundaries,
explicit origins and negative/limit cases are local API regressions, not claims
of behavior observed in the single-file web UI.

## Regression coverage

The 75 new parameterized tests cover explicit alignment, automatic typed-data
alignment and bytes/initialization, aliases, metadata, zero-sized allocations,
section round trips, constant snapshots, cross-file exports, file boundaries,
origin changes, text/kernel sections, runtime store/load and reversal, deliberate
misalignment, invalid arguments, duplicates, symbol limits and data limits.

Validation commands:

```sh
ruff check src tests
mypy src/csetty_mips
pytest -q
python -m build
```

Local validation on 2026-10-21: 716 tests passed, with only the optional SPIM
executable test skipped. Ruff and strict mypy (17 modules) passed. Wheel metadata
and source-archive contents were inspected, including the new tests and fixtures.

No user coursework is included in this repository or distribution. A private
source was checked locally without modifying it; this is not a claim that every
path in that program or every assembler dialect is compatible.
