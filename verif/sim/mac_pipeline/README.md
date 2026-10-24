# Late-C MAC pipeline

`MUA_MUL: dadda_mac` is the canonical split PP/Dadda/BK implementation: product-only compression in EX1, exactly two registered rows, and late C through a 3:2 layer before the final MEM/EX2 addition. Older EX1-fused MAC and three-row cuts have been removed.

C travels in a 32-bit parent-owned payload with a source address, captured flag and accumulate tag. The core hazard unit resolves C from registered WB or an authoritative captured payload. It cannot use a pending younger producer's older WB value, a live LSU response, a stale RF value or a second XIF destination. Ready C is captured if the consumer stalls, so the supplying WB slot may drain independently. No additional GPR port arbitration is introduced. Native multiply operations force C=0; division stays in the original local MDU.

The fixture instantiates the actual `uqu_hazard`, `uqu_gpregfile`, `uqu_stage_ex` and `uqu_stage_mem`, with parent-owned EX, MEM and WB slots. It accepts internal MAC/MUL transactions identified by register addresses and maintains architectural register storage through WB. It adds no instruction encoding. The core's ordinary decoder does not yet emit MAC, so core software regressions verify native instruction behavior, not software-executable MAC.

```sh
make test COMPONENT=mac_pipeline CONFIG=rv32im_dadda_mac PYTHON=.venv/bin/python
make test COMPONENT=hazard CONFIG=rv32im_dadda_mac PYTHON=.venv/bin/python
make test COMPONENT=mem CONFIG=rv32im_dadda_mac PYTHON=.venv/bin/python
.venv/bin/python -m unittest scripts.tests.test_mul_late_accumulate
```

The pipeline tests cover:

- 128 C-dependent MACs with consecutive issue and retirement clocks under forwarding; A/B dependencies still stall.
- Youngest-producer priority, overlapping register names, x0 writes/reads, ordinary MUL mixed with MAC, and modulo-32 arithmetic.
- 1,088 transactions with randomized WB backpressure and stable stalled outputs; C retention across producer drain.
- Flush and synchronous reset of occupied EX/MEM slots, followed by clean reissue.

The same tests run with global forwarding disabled, with DE operand retention enabled and with all ordinary optional forwarding routes disabled. Global disable removes the one-clock recurrence guarantee. The dedicated late-C WB→EX2 route remains available when the ordinary EX bypass selectors are disabled.

`mem.late_mac` separately checks arbitrary 64-bit rows and 32-bit addends, missing-C backpressure, native high-half multiplication, exception drain and flush. `hazard.late_c` checks safe producer admission and registered-value qualification. A local Yosys SAT check proves, for arbitrary rows A/B, C and the accumulate selector, that both 32-bit halves of finishing equal A+B+(accumulate?zero_extend(C):0) modulo 2^64. Product generation is covered by the existing PP/Dadda proofs and full EX tests. This is a combinational leaf proof, not a whole-core formal verification claim.
