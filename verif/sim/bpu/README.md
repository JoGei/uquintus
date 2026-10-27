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
MUA_BTB_IDATA_HWORDS: 0
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
| `invalidate_i` | Suppress lookups immediately and clear valid bits and pending events on the edge, taking priority over pending and incoming updates/captures. The core asserts this when FENCE.I retires. Ordinary redirects retain learned state. |
| `lookup_valid_i`, `lookup_pc_i` | Combinational lookup of the current aligned instruction PC. |
| `hit_o`, `taken_o`, `target_o` | Exact BTB tag hit, effective target-steering decision and target. Target is zero unless taken; lookup/update collisions see the old entries before the edge. |
| `update_valid_i`, `update_pc_i` | Enqueue one accepted, nonfaulting DE instruction; the tables consume it on the next edge. A held, flushed or faulting token does not train. Training precedes retirement and may include an instruction later discarded by an older event. |
| `update_control_flow_i`, `update_conditional_i` | Allocate/train a branch or jump. A non-control instruction removes a matching stale entry without evicting another tag. |
| `update_taken_i`, `update_target_i` | Actual direction and branch target, including the target of an untaken conditional branch. Misaligned PC updates are ignored; an invalid target removes a matching entry. |

`uqu_bpu` registers one aligned update/capture/ordinary-flush bundle per edge.
An event accepted at edge N updates storage at edge N+1. Lookup stays
combinational and sees stored state, with no pending-event bypass. Direction
and target training use the same registered PC and target alignment. Ordinary
flushes are ordered with captures; a new taken update can start a fresh stream
in its flush bundle. Reset/FENCE.I instead discard pending events immediately
at their edge. Only event-valid/flush bits require reset. Disabled effective
BTBs omit the event register; zero payload omits capture fields.

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

## Target instruction data

`MUA_BTB_IDATA_HWORDS` selects 0..2048 halfwords of payload per entry. Zero is
the default and removes payload/fill/replay storage. Without C, reject odd
counts and use word-sized storage/access. With C, automatically pack C16 as
one halfword and C32/I32 as two, including across storage-word boundaries.
Stop at the first instruction that does not fit; never cache partial encodings.
Low prefix bits identify length without additional per-instruction metadata.

Replay data is banked by BTB entry. Each bank has an entry-local write enable
and halfword/word offset; entry selection does not participate in combined
entry-times-capacity address arithmetic. The payload capacity, fill protocol
and combinational lookup latency are unchanged. Writes use constant slot
destinations so synthesis does not pad a six-halfword bank to eight physical
slots when widening its two write ports.

`rv32i_bimodal_idata` selects eight halfwords (four I32 instructions), adding
`+idata-hw8` to the active BTB label. `rv32ic_bimodal_idata` selects six halfwords
(96 bits), enough for three I32, six C16, or a mixed sequence such as 32/16/32/16.
The active IF replay snapshot has the same packed capacity as one entry.

| Additional BPU ports | Contract |
| --- | --- |
| `capture_valid_i`, `capture_pc_i`, `capture_instr_i` | Successful IF-to-DE transfer, with original assembled bits. Held/faulting tokens do not capture. |
| `stream_flush_i` | Stop the current fill stream, retaining stored prefixes; an accepted DE taken-branch update may start a new stream on the same edge. |
| `idata_hwords_o`, `idata_next_pc_o`, `idata_o` | Valid halfword count, first uncached instruction PC (`target + 2*count`) and packed original encodings (earliest halfword in bits 15:0), qualified by BTB hit. Payload width is `16*H`; disabled ports use a 16-bit placeholder. Effective taken steering remains a separate decision. |

Taken DE updates start collection at the actual target. Exact sequential PCs
extend the prefix; unchanged targets preserve existing bytes. Reset/FENCE.I,
entry replacement and changed targets invalidate entry data. IF snapshots a
usable prefix into one shared active window and advances its read index only
on transfer; fills may continue without rewriting replayed bytes. Live PMP
permissions are checked again at replay, using the core-owned checker's added
word comparison banks. Continuation prefetch keeps the ordinary IF lane.

```sh
make test COMPONENT=bpu CONFIG=rv32i_bimodal_idata
make test COMPONENT=if CONFIG=rv32i_bimodal_idata TEST=idata
make test COMPONENT=core CONFIG=rv32i_bimodal_idata
```

The `idata` case uses an independent instruction-list model for allocation,
partial extension, wraparound, flushes, halfword capacity, replacement and randomized
capture/update interleavings. IF tests add stable replay during replacement,
raw compressed placement, continuation merging, current permission failures
and code changes after invalidation. Benchmark statistics count replay source
at retirement, excluding speculation and faults.
Directed cases also cover zero-extended C16 output, one-halfword capacity,
rejected C32 with one halfword remaining, and extending that prefix with C16
after a new visit. The comparison of original bits ignores C16 upper input padding.
The `idata_banks` case fills every entry with distinct mixed-length payloads
while reading another entry, then checks replacement and a rejected append
beyond the final slot for isolation between banks.
The `event_pipeline` case checks exact update visibility, consecutive targets
with different alignment, ordered capture/flush, simultaneous flush/new start,
and pending-event cancellation without resurrection after reset or FENCE.I.
