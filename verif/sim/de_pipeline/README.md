# DE parent-pipeline integration fixture

`uqu_de_pipeline_tb.v` is verification-only core-parent wiring around
[uqu_stage_de](../de/README.md), the real GPR file and the shared hazard unit.
IF/DE and DE/EX validity, PCs, instruction payloads, source addresses/values,
capture masks and control/exception metadata live in the parent. Held EX
operands obtained from a departing producer are captured independently of
pipeline advancement. The fixture is not the production core.

```sh
make test COMPONENT=de_pipeline CONFIG=rv32i
make test COMPONENT=de_pipeline CONFIG=rv32i_retained
```

Use a complete configuration with EX-to-DE disabled to exercise admission via
MEM-to-EX guarantees. Both retention modes, stall-only dependencies, disabled
DE/MEM-to-EX paths, compressed alignment, RV32E and FF/latch GPR backends are
covered by the initial ten-profile sweep. The
[manifest](../../../config/sim/de_pipeline.yml) selects its parameters and tests.

- `dependencies`: adjacent producer/consumer transfers, an uncaptured source
  admitted through a future bypass, retention in a held EX slot as older work
  drains, WB/GPR visibility with forwarding disabled, and separate store data
  versus address-offset selection.
- `branch_faults`: a branch held by an unfinished load, registered-result
  forwarding or RF fallback, one-time resolution, permit-blocked exception
  admission, incoming fetch-fault priority and fault metadata association,
  parent flush and JALR target alignment.

Native instructions only: EX arithmetic and MEM/WB producer completion are
external stubs, with successful WB writes updating the actual GPR file. XIF
issue behavior is tested in the DE component suite; the fixture does not add
an XIF allocator, coprocessor or global controller. It does not implement IF
fetch/expansion, EX functional units, a memory bus, architectural retirement,
debug/interrupt arbitration or the complete core.
