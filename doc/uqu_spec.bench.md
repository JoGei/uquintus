# uquintus Benchmarking and PPA Measurement

**Status:** Minimum-period definition agreed; CoreMark cycle-only RTL integration
implemented with native fast and fully checked modes. Wider workload coverage
remains open.

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
Both synthesis and placement runs retain setup/hold summaries and full reports
for all constrained paths, internal register-to-register paths and each interface
path class, with endpoints and slacks displayed in the HTML run page.

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

## 3. RTL workload measurements

Benchmark ports, source pins, software configurations and build instructions
shall live under `verif/sw/benchmark/<suite>/`. Hardware configurations remain
under top-level `config/`. Shared build/run helpers live in `verif/sim/common/`.
Upstream sources shall use explicit revision/checksum-pinned archive fetching
under `build/deps/`, without submodules or implicit network activity in builds.

The initial [CoreMark port](../verif/sw/benchmark/coremark/README.md) executes both
standard 2000-byte seed profiles through the existing ELF/RVFI harness. Each
profile requires valid CRCs, valid workload/timing output and successful
completion. A zero software exit code alone shall not establish correctness.
Official CoreMark scores are not claimed.

`BENCHMARK_MODE=fast` shall be the benchmark default. Its compiled Verilator
C++ driver shall execute the real RTL without Python callbacks, VPI, cocotb,
pyuvm, instruction traces, RVFI collectors or per-edge CSR models. Keep lightweight
completion/response, unexpected-trap, watchdog, enabled-counter and timer-window
checks. Python may prepare the ELF memory image and validate results afterward.
`BENCHMARK_MODE=checked` shall retain the existing instruction oracle, RVFI,
CSR and per-edge counter checks. Both modes shall validate the final workload
CRCs; a fast pass shall not be represented as per-instruction ISA verification.
Seed profile selection (`performance`/`validation`) is independent of run mode.

Both modes shall implement the same active memory transaction schedule, store
visibility/response ordering and retirement-based timing boundaries. Qualify
backend changes by comparing cycle/instruction counts and timer points on the
same executable/configuration/memory profile. The initial RV32I CoreMark profiles
match exactly across both modes. Keep mode and validation scope in report
comparison context. Waveform and Spike options require checked mode.

Measurements shall record deterministic, independent instruction/data memory
response latencies, grant behavior, fence acknowledgements, compiler/version/
flags/ISA/ABI and runtime identity, ELF/source hashes, configuration and the
measurement boundary. Random memory wait regressions remain verification tests.
The initial environment grants immediately, responds after a configurable
positive integer number of cycles (one by default) and acknowledges fences
immediately. These conditions do not imply a physical memory implementation.

Time the interval between retirement of the labeled `mcycle` reads in
`start_time()` and `stop_time()`: `(start, stop]`. Count cycles and retired
instructions independently; confirm the cycle delta against the software CSR
results. Include timer overhead within those boundaries consistently. Exclude
startup, initialization and result reporting. Reject incomplete/repeated/
reordered windows, disabled counters and intervals of 2^32 cycles or longer.

Report cycles, instructions, CPI and cycles per iteration alongside executable
segment and loaded-memory footprint. Whole-program execution counts shall be
distinguished from workload-window metrics. Retain raw evidence and publish
native records in the shared report's Benchmarks category, including failures.
Short cycle-only simulation runs shall be labeled separately from official
suite scores and shall not invent an operating frequency.

For a matching hardware configuration and explicitly stated implementation/
memory timing context, an estimated workload execution time may be derived as:

```text
estimated_execution_time [ns] = workload_cycles * T_min [ns]
```

This combines an RTL measurement with an implementation estimate, rather than
a measured silicon result. Predictor comparisons should first hold the ISA,
compiler, executable and memory model constant, then assess cycle savings
alongside implementation area and `T_min`. A broader suite such as Embench and
dynamic-predictor event metrics remain follow-ups.

## 4. Measurement decision record

| ID | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-307 | Define `T_min` as the setup-derived minimum period of one implemented netlist under an explicit timing context, with `estimated_fmax [MHz] = 1000 / T_min [ns]`. Retain path/interface scope, stage, corner, constraints and non-setup qualification separately. | Make PPA and benchmark frequency claims reproducible without confusing a target clock, positive margin or an optimistic timing subset with a qualified operating limit. | Agreed; definition documented; initial benchmark integration implemented separately |
| D-313 | Place benchmark ports/configurations in `verif/sw/benchmark/<suite>/`; start with pinned, unmodified CoreMark workloads, both standard seed profiles, deterministic memory timing, independently checked workload windows and native report artifacts. | Establish reproducible cycle measurements before implementing dynamic branch prediction, while reusing ELF/RVFI correctness checks for baseline qualification. | Implemented; broader suites and official-score qualification remain open |
| D-314 | Default benchmarks to a native Verilator fast mode with final CRC and lightweight execution/timing checks; retain explicit cocotb/pyuvm checked mode and identify both scopes in reports. Require matching cycles/instructions on identical backend qualification inputs. | Remove per-cycle verification overhead from performance sweeps while retaining a path for architectural checking and diagnosis. | Implemented; both initial RV32I CoreMark profiles match checked baselines exactly |
