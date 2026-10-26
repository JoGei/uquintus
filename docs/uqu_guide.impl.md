# Implementation, benchmarking and timing diagnosis

Use this workflow to compare core configurations with the same software and timing assumptions, then locate the logic that limits useful performance. The [build specification](uqu_spec.build.md) defines flow contracts; the [benchmark specification](uqu_spec.bench.md) defines metrics. The [perfsim guide](uqu_guide.perfsim.md) provides the faster cycle-exploration path.

## Run synthesis and repaired placement

The supported ASIC flow is externally provisioned OpenROAD-flow-scripts (ORFS). Supply Python/PyYAML, Bender, GNU Make, Yosys and OpenROAD; enabled Zfinx also needs a compatible Slang plugin. Make does not install tools, modify the ORFS checkout or launch containers.

```sh
export ORFS_ROOT=/path/to/OpenROAD-flow-scripts
export YOSYS_EXE=/path/to/yosys
export OPENROAD_EXE=/path/to/openroad
# If Slang is not installed in Yosys's plugin directory:
export YOSYS_PLUGIN_PATH=/path/to/plugin-directory

make synth PYTHON=.venv/bin/python ASIC_FLOW=orfs \
  CONFIG=rv32i TOP=core PLATFORM=sky130hd
make impl PYTHON=.venv/bin/python CONFIG=rv32i TOP=core \
  PLATFORM=ihp-sg13g2 CLOCK_PERIOD_NS=20 RESET_INPUT_DELAY_NS=1
make report PYTHON=.venv/bin/python
```

`TOP=core` measures the full processor interface; `TOP=fpu` measures the standalone adapter/backend. `PLATFORM` supports `sky130hd` and `ihp-sg13g2`. `ASIC_FLOW` separates implementation tools from the core YAML and simulator. Future flows belong alongside `impl/asic/orfs/`; current platform adapters are ORFS-specific.

`make synth` stops after mapping and preplacement timing. `make impl` continues through floorplanning, placement and timing repair, before CTS and routing. Floorplan controls are `DIE_AREA`, `CORE_AREA` and `PLACE_DENSITY`; `JOBS` controls workers. Keep these fixed in a paired experiment.

The generated standalone SDC applies generic I/O delays, transition and output-load assumptions. It does not represent a particular SRAM, XIF coprocessor or integrated SoC. `RESET_INPUT_DELAY_NS=1` requires reset to arrive within 0–1 ns; it is an integration promise, not a timing waiver. Holding synchronous reset for several cycles does not justify a false path or multicycle release path.

For real integration assumptions, supply `SDC=/absolute/path/system.sdc`, omit the reset override and make `CLOCK_PERIOD_NS` match the supplied clock. The file is used in place so relative Tcl includes keep their meaning. Check both its original snapshot and resolved constraints. The SoC owns final interface timing.

## Establish a controlled comparison

1. Copy a complete core YAML and change one design choice. Use the shared validator and descriptive label; do not revive removed selector names from an old result.
2. Freeze the ELF and software-visible configuration for a microarchitecture comparison. Record the same memory timing, benchmark window and workload set.
3. Run appropriate component/core checks and the software self-check. A physical improvement with a functional regression is not a candidate.
4. Compare the same implementation stage, platform/corner, tools, constraints, mapping policy, floorplan and worker settings. Remeasure the control when surrounding RTL changes.
5. Compare execution time as well as cycles, area and clock period. Repeat marginal physical results before treating their ordering as stable.

Core synthesis preserves the public top-level inputs/outputs. Check the resolved top, parameters and mapped cell/register inventory to confirm that optional units remain live. A standalone arithmetic wrapper can isolate a datapath, but does not measure full-core timing or the cost of operand/result selection and pipeline control.

The baseline selects ORFS's speed ABC script with wire-load estimates enabled (`ABC_AREA=0`), removes ABC buffers before physical buffering (`REMOVE_ABC_BUFFERS=1`) and enables timing-driven placement (`GPL_TIMING_DRIVEN=1`). The runner verifies the installed script and effective settings. Keep this policy fixed; evaluate an alternative as a separate experiment rather than changing it silently. A clock target supplied to OpenROAD does not prove that an ABC script consumes Yosys's delay-target option.

## Use the exploration helpers

Reusable helpers live in `impl/asic/orfs/explore/`; generated experiment records remain under `build/`. Use `--help` to inspect required inputs before launching a sweep.

| Helper | Use case |
|---|---|
| `bpu_replay_sweep.py` | Compare direction/BTB entries, replay halfword budgets and compressed-decode variants with the same ELF; use `--candidates` for a bounded YAML list. |
| `forwarding_sweep.py` | Add forwarding routes in a controlled sequence while holding arithmetic and software fixed. |
| `place_compare.py` | Reuse mapped controls through a common floorplan/repair context to distinguish mapping from physical buffering. |
| `reset_timing.py` | Reanalyze a retained placement with an explicit reset-arrival budget; this changes constraints, not the netlist. |

The candidate lists, Tcl collateral and fixed-budget SDC examples beside these scripts are inputs to explicit experiments, not defaults for production or SoC integration. Choose the clock, memory, reset and physical scope deliberately. Keep raw outputs and the run's method/configuration snapshots with its generated report.

## Read the result at the right scope

Runs live under `build/uquintus-<hw>/orfs_<platform>/<synth|impl>-<top>-<id>/`. `make report` collects their summaries into `build/report/synthesis/`. Detailed records, raw tools' outputs and hashes remain with each generated run.

| Observation point | What it answers |
|---|---|
| `config.yml`, `parameters.json`, `config.mk`, `sources.f` | Which hardware, top and effective flow settings were measured? |
| `constraints.sdc`, resolved SDC, `coverage.rpt` | Which clock, I/O, reset and load assumptions constrain the result? Are paths missing? |
| `cells.json`, mapped/physical inventories | Did register count, arithmetic structure, buffering or physical-only cells change? |
| `timing/mapped_preplacement/` | What does the mapped design look like before physical wires and repair? |
| `timing/placed_pre_cts/` | What limits repaired placement with estimated RC and ideal clocking? |
| `summary.json`, `paths.tsv`, scoped `.rpt` files | Which launch/capture points and cells create the worst setup/hold paths? |
| `register_regions.tsv`, `regions.tsv` | Which mapped registers belong to IF, DE, EX, MEM, WB or CORE? |
| `physical/`, electrical/placement reports | Is placement legal, and do slew, capacitance, fanout or buffering dominate? |

Setup slack is required time minus arrival time. Larger is better; negative slack misses the target. Hold slack must also be nonnegative, but cannot be interpreted as a maximum-frequency estimate. For the baseline single-clock, same-edge setup context with fixed absolute constraints:

```text
T_min [ns] = target_period [ns] - worst_signed_setup_slack [ns]
Fmax_est [MHz] = 1000 / T_min [ns]
execution_time_est = workload_cycles * T_min
```

Use the actual worst signed slack, including positive margin, rather than a WNS field clamped to zero. Do not subtract TNS or add setup/uncertainty twice. Multicycle paths, latch borrowing or different clock relationships require their actual STA equations. Internal-only slack is a diagnostic, not a replacement for the full-interface frequency estimate.

A stage-region report groups paths by capture registers; the launch can be in another stage or at a port. EX→DE forwarding followed by branch and IF control can therefore be critical even when paths into EX registers have positive slack. Parent-owned pipeline boundaries belong to their receiving region. Empty/optimized-away regions have no constrained path, rather than zero delay.

Synthesis success means mapping and structural/reporting checks passed; it does not require positive setup slack. Implementation success additionally requires legal placement, setup/hold closure and zero reported electrical violations. A failed target can still have useful measured metrics. Preplacement estimates, repaired placement and routed signoff are different scopes; never compare their frequencies as if they were interchangeable.

## Diagnose high CPI

Start from verified RTL benchmark windows and an identical ELF:

```sh
make benchmark-fetch BENCHMARK=embench/embench-iot
make benchmark BENCHMARK=embench/embench-iot \
  CONFIG=rv32imc_bimodal_idata_dadda_div1 BENCHMARK_PROFILE=crc32,nsichneu,ud
# For a second compatible configuration, reuse the printed software suite:
make benchmark-run BENCHMARK=embench/embench-iot CONFIG=<candidate> \
  BENCHMARK_REUSE_SUITE=<software-suite.json> BENCHMARK_TRACE=1
```

`BENCHMARK_MODE=fast` is the native Verilator path; it still checks software completion, workload results, watchdog and timer agreement. Use `BENCHMARK_MODE=checked` when RVFI/instruction checking is needed. Tracing changes host simulation cost, not the intended workload window. See the [port guide](../verif/sw/benchmark/embench/embench-iot/README.md) for workload selection and runtime-library requirements.

| Symptom | Check first | Lesson from the experiments |
|---|---|---|
| High CPI despite full forwarding | IF supply, load/store occupancy, load-to-DE dependencies, redirects | Forwarding cannot remove structural memory waits or refill latency. Backend pressure and frontend bubbles overlap. |
| More replay storage gives little benefit | Direction/target hits and usable captured prefix | A large payload behind a colliding BTB entry is wasted. Resolve capacity/indexing before increasing payload. |
| Excellent unlimited-BTB prediction | First pass, warmup and repeated kernel behavior | Repeated deterministic paths make warmed opportunity models optimistic; a target hit alone does not prove usable replay or zero branch bubbles. |
| Compressed code lowers cycles but slows projected execution | Same-stage full-core period and DE/frontend path | Compression changes alignment, interpretation and control fan-in. The same startpoint name can hide a different path. |
| A one-cycle multiplier does not improve CPI | Operand dependencies, MEM/WB occupancy and branch recovery | Arithmetic latency is only one part of elapsed execution; compare representative workloads. |

Retain fast-mode retirement records with `BENCHMARK_TRACE=1`, then run:

```sh
.venv/bin/python verif/sim/common/benchmark_prediction.py \
  --suite <execution-suite>/suite-results.json \
  --output build/investigations/embench-prediction --jobs 2
```

Use the analyzer to separate unique branch PCs, dynamic executions, taken directions, target reuse, table conflicts and first-pass versus steady-state behavior. Its retired-path models learn online; they do not model speculative DE training, actual replay fill or fetch timing. They cannot establish hypothetical CPI or the PPA of an unlimited table. In large control-flow workloads such as nsichneu, recurring branch working sets can exceed small direct-mapped tables despite simple repeated outcomes.

Instruction/data memory assumptions must remain explicit. The current LSU issues requests in MEM and completes responses in WB; a next-cycle response can overlap the next request. Historical results from the older blocking MEM sequence must not be applied to the current design. Loads still need registered visibility before forwarding. The fetch engine has two ordered outstanding reservations; that removes local response-dependent turnover but cannot hide arbitrary external latency.

## Explore frontend and forwarding tradeoffs

Use small, separate sweeps rather than changing every capacity and bypass at once:

- Compare direction and target entries independently. Packed replay capacity is `MUA_BTB_IDATA_HWORDS`, not a count of 32-bit instructions; with C disabled it must cover whole words. More compressed instructions may fit in the same byte budget.
- Compare `MUA_REDIRECT_BYPASS` settings with replay off and on. Word-buffer bypass, same-cycle redirect request and result-queue fall-through remove different boundaries. Combined response/word bypass can extend a live memory-data path through alignment, decompression and prediction.
- Compare all supported compressed-decode placements with the same compressed ELF. Equal CPI can still produce different mapped timing, and the ordering can change with platform or replay capacity.
- Change forwarding paths individually, including retention where operands can miss a usable window. Keep youngest-writer priority; an unavailable young value must not fall back to an older producer.

The useful objective is workload execution time under a stated physical scope, not the largest table, lowest CPI or best standalone adder delay in isolation. Local frontiers from one benchmark or technology are not final Greek profiles. The general search and selection policy are in the [benchmark specification](uqu_spec.bench.md).

## Trace unexpected cross-stage timing paths

A path from data-memory status or an IRQ input to an instruction request can be real control propagation: precise fault containment, CSR read data, forwarding, branch resolution and fetch cancellation connect these regions. Distinguish a long combinational dependency from an actual feedback loop.

1. Read the full cell path and cumulative arrival times, not just endpoint names. Map nets back to hierarchy/RTL and mark data selection, ownership, readiness and side-effect boundaries.
2. Check whether idle or invalid payloads are unnecessarily forced to zero. Keeping candidate data independent of qualification can remove late control from an arithmetic cone, while valid/ready and exception rules still gate effects.
3. Check register-capture invariants and legal FU operands. Exposing a configuration's already-captured EX operands or routing native MUL/DIV's RS1/RS2 directly can remove selectors. Preserve deferred-operand routes where they are actually supported.
4. Inspect result and forwarding muxes after arithmetic. Separate source selection from completion/error controls, but preserve held results, x0, youngest-writer blocking, serialization and cancellation.
5. Run targeted behavioral/structural checks, then remeasure both full-core timing and workloads. A smaller RTL expression or fewer gates in one cone does not guarantee a better placement.

Examples of retained design lessons include separating DE candidate data from live flush/permission, keeping serialized CSR data out of speculative forwarding, distinguishing current privilege from saved event privilege, and separating idle fetch-address selection from request cancellation. None authorizes removing qualification at an architectural side-effect boundary.

Structural ancestry and zero-SCC checks establish connectivity properties. A local Boolean sensitization result may show that one reported stable path combines incompatible conditions, while its endpoints remain sensitive through other routes. That is not a timed-glitch analysis, sequential reachability proof or justification for a false-path/multicycle exception. Prefer making real architectural invariants visible in RTL over hiding a path with an exception.

## Evaluate arithmetic and storage changes

The retained multiplication choices are `iterative`, EX1-only `dadda`, and split `dadda_mac`. The split carries two product rows into MEM/EX2, inserts late C through a compressor and performs one final carry-propagate addition. It preserves independent throughput and a late-accumulator recurrence, while A/B dependencies still need the previous result before EX1. MAC hardware capability does not assign a software instruction encoding. See the [multiplier specification](uqu_spec.mul.md).

The comparisons motivated a compact set of implementations rather than a universal algorithm ranking. Booth reduces partial-product counters but adds recoding/selection; Wallace and alternative prefix adders can change both wiring and mapper behavior. Fewer counters, a faster isolated wrapper or an earlier pipeline cut did not consistently improve complete-core PPA. Measure the full cone from operand selection to its real consumer, including cross-stage forwarding.

For split versus unsplit multiplication, compare both `cycles` and `cycles * T_min`; a frequency gain must exceed any dependency penalty. Distinguish product-only execution with C tied to zero from a live-C MAC test. A third payload row or extra metadata has a register, enable and routing cost even when the arithmetic split looks balanced.

Pipeline storage can share mutually exclusive meanings. The instruction/trap-value word uses the saved exception bit as its tag; original encodings remain in passive verification history where needed. This removes hardware register bits without pruning per-stage PCs. Count surviving mapped register bits, then inspect enable fanout and repaired area. A register-count reduction can be offset by buffering and does not automatically improve placed PPA.

## Avoid misleading physical conclusions

- Compare Liberty logic area, LEF master area, physical-only cells and core/die area separately. Similar process-node names do not imply identical standard-cell density, drive strengths or library functions.
- Inspect wire-load models, sizing and synthesis buffer counts when mapping area changes dramatically. Physical buffer removal/reinsertion can erase much of a prelayout gap.
- Inspect cell versus wire delay, fanout, capacitance and slew before blaming the arithmetic algorithm. High-fanout enables and request controls can dominate unplaced timing; placement repair may expose a different limit.
- Remeasure buffer chains on the current netlist. A historical long buffer chain is not evidence that disabling buffering globally will improve the present design.
- Keep the same absolute I/O/reset budgets and analysis scope when deriving `T_min`. An earlier reset arrival can improve margin by tightening the source requirement; extra reset cycles do not create that budget.
- Do not add per-stage worst slacks or compare their raw values across different capture groups as isolated stage delays. Use the launch-to-capture table to locate coupled paths.

Keep raw measurements, commands, input identities and failed results in generated build/report artifacts. Source documentation should explain how to reproduce and interpret the experiment, while current functional requirements remain in the specs.
