# MEM with parent-owned pipeline registers

[uqu_mem_pipeline_tb.v](uqu_mem_pipeline_tb.v) wraps the real
[uqu_stage_mem](../../../src/uquintus/uqu_stage_mem.v) in EX/MEM and MEM/WB registers owned
by the verification parent. PC, original instruction, destination, and decoded
control travel in these parent registers. Only boundary validity resets; payloads
need no reset. `flush_i` kills MEM/EX-MEM only, leaving older MEM/WB work intact.

The parent also instantiates one two-port PMP block. Its IF port is unused;
its MEM port consumes the stage's query and returns its permission result.
`ISA_PMP` selects that block. Configuration/address inputs are supplied by the
testbench as the stand-in for CSR-owned state. This verifies parent ownership
and routing without duplicating PMP inside MEM or implementing a CSR controller.

```sh
make test COMPONENT=mem_pipeline CONFIG=rv32i
make lint COMPONENT=mem_pipeline CONFIG=rv32i
```

Repeat with a complete hardware configuration containing `ISA_PMP: 1` to test
protection. The test uses one unlocked read/write NAPOT region at 0x1000–0x1fff;
its independent reference checks complete coverage, M-mode bypass, and U-mode
default denial. Both enabled and disabled configurations pass the same suites:

- `turnover`: 24 alternating loads/stores with next-cycle responses sustain
  one grant and one WB completion per clock after pipeline fill.
- `pipeline`: 64 pass-through tokens at one transfer per cycle, then 512 mixed
  load/store/pass/fault tokens under independent input, bus, permission, and WB
  stalls. A FIFO scoreboard checks order, data, flags, faults, load readiness,
  and exact PC/instruction/destination association. Bus grant counting proves
  one request per nonfaulting memory instruction. Byte-memory results freeze at grant so
  subsequent stores cannot change an older load's expected value.
- `drain_flush`: an older load waits in WB while a younger store is held in
  MEM. A MEM-only flush preserves that older response and discards the younger
  token. A separately presented store request survives cancellation through
  grant/response; its killed error cannot leak into later tokens.

The fixture models WB completion by consuming the independent LSU response
channel with the retained MEM/WB identity. Actual architectural WB/CSR behavior
is tested separately and in the controller-parent/core regressions.

This is a MEM integration fixture, not a full core or architectural WB/retirement
implementation. See the [stage interface guide](../mem/README.md).
