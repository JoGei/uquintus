# uquintus Benchmarking and PPA Measurement

**Status:** Minimum-period definition agreed; benchmark workloads and suite
integration remain open.

[Specification index](uqu_spec.md) · [Build](uqu_spec.build.md) · [Interfaces](uqu_spec.interfaces.md)

This document defines measurement terms used for performance and PPA reporting.
Build execution and report artifacts remain defined in the
[build specification](uqu_spec.build.md#61-shared-build-report).

## 1. Minimum clock period and maximum frequency

**Status:** Agreed

`T_min` (typeset as $T_{\min}$) shall mean the **minimum clock period required
by setup-related timing for a particular implemented netlist under its declared
timing context**. It is an STA-derived estimate, not a measured silicon limit or
the best period that another implementation might achieve. Report it in ns.

The corresponding estimated maximum clock frequency shall be:

```text
estimated_fmax [MHz] = 1000 / T_min [ns]
```

The requested implementation period, `T_target`, and `T_min` are distinct:
`T_target` is the constraint supplied to the flow; `T_min` describes the resulting
implementation. A 20 ns target corresponds to 50 MHz; positive setup margin
can support a higher estimated limit under the analyzed conditions. A result
shall require timed paths and a finite, positive `T_min`; an untimed design shall
not be reported as having unlimited frequency.

### 1.1. Relationship to setup slack

For the baseline single-clock design's same-edge, single-cycle setup paths, with
the netlist, parasitics, absolute I/O delay budgets, clock uncertainty and other
constraints held fixed:

```text
T_min [ns] = T_target [ns] - worst_setup_slack [ns]
```

Use the worst signed setup slack, including positive slack. Do not substitute
TNS or a WNS field that is clamped to zero when all paths meet timing. Setup
slack already includes applicable library setup time, clock/data delays and
uncertainty; do not add those terms a second time.

For example, the default IHP placed Zfinx core has `T_target = 20 ns` and
`worst_setup_slack = +3.668873 ns`, giving `T_min = 16.331127 ns` and
`estimated_fmax = 61.2328 MHz` under that experiment's constraints. See the
[placement comparison](../impl/asic/orfs/investigations/ihp-placement.md).

This subtraction is not a general solution for half-cycle paths, multicycle
exceptions, latch borrowing or multiple clock relationships. Those cases require
the applicable STA timing relationships. A period sweep that changes I/O delays
as a fraction of the period also changes the timing context and is not equivalent
to subtracting slack from one fixed implementation.

### 1.2. Required scope and qualification

Every `T_min`/frequency result shall identify:

- The hardware configuration, implemented netlist, flow and tool revisions.
- The clock and path scope. The baseline full-interface scope includes constrained
  inputs/outputs and synchronous reset. Internal-register-only or reset-inactive
  results shall be separately labeled and shall not replace the full-interface result.
- Platform, Liberty corner and PVT conditions; the analysis stage and parasitic
  model; ideal or propagated clock; clock uncertainty and relevant timing exceptions.
- Input/output delays, reset arrival/slew assumptions and their clock relationship.
  Comparisons shall use the same declared interface timing contract.

A valid operating-point claim additionally requires the applicable hold,
recovery/removal, clock pulse-width/period and electrical checks to pass. A
setup-derived `T_min` does not waive those checks. For several required corners,
report the largest `T_min` (smallest frequency) across the required analyses.

The current ORFS reports call:

```tcl
report_clock_min_period -clocks core_clk -include_port_paths
```

The native report and per-clock frequency metric shall be retained as evidence.
Treat internal-path reporting as a separate diagnostic with explicit path
selection and a corresponding critical-path report. With multiple clocks, retain
per-clock results; a maximum over unrelated clock frequencies is not a system limit.

Synthesis/ideal-wire and placement-estimated results shall remain labeled as
estimates. Post-CTS, routed, corner-qualified timing is stronger implementation
evidence; measured silicon frequency is a separate result. To explore the best
achievable implementation period, sweep clock targets through a flow that
actually consumes those targets, optimize each implementation, and report the
conditions of each point.

Each result shall identify whether its interface environment is the generic
standalone profile or a concrete integration, as defined in the
[build timing policy](uqu_spec.build.md#41-interface-timing-scope). Retain the
selected constraints and hashes. Internal and interface critical-path summaries
shall keep explicit endpoints and path selection; an internal-only diagnostic
shall not replace the full-interface result or imply an integrated SoC limit.
Separate path summaries remain a reporting follow-up.

## 2. Reset assumptions in frequency comparisons

The authoritative reset behavior remains the
[synchronous reset contract](uqu_spec.interfaces.md#3-active-low-synchronous-reset).
Holding reset active for several cycles does not by itself authorize multicycle
or false-path timing exceptions, particularly on reset release.

The initial exploratory SDC assigns reset the same input-delay budget as other
non-clock inputs: 20% of the target period, or 4 ns at a 20 ns target. This is a
flow assumption, not an architectural reset latency requirement. A separate
reset arrival budget may be used when justified by the integration, and shall
be recorded for the resulting `T_min`/frequency measurement. A smaller maximum
input delay gives the core more time by requiring the reset source to arrive earlier.

The build flow supports an explicit trial override, `RESET_INPUT_DELAY_NS=1`,
which selects a 0 ns minimum and 1 ns maximum reset arrival without changing
other input/output budgets. Omission preserves the original default. Resolved
reset min/max values shall be retained with the result. The
[IHP trial](../impl/asic/orfs/investigations/ihp-reset-timing.md) demonstrates the
effect on unchanged placements; its improved frequency remains conditional on
the integration meeting that reset-arrival contract.

Changing the core to tolerate distributed or multicycle reset release requires
an explicit startup/inactivity protocol and verification before corresponding
timing exceptions can be used. Such a reset-sequencer feature is not selected
by this measurement definition.

## 3. Measurement decision record

| ID | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-307 | Define `T_min` as the setup-derived minimum period of one implemented netlist under an explicit timing context, with `estimated_fmax [MHz] = 1000 / T_min [ns]`. Retain path/interface scope, stage, corner, constraints and non-setup qualification separately. | Make PPA and future benchmark frequency claims reproducible without confusing a target clock, positive margin or an optimistic timing subset with a qualified operating limit. | Agreed; definition documented; dedicated benchmark integration remains open |
