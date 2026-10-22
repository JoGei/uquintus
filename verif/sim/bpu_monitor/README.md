# Passive BPU statistics monitor

`verif/common/uqu_bpu_monitor.sv` shadows the four core-owned pipeline
boundaries. It observes first-presentation IF prediction metadata, accepted DE
outcomes and successful WB retirement. It has no influence on processor RTL.
The native benchmark and checked RVFI harness use the same connection header.

Run the cocotb/pyuvm lifecycle test with:

```sh
make test COMPONENT=bpu_monitor CONFIG=rv32i_bimodal
make test COMPONENT=bpu_monitor CONFIG=rv32i
```

The test covers correct and incorrect direction/target predictions, JAL/JALR,
compressed control flow, stale BTB hits, held IF lookup changes, stalls at each
boundary, squash, nonretiring fault tokens, held-lookup flush and reset. No
held/squashed observation may increase the retirement counters. Core prediction
regressions additionally compare instruction mix with architectural execution.

`uqu_bpu_counter_list.vh` defines packed-counter ordering for SystemVerilog and
Python. `verif/sim/common/bpu_stats.py` validates snapshots and derives report
metrics. Tests for denominators, full-width serialization and invalid evidence
run in `make test-runner`; report consistency tests run in `make test-report`.
See the [measurement contract](../../../doc/uqu_spec.bench.md#31-passive-branch-prediction-statistics)
for scope and rate denominators.

`make test COMPONENT=core TEST=bpu_statistics` times a short branch/JAL loop
with real CSR markers and checks its retired instruction mix. Set
`UQU_BPU_NATIVE=/absolute/path/to/obj/uqu_benchmark` to a native driver built
for the same hardware configuration to additionally compare both timer points
and every BPU snapshot/rate between the checked and native harnesses.

The appended `IDATA_REPLAYED_INSTRUCTIONS` counter carries the IF source flag
through the same shadow boundary state, counting only successful retirement.
It excludes held presentations, squashes and traps. Benchmark statistics schema
2 exposes its count and fraction of all window retirements; historical schema-1
artifacts retain their original twenty-counter interpretation. The passive
monitor regression includes replay-origin instructions that retire, squash and
fault without incrementing the wrong population.
