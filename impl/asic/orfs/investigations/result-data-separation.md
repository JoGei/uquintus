# Separate candidate results from completion and fault control

The [memory-to-fetch path audit](memory-fetch-path.md) found a structural route
from data response status through MEM result masking, operand forwarding, EX
multiplication, DE branch resolution and IF request control. Its complete worst
paths were not stably sensitizable, but the graph still constrained mapping and
placement. This change removes the data/control coupling at its RTL source.

## Payload contract and implementation

An invalid result need not be zero. Consumers must require the associated
readiness/availability and success qualification before using it. Valid blocked
results must still remain stable. Architectural zeros, disabled-unit constants,
exception metadata conventions and actual transfer/write enables retain their
existing behavior. Candidate words use ordinary complete Verilog assignments;
they are not assigned explicit X/Z values.

- MEM passes its result/address word through without completion/fault masking.
  An LSU effective address remains forbidden as a destination-register result.
- Hazard muxes select candidate data using producer identity, youngest-writer
  priority and configured routes. Availability and forwardability still control
  readiness and EX guarantees, but no longer zero the selected word. Unavailable
  younger writers continue to block older values.
- EX exposes the selected result and store data without completion/fault masks.
  The shared arithmetic mux follows the retained FU selector instead of the
  request-dependent `arith_use_o` indication.
- ALU arithmetic inputs and candidate results are independent of request-valid
  and flush control. MUL/DIV similarly selects candidate arithmetic phases from
  its registered state and idle request payload; actual request acceptance,
  result validity, held-result capture and state changes remain qualified.
- WB exposes an unmasked forwarding candidate. Loads use a separate wire from
  the LSU's existing response register (`res_forward_data_o`, routed through
  MEM as `lsu_res_forward_data_o` into WB's `lsu_res_forward_data_i`). This adds
  no storage. Live response data remains available for same-edge architectural
  writeback, but never enters the candidate forwarding datapath.

No pipeline boundary, native-unit latency, forwarding availability rule,
memory request permission or precise-trap rule is changed. Tests ignore
unqualified result words while continuing to check successful data, exception
metadata, readiness, identity, held payload stability and all side effects.
New directed checks vary qualification controls without changing candidate
data and distinguish registered load candidates from live responses.

## Validation

The retained evidence is under
[`build/investigations/result-data-separation/`](../../../../build/investigations/result-data-separation/),
including `validation.json`, run logs, generated complete test configurations,
the RTL ancestry script/model and CoreMark records.

**66 supported regression runs / 322 cocotb test cases pass**, covering:

- ALU, MUL/DIV, shared arithmetic, EX, hazard, LSU, MEM and WB components;
  EX/MEM/WB parent fixtures and the pipeline-control/MEM/WB fixture.
- Full RV32I, RV32IM, RV32IMC/Dadda, operand-retention, PMP, XIF and Zfinx cores;
  Zfinx EX and debug-capable WB separately.
- All sixteen individual forwarding combinations in both DE retention modes.
- Iterative factors 1, 2, 4, 8, 16 and 32 across the arithmetic regressions,
  inferred parallel, two-stage parallel and single-cycle Dadda implementations.

An additional attempted `rv32i_xif_debug` core build is rejected by the existing
`DEBUG=1` unsupported-feature elaboration guard. It is not counted as a passing
run. The supported `rv32i_xif` core and `rv32i_xif_debug` WB regressions both
pass; this change does not implement core debug integration.

Both matched multiplier presets pass the existing CoreMark performance ELF,
with successful CRC validation and identical measurements before and after:

| Multiplier | Window cycles | Retired instructions | CPI |
| --- | ---: | ---: | ---: |
| Inferred parallel | 463,144 | 314,834 | 1.471074 |
| Structural Dadda | 463,144 | 314,834 | 1.471074 |

For the full RV32IMC/Dadda configuration, a flattened generic RTL ancestry check
maps memories to storage and stops at sequential outputs. None of
`dmem_err_i`, `dmem_rvalid_i` or `dmem_rdata_i` is a combinational ancestor of
`mem_result`, `wb_result`, `ex_a`, `ex_b` or `ex_result`. The response/error
control dependency to `imem_req_o` remains present. Reset and live IRQ inputs
remain in some candidate cones, including CSR reads; this is not a claim that
all core control/data coupling has been removed. This structural check does
not substitute for sequential ISA verification or timed hazard analysis.

## Physical measurement

The earlier [matched comparison](efficient-mul.md#encoding-compression-and-final-addition) records the pre-cleanup
circuits. Its area/period figures must not be reused as measurements of this
RTL revision. No SDC exception, target relaxation or pipeline stage was added.

Fresh matched Sky130 HD runs use the same 20 ns target, 4 ns data-I/O budgets,
0–1 ns reset arrival, die/core geometry, density, tools and two threads per run.
Their retained flow reports are:

- [Dadda implementation](../../../../build/uquintus-rv32imc_bimodal_idata_dadda_div1/orfs_sky130hd/impl-core-20261023T141133Z-4a9f5ab4/report.json).
- [Inferred implementation](../../../../build/uquintus-rv32imc_bimodal_idata_parallel_div1/orfs_sky130hd/impl-core-20261023T141133Z-d4b2fc06/report.json).

Both placement/timing-repair runs have now completed. Their supplied SDC and
hardware parameters match the corresponding pre-cleanup runs exactly.

| Multiplier | Before Tmin (ns) | After Tmin (ns) | Before Fmax (MHz) | After Fmax (MHz) | Frequency change |
| --- | ---: | ---: | ---: | ---: | ---: |
| Inferred parallel | 32.346 | 33.123 | 30.916 | 30.190 | −2.35% |
| Structural Dadda | 30.885 | 30.477 | 32.378 | 32.812 | +1.34% |

These are placed, ideal-clock, pre-CTS estimates with the retained I/O budgets,
not routed/signoff frequencies. Both runs still fail the 20 ns setup target;
hold slack is +0.305 ns and all electrical violation counts are zero. Logical
cell area changes from 477,536.7 to 469,985.8 µm² for inferred multiplication,
and from 465,367.6 to 468,224.1 µm² for Dadda. The cleanup therefore provides
no consistent whole-core frequency or area improvement across this pair.

The new first placed paths are IRQ-to-fetch paths. The
[follow-up audit](post-cleanup-path.md) traces their CSR/forwarding arithmetic
routes, a contradictory WB privilege fallback, and a long repair-buffer chain.
Raw before/after metrics are retained in
[`comparison.json`](../../../../build/investigations/post-cleanup-path/comparison.json).

For reference, the earlier **mapped, preplacement** estimates showed that the first
worst path has moved away from data-memory response status:

| Multiplier | Setup WNS (ns) | Estimated Tmin (ns) | First worst path |
| --- | ---: | ---: | --- |
| Inferred parallel | −12.584 | 32.584 | `irq_timer_i` → `imem_req_o` |
| Structural Dadda | −15.832 | 35.832 | `irq_software_i` → `imem_req_o` |

These are not the placed results or a timing-closure claim. In particular,
removing one source of data/control coupling does not remove live IRQ/CSR
candidate routes or establish an improvement in the whole-core period. The
remaining first paths require their own analysis; do not extend the earlier
data-memory sensitization conclusions to them without checking.

Run commands/logs and the completed driver manifest are retained in the
investigation directory. No timing exceptions have been added for any of the
new paths; the sensitization conclusions for the original memory paths cannot
be applied to other paths without checking them.
