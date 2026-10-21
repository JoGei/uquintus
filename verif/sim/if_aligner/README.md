# IF instruction aligner

[uqu_if_aligner.v](../../../src/uquintus/uqu_if_aligner.v) selects one original
instruction from fetched words. It is combinational Verilog-2005, with only
`ISA_C` (default 0) as a parameter. There is no clock, reset, queue, handshake
state, bus port, PMP checker or decompressor in this component.

```sh
make test COMPONENT=if_aligner CONFIG=rv32i
make test COMPONENT=if_aligner CONFIG=rv32ic
make lint COMPONENT=if_aligner CONFIG=rv32ic
```

Use `PYTHON=.venv/bin/python` for the repository environment. The
[manifest](../../../config/sim/if_aligner.yml) uses the shared component runner.
The aligner is the same for `decompress/if`, `decompress/de` and
`decode_compressed`: its output is always the original selected instruction.

## Input words and ownership

| Input | Meaning |
| --- | --- |
| `valid_i`, `pc_i[31:0]` | A live instruction-selection candidate and its original PC. |
| `word0_valid_i`, `word0_data_i[31:0]`, `word0_error_i` | The containing fetched word at `{pc_i[31:2],2'b00}`, with its retained access-fault status. |
| `word1_valid_i`, `word1_data_i[31:0]`, `word1_error_i` | The next consecutive word, at containing-word address +4 modulo 2^32. |

The parent must supply words for those addresses, not merely arbitrary FIFO
slots. A future word buffer owns address association, storage, occupancy and
response capture. The [ifetch engine](../ifetch/README.md) supplies aligned words
and errors after checking the denial from the one core-owned PMP. Neither
requesting memory nor checking protection occurs in the aligner.

Invalid word data/error inputs are ignored. A valid second word cannot replace
a missing first word. The parent owns PC updates, accepted-transfer detection,
buffer consumption, redirects, invalidation and the IF/DE register.

## Outputs and consumption

| Output | Meaning |
| --- | --- |
| `valid_o` | A complete instruction or contained fetch-fault token is available. |
| `instr_o[31:0]` | Original 32-bit instruction, or original 16-bit instruction zero-extended; zero when unavailable or faulting. |
| `compressed_o` | Successful two-byte selection. Faults and invalid selections use zero; length is not trusted on faults. |
| `next_pc_o[31:0]` | PC+2 or PC+4 for a successful selection, modulo 2^32. Otherwise the input PC. |
| `drop_word_o` | The current word becomes fully consumed if this successful selection transfers. At most one word is released. |
| `word1_needed_o` | A successful first-word prefix identifies a 32-bit instruction starting in the upper halfword. High whether the second word is present or missing. |
| `misaligned_o` | Active candidate violates four-byte alignment with C disabled or two-byte alignment with C enabled. No instruction/fault token is emitted for this invalid input. |
| `exception_valid_o`, `exception_cause_o[4:0]`, `exception_tval_o[31:0]` | Selected fetch-access fault: cause 1 and the faulting instruction portion's byte address. Otherwise all zero. |

`drop_word_o` is a proposed action, not a pulse or independent handshake.
The parent may pop its buffer and apply `next_pc_o` only on an actual accepted
transfer, e.g. `valid_o && ready && permit`. Holding DE/IF must not consume
anything merely because the aligner's outputs remain asserted. A low-halfword
compressed instruction retains its word; an upper-halfword compressed or any
32-bit instruction releases exactly the old head word. A crossing 32-bit
instruction leaves the next word's upper halfword available for reuse.

After transferring a fault token, the parent must contain the fault, suppress
repeat delivery and wait for the appropriate redirect/invalidation. The aligner
keeps PC unchanged and proposes no word release on faults; it owns no fault-
issued tracking or architectural trap entry.

`misaligned_o` is a defensive input diagnostic. Architectural branch/jump
alignment faults remain with DE's branch unit and their originating instruction;
the core must not deliver an unvalidated misaligned target here and reattribute
its fault to a different instruction. Boot/return/debug PC rules remain with
their existing owners. Inactive candidates clear the diagnostic.

## Selection and faults

With C disabled, an aligned PC selects the complete first word and ignores its
prefix and all second-word inputs. With C enabled, the selected first halfword's
bits 1:0 distinguish 16-bit instructions from the core's 32-bit instruction
window. Compressed legality, expansion and native decode remain downstream.
Unsupported longer prefixes still deliver the first 32 bits for ILEN=32 decode
and diagnostics; this component does not fetch or execute longer instructions.

For a 32-bit instruction at 0x1002, word 0x1000 supplies instruction bits 15:0
from its upper halfword, and word 0x1004 supplies bits 31:16 from its lower
halfword. If the second word is missing, output validity stays low. For example,
word0=`0x00930001`, word1=`0x00010050` yields instruction `0x00500093`, next
PC 0x1006 and one released word. The compressed instruction at 0x1006 can then
reuse the upper halfword of the old word1.

| Condition | Result |
| --- | --- |
| Missing first word | Wait; do not infer length from invalid data. |
| First word has an error | Emit a fault immediately with tval=PC, without inspecting data or waiting for word1. |
| Selected instruction does not cross words | Ignore word1 validity, data and errors. |
| Crossing instruction, word1 missing | Wait; an error bit on an invalid word is ignored. |
| Crossing instruction, word1 has an error | Emit a fault with tval=PC+2, including wraparound to zero. |

Thus a first-word fault for an instruction at 0x1002 reports 0x1002, while a
second-word fault reports 0x1004. The original PC remains the instruction's
identity for later `mepc`; access-fault `tval` is independent of the normalized
instruction encoding. Fetch faults take priority over downstream illegality.

## Verification

The local [byte-window oracle](aligner_model.py) slices a little-endian byte
image and checks required-word availability/error membership independently of
the RTL's bit concatenations.

- `directed`: both halfword positions, invalid/missing words, error and enable
  combinations, misaligned-PC rejection, fault priority, known stitched values,
  short-instruction reuse, and PC/tval wraparound.
- `prefixes`: all 65,536 first halfwords at both positions, 131,072 selections
  for each C configuration, including reserved and unsupported prefixes.
- `randomized`: 16,384 candidates per seed with arbitrary data, PCs, availability,
  errors and candidate enable.
- `stream`: 128 original instructions across address wraparound, with a two-word
  buffer model, delayed word availability and randomized consumer stalls. It
  checks exact bits, lengths, next PCs and consumption, without word refetches.

Lint and Yosys checks find no flops, latches or memories in either configuration.
With C disabled, second-word inputs and compressed-length selection are removed;
the high half of word1 is unused in both configurations. Invalid `ISA_C` values
fail elaboration. These tests cover the aligner, not a hardware FIFO, actual
IF/DE registers, OBI/PMP transactions, the complete IF stage or full-core execution.
