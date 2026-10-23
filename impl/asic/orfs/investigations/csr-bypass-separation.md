# Serialized CSR bypass and privilege-context separation

This implements the two RTL fixes identified by the
[post-cleanup timing audit](post-cleanup-path.md). Physical buffer-chain analysis
is deferred. The Dadda multiplier, placement/timing-repair policy and constraints
are unchanged.

## Keep CSR read data out of core forwarding

Every native CSR instruction already serializes younger admission through
retirement. Consequently, the following core descriptor does not need to carry
the CSR read value into younger candidate arithmetic:

```verilog
wire wb_csr = (wb_kind_q == `UQU_WB_CSR);
wire wb_forwardable = wb_result_valid && !wb_csr;
wire [31:0] wb_forward_data = wb_csr ? wb_data_q : wb_result;
```

The hazard unit receives `wb_forward_data` and `wb_forwardable`, while WB still
writes the actual architectural CSR read value into the GPR file at retirement.
The CSR destination remains pending until then. In the following cycle, younger
consumers read its committed value from storage, as existing serialization
already requires. No extra stall cycle, register or microarchitecture parameter
is added. Standalone WB retains its retirement-time CSR result output contract.

For a CSR token, `wb_data_q` is only an unqualified candidate placeholder; it is
never advertised as an available architectural result. Candidate selection uses
registered instruction kind, rather than dynamic readiness/fault gating of a
wide word. This removes the live `mip` read route into EX multiplication without
changing IRQ inputs, pending state, CSR read semantics or interrupt eligibility.
Any future relaxation of uniform CSR serialization must revisit this policy.

## Separate access privilege from saved event privilege

Previously the core supplied WB with:

```verilog
.priv_m_i(wb_valid_q ? wb_priv_m_q : priv_m_q)
```

The empty-slot fallback supplied current privilege for asynchronous trap entry,
but also connected it structurally to CSR permission/read qualification. CSR
reads require an occupied WB slot, making that fallback path contradictory.

The core now connects two independent inputs:

```verilog
.priv_m_i(wb_priv_m_q),
.event_priv_m_i(priv_m_q)
```

WB access checks, MRET legality and local EBREAK selection use the instruction's
saved privilege directly. For trap/debug state updates only, WB selects:

- The current event context for an accepted external trap/debug entry.
- The owning WB context for synchronous exceptions and local EBREAK entry.

The CSR unit has a separate `event_priv_m_i` input used only for saving
`mstatus.MPP` or `dcsr.prv`. CSR access permissions, counter-access checks and
MRET qualification continue to use `priv_m_i`. An interrupt taken immediately
after MRET to U-mode therefore saves U-mode even while an empty WB slot retains
stale M-mode payload bits. No new core-level external ports are introduced.

## Validation

**20 component/core runs, 231 cocotb test cases pass**, covering full RV32I,
both matched RV32IMC multiplier presets, retained operands, disabled forwarding,
retained operands with forwarding disabled, M-only, PMP, XIF and Zfinx cores;
CSR/WB units including debug; and WB/pipeline-control parent fixtures. The
shared runner's 134 unit tests complete with 132 passes and two conditional
skips.

New directed checks cover adjacent CSR-to-MUL/ALU-to-branch consumers, live
masked IRQ bits read through `mip`, empty-WB trap entry after MRET, opposite
owner/event privilege values, synchronous fault context, external debug context
and independent CSR access permissions. Every core cycle checks that a CSR in
WB cannot advertise a core bypass result or admit a younger instruction to EX.

Both matched CoreMark performance ELFs pass CRC validation with the same
463,144 cycles, 314,834 retired instructions and CPI 1.471074 as before.

A flattened, memory-mapped generic RTL ancestry check of the RV32IMC/Dadda
core confirms:

- IRQ inputs and data-memory response/error/data inputs are absent from the
  combinational ancestors of `wb_forward_data`, `ex_a`, `ex_b` and `ex_result`.
- Current `priv_m_q` is absent from their sequential-boundary ancestors.
- CSR access privilege is exactly `wb_priv_m_q`, while WB's external event
  input is exactly current `priv_m_q`.
- IRQ inputs still reach architectural WB write data and fetch/drain control.
- `scc -expect 0` finds no combinational feedback loops.

These are structural dependency checks plus functional regressions, not timing
exceptions or a sequential formal ISA proof. No period/frequency improvement
is claimed solely from eliminating these ancestors.

Logs, generated test configurations, input hashes, models and validation records
are retained under
[`build/investigations/csr-bypass-separation/`](../../../../build/investigations/csr-bypass-separation/).

## Matched physical measurements

Fresh standard-flow runs use the same Sky130 HD evaluation profile as the prior
pair: 20 ns target, 4 ns data-I/O budgets, 0–1 ns reset arrival, identical
geometry/density and two tool threads per run. No buffer-policy experiment or
constraint exception is part of this change. Their flow records are:

- [Dadda](../../../../build/uquintus-rv32imc_bimodal_idata_dadda_div1/orfs_sky130hd/impl-core-20261023T173431Z-71569182/report.json).
- [Inferred parallel](../../../../build/uquintus-rv32imc_bimodal_idata_parallel_div1/orfs_sky130hd/impl-core-20261023T173431Z-0fcf3f2f/report.json).

Use completed measurements from these records for this RTL revision; the
earlier comparison and its path audit describe the prior circuits.

The completed mapped, preplacement estimates improve relative to the immediately
preceding candidate-data cleanup:

| Multiplier | Before mapped Tmin (ns) | After mapped Tmin (ns) | New first worst-path source |
| --- | ---: | ---: | --- |
| Structural Dadda | 35.832 | 28.003 | `mem_rd_q[2]` |
| Inferred parallel | 32.584 | 25.682 | `rst_ni` |

Both first paths end at `imem_req_o`. These are preliminary mapped estimates;
they do not substitute for placed results or establish 20 ns closure.

The completed placement runs show an improvement with byte-identical supplied
SDC constraints and identical tool, library and flow settings:

| Multiplier | Before placed Tmin (ns) | After placed Tmin (ns) | Before estimated Fmax (MHz) | After estimated Fmax (MHz) | Fmax change |
| --- | ---: | ---: | ---: | ---: | ---: |
| Structural Dadda | 30.477 | 27.639 | 32.812 | 36.181 | +10.27% |
| Inferred parallel | 33.123 | 26.788 | 30.190 | 37.330 | +23.65% |

The baseline is the immediately preceding candidate-data cleanup, measured in
the `20261023T141133Z` runs. Logical cell area falls from 468,224 to 462,084 µm²
for Dadda and from 469,986 to 463,434 µm² for inferred parallel (about 1.3–1.4%).
The comparison and current source-hash checks are retained in
[`comparison.json`](../../../../build/investigations/csr-bypass-separation/comparison.json).

Both runs complete placement but correctly report failure of the **20 ns setup
target**: worst setup slack is −7.639 ns and −6.788 ns, respectively. Hold slack
is +0.305 ns and slew, capacitance and fanout violation counts are zero in both.
These frequencies use placement-estimated parasitics and an ideal clock, before
CTS and routing; they are evaluation estimates rather than signoff frequencies.

The Dadda worst reported path is now `wb_rd_q[1]` → `imem_addr_o[11]`; the
inferred-parallel worst path is `rst_ni` → `imem_req_o`. Both worst register-to-
register paths start at `wb_rd_q[1]` and end at an IF fetch-address register.
These endpoint reports identify remaining timing work; they do not by themselves
establish stable sensitizability or justify timing exceptions. No further
multiplier or physical buffer-chain changes are included here.

The [next timing audit](forwarding-fetch-path.md) rechecks the current buffer
chains and traces the remaining forwarding/fetch-control paths.
