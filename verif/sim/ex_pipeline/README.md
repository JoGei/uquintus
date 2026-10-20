# EX with parent-owned pipeline registers

[uqu_ex_pipeline_tb.v](uqu_ex_pipeline_tb.v) owns DE/EX and EX/MEM register sets
around the actual `uqu_stage_ex` DUT. It supplies stable decoded operands and metadata,
computes EX/MEM capacity, and captures EX outputs. This is verification RTL,
not the processor's full pipeline or hazard/forwarding implementation.

The parent retains PC, original instruction, destination register, decoded
controls/operands, pass data, store data, and incoming exception metadata in
DE/EX. EX/MEM captures result, store data, flags, updated exception metadata,
and the original instruction identity. Only validity resets; invalid payload
values are unspecified. There are no corresponding boundary registers in EX.

`flush_i` affects the EX instruction and DE/EX validity. It does not clear an
older EX/MEM instruction. An older occupied EX/MEM slot can drain while EX
continues multi-cycle computation, becoming empty until EX has a result.

```sh
make test COMPONENT=ex_pipeline CONFIG=rv32im
make test COMPONENT=ex_pipeline CONFIG=rv32i
make lint COMPONENT=ex_pipeline CONFIG=rv32im
```

`pipeline` scoreboards ordered input/output tokens with PC, instruction,
destination, result, store data, flags, and precise exceptions. It verifies
one-per-cycle ALU throughput across the two parent registers, then randomizes
operands, execution classes, operand readiness, and downstream backpressure.
Blocked EX/MEM outputs and blocked DE/EX identity must remain stable.

`drain_flush` checks an older MEM result draining while DIV occupies EX,
EX cancellation without a late result, EX-only flushing while older EX/MEM
payload is retained, and reset recovery. RV32I profiles explicitly exercise
disabled-M exceptions in the randomized stream and pass-through cancellation
in the drain scenario. The [standalone stage tests](../ex/README.md) additionally
cover request uniqueness and precise execution latencies without boundary delay.

All three MUL styles and unroll factors 1, 2, 4, 8, 16, and 32 can use these
tests through complete hardware profiles. The [shared EX model](../common/ex_model.py)
uses mathematical ALU/MUL/DIV results and instruction-level expected outcomes,
independently of the DUT's local tracking and pipeline-register implementation.
