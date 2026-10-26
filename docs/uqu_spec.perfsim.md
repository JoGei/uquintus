# uquintus performance simulation and design-space exploration

**Status:** Working specification for `feat/perfsim`. Sections 12–17 define the canonical MAP-DSE contract and separate queue reference. Section 17 describes current platform coverage; sections 8–11 retain earlier implementation/queue evidence.

[Overview](uqu_spec.md) · [Architecture](uqu_spec.arch.md) · [Benchmarks](uqu_spec.bench.md) · [Build](uqu_spec.build.md)

## 1. Purpose and boundaries

Provide an ETISS-based instruction-set simulation path for fast exploration of
uquintus microarchitecture settings. Use CoreDSL-derived ISA behavior and
CorePerfDSL-generated timing schedules, rather than another hand-written ISA
interpreter or importing a different processor's timing as uquintus results.
RTL remains the reference for microarchitectural timing; Spike remains the
independent ISA reference in the existing verification flow.

Performance estimates shall be identified as estimates and qualified by model
coverage and validation evidence. Successful ISA execution does not establish
cycle accuracy. Area and maximum frequency shall still come from synthesis and
physical implementation; an ISS does not supply either metric.

## 2. Source material and upstream tooling

The supplied papers are:

- Foik et al., *Flexible Generation of Fast and Accurate Software Performance
  Simulators from Compact Processor Descriptions*, TCAD/ESWEEK 2024,
  DOI [10.1109/TCAD.2024.3445255](https://doi.org/10.1109/TCAD.2024.3445255).
- Foik et al., *MAP-DSE: A Fast Performance Simulator for Large-Scale
  Microarchitectural Design Space Exploration*, supplied ASPDAC 2027 paper,
  DOI [10.1145/3840404.3848185](https://doi.org/10.1145/3840404.3848185).

The first describes a generated ASAP scheduling model driven by an ISA trace.
The second extends this approach with multiple timing states per functional
execution, shared external component evaluations and generated block schedules.
Its performance numbers are results for its evaluated processors, not promised
uquintus accuracy or simulation speed.

Relevant primary sources are [ETISS](https://github.com/tum-ei-eda/etiss),
[M2-ISA-R](https://github.com/tum-ei-eda/M2-ISA-R),
[M2-ISA-R-Perf](https://github.com/tum-ei-eda/M2-ISA-R-Perf),
[CorePerfDSL examples](https://github.com/tum-ei-eda/CorePerfDSL-Examples),
[SoftwareEvalLib](https://github.com/tum-ei-eda/SoftwareEvalLib),
[SoftwareEval-Backends](https://github.com/tum-ei-eda/SoftwareEval-Backends), and
the [performance workspace](https://github.com/tum-ei-eda/PerformanceSimulation_workspace).
The public workspace and backend have `blockSched_dev`/`dse_dev` development
branches. Integration shall pin complete commit IDs, including transitive
dependencies, and retain licenses and archive hashes. A branch name alone is
not a reproducible dependency specification.

## 3. Functional simulation contract

Reuse existing little-endian ELF32 executables and their initialized segments,
zero-filled regions, entry point and `tohost` completion convention. Reuse
benchmark symbols identifying measurement boundaries. Functional execution
shall have a host-time/instruction watchdog, a checked completion status and
retained diagnostics on failure.

One functional execution may feed multiple timing variants only when ISA,
executable, initial memory and externally visible inputs are identical. Changing
ISA extensions, software/compiler settings, timing-dependent MMIO, interrupts,
threads or instructions that use timing to affect control flow can invalidate
trace sharing. Such cases shall be rejected or separated into independent runs.
Reading the ISS's own cycle counter shall not be mistaken for the modeled
pipeline cycle count. Benchmark start/stop symbols select the timing window.

The initial profile targets deterministic single-hart integer bare-metal
execution. Unsupported XIF behavior, Zfinx, debug, asynchronous interrupts and
unmodeled instructions shall be reported explicitly rather than silently given
an ALU-like latency. Expand coverage only with corresponding validation.

## 4. Microarchitecture model contract

Complete YAML configurations in `config/` remain authoritative. A deterministic
adapter shall derive a model configuration and descriptive label using the
existing configuration validator. It shall distinguish:

| Category | Treatment |
| --- | --- |
| ISA and software inputs | Functional-execution identity. |
| Pipeline/forwarding/arithmetic structure | Generated CorePerfDSL schedule identity. |
| Predictor or memory component settings | External model identity; share evaluations only when their state/input contracts match. |
| FF/latch backend and other timing-neutral implementation choices | Recorded in the hardware identity, without inventing an execution-cycle effect. |

The model shall represent the actual five stages IF, DE, EX, MEM/EX2 and WB,
with single issue, in-order retirement, backpressure, and DE branch resolution.
MUL's EX1-only, iterative and split MEM/EX2 choices and DIV's fixed unroll-based
latency shall remain distinct. Store data is required in EX. LSU requests issue
in MEM and responses complete in WB; loads may not forward a raw response.
CSR serialization, forwarding choices and fetch buffers/bypasses require their
own timing semantics; a generic five-stage reference is not an accuracy claim.

For each exposed configuration field, report whether it is modeled, inactive,
timing-neutral or unsupported. A requested active feature outside the current
model profile shall fail before a DSE result can be labeled valid.

### 4.1. Shared YAML configuration frontend

The performance simulator shall accept the same `CONFIG=<preset-or-YAML-path>` entry point as the RTL flows, and use their shared complete-schema validator and canonical selector catalog. A reusable configuration frontend shall derive one resolved plan for both CorePerfDSL generation and external-model configuration. Generation and execution shall consume that plan rather than independently reinterpreting hardware fields.

| Hardware input | Resolved consumer |
| --- | --- |
| `ISA_*`, `HART_ID` | Functional ISA/profile guard, `misa`, available privilege modes and hart identity. Execution starts in M mode; v7 adds declared synchronous M/U trap scenarios. |
| `MUA_MUL`, `MUA_DIV`, `MUA_MULDIV_ITERUNROLL` | Generated execution latencies and split MUL schedule. |
| `MUA_FORWARDING`, forwarding path selectors | Supported generated dependency paths or an explicit unsupported-profile error. |
| `MUA_BRANCH_PREDICTOR` | Shared trace-driven branch-outcome/PC mapping; branch-hold policy in the queue reference. |
| `MUA_IF_BUFFER_WORDS` | Finite word-buffer capacity in the queue reference and all supported MAP-DSE branch policies. |
| `MUA_REDIRECT_BYPASS` | RTL-encoded queue-reference bypass mask; constant branch redirect transport in MAP-DSE. |
| Timing-neutral/inactive settings | Retained in the complete hardware identity and coverage; no invented cycle effect. |

`make perfsim-config` shall validate and export the resolved plan without requiring ETISS, upstream downloads or model-generator environments. Outputs are `resolved.json`, a complete `config.yml`, `uqu.corePerfDsl` and `external_models.inc` under `build/uquintus-<hw>/perfsim/config/`. Normal execution shall retain the same resolved artifacts in its run directory. The plan shall include source/parameter/selector identities, encoded RTL values, functional settings, CorePerfDSL identity/settings, external-model implementation/parameters, coverage and calibration status.

The complete hardware fingerprint shall remain distinct from the effective timing-model fingerprint: FF/latch variants can share a cycle schedule while remaining separate hardware candidates. External-model settings shall participate in timing-model identity. Batched execution shall still require identical functional/integration settings. Memory response latencies remain environment settings recorded alongside the hardware plan, rather than extra synthesizable-core parameters.

## 5. MAP-DSE integration strategy

Start with generated instruction scheduling and validate the instruction trace
and timing windows. Keep the upstream multi-variant/block scheduling interfaces
available for subsequent acceleration. Group variants by pipeline schedule
identity: forwarding or execution-latency changes may require separate generated
schedules. Predictor capacities can share a structural schedule when their
external timing interface is identical.

Each timing variant needs independent pipeline and dependency state. Predictor state may be shared across combinations under the trace-driven model contract.
Share a component evaluation only across variants using the same component
instance semantics and the same input trace. Preserve startup/warmup history;
do not reset predictor state at the measurement boundary unless a separately
labeled cold-start experiment requests that behavior.

Block scheduling shall be enabled only after equivalence against instruction
scheduling on the same traces, including branches, register dependencies and
variable memory delays. Report model-generation/compilation time separately
from execution time. Do not label a Python trace replay or independent ISS runs
as the paper's generated multi-variant/block backend.

## 6. Build, artifacts and reporting

Use explicit Make targets for dependency fetching, model generation and execution.
Do not add repository submodules or automatically install host dependencies.
Tools and their installations may be supplied by environment; downloaded source
archives and optional local builds belong under ignored `build/` directories.
Project-owned model/runner files and pinned dependency metadata are versioned.

Generated model inputs, C++ schedules, ETISS configuration, commands, executable
and source hashes, dependency/tool versions, logs, measured windows and JSON
results shall be retained under `build/uquintus-<hw>/perfsim/`. Report host wall
time, modeled cycles, instructions and CPI separately. Existing HTML reporting
shall identify the performance-simulation backend, estimator scope and validation
status so estimated cycles cannot replace measured RTL benchmark records.

## 7. Validation and DSE acceptance

First validate dependency identity, configuration translation, generator output,
actual ETISS execution and checked completion on directed programs. Cover ALU
dependencies, loads/stores, taken/not-taken branches, multiply/divide and the
measurement boundary. Compare functional traces with the same executable on
the native RTL harness before interpreting timing estimates.

For calibrated timing profiles, report per-program absolute/relative cycle error
against matched RTL runs, with identical software, measurement windows, memory
latencies and warmup policy. Include worst error, not just an average. A model
without calibration shall remain explicitly uncalibrated; no numeric accuracy
threshold is assumed from another processor's paper results.

Candidate ranking uses the existing geometric mean of per-workload cycle ratios
against a declared reference. Do not compare CPI alone across differently
compiled executables. Greek-letter Pareto configurations remain provisional
and require RTL/PPA confirmation on the selected workload suite. Automated
search and claims of a complete uquintus timing model are later milestones.

## 8. Implementation record

The first implementation uses a pinned public `blockSched_dev` workspace, two isolated generator environments and a native C++ harness. See the [setup and usage guide](../verif/perfsim/README.md). Commit IDs and archive hashes for all 17 source dependencies are stored in `config/perfsim/upstream.lock.json`; no repository submodules are added. The Make targets are `perfsim-fetch`, `perfsim-model` and `perfsim`.

The executable profile is deliberately narrower than Sections 3–5's full target. The frontend was subsequently refined as described in Section 9:

| Feature | Initial implementation |
| --- | --- |
| Functional ISA | RV32I/M, M-mode deterministic bare-metal execution, little-endian ELF32 and checked `tohost`. |
| Arithmetic | Iterative MUL, EX-only PP/Dadda/BK MUL, split EX/MEM MUL; iterative DIV with the configured unroll factor. Custom MAC instructions are excluded. |
| Dependencies | Register availability with aggregate full forwarding or global forwarding disabled. Partial paths are rejected. |
| Frontend | None/static-not-taken policy; two outstanding/reserved requests, registered results, configurable word FIFO and all eight bypass combinations. No compressed or BTB/replay model. |
| Memory | Immediate ordered instruction grants with fixed response latency; simplified data-memory scheduling resource. No timing-dependent MMIO, traps, IRQs or protection. |
| CSR | Serialized startup identity/vector/scratch operations and the two recognized measurement-counter reads. Other CSR accesses fail. |
| Multi-variant execution | One functional execution feeds independent generated schedules with an identical trace schema; timing-neutral configurations can reuse a schedule. |
| MAP-DSE acceleration | Deferred in this historical first implementation; Sections 12–17 define the current composed-block/shared-model path. |
| PPA | Still supplied by synthesis/implementation, never estimated by ETISS. |

The runner records complete configuration/coverage, executable/source hashes, the actual upstream tree digest, ETISS/ISA/JIT binary hashes, generator package versions, commands, build/execution time and estimator scope. Generated sources and build logs live in a shared content-addressed cache under `build/perfsim-models/`; each run records that cache location and a build snapshot. Estimated results have their own HTML report category and cannot replace RTL benchmark records.

Two recorded patches adapt development-branch generator code: ISA-name-based branch classification replaces hard-coded example-core IDs, and numeric instruction emission replaces bitset strings that C otherwise interprets as octal. The latter was caught by comparing original instruction encodings against RTL. The downloaded upstream trees remain unchanged.

Initial validation on 2026-10-25 executed the existing smoke program, a directed self-checking ALU/RAW/load/store/branch/MUL/DIV program, and the one-iteration CoreMark performance profile. The corrected ETISS stream exactly matches the directed RTL stream and CoreMark's 327,654-instruction prefix through the stop marker. The CoreMark measured window contains 314,834 instructions on both backends; all workload CRC checks pass.

A five-model batch also exercises global forwarding disable and static-not-taken prediction. Separate negative probes reject a failing software exit, an infinite loop at the instruction watchdog, an unsupported CSR program and execution of M instructions under an RV32I identity. These are checks of coverage/error handling, not evidence of timing accuracy.

For `rv32im_dadda` with next-cycle memory, the initial generated estimate is **463,858 cycles**, compared with **573,657 RTL cycles**: signed error **−109,799 cycles (−19.14%)**. This is evidence of remaining timing-model error, not an accuracy qualification. Calibration status remains **uncalibrated**. The trace comparator records signed, absolute and relative cycle errors only when ELF/configuration/memory/window identities agree. It excludes post-stop timer formatting, whose instruction path may depend on the backend's counter value.

Subsequent compressed/admission calibration and experimental scheduling acceleration are recorded below. Automatic Pareto promotion remains deferred.

## 9. Queue-reference frontend model refinement

Version `uqu-five-stage-frontend-v2` keeps [CorePerfDSL](../verif/perfsim/models/uqu.corePerfDsl.in) as the source of the generated pipeline schedule. A native external connector component models the frontend's stateful queues, as permitted by CorePerfDSL's external-model interface. ETISS supplies instruction identity and the architectural next PC; the timing component does not implement branch semantics itself.

The generated `IfConsumed` callback is driven by IF completion, after DE backpressure is applied. `DeAdvanced` is driven by DE completion, after EX backpressure is applied. These callbacks distinguish branch arithmetic readiness from permission to advance and redirect. Each variant retains independent frontend state because downstream stalls affect its prefetch history even when frontend parameters match.

The component tracks two granted/result reservations, ordered outstanding responses, two registered result slots, the private request slot and the configurable fetched-word FIFO. It preserves killed work until its response, registered-credit release, request persistence and the independent `if_buffer`, `redirect_request` and `ifetch_result` bypass policies. The no-prediction policy stops new native fetches while a control-flow instruction occupies DE, while respecting previously armed requests and buffered delivery. Target fetching includes the actual request, response and storage boundaries rather than a fitted branch penalty.

`make perfsim-test-frontend` compares this queue component with the actual `uqu_stage_if` RTL on every simulated edge. Its default matrix covers all eight bypass masks, word depths 2/4 and grant-to-response latencies 1/2/5. All **48 cases / 144,000 edges** pass, checking IF valid/PC and OBI request/address under consumer stalls, branch holds and consecutive redirects. This is simulation evidence for the stated profile, not a formal proof or coverage of compressed instructions, faults, variable grants or predictor replay.

Workload validation holds each ELF, complete hardware parameters, measurement window and fixed memory latency identical between the model and RTL. The baseline is `rv32im_dadda`: no C/BTB/prediction, Dadda EX-only MUL, iterative DIV/unroll 8, full forwarding, two word-buffer slots. The second configuration changes only `MUA_REDIRECT_BYPASS` from `none` to `if_buffer+redirect_request+ifetch_result`. GCC 13.2.0 and the existing `-O2` ports are used; both memories grant immediately and return next cycle.

| Workload | Bypass | RTL cycles | Estimated cycles | Signed error |
| --- | --- | ---: | ---: | ---: |
| CoreMark performance | None | 573,657 | 568,684 | −0.87% |
| CoreMark performance | All three | 457,495 | 449,149 | −1.82% |
| Embench CRC32 | None | 6,792,236 | 6,618,499 | −2.56% |
| Embench CRC32 | All three | 5,224,484 | 5,050,747 | −3.33% |
| Embench nsichneu | None | 6,231,380 | 6,232,613 | +0.02% |
| Embench nsichneu | All three | 5,156,702 | 5,157,936 | +0.02% |
| Embench UD | None | 5,453,887 | 5,416,939 | −0.68% |
| Embench UD | All three | 4,343,897 | 4,296,604 | −1.09% |

All eight executions pass their workload self-checks, have matching window instruction counts and match the RTL PC/original-encoding prefix through the stop marker. The former CoreMark baseline error of −19.14% falls to −0.87% without introducing a workload-specific penalty. Native per-model stage timestamps are optionally retained as `timing-<model-id>.csv` alongside the functional trace.

The largest absolute aggregate error in this small validation set is **3.33%**. This is an observation, not a bound for other workloads/configurations or per-instruction timing. Remaining register/LSU/serialization and backend-admission approximations can interact with frontend stalls; low total error can conceal cancellation. Model status remains **uncalibrated**, and RTL confirmation is still required for Pareto decisions.

## 10. Compressed-instruction accuracy and DE admission

The integer performance-simulation profile shall include RV32C using the pinned CoreDSL ISA semantics and explicit CorePerfDSL mappings for compressed arithmetic, loads/stores and control flow. Register identifiers shall account for compact-register offsets, implicit stack/link registers and read-modify-write operands. Functional execution shall enforce the configured M/C availability. PC and trace comparison shall support two-byte instruction alignment.

The external frontend model shall consume two or four bytes per accepted instruction, retain the unconsumed halfword, align redirect memory requests to words and wait for a consecutive successor word when a 32-bit instruction crosses a boundary. All three C decode implementation/placement choices remain cycle-equivalent until RTL comparison demonstrates otherwise; they remain distinct hardware configurations. Queue checks shall include both I and C fetch with redirects, backpressure, every bypass combination and varied buffer depths/response latencies.

Generated schedules shall model operand admission in DE separately from execution-result availability. With full forwarding, EX/MEM arithmetic candidates may qualify same-cycle DE capture. An incoming load response may retire at its response edge, but does not provide a combinational response-to-DE bypass: capture becomes possible at the following edge. With forwarding disabled, RF writeback similarly precedes the next DE capture edge. Branch comparison shall constrain the DE completion edge directly, using DE operand admission times; the decoder supplies the ordinary DE cycle. Same-cycle EX-to-DE forwarding shall not acquire an extra serial comparison cycle. No workload-specific cycle correction shall replace these constraints.

`verif/perfsim/calibrate.py` shall automate matched RTL/perfsim pairs over complete hardware YAMLs and benchmark ELFs. It shall preserve functional validation, exact PC/original-encoding comparison through the stop marker, identical instruction-count windows and memory timing before reporting cycle errors. The fast RTL memory trace shall be length-normalized for C; bytes following a compressed instruction shall not be treated as part of its encoding. Sweeps shall retain failed pairs and report mean signed, mean absolute and worst absolute relative errors with per-pair cycles/CPI and run provenance. A model revision may reuse completed RTL evidence while retaining the previous summary.

The first declared matrix is `config/perfsim/rv32imc-accuracy.yml`. It expands experiment choices into complete core YAMLs using the shared validator. In that historical implementation F/Zfinx, BTB/replay/bimodal and partial forwarding were unsupported; Sections 12 and 15 describe the later BPU support and remaining limits. The model remains experimental and uncalibrated beyond the tested conditions.

## 11. Host execution cost

Simulation-level cost shall be measured independently of modeled/RTL target cycles. Compare the same validated workload/configurations using the native fast RTL harness and native ETISS/CorePerfDSL execution. Disable waveform, retirement, instruction and per-stage timestamp traces on both sides. Retain CRC/self-check, completion/watchdog and count validation. Do not derive trace-free speedups from the earlier traced accuracy-run wall times.

Report separate single-configuration and multi-configuration costs. A single-model executable shall actually contain one timing state. A batch shall disclose the number of hardware candidates and distinct timing states; equivalent schedules may share a state. RTL sweep cost is the serial sum of per-configuration runtime medians; the ISS batch executes the functional ISA once per workload. This does not imply MAP-DSE block scheduling or measure a bare ISS without timing estimation.

Elapsed time shall cover a complete native process: startup/JIT, input loading, startup/warmup/software completion and native output writing. It shall exclude Python preparation/post-validation and build/report generation. Retain the distinction from full Make/runner latency and from the benchmark's target-cycle window. Fresh processes include JIT compilation in every trial; discarded process warmups do not turn the experiment into persistent-JIT throughput. Rotate backend trial order and retain common CPU affinity, host/load, executable identities, sample counts, medians and ranges. Shared-host results remain empirical observations.

Build costs shall be reported separately, with cache-hit status and tool/job identities. Historical build records must not be labeled a synchronized cold-build comparison. Dependency/tool installation and software compilation shall not enter execution speedups. CPU resource accounting shall be per child rather than a cumulative process-tree maximum; launch-inclusive RSS shall not be advertised as the backend's working-set footprint. Suite speedup shall divide summed runtimes, without averaging per-workload speedups.

`make perfsim-cost PERFSIM_ACCURACY=<completed-run>` shall expose the default experiment. `verif/perfsim/benchmark_cost.py` supplies sampling, CPU and baseline controls. Artifacts belong under `build/investigations/perfsim-cost/`, with machine-readable samples, validated outputs and a portable human-readable table.

## 12. Canonical MAP-DSE execution contract

The DSE path shall follow the MAP-DSE formulation and pinned upstream implementation: one CoreDSL/ETISS functional trace; trace-driven external resource/branch models shared across combinations; independent timing-state vectors; branch-boundary PC mapping; and max-plus composition of instruction matrices into block matrices. `PERFSIM_SCHEDULER=map_explorer` shall be the Make/CLI default. The complete hardware YAML remains the entry point; these host-model choices do not add RTL parameters.

The model contract shall be explicitly identified as `map_dse`, separately versioned from the detailed `queue` reference. The generated CorePerfDSL shall describe pipeline resources, register readiness/admission and serialization. Shared resource models shall return instruction-trace-derived delays and shall not consume IF acceptance, DE advance or other scheduling timestamps. Branch models shall cache control-flow outcomes and select candidate PC timestamps from scheduling state, as in MAP-DSE. Model sharing shall reuse each distinct trace-driven model's outputs across combinations rather than use histories of pipeline callbacks as cache keys.

The integer contract shall use shared trace-driven frontend and BPU components; fixed arithmetic/data-memory latencies shall remain in the scheduling graph. Version `uqu-map-dse-v6` shall model finite request/result/word queues for none/static-not-taken/bimodal policies on an independent reference clock. Its reference occupancy calendar shall account for EX arithmetic, MEM/WB backpressure, operand admission, split multiplication and CSR serialization without consuming timestamps from scheduled timing combinations. Queues may skip idle cycles only when no state transition can occur, and shall stop before response/branch events. Component-state equivalence shall check this optimization.

Identical backend/frontend envelopes may share outputs; different backend occupancies shall be part of envelope identity. BPU event histories shall share only across identical reference timing envelopes; matching direction/target/replay parameters alone shall not permit sharing across different backend clocks. It shall model tagged saturating counters, direct-mapped target replacement, ordinary-instruction invalidation and packed halfword prefixes. The event-level component shall preserve read-before-write lookup, simultaneous DE update/IF capture, retained-prefix checks, capacity and invalidation semantics. DE updates before IF validity shall precede lookup. Updates on the IF capture edge shall preserve read-before-write semantics and simultaneous prefix capture; lookup decisions shall remain held through IF backpressure. A local prediction clear shall preserve same-cycle source consumption and registered result-credit release, while global recovery shall suppress old-stream outputs. The no-trap integer core shall suppress IF acceptance during DE correction; speculative memory traffic shall remain modeled separately from accepted instruction capture.

Prediction at IF shall select a predicted candidate, with normal fetch transport or immediate replay availability. Replay shall preserve original encodings/lengths, discard a prefix on correction and resume memory fetch after the prefix. A target equal to fallthrough shall not incur a steering penalty. DE correction shall use actual DE-advance timing through a linear scheduling-state edge. A fallthrough branch may consume prefetched instructions; request hold shall be represented by queue state rather than an unconditional DE wait. Memory-response and redirect delays shall reflect outstanding traffic in the reference queues.

Operand retention shall be cycle-equivalent in the full/global-disabled forwarding profile. With partial forwarding, the model shall preserve sources captured while DE waits and distinguish retention from continuous resolution. RTL checks shall include multi-operand waits, missed bypass windows and sustained memory/arithmetic pressure. This shall not qualify custom MAC or XIF behavior. Configuration coverage shall distinguish modeled, cycle-equivalent, inactive and unsupported features. No per-workload correction factors shall be fitted, and passing one latency profile shall not qualify another.

## 13. Upstream implementation and block verification

The integration shall reuse upstream `BlockExtractor`, `MatrixTransformer`, instruction-matrix multiplication, `BlockScheduleGenerator` composition/reduction and `MAPExplorer` resource groups, delay vectors and timing combinations. Tracked patches shall apply only to private build copies and preserve upstream version/hash pins and license notices. Patches shall provide explicit uqu connector mappings and fix demonstrated generator/runtime defects; they shall not introduce a per-instruction cycle-simulation feedback path.

Extraction shall preserve blocks across ETISS channel batches and terminate at actual control flow. Measurement markers and program completion may additionally terminate blocks without becoming branch-prediction events. Blocks exceeding the upstream delay-vector capacity may be split consistently across timing variants. Profile caches shall bind ELF, functional configuration, normalized trace schema, operand masks and extractor identity. Reuse shall check the profile hash. Each PC shall have an immutable encoding/type/operand identity, and unknown identities or block starts shall fail execution without a hidden instruction-scheduler fallback. Missing monitor register fields shall be explicitly zero initialized; explicit ISA mappings shall be preserved.

Block generation shall compose complete instruction matrices before emitting a scheduling function. External model delays may still be evaluated per instruction; timing-state scheduling shall occur once per completed block and combination. Shared fetch/branch model counts, actual model evaluations, block calls and scheduled-instruction counts shall be reported. Upstream byte delay vectors shall be range checked, including straddling-instruction costs. Register result availability, operand admission, x0, load visibility and CSR committed-time contracts shall be preserved in the matrices.

`PERFSIM_VERIFY_SCHEDULING=1` shall compare block-boundary timing state with independently generated instruction schedules of the **same timing contract**. The oracle shall advance for every instruction and compare stages, entrance, both GPR timestamp banks, serialization and candidate/input PC timestamps at every completed block. The oracle shall not provide inputs to the block scheduler or shared models. Randomized algebra tests shall compare emitted block functions against numeric products of individual instruction matrices. Runtime tests shall cover cross-channel blocks, shared delay-vector reuse/reset, branch-boundary mapping, independent combinations and small/unknown block dictionaries.

`verif/perfsim/compare_map.py` shall separately validate functional instruction prefixes and timing windows against retained matched RTL runs, reporting per-configuration/benchmark cycles, CPI and signed/absolute error. A changed timing contract shall not be forced to match an earlier estimator's cycle counts. Host-cost trials shall compare instruction and block scheduling of the same contract, disable traces/reference checks, use repeated fresh processes with common CPU affinity and preserve software CRC/self-checks. Preparation and native runtime costs shall be separate. The driver shall record and enforce configurable mean/worst relative RTL-error budgets (default 0.1% / 0.5% for the current integer matrix). Optional retained queue-hybrid comparisons shall validate identical configuration/ELF identities, executable hashes and each contract's own expected cycles, then remeasure native processes with common affinity and tracing disabled.

## 14. Detailed queue reference and historical adapters

`PERFSIM_SCHEDULER=instruction` with `--model-contract queue` shall retain the detailed frontend queue model as an accuracy reference. The earlier project `block` adapter remains available for that contract, with ordered per-instruction frontend feedback and optional history-based sharing. These paths shall be labeled distinctly from canonical MAP-DSE; they shall not be presented as upstream whole-block scheduling. Their existing instruction-level state checks and retained measurements remain useful reference evidence.

The initial MAPExplorer experiment using one-instruction feedback boundaries is superseded by the composed-block integration. Its retained artifacts document that historical experiment; its speed/accuracy results shall not be attributed to the current model contract.


## 15. Qualification and remaining extensions

The historical v6 forwarding refinement and evidence are described in [fine forwarding](../verif/perfsim/investigations/fine-forwarding.md). The retained v5 refinement and evidence are described in [replay event ordering](../verif/perfsim/investigations/replay-events.md); [frontend/BPU qualification](../verif/perfsim/investigations/frontend-bpu.md) retains the v4 results. Separate studies shall cover the original RV32IMC matrix, frontend pressure under longer fixed memory latency, and BPU/replay configurations. Native measurements shall run sequentially on the same CPU with traces/reference checks disabled. A retained RTL trace may be reused only after validating hardware, ELF/environment, all recorded source hashes and the trace hash. Environment overrides shall preserve unchanged ELF identity and record the parent metadata hash.

Combined replay/longer-memory profiles shall pass their own unchanged accuracy gates before promotion. The v4 failure remains retained as historical evidence; correcting event order shall not relabel old results. Replay capacity, arithmetic occupancy and memory latency shall be varied in matched RTL studies rather than hidden with a benchmark correction or a looser implicit threshold.

Subsequent extensions shall remain fail-closed until their own functional and RTL evidence exists:

- Zfinx requires authoritative integer-register floating-point semantics, three-source instructions, FCSR/rounding/exception flags and the selected CVFPU configuration/latency model. Standard F is deferred in RTL and shall not be enabled by merely removing an estimator guard.
- Section 17 defines the initial protection/synchronous-trap profile. XIF, asynchronous interrupts and debug still require event and architectural-state checks covering commit/cancel, side effects and redirection. A matching ordinary retirement PC stream alone shall not qualify them.
- Fence.i/invalidation, writable code and external memory errors remain unsupported. Section 17 defines variable-grant timing and cache placeholders.

DSE shall use only error-gated, qualified profiles for candidate promotion. PPA and final selection shall still be confirmed in RTL/implementation; the shared resource calendar is not a physical timing model.


## 16. Fine forwarding and DE operand retention

The MAP-DSE frontend shall consume every existing forwarding selector from the same complete core YAML used by RTL. `MUA_FORWARDING` shall gate the four independent paths `MUA_FORWARD_EX_TO_DE`, `MUA_FORWARD_MEM_TO_DE`, `MUA_FORWARD_MEM_TO_EX` and `MUA_FORWARD_WB_TO_EX`. WB-to-DE shall follow the master, as in RTL. Disabled subordinate choices shall normalize out of timing identity when the master is off.

An independent trace-derived producer calendar shall preserve each youngest writer's EX readiness and EX/MEM/WB occupancy windows. A pending younger writer shall prevent fallback to an older value or the RF. Branch/JALR and CSR sources shall be available in DE; native EX consumers may enter under the same future MEM/WB bypass guarantee as RTL. A missing path shall stall until an enabled usable path or post-write RF read becomes possible. Store data shall obey the EX operand contract. Raw memory responses shall remain excluded from forwarding; split multiplication shall become forwardable in MEM.

`MUA_DE_OPERAND_RETENTION=1` shall retain sources available while the DE instruction is held. Continuous resolution shall revisit live windows and RF state. For example, with EX-to-DE enabled and MEM-to-DE disabled, a branch waiting for two preceding ADD results may see its younger source in EX while its older source waits in MEM. Retaining the younger source allows the branch to proceed when the older reaches WB; continuous resolution must also wait for the younger source's next enabled window.

A trace-driven external `hazardModel` resource shall return the additional admission delay. Its independent reference state may share the frontend/BPU envelope but shall never consume timing-vector timestamps. The generated CorePerfDSL shall express the admission base and resource dependency; upstream instruction-matrix multiplication and block composition shall retain whole-block scheduling. The ordinary generated instruction schedule shall provide a separate full-state equivalence oracle. Upstream positive symbolic delays shall encode an admission wait as `wait+1`, paired with a base biased by minus one. Byte overflow shall fail explicitly. V6 used two delays per instruction. V7 adds grant/response delays on memory operations: splitting shall respect the upstream 100-entry delay-vector bound (50 non-memory or 25 memory operations, with mixed blocks bounded by their actual delay count).

All 16 route masks, both retention policies and master-off controls shall pass component comparisons with actual RTL. Whole-core qualification shall include the same ELF/hardware/environment, predictor/replay feedback, fixed memory pressure, exact retirement-prefix checks and unchanged error budgets. `config/perfsim/forwarding-accuracy.yml` shall define the initial matrix. The legacy queue contract may continue rejecting partial forwarding explicitly; it shall not silently substitute aggregate forwarding.


The v6 qualification record covers 166 comparisons / 165 distinct hardware/workload/environment pairs, with maximum absolute cycle error one. All 68 forwarding-matrix CoreMark pairs and 12 additional Embench forwarding pairs pass the unchanged gates. The component check covers 34,000 admission scenarios and 264,649 RTL edges. See [fine forwarding](../verif/perfsim/investigations/fine-forwarding.md) for scope, evidence hashes, per-case CPI and native scheduling-cost measurements. These observations shall not be generalized into a universal timing-error bound.

## 17. Memory environments, RV32E and synchronous architectural events (v7)

`uqu-map-dse-v7` extends the preceding v6 contract. Earlier qualification tables remain historical evidence for their recorded source hashes; they do not qualify v7 automatically.

### 17.1. External memory timing and cache placeholders

The complete core YAML remains the hardware entry point. `PERFSIM_MEMORY=<YAML>` / `--memory <YAML>` optionally selects a separate external memory environment. Caches are outside the core and therefore shall not introduce fictitious RTL cache parameters. Without this option the existing instruction/data latency arguments select independent, immediately granted fixed-latency ports.

Each `imem` / `dmem` entry supplies all fields:

```yaml
imem:
  grant_pattern: [1, 0, 1, 1]
  response_cycles: [1, 3, 2, 1]
  cache: {lines: 0, line_bytes: 16, hit_cycles: 1, miss_cycles: 8}
dmem:
  grant_pattern: [1]
  response_cycles: [2]
  cache: {lines: 16, line_bytes: 16, hit_cycles: 1, miss_cycles: 8}
```

Grant availability is periodic in post-reset edges, starting at slot zero on edge one. Without a cache, `(byte_address >> 2) % len(response_cycles)` selects the response delay. Responses remain ordered, with at most one response per port per cycle. Finite frontend credits, held requests and backend backpressure remain modeled. Data grants and responses have separate shared CorePerfDSL resource models; a grant in MEM and completion in WB may overlap successive instructions. They use the independent reference calendar, never timestamps fed back from a scheduled timing combination.

`lines: 0` disables caching. Otherwise the minimal timing placeholder is a cold, direct-mapped, blocking tag array with power-of-two lines and line size. A read miss installs a tag and blocks new grants until fill completion; stores update backing memory at grant, use the hit/miss delay, and do not allocate on a miss. No architectural data resides in this array. There are no dirty lines, writeback, bursts, MSHRs, prefetching, coherence or cache RTL. This is deliberately a small exploration stub, not a validated cache implementation or a predictor of cache area/energy. Independent RTL/reference memories exercise identical timing policies; software self-checks validate data effects separately.

The environment participates in timing-model identities and retained reports. It does not change functional trace identity for the deterministic, single-hart programs accepted here. Timing-dependent MMIO and asynchronous interrupts remain excluded. Native delay vectors remain byte-sized: each response is 1..254 cycles, and combined grant/hazard/fetch waits are range checked; unsupported long stalls fail explicitly.

### 17.2. RV32E

`ISA_E=1` selects a 16-register architectural profile, E rather than I in `misa`, and separately compiled `rv32e...` / `ilp32e` software. The adapter checks only actually used operands, rejecting encodings that reference x16–x31 before effects occur. Existing integer timing, compressed instructions, arithmetic configuration and individual forwarding selectors continue to derive from the same complete hardware YAML. RV32I and RV32E executables shall never be merged into one functional execution. `config/rv32e.yml` is the basic preset; `verif/sw/perfsim_e/` checks legal low-register execution and an explicitly declared forbidden-register trap.

### 17.3. CSRs, PMP and traps

CSR serialization was already represented in the schedule; that did not imply a complete functional CSR model. The v7 native architectural adapter implements the sparse RTL CSR map, read/write suppression, privilege checks, WARL masks, PMP locking and M/U transitions. Normal integer instruction semantics continue to come from CoreDSL/ETISS. Unreset PMP address payloads must be initialized before reads; unsupported accesses fail rather than inventing reset contents.

PMP uses the RTL's sixteen G=0 entries with TOR, NA4, NAPOT, first-match/whole-access permission checks, M-mode lock rules and data MPRV. Denied loads/stores produce no architectural memory access. The initial timing profile requires prediction disabled and immediate-grant, one-cycle instruction memory without a cache. A denied fetch still approximates the frontend's local fault transport to within the measured directed-test error; arbitrary protection changes affecting prefetched words and longer/cacheable fetch-fault transport are not yet qualified.

An ETISS successor PC tells us where a handler runs, but does not specify the pipeline cost. The trace therefore carries architectural events classified by discovery stage. Faults and MRET terminate blocks, suppress normal instruction effects and update PC/recovery state at WB. The model preserves pipeline occupancy and older-operation completion before recovery. Faulting instructions appear in the execution trace but do not increment retired-instruction metrics. The core's no-interrupt WFI behavior is a nop. Decoder-fallback illegal instructions must be traced explicitly because the upstream tracer omits them by default.

Synchronous traps are opt-in through the existing ELF-embedded ordered `(PC, cause, mtval)` manifest. Unexpected/missing/extra events fail. The native and RTL references compare this sequence as well as exact instruction PC/original encoding through the stop marker. The adapter implements trap-state updates (`mepc`, `mcause`, `mtval`, `mstatus`), direct BASE entry for synchronous traps even with vectored `mtvec`, and serialized MRET. Initial trap timing requires prediction disabled. There are no injected IRQs, coprocessor exceptions or debug events. The MAPExplorer dictionary still requires immutable instruction/event identity per PC; retrying one PC first as a fault and then as a successful operation is explicitly unsupported.

`mcycle` values supplied by the functional ISS are not the modeled pipeline's clock. Uninhibited cycle-counter reads are limited to measurement markers; their values may not control the measured path. Functional retirement counters and CSR masks/permissions are modeled, while actual cycle estimates come from CorePerfDSL scheduling state. CSR/PMP policy checks are native C++ hooks, conditional on CSR instructions or architectural guard profiles; there is no Python instruction callback and no schedule-timestamp callback into external models.

### 17.4. Qualification

`verif/perfsim/validate_platform.py` runs a matched ELF/core/environment through upstream MAPExplorer with instruction-schedule state equivalence enabled, then through the native RTL reference in `verif/perfsim/rtl/`. It checks software completion, declared traps, exact instruction streams, retired window counts and cycle error. Default gates allow at most 0.5% error, or one cycle for short directed tests. This does not promote every combination of newly exposed settings to a calibrated model. Keep failed studies and source/executable identities alongside successful evidence. See [the v7 investigation](../verif/perfsim/investigations/platform-memory.md).
