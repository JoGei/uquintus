# DE parent-pipeline integration fixture

`uqu_de_pipeline_tb.v` is verification-only core-parent wiring around
[uqu_stage_de](../de/README.md), the real GPR file and the shared hazard unit.
IF/DE and DE/EX validity, PCs, instruction payloads, source addresses/values,
capture masks and control/exception metadata live in the parent. Held EX
operands obtained from a departing producer are captured independently of
pipeline advancement. The fixture is not the production core.
In IF placement it instantiates the actual `uqu_decompressor` before IF/DE;
in DE placement that RTL sits inside the real DE adapter after IF/DE. Direct
mode uses the real `uqu_decoder_c` after the same register. Every mode accepts
raw selected compressed instruction bits; Python does not pre-expand them.

```sh
make test COMPONENT=de_pipeline CONFIG=rv32i
make test COMPONENT=de_pipeline CONFIG=rv32i_retained
make test COMPONENT=de_pipeline CONFIG=rv32ic
make test COMPONENT=de_pipeline CONFIG=rv32ic_decompress_de
make test COMPONENT=de_pipeline CONFIG=rv32ic_decoder_c
```

Use a complete configuration with EX-to-DE disabled to exercise admission via
MEM-to-EX guarantees. Both retention modes, stall-only dependencies, disabled
DE/MEM-to-EX paths, compressed alignment, RV32E and FF/latch GPR backends are
covered by the initial ten-profile sweep. The
[manifest](../../../config/sim/de_pipeline.yml) selects its parameters and tests.
The fixture forwards both compressed-decode selectors to DE. The strategy
sweep additionally runs all four suites for all three C-enabled strategies;
it still supplies selected instruction tokens rather than implementing fetch.
The placement sweep covers I+C, E+C with operand retention, and stall-only
forwarding settings for each strategy, plus C-disabled handling. Boundary
outputs expose original/normalized bits, length, faults and call links for
independent checks through stalls and replacement.

- `dependencies`: adjacent producer/consumer transfers, an uncaptured source
  admitted through a future bypass, retention in a held EX slot as older work
  drains, WB/GPR visibility with forwarding disabled, and separate store data
  versus address-offset selection.
- `branch_faults`: a branch held by an unfinished load, registered-result
  forwarding or RF fallback, one-time resolution, permit-blocked exception
  admission, incoming fetch-fault priority and fault metadata association,
  parent flush and JALR target alignment.
- `compressed_tokens`: held compressed calls resolve once; compressed ALU
  controls use real GPR values; reserved encodings preserve original fault bits
  across permit stalls; prior fetch faults win; flush discards a held call;
  original length controls PC+2 versus PC+4 links; C-disabled tokens fault.
- `compressed_stream`: a scoreboard follows mixed 16-/32-bit tokens through
  both parent registers under randomized downstream backpressure and permit
  stalls. It checks encoding, original bits, length, PC wraparound, one-time
  branch resolution and links without drops, duplication or stale metadata.

Native instructions only: EX arithmetic and MEM/WB producer completion are
external stubs, with successful WB writes updating the actual GPR file. XIF
issue behavior is tested in the DE component suite; the fixture does not add
an XIF allocator, coprocessor or global controller. It does not implement IF
bus fetching, alignment/stitching, EX functional units, architectural retirement,
debug/interrupt arbitration or the complete core.
