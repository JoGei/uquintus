# Forwarding, fetch control and physical buffers

The address-selector candidate rejected in the historical sections below is now retained for the canonical split-MAC configuration after a fresh matched measurement; see [the MEM/EX2 re-evaluation](#re-evaluation-on-canonical-memex2).

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

## Re-evaluation on canonical MEM/EX2

On 2026-10-24, the canceled-private-address candidate above was re-evaluated against a fresh control after multiplier consolidation. The hardware is now `rv32imc_bimodal_idata_dadda_mac_div1`: canonical two-row PP/Dadda/BK with late C, RV32IMC, BPU16/BTB16/H6, IF decompression, FF GPRs, all forwarding, continuous DE operands and DIV factor one. The same-cycle redirect-request bypass is disabled. The earlier rejection remains evidence for the older EX1-only configurations; it does not predict this different implementation's outcome.

### Current dependency and retained fix

The historical late-C path `MDU state_q[0] → imem_addr_o[27]` is no longer the fresh control's first path. Its worst path starts at `wb_kind_q[1]` and ends at `imem_addr_o[24]`. The structural MDU-state-to-address dependency nevertheless still exists: EX completion/forwarding and DE branch acceptance can affect IF cancellation, which controls `use_queued`, the address mux selector.

An unpresented private request canceled without replacement cannot assert `imem_req_o`. Retaining its queued address during that idle cycle is permitted. The retained implementation separates `address_queued` from request ownership:

```verilog
wire use_queued = request_valid_q && (!invalidate || request_presented_q);
wire address_queued = request_valid_q &&
                      (request_presented_q || !replace_i || !invalidate);
assign imem_addr_o = address_queued ? request_addr_q : {req_addr_i[31:2],2'b00};
```

The selectors differ only with a private queued request, cancellation asserted, and no replacement. Presented requests keep their address through grant; replacements still select the new stream. Request, grant, protection, capacity, cancellation and response equations are unchanged. No pipeline register, startup cycle or new microarchitecture parameter is added.

In the measured no-redirect-bypass configuration, `replace_i` is constant zero and address selection reduces to the registered request-valid bit. A flattened core ancestry check confirms that the candidate address output depends only on registered IF fetch/request addresses and request ownership. MDU state, DE arithmetic, WB control and external memory-response inputs no longer enter that cone. Both compared cores have zero combinational strongly connected components.

### Matched repaired-placement result

Both full-core runs use the same Sky130 HD TT/1.80 V/25 °C library, tools, ABC/buffering policy, 20 ns constraint, 4 ns ordinary I/O budget, 0–1 ns reset arrival, 0.1 ns uncertainty, floorplan/density and two workers. The audit checks identical parameter dictionaries, physical/tool contexts, SDC bytes and shared RTL/flow hashes; only `src/uquintus/uqu_ifetch.v` differs. A source copy isolates the candidate while the control runs. These are repaired-placement estimates with ideal clocks and placement-estimated RC before CTS/routing.

| Metric | Fresh control | Separate address selector |
| --- | ---: | ---: |
| Tmin (ns) | 21.347169 | 20.684476 |
| Estimated Fmax (MHz) | 46.844618 | 48.345435 |
| Setup WNS at 20 ns | −1.347169 ns | −0.684476 ns |
| Setup TNS | −520.554 ns | −0.684 ns |
| Register-to-register WNS | −0.348047 ns | +0.379393 ns |
| Logical cell area (µm²) | 458,965.1840 | 443,849.4368 |
| Buffer count | 5,842 | 4,782 |
| Minimum hold slack | +0.304504 ns | +0.304504 ns |
| Placement / slew / capacitance / fanout violations | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |

Retain the candidate: estimated Fmax improves by 3.204%, cell area decreases by 3.293%, and setup improves by 0.662693 ns in this matched point. Mapping and physical optimization change globally; the area difference is not a standalone mux-area estimate or a general guarantee for every configuration. Both flow records remain `failed` because setup still misses the unchanged 20 ns target. No timing exception was added.

### Remaining first path

The candidate's first STA path starts at MDU `state_q[0]` and ends at `imem_req_o`. Annotated arrivals include shared `u_ex.arith_result[32]` at 6.386 ns, ALU `computed_result[0]` at 6.623 ns, and DE source-one bit zero at 7.412 ns, followed by branch/acceptance and IF request logic. This is a shared-arithmetic-to-forwarding-to-control route, not an isolated multiplier delay. The source state and the ALU result selection represent resource-sharing correlations that STA does not resolve automatically.

A two-stable-snapshot Boolean check of that placed path, allowing 3,504 arbitrary shared boundary bits and 7,833 combinational cells, is UNSAT for simultaneous change of every traversed net when only the source toggles. Endpoint sensitivity is SAT: MDU state can affect fetch request through other routes. This is neither timed-glitch analysis nor sequential reachability proof. It does not justify a false-path/multicycle constraint, and the recorded setup failure remains unchanged. The address-control fix is supported by the unconstrained physical comparison above, independently of that sensitization result.

### Verification and evidence

All eight fetch-bypass selectors pass their ten fetch-engine cases, including stalled grants, simultaneous replacement, outstanding responses and randomized cancellation. IF and IF/DE fixtures pass default, redirect-request and full bypass; native core tests pass canonical RV32IMC, EX1 Dadda, iterative MUL and PMP configurations. Both compressed-expansion placements and direct compressed decoding pass their component fixtures. Sequential Yosys equivalence passes for bypass selectors 0 and 7, comparing state/control and all outputs while qualifying address equality by `imem_req_o`; idle address values are deliberately unspecified. New directed cases check idle queued-address retention under local clear and global flush.

After correcting previously unconnected, unused `late_c_o` outputs in three fixtures, the resolved matrix passes 212 RTL cases across 22 runs. The initial fixture elaboration failures are retained separately; they were not simulated RTL failures. A further ten-case fetch run passes on the retained production source. Pipeline timing and transaction behavior are unchanged, so no benchmark cycle reduction is claimed.

Control: `impl-core-20261024T213041Z-1c3e7d7a`. Candidate: `impl-core-20261024T213331Z-e0a3d482`, published into the standard core-report directory with a pointer to the original isolated run and ODB. Configurations, source snapshots, commands, comparison audit, annotated gate paths, structural ancestry, equivalence proofs, stable-sensitization model and all test logs are retained under `build/investigations/ex-fetch-critical/`. `comparison.json` records the measured pair and `address-cone.json` records the dependency change. Historical 45.442 MHz late-C and 49.685 MHz product-only results belong to different source snapshots and are not used as the control here.
