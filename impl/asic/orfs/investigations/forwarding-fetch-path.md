# Forwarding, fetch control and physical buffers

This continues the [CSR timing cleanup](csr-bypass-separation.md) using its
completed Sky130 HD placements. It rechecks the current buffer chains, identifies
another address/control dependency, and examines the operand-capture contract
behind the remaining multiplier paths. No timing exceptions are introduced.

## Current critical path

The baseline runs are the Dadda `20261023T173431Z-71569182` and inferred-parallel
`20261023T173431Z-0fcf3f2f` implementations. Their worst register-to-register paths
both start at `wb_rd_q[1]` and end at IF fetch-address registers:

```text
WB destination matching → EX operand candidate mux → EX multiplication
    → EX-to-DE forwarding → DE next-PC logic → fetch control/address selection
```

This is a structural timing route through several stages, not the delay of an
isolated multiplier. For example, the Dadda first reported output path reaches
`ex_result[26]` at 12.280 ns and `de_next_pc[31]` at 16.391 ns, then reaches
`imem_addr_o[11]` at 23.538 ns. The 4 ns output budget and 0.1 ns uncertainty
bring its estimated minimum period to 27.639 ns.

Worst setup slacks into each stage's registers are:

| Register region | Dadda (ns) | Inferred parallel (ns) |
| --- | ---: | ---: |
| IF | −5.948 | −5.279 |
| DE | −2.117 | −0.740 |
| EX | +1.954 | +2.820 |
| MEM | +6.519 | +7.233 |
| WB | +14.000 | +12.853 |

These are worst incoming paths, which may start in another region. They do not
measure isolated IF/DE/EX logic. In particular, positive slack into EX does not
mean that forwarding EX's result into DE and IF in the same cycle also meets
timing.

## The old long buffer chain is no longer the current bottleneck

The earlier audit found 43 consecutive buffers contributing 5.317 ns. Following
the CSR cleanup, the current first Dadda path has:

- 123 cell-output arcs, including 29 buffer/delay-cell arcs.
- 3.961 ns of buffer/delay-cell delay over the whole path.
- A longest consecutive run of seven buffers, contributing 0.753 ns.

The corresponding inferred-parallel path has 120 cell-output arcs, 28
buffer/delay-cell arcs totaling 4.609 ns, and a longest run of three contributing
0.499 ns. These sums exclude wire delay and are taken from each first path,
not all three paths printed in a report.

The repair pass improves the complete design's setup slack:

| Multiplier | Before final repair (ns) | After repair/legalization (ns) |
| --- | ---: | ---: |
| Dadda | −11.222 | −7.639 |
| Inferred parallel | −10.184 | −6.788 |

Thus the previous 43-buffer observation must not be applied to the current
netlist. Individual buffers contribute delay, but removing buffering globally
is not supported by these results. The current experiment preserves the flow's
buffer insertion/removal, sizing, placement and timing-repair policies.

## Rejected candidate: separate idle address selection from cancellation

`uqu_ifetch` previously used the same select for request ownership and its address:

```verilog
wire use_queued = request_valid_q && (!invalidate || request_presented_q);
assign imem_addr_o = use_queued ? request_addr_q : {req_addr_i[31:2], 2'b00};
```

An unpresented queued request canceled without replacement cannot assert a bus
request in that cycle. Switching its idle address to the live input is therefore
unnecessary. The candidate uses a separate address selector:

```verilog
wire address_queued = request_valid_q &&
    (request_presented_q || !replace_i || !invalidate);
assign imem_addr_o = address_queued ? request_addr_q : {req_addr_i[31:2], 2'b00};
```

All request ownership, permission, capacity and cancellation equations remain
unchanged. The selectors differ only when a private request is invalidated
without replacement, when `imem_req_o` is zero. Presented requests retain their
address through grant, including concurrent cancellation/replacement. New
same-cycle replacements still select the incoming address. With replacement
disabled, address selection no longer depends on flush/clear.

Changing even this small cone changes global technology mapping and placement.
Its initial mapped estimates are worse: Dadda Tmin 28.003 → 37.054 ns and
inferred parallel 25.682 → 33.343 ns. The completed placement metrics are:

| Multiplier | Baseline Tmin (ns) | Candidate Tmin (ns) | Baseline Fmax (MHz) | Candidate Fmax (MHz) |
| --- | ---: | ---: | ---: | ---: |
| Dadda | 27.639 | 27.394 | 36.181 | 36.505 |
| Inferred parallel | 26.788 | 29.856 | 37.330 | 33.494 |

Dadda improves by about 0.90%, while inferred parallel loses about 10.28% and
acquires one slew and one capacitance violation. Both still fail the 20 ns setup
target; worst setup slack is −7.394 ns and −9.856 ns. Hold slack is +0.305 ns
in both. These are ideal-clock, placement-estimated results before CTS/routing.

**Reject the candidate as a general timing improvement.** The source, test and
component-guide edits are restored to the measured baseline. The candidate,
its passing tests and its equivalence results are preserved for reproducibility
in [`candidate.patch`](../../../../build/investigations/fetch-address-selection/candidate.patch).
Removing a structural dependency alone does not establish a PPA improvement.

The matched candidate runs, with unchanged parameters, SDC and flow policy, are:

- [Dadda](../../../../build/uquintus-rv32imc_bimodal_idata_dadda_div1/orfs_sky130hd/impl-core-20261023T181515Z-2183d2dd/report.json).
- [Inferred parallel](../../../../build/uquintus-rv32imc_bimodal_idata_parallel_div1/orfs_sky130hd/impl-core-20261023T181515Z-9ad40e27/report.json).

## Next candidate: expose the EX capture invariant to synthesis

With both EX-to-DE and MEM-to-DE forwarding enabled, the synthesized
`de_guaranteed` mask is constant zero. DE cannot admit a native EX operand with
only a promise of later forwarding: it must already capture the value. The
same condition holds for several other forwarding combinations.

An exhaustive elaboration of the sixteen individual forwarding combinations
matches this condition for possible deferred EX operands, with forwarding enabled:

```text
(!EX_TO_DE && MEM_TO_EX) ||
(!MEM_TO_DE && (MEM_TO_EX || WB_TO_EX))
```

Eight combinations make that condition false. Disabling the forwarding master
also disables all guarantees. A local DE SAT check with zero guarantee inputs
proves `valid_o → ((rs_ex_used_o & ~rs_captured_o) == 0)` for IF decompression,
DE decompression and direct compressed decoding, with native M and Zfinx enabled.
That check uses the native `XIF=0` DE implementation.

The parent captures this mask on admission and only adds captured bits while
holding EX. Consequently, an occupied EX instruction in these configurations
has all its used operands captured. STA does not infer that state correlation
from the dynamic capture bits and can still traverse the MEM/WB-to-EX muxes.
As a cross-check, extracting the actual generic EX result cone and fixing all
EX capture bits to one removes WB destination bits from its combinational
ancestors. They are present without that condition. This confirms which mux
route the capture invariant eliminates; it is not a whole-core reachability
proof.

A subsequent optimization can select registered EX operands directly whenever
the configuration forbids deferred operands, preserving the existing hazard
unit for configurations that admit them. Keep its standalone contract intact;
this is a core-integration specialization. This note does not implement that
change or add a false-path exception. The
[EX capture implementation](ex-operand-capture.md) follows up this candidate,
including both retention policies, extended XIF proofs and forwarding-matrix
regressions.

## Validation and retained evidence

For the rejected address-selector candidate, all **18 runs / 204 cocotb cases pass**:
the eight fetch-bypass settings; IF with default, request and full bypass;
both matched multiplier cores; full bypass with the three compressed-decoding
arrangements; and PMP core/checker integration. New directed cases cancel private
requests without replacement through both flush and local clear.

Yosys equivalence checks pass for the full fetch unit with its address output
qualified by `imem_req_o`, covering both distinct result-queue implementations
(selector values 0 and 7). The checks compare control, response and state
behavior as well as qualified addresses. Idle address equality is intentionally
excluded. Existing simulation exercises reset and initial state.

Both matched CoreMark performance ELFs pass CRC checking with the unchanged
463,144 cycles, 314,834 retired instructions and CPI 1.471074.

Evidence, generated configurations, annotated baseline paths, buffer counts,
the sixteen-entry guarantee matrix, DE capture proofs and flow logs live under
[`build/investigations/fetch-address-selection/`](../../../../build/investigations/fetch-address-selection/).
