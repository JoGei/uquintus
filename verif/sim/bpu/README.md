# Branch prediction

[`uqu_bpu.v`](../../../src/uquintus/uqu_bpu.v) is owned
by IF and composes separate direction and target components. DE still computes the
architectural branch outcome. The core owns prediction metadata in IF/DE and
compares the carried predicted next PC with the resolved next PC on DE transfer.

```sh
make test COMPONENT=bpu CONFIG=rv32i_bimodal
make test COMPONENT=if CONFIG=rv32i_bimodal
make test COMPONENT=core CONFIG=rv32i_bimodal TEST=prediction
```

Select the components independently, for example:

```yaml
MUA_BRANCH_PREDICTOR: bimodal
MUA_BP_ENTRIES: 16
MUA_BTB: direct_mapped
MUA_BTB_ENTRIES: 32
```

[`uqu_bp_bimodal.v`](../../../src/uquintus/uqu_bp_bimodal.v) stores tagged two-bit
direction counters, selected by `MUA_BRANCH_PREDICTOR: bimodal`.
[`uqu_btb.v`](../../../src/uquintus/uqu_btb.v) stores tagged targets and
conditional/unconditional classification, selected by `MUA_BTB: direct_mapped`.
`MUA_BTB: none` disables target storage. Each capacity is an independent power
of two from 2 through 1024, default 16. All settings remain explicit in YAML.
The example labels as `mua-bp:bimodal+entries16_mua-btb:direct+entries32`.

Direction mode `none` preserves the branch hold and disables BTB use, regardless
of its inactive setting. `static_not_taken` predicts conditional branches not
taken, but can use an enabled BTB for unconditional jumps. Without a BTB, this
PC-only frontend has no early target source and follows sequential fetch even
if bimodal direction prediction is selected; unused counter logic may be
optimized away. With both components enabled, conditional target steering
requires a hit in both tables and a taken direction prediction. A direction
miss falls back to not taken. The default preset selects `none` for both modes;
the existing `rv32i_bimodal` preset explicitly enables both components at 16/16.

Both tables index by instruction words without C, halfwords with C, and check
every remaining PC tag bit independently. Cold/tag-miss lookups follow the
sequential PC. Allocate a conditional counter weakly toward its first observed
outcome; subsequent outcomes increment/decrement it with saturation. An
unconditional transfer invalidates its direction-table slot without allocating
a counter. Unconditional JAL/JALR target hits predict their last observed target.
There is no global history, return-address stack or first-encounter predecode.

| Ports | Contract |
| --- | --- |
| `clk_i`, `rst_ni` | Single clock, synchronous active-low reset of valid bits only. |
| `invalidate_i` | Suppress lookups immediately and clear valid bits on the edge, taking priority over updates. The core asserts this when FENCE.I retires. Ordinary redirects retain learned state. |
| `lookup_valid_i`, `lookup_pc_i` | Combinational lookup of the current aligned instruction PC. |
| `hit_o`, `taken_o`, `target_o` | Exact BTB tag hit, effective target-steering decision and target. Target is zero unless taken; lookup/update collisions see the old entries before the edge. |
| `update_valid_i`, `update_pc_i` | One accepted, nonfaulting DE instruction. A held, flushed or faulting token does not train. Training precedes retirement and may include an instruction later discarded by an older event. |
| `update_control_flow_i`, `update_conditional_i` | Allocate/train a branch or jump. A non-control instruction removes a matching stale entry without evicting another tag. |
| `update_taken_i`, `update_target_i` | Actual direction and branch target, including the target of an untaken conditional branch. Misaligned PC updates are ignored; an invalid target removes a matching entry. |

IF looks up the aligned instruction before IF/DE transfer. It snapshots the
predicted next PC if the token stalls, even if an older instruction subsequently
changes the table. On a taken prediction's accepted transfer, IF clears the
sequential word queue synchronously, cancels/drains old fetch work, and begins
ordinary target fetching through the core-owned PMP check. The original token
still transfers once; the synchronous clear does not mask the head used to
make the prediction. An external redirect/flush has priority.

DE corrects every successful token whose resolved next PC differs from its
carried prediction, including predicted-taken branches resolving not taken,
changed JALR targets and stale entries on non-control instructions. A correct
prediction does not cause a flush. Older fault/trap/fence/interrupt arbitration
retains priority, and discarded instructions cannot commit effects.

The pyuvm/cocotb tests use an abstract Python model and cover both allocation
directions, saturation, reversals, jumps, target changes, tag collisions,
halfword indexing, inactive lookup/update, stale removal, invalidation/reset
priority, and 4096 randomized lookup/update cycles, including independent table sizes,
disabled target storage and static direction with an active BTB. IF separately checks held
metadata, target PMP faults, external recovery and invalidation. Core directed
programs verify loop entry/exit, correct predictions and changing JALR targets
against the retirement/RVFI oracle, including compressed branch loops when C
is enabled and cold lookup after a retiring FENCE.I. Supporting fixtures and the normal core regression cover random
memory waits, traps and redirects.

## Initial cycle comparison

The initial RV32I CoreMark performance profile used the same ELF in all three
modes, one iteration, 2000-byte data configuration, immediate grants and
one-cycle independent instruction/data responses. Fast-mode CRC and timing
checks passed; each workload window retired 757,486 instructions.

| Predictor | Workload cycles |
| --- | ---: |
| `none` | 3,489,633 |
| `static_not_taken` | 3,489,633 |
| `bimodal`, 16 entries | 3,295,230 |

This is a 5.57% cycle reduction for one executable and memory context. It is
not a Pareto selection or an execution-time/area claim; new predictor timing
and area costs remain unmeasured. Native benchmark records retain the complete
configuration, ELF identity and validation scope under `build/` for the shared
report. Broader workloads and prediction-event statistics remain follow-ups.
