# Remaining critical paths after candidate-data separation

The [cleanup results](result-data-separation.md#physical-measurement) show a
small placed frequency improvement for Dadda (+1.34%) and a regression for
inferred multiplication (−2.35%). Both retain failed 20 ns setup status. This
audit explains why removing the memory-response route was not sufficient.
No RTL, SDC, tool configuration or placement result is changed by this audit.

The later [CSR bypass/context cleanup](csr-bypass-separation.md) implements the
two RTL fixes identified here. The physical buffer-chain investigation is
deferred; the measurements below describe the prior netlists.

## New first paths

| Configuration | Source | Endpoint | Setup slack (ns) |
| --- | --- | --- | ---: |
| Dadda | `irq_external_i` | IF fetch-result register data-enable pin | −10.477 |
| Inferred | `irq_timer_i` | `imem_req_o` | −13.123 |

The Dadda endpoint is
`u_if.u_ifetch.result_data_q[0][5]$_DFFE_PP_/DE`: **DE means the cell's data-enable
pin here**, not the pipeline decode stage. Stream cancellation gates whether
the incoming instruction response is enqueued, hence the endpoint on its write
enable rather than on an instruction-data bit.

Both paths pass through the EX multiplier and DE control-flow logic:

```text
IRQ input → mip CSR read → WB candidate forwarding → EX multiplication
          → EX-to-DE candidate forwarding → branch/JALR resolution
          → redirect/flush/fetch qualification → fetch request or queue enable
```

`uqu_csregfile` exposes the IRQ inputs in `mip` (CSR 0x344). WB can select that
read value as its candidate destination word; the normalized hazard mux can
select it as an EX source, and EX can supply the resulting multiplication to DE.
The ending IF request/queue qualification is ordinary cancellation and capacity
logic. There is also a genuine shorter IRQ-to-drain/trap/fetch-control route.

An additional gate-level Dadda check confirms that the sensitizable prefix
through point 42 requires **WB kind CSR and CSR address 0x344**. Disallowing
either makes that prefix UNSAT. Thus this is specifically a `mip` read route,
not evidence that interrupt dispatch intrinsically requires multiplication.

CSR serialization makes the represented overlap suspect: native CSR decoding
sets serialization, and an occupied serializing WB slot blocks DE admission.
This registered metadata correlation is not automatically enforced by STA.
A useful next RTL investigation is whether the existing serialization permits
keeping CSR candidate read data out of core forwarding altogether, while
preserving CSR retirement/writeback and the standalone WB contract.

## Contradictory privilege fallback

The Dadda worst internal register path starts at `priv_m_q` and also passes
through CSR/read qualification and multiplication before reaching the fetch
queue enable. Core integration supplies WB privilege using:

```verilog
.priv_m_i(wb_valid_q ? wb_priv_m_q : priv_m_q)
```

The fallback exists to supply current privilege when there is no WB owner.
But a CSR query requires an active WB owner. Propagating current `priv_m_q`
through the fallback requires `wb_valid_q=0`, whereas reading a CSR requires
`wb_valid_q=1`. This is another data/control correlation that a structural
timing traversal can join even though the two cases cannot coexist.

A two-snapshot check confirms that the whole reported register path is not
stably sensitizable, even with arbitrary shared values at all other register
outputs. A broader single-result sensitivity query was stopped without a
conclusion; it is not claimed as a proof of result independence. The fallback's
legitimate use by other WB/CSR control must
be reviewed before changing its connection; deleting the whole port-pair
constraint would hide legitimate privilege-to-fetch control.

The inferred worst internal path starts at a WB CSR-address bit and follows
the CSR-to-multiply-to-DE-to-IF route. It needs a separate semantic review;
the current-privilege fallback contradiction is specific to the Dadda path.

## Physical buffer chain

The Dadda first worst path contains **161 cell-output arcs, including 71
buffer cells**. Its longest consecutive buffer chain has **43 buffers**, from
`rebuffer15009` through `place7722`, contributing approximately **5.317 ns of
cell delay** (wire delays are additional). These buffers are physically
connected in series on the reported path, not separate parallel sinks.

The retained ODB snapshots contain `rebuffer15009` and `rebuffer14920` only
after `3_6_place_repair_timing`, not in `3_3`, `3_4` or `3_5`. The final repair
log reports 146 inserted buffers, 351 resized cells and **no hold violations**.
This identifies the setup-repair pass as their source; it does not establish
why its optimization selected such a deep chain or that simply deleting it
would improve the complete design. Inspect that repair sequence and its
load/placement/parasitic assumptions before adding RTL stages to compensate.
That physical-flow investigation is deferred by project decision. It is separate
from the previously measured intrinsic Dadda multiplier delay below 10 ns.
The inferred first path contains 15 buffers across 121 cell-output arcs.

## Checks and limits

The same two-snapshot Boolean method as the original audit was applied to the
actual placed netlists and library functions. Every boundary value is shared
and arbitrary; only the reported source toggles. Both complete first worst
paths and both first internal register paths are UNSAT for simultaneous stable
change along every traversed net. Their endpoint-sensitivity queries are SAT:
the sources can still affect their endpoints through other routes. Prefix
searches first block at point 43 for Dadda and point 18 for inferred
multiplication; these positions alone do not identify the architectural reason.

Stable sensitization is not timed hazard analysis or sequential reachability
proof. These results do not justify a false-path or multicycle exception, and
the raw STA failure records remain unchanged. The flattened, memory-mapped
generic Dadda core also passes `scc -expect 0`: no actual combinational feedback
loop is found in that configuration. The findings above concern long
dependency chains and reconvergence.

Models, scripts, guard queries, logs, hashes and the controlled before/after
comparison are retained under
[`build/investigations/post-cleanup-path/`](../../../../build/investigations/post-cleanup-path/).
