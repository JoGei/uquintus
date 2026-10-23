# uquintus Benchmarking and PPA Measurement

**Status:** Minimum-period definition agreed; CoreMark and all 19 Embench-IoT
1.0 workloads integrated with the shared native fast/checked execution flow.
Initial RV32IMC Embench native measurements pass. Pareto-profile naming and
initial objectives are agreed;
configuration search and selection are deferred.

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
checks (CoreMark CRCs or the upstream Embench verifier); a fast pass shall not
be represented as per-instruction ISA verification.
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
immediately. Both grants and response inputs shall settle before either
accepted request/address is sampled: a data grant may release DE and steer a
same-cycle instruction request. Remeasure every comparison baseline when this
memory-agent behavior changes, retaining its source hash in the run report.
These conditions do not imply a physical memory implementation.

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
alongside implementation area and `T_min`. The Embench-IoT port below extends
workload coverage; normalized reference-suite selection remains open.

### 3.1. Passive branch-prediction statistics

Both fast and checked benchmark harnesses shall use the same verification-only
`uqu_bpu_monitor`. It shall observe existing core signals, without adding
synthesizable counters or changing processor ports. Carry shadow prediction
metadata through the core-owned pipeline boundaries. Sample lookup metadata
on the first valid IF presentation and retain it through backpressure; attach
actual control-flow outcomes on accepted DE transfer. Count only successful WB
retirement, excluding squashed and faulting instructions. Speculative training
may still affect the tables; these statistics describe retired instructions,
not total physical table accesses or speculative activity.

Snapshot cumulative 64-bit counters after the retirement edges of both timer
markers and subtract them to cover exactly `(start, stop]`. The retired counter
delta shall equal the independently measured instruction window. Keep the
counter catalog shared between the SystemVerilog observer and Python reader.
Retain snapshots, counts, denominators and derived rates in `bpu-stats.json`,
embed matching evidence in `benchmark.json`, and publish flat `bpu_*` metrics
and a labeled branch-prediction section in the HTML run report. The report
collector shall reject inconsistent snapshots, derived metrics or duplicate
artifact evidence. Older artifacts without the statistics scope remain usable
without inventing missing measurements.

| Measurement | Denominator / meaning |
| --- | --- |
| Control-flow mix | Retired conditional branches, JAL and JALR; taken conditional branches and compressed control flow are counted separately. |
| BTB hit rate | All retired instructions with the BTB active. Also report hits among actual retired control-flow instructions, misses and hits on ordinary instructions. |
| Raw direction accuracy | Conditional branches with prediction enabled; compare the direction policy before BTB availability gates steering. |
| Effective direction accuracy | The same conditional branches; compare actual taken state against effective predicted-taken steering. |
| Target accuracy | Actually taken, predicted-taken control-flow instructions; a wrong target is separate from a direction error. |
| Next-PC accuracy | All retired control-flow instructions with prediction enabled; compare carried prediction against actual next PC. |
| DE redirects | Actual DE correction events attached to retired instructions, including a count per 1,000 retired instructions. These do not measure lost cycles or assume a fixed branch penalty. |

Prediction mode `none` has no direction-accuracy denominator. An inactive BTB
has no hit-rate denominator. Undefined rates shall be JSON `null` and rendered
as “Not applicable”; omit their flat numeric metrics. Static-not-taken is an
enabled prediction policy and shall have a direction denominator. Always
retain predictor/BTB configuration and measurement scope with comparisons.

The same observer also carries instruction-source provenance through the
pipeline. `idata_replayed_instructions` counts successful retirements supplied
by a target instruction-data snapshot, and `idata_replay_rate` divides this by
all window retirements. Squashed, faulting and stalled presentations do not
inflate it. Schema version 2 appends this counter to the previous twenty;
validation/reporting continue accepting historical schema-1 artifacts without
inventing replay measurements for them. The retirement-window scope is unchanged.

An initial same-ELF, same-memory CoreMark performance-profile comparison on
2026-10-22 measured 1,703,569 cycles with the 16/16 bimodal/BTB configuration
and zero data slots, versus 1,280,224 with four slots per entry (now expressed
as `MUA_BTB_IDATA_HWORDS=8` without C). Both CRCs passed
and the workload retired 757,486 instructions: about 24.9% fewer cycles. These
are fast RTL cycle measurements, with one-cycle memory responses and no claimed
silicon frequency or Pareto optimality. The halfword-capacity migration preserves
the 1,280,224-cycle RV32I result. Historical fixed-slot physical measurements
are recorded in [the BPU investigation](../impl/asic/orfs/investigations/bpu-replay.md);
the [RV32IC follow-up](../impl/asic/orfs/investigations/bpu-rv32ic.md) measures
selected packed-C capacities and compares IF decompression, DE decompression
and direct compressed decoding with the same executable and physical envelope.
The [RV32IMC forwarding study](../impl/asic/orfs/investigations/forwarding-rv32imc.md)
holds BP16/BTB16/H6, IF decompression and a parallel multiplier fixed while
adding WB-to-DE, WB-to-EX, MEM-to-EX, MEM-to-DE and EX-to-DE bypasses in sequence.
Broader workloads remain to be measured.

### 3.2. Embench-IoT workloads

The [Embench-IoT port](../verif/sw/benchmark/embench/embench-iot/README.md)
shall pin stable Embench 1.0 and explicitly cover every upstream workload and
translation unit. Builds shall check manifest completeness and unchanged
local repeat counts against the verified source tree. Fetch upstream sources
only through the existing explicit archive flow, retaining license notices.

The initial preset `rv32imc_bimodal_idata_unroll32` shall use RV32IMC, full
forwarding, IF decompression, a 16-entry bimodal predictor, a 16-entry BTB with
six packed instruction halfwords per entry, iterative MUL and DIV, and a
shared unroll factor of 32. This shall not replace other hardware presets or
assign a Greek-letter profile.

Run one timed upstream `benchmark()` call after initialization and one warmup
invocation. Retain upstream `CPU_MHZ=1` workload scaling and each kernel's
`LOCAL_SCALE_FACTOR`; the scale shall not imply an operating frequency.
Exclude initialization, warmup, result verification and logging from the timed
window; include timer-call overhead under Section 3's retirement convention.
Use the unchanged upstream verifier and require its return value to equal
exactly 1. Treat unverified, failing, incomplete and watchdog runs as failures.

All 19 workloads shall be attempted in a full suite. On RV32IMC, `cubic`,
`minver`, `nbody` and `st` use software floating-point runtime routines; report
that execution policy explicitly and keep their aggregates separate from the
15 integer workloads. Use externally supplied real RV32 C/math/compiler
runtime libraries and retain their identities and hashes. Upstream dummy
libraries shall not establish correctness.

Both native and checked execution shall validate RAM-log workload identity,
scale, warmup, verification and software-cycle output against the independent
timer window. Retain per-workload report artifacts and an explicit suite
selection/completion manifest. A partial run shall not claim full coverage;
a failed required workload shall not disappear from suite aggregation.
Report cycles, instructions, CPI, footprint and passive BPU statistics without
claiming an official Embench speed/size score. Normalized suite cycle ratios
require a separately declared matching reference.

Prediction investigations shall preserve those standard warmed measurements
and report additional diagnostics separately. An empty predictor at the timer
boundary does not imply cold execution throughout a window containing many
kernel repetitions. Distinguish first kernel visits, steady repetitions and
loop-exit behavior where the execution trace permits reliable boundaries.
State whether startup history is retained or model state is explicitly empty.
Measured subwindow CPI shall identify its exact retirement boundaries and
incoming-transition costs; it shall not replace the standard timer window.

Optional fast-mode retirement traces shall retain original instruction bytes,
PCs and retirement cycles across startup, warmup and measurement, with count,
window-marker and checksum validation. The offline architectural-path model
shall compare finite direction/target capacities as well as unlimited history,
expose differences from measured RTL at its real capacity, and identify omitted
speculation and instruction-data fill timing. Unlimited history is a diagnostic
upper bound on history reuse, not evidence of perfect direction prediction,
successful replay or counterfactual CPI. Hardware selection still requires
cycle-accurate runs across the declared workload suite and physical metrics.

## 4. Pareto-optimal configuration profiles

**Status:** Naming and initial selection goals agreed; search and profile
parameter values deferred

The configuration-exploration goal shall be to identify Pareto-optimal hardware
configurations across normalized suite cycle cost, implementation area and
estimated maximum frequency. Within a declared comparison context, a
configuration is dominated if another eligible configuration has no higher
suite cycle cost, no greater area and no lower maximum frequency, with a strict
improvement in at least one objective. The Pareto set consists of the
configurations that are not dominated.

Selected points shall receive Greek-letter codes, written out in lowercase
ASCII in preset filenames. Reserve the following initial profiles:

| Code | Planned preset | Selection goal |
| --- | --- | --- |
| `alpha` | `config/uquintus-alpha.yml` | Lowest normalized suite cycle cost among eligible configurations. |
| `beta` | `config/uquintus-beta.yml` | Lowest implementation area among eligible configurations. |
| `gamma` | `config/uquintus-gamma.yml` | Highest estimated maximum frequency, equivalently lowest `T_min`, among eligible configurations. |

These are objective assignments, not measured rankings of existing presets.
Actual parameter values shall remain unspecified until selection is supported
by the completed flows and evidence. If several configurations tie for a
primary objective, the selected representative shall remain nondominated.
Different objectives may select the same parameter set; the codes shall not
force three distinct hardware implementations.

Hyperparameter search, candidate generation and automated selection shall be
deferred until the necessary implementation flows, benchmark coverage and
metrics are finalized. Before searching, define the eligible ISA/software
capabilities, versioned workload set and weights, reference measurements,
area metric and implementation stage, platforms/corners, memory timing and
constraints. Compare candidates
within consistent declared contexts; do not mix technology or timing scopes
into one unlabeled frontier. The search method, tie-breaking policy and
numerical target values remain open.

The `alpha` goal shall minimize cycles rather than estimated execution time;
it shall not imply the shortest execution time once frequency is considered.
The `gamma` goal shall use the qualified
estimated maximum-frequency definition in Section 1, rather than the requested
clock target. Area and frequency claims shall retain their implementation
context and raw evidence.

Each selected profile shall eventually be a complete explicit hardware YAML
under top-level `config/`, following the
[shared configuration contract](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets).
Retain its generated descriptive label, complete parameter fingerprint,
selection context and supporting run artifacts. A profile name shall identify
its selection goal without making a context-independent claim of optimality.

### 4.1. Normalized suite cycle cost and diagnostic CPI

For each declared workload `i`, measure the candidate's and reference's cycle
counts using the same workload-window contract from Section 3. Define:

```text
ratio_i = candidate_cycles_i / reference_cycles_i

suite_cycle_ratio = geometric_mean(ratio_1, ..., ratio_N)
                  = exp(sum(log(ratio_i)) / N)
```

`suite_cycle_ratio` shall be the initial `alpha` selection metric; lower is
better. A value of `1.0` matches the reference's aggregate cycle cost. Each
workload shall receive equal weight by default. A declared weighted suite may
instead use `exp(sum(weight_i * log(ratio_i)))`, with positive weights summing
to one. Freeze the workload membership and weights before comparing candidates;
changing a workload's run length or adding extra profiles shall not implicitly
redefine its weight. This aggregation approach follows the use of geometric
means for normalized performance ratios in the
[SPEC CPU methodology](https://www.spec.org/cpu2017/Docs/overview.html);
uquintus measurements do not constitute SPEC scores.

The suite definition shall identify workload revisions, inputs, iteration
counts, measurement windows and weights. Freeze the reference hardware
parameter snapshot, executable/compiler identities and reference cycle counts
for each selection context. All candidates shall perform the same work and
pass the required correctness checks under consistent memory timing and
software-build policies. Microarchitecture-only comparisons shall reuse the
same workload executables. Comparisons across ISA choices may rebuild with
the corresponding ISA/ABI flags, retaining compiler/options and executable
identity for each candidate. Ratios shall use finite, positive measured cycle
counts. A missing, unsupported or failing required workload shall make the
candidate ineligible for that suite, rather than disappear from its aggregate.

Integer and floating-point workload aggregates shall be reported separately.
A combined selection suite shall declare their workloads and weights explicitly.
The reference must be capable of completing every required workload under the
declared execution policy; changing that policy or reference defines a new
comparison context.

CPI shall remain a diagnostic metric:

```text
CPI_i = workload_cycles_i / retired_instructions_i
suite_CPI = sum(weight_i * CPI_i)
```

Use equal weights `1/N` by default. This is a workload-weighted mean, distinct
from dividing total suite cycles by total retired instructions, which weights
workloads by instruction count. CPI comparisons shall identify ISA/executable
differences; a lower CPI may accompany more cycles if an operation is expanded
into many software instructions. Retain per-workload cycles, instruction
counts, CPI and normalized ratios alongside both aggregates. CPI shall not
replace the normalized cycle-cost objective for selecting `alpha`.

### 4.2. Revisable Greek-letter profiles

Greek-letter codes shall retain their selection goals while their hardware
parameter sets may change. Adding benchmarks, changing workload weights,
qualifying new implementation flows or supporting new core features may produce
a different Pareto set and new `alpha`, `beta` or `gamma` representatives.
Reselection shall be an explicit reviewed update to the complete preset and its
supporting evidence, not an implicit change during a build.

For example, a CoreMark-only suite exercises integer workloads and does not
reward enabling the Zfinx FPU. A nondominated representative can therefore omit
the FPU. Adding required floating-point workloads can change eligibility and
the selected parameters, so a later profile may enable Zfinx. These outcomes
shall depend on the declared suite and eligible capabilities rather than a
permanent feature assignment to a Greek letter.

Each selection shall retain the suite definition/version or fingerprint,
reference measurements, eligible feature set, implementation context and
selected hardware parameter fingerprint with its run artifacts. Preserve prior
parameter snapshots and evidence so historical results remain attributable
after a preset changes. Reports shall compare matching contexts and distinguish
revisions with the same profile name; a Greek-letter name alone shall not
identify an immutable hardware implementation.

## 5. Measurement decision record

| ID | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-307 | Define `T_min` as the setup-derived minimum period of one implemented netlist under an explicit timing context, with `estimated_fmax [MHz] = 1000 / T_min [ns]`. Retain path/interface scope, stage, corner, constraints and non-setup qualification separately. | Make PPA and benchmark frequency claims reproducible without confusing a target clock, positive margin or an optimistic timing subset with a qualified operating limit. | Agreed; definition documented; initial benchmark integration implemented separately |
| D-313 | Place benchmark ports/configurations in `verif/sw/benchmark/<suite>/`; start with pinned, unmodified CoreMark workloads, both standard seed profiles, deterministic memory timing, independently checked workload windows and native report artifacts. | Establish reproducible cycle measurements before implementing dynamic branch prediction, while reusing ELF/RVFI correctness checks for baseline qualification. | Implemented; extended to all 19 Embench 1.0 workloads; official-score qualification remains open |
| D-314 | Default benchmarks to a native Verilator fast mode with final CRC and lightweight execution/timing checks; retain explicit cocotb/pyuvm checked mode and identify both scopes in reports. Require matching cycles/instructions on identical backend qualification inputs. | Remove per-cycle verification overhead from performance sweeps while retaining a path for architectural checking and diagnosis. | Implemented; both initial RV32I CoreMark profiles match checked baselines exactly |
