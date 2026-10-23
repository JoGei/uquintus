# Result selection and forwarding timing audit

This audit applies the RI5CY resource-selection lesson to the accepted [two-outstanding fetch implementation](fetch-outstanding.md). It inspects existing RTL and reopens its final repaired Sky130 HD databases; it does not change RTL, constraints or pipeline timing.

The first candidate is evaluated separately in [Direct register operands for MUL/DIV](muldiv-operands.md).

## RI5CY comparison

The [original RI5CY paper, Section IV-A](https://arxiv.org/pdf/1608.08376), describes a separate LSU register-file write port to avoid load/ALU writeback conflicts and remove writeback multiplexers from the critical path. Its reported register-file area cost belongs to that implementation and technology, rather than providing an area estimate for uquintus.

uquintus retires native arithmetic and memory instructions through the same WB stage. They do not compete for simultaneous architectural GPR writes. Its optional second GPR port serves paired XIF results; it does not provide independent native EX retirement. Moving native arithmetic writes into EX to reproduce RI5CY's arrangement would change our architectural-effect and pipeline contracts.

The useful general lesson is to locate selection logic on the actual slow producer-to-consumer path before spending area on dedicated routes.

## Measured paths

The evaluated presets use RV32IMC, bimodal/BTB 16/16, six replay halfwords, IF decompression, all forwarding enabled, DE retention disabled, one-cycle Dadda or inferred multiplication, iterative division with factor one, and a flip-flop GPR file. Both have XIF and Zfinx disabled. These are ideal-clock placement estimates after repair, before CTS/routing, with the existing 20 ns target, 4 ns data-I/O budget and 0–1 ns reset window.

| Path scope | Dadda worst setup slack (ns) | Inferred worst setup slack (ns) |
| --- | ---: | ---: |
| Complete design | −4.184 | −4.627 |
| Any startpoint to GPR storage | +10.084 | +9.923 |
| Data-response word to GPR storage | +11.747 | +11.827 |
| Response-valid/error to GPR storage | +10.084 | +9.923 |
| WB registers to GPR storage | +13.911 | +13.439 |
| WB registers to DE registers | +4.713 | +4.722 |
| WB registers to EX registers | +8.235 | +9.091 |

The fresh GPR queries include all 992 architectural storage bits. The scoped reports include data, control and enable routes rather than isolating one source-level mux. Their worst endpoint is sometimes the flop's data-enable pin; `DE` in that pin name does not mean the decode stage. Full-design slack from the reopened databases matches the retained implementation reports. Every recorded RTL source hash also matches the current workspace.

**A dedicated LSU write port is not justified by these results.** The existing WB result selection and load alignment are not the dominant paths in these presets. This finding does not predict timing in an enabled XIF/FPU configuration or a different physical integration.

Both first critical paths instead start at `ex_a_sel_q[0]`, traverse EX arithmetic and result selection, then feed DE control flow and fetch. The Dadda endpoint is `imem_req_o`; inferred multiplication ends at `imem_addr_o[7]`.

```text
EX operand selection → multiplication / MDU result selection
    → EX result selection → DE forwarding / branch control → IF request/address
```

The retained first paths expose these arrival milestones:

| Milestone | Dadda arrival (ns) | Inferred arrival (ns) |
| --- | ---: | ---: |
| MDU `completed_result` | 9.307 | 10.997 |
| Core `ex_result` | 9.923 | 11.659 |
| Difference | 0.616 | 0.662 |

These are cumulative arrival times on each implementation's first path, using bit 26 in Dadda and bit 24 in inferred multiplication. The difference includes the MDU held-result selection, EX functional-unit result selection, and intervening cell/wire/buffer delay. It excludes the earlier selection between MUL/DIV phase results and the later DE forwarding logic. It is not the standalone multiplier delay or a guaranteed saving from rewriting a mux. Even eliminating that interval entirely would not close the remaining setup deficit.

## Candidates, in order

1. **Give MUL/DIV its register operands directly.** The core currently selects PC/RS1/zero and immediate/RS2/zero into the common EX `a_i`/`b_i` ports. Those ALU-oriented selections also feed MUL/DIV. Legal native M instructions always select RS1 and RS2, so their datapath need not include PC/immediate selection. A candidate should supply the already resolved EX register operands separately to MUL/DIV, preserving hazards, captured/deferred forwarding, qualification, shared arithmetic-slice ownership and all operation latencies. This removes an unnecessary selector from the multiplier cone without duplicating a register file or arithmetic unit. The remaining data-register-to-multiplier path still needs physical measurement.
2. **Measure parallel EX result selection.** `uqu_stage_ex.result_o` selects ALU, MDU, FPU or pass-through data using a nested conditional. The four FU codes are mutually exclusive, so predecoded enables and a parallel masked-OR merge are a candidate for shortening the late data path. Keep selection independent of completion/fault qualification. Synthesis can already combine or rebalance the current expression, so source-level simplification alone is not evidence of a gain. The MDU's own held/completed-result selection also remains semantically necessary under backpressure.
3. **Inspect DE forwarding selection after those changes.** Source origin can be predecoded while producer arithmetic executes. A parallel data merge could avoid a serial priority-mux structure, but must retain the youngest matching producer's priority even if its result is unavailable or its route disabled. It must preserve x0, retained-operand priority, secondary-XIF-destination blocking and future-EX guarantees. Missing an EX result must never select an older MEM/WB value for the same register. Replicating branch arithmetic per producer would cost more area and needs a stronger measured justification.

Do not combine these experiments initially. Compare each retained candidate against the same baseline with fixed configurations, workloads, constraints, tools and flow settings. Preserve the current forwarding and retention configuration choices; no extra pipeline cycle or timing exception is selected by this audit.

## Contract check and provenance

Six local DE SAT checks pass `valid_o && !exception_valid_o && fu_o == MULDIV -> a_sel_o == RS1 && b_sel_o == RS2`, covering RV32I/E and the three compressed-decode arrangements. They enable native M/Zfinx and three-source, paired-write XIF, with arbitrary initial XIF state and unconstrained inputs. This checks the DE output contract; it is not a proof of whole-core reachability or a waiver for an STA path.

The Dadda baseline is `impl-core-20261023T200429Z-fee3172c`; inferred multiplication is `impl-core-20261023T200429Z-3a0d2d02`. Evidence is retained in [`build/investigations/producer-selection/`](../../../../build/investigations/producer-selection/): source-hash checks, mapped-cell annotations, fresh OpenROAD GPR path queries and reports, local proof wrappers/scripts/logs, and the summary JSON. No candidate RTL or new PPA claim is introduced here.
