# ETISS / CorePerfDSL performance simulation

The [specification](../../docs/uqu_spec.perfsim.md) defines this experimental flow. A native ETISS process executes an existing ELF and sends one CoreDSL-generated instruction channel to several independently generated CorePerfDSL timing models. There is no Python callback per simulated instruction.

**Timing estimates are experimental and require profile-specific qualification.** MAP-DSE v7 extends the finite frontend/backend/BPU/forwarding model with external memory timing, minimal I$/D$ tag stubs, RV32E, sparse CSR policy and declared synchronous traps/PMP. XIF, floating point, asynchronous interrupts and debug remain unsupported. Protection/trap timing initially requires prediction disabled; PMP fetch faults require one-cycle immediate-grant instruction memory. See [platform and memory validation](investigations/platform-memory.md) for v7 evidence, [fine forwarding](investigations/fine-forwarding.md) for historical v6 qualification, and [replay ordering](investigations/replay-events.md) for v5.

## Provision tools

Requirements: Linux, Python 3.12+, a C++17 compiler, CMake 3.16+, Make, `patch`, Boost development packages, and the existing project Python environment. Cross-compilation uses the existing `RISCV_CC` / `RISCV` / `PATH` discovery. Make does not install host tools or launch a container.

Fetch the exact research stack from [the lock file](../../config/perfsim/upstream.lock.json):

```sh
make perfsim-fetch PYTHON=.venv/bin/python
```

This downloads SHA-256-checked GitHub archives, including all transitive pinned dependencies, into `build/deps/perfsim-upstream`. It never initializes Git submodules. For offline reuse, invoke `.venv/bin/python verif/sim/common/perfsim.py fetch --offline`; the archives must already exist in `build/deps/perfsim-archives`. `PERFSIM_ROOT` can select another provisioned source directory.

The two pinned generators require incompatible ANTLR runtimes, so supply separate Python environments:

```sh
python3 -m venv build/perfsim-tools/isa-python
python3 -m venv build/perfsim-tools/model-python
build/perfsim-tools/isa-python/bin/python -m pip install -r verif/perfsim/requirements-isa.txt
build/perfsim-tools/model-python/bin/python -m pip install -r verif/perfsim/requirements-model.txt
export PERFSIM_ISA_PYTHON="$PWD/build/perfsim-tools/isa-python/bin/python"
export PERFSIM_MODEL_PYTHON="$PWD/build/perfsim-tools/model-python/bin/python"
```

Build the pinned ETISS ISA/JIT installation once. SoftwareEval's channel, monitor and scheduling support are compiled directly into our harness; its upstream example-core factories are not needed:

```sh
export ETISS_ROOT="$PWD/build/perfsim-tools/etiss-install"
cmake -S build/deps/perfsim-upstream/etiss-perf-sim/etiss \
  -B build/perfsim-tools/etiss-build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$ETISS_ROOT" -DENABLE_JIT_LLVM=OFF \
  -DETISS_BUILD_MANUAL_DOC=ON -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --build build/perfsim-tools/etiss-build --parallel 2 --target install
```

ETISS needs its installed `RV32IMACFD` and `TCCJIT` plugins. This superset ISA implementation is restricted by the runner to the selected integer profile; executed M/C instructions are rejected when their respective ISA setting is disabled. The native harness initializes `misa`, hart identity and M-mode state explicitly. Its instruction-stream checker has been compared with the actual core's retirement stream.

If CMake discovers an incompatible home-directory Boost installation, explicitly select the desired `Boost_DIR` in both the ETISS configure command and `PERFSIM_CMAKE_ARGS`. For example, this host needed `-DBoost_DIR=/usr/lib/x86_64-linux-gnu/cmake/Boost-1.83.0`. `PERFSIM_CMAKE_ARGS` supplies additional native-harness configure arguments; it is not a shell command.

## Generate and execute

Use existing complete hardware configurations; no parallel set of partial CPU YAML files is introduced:

```sh
# Same CONFIG argument as RTL simulation/synthesis; no ETISS tools needed:
make perfsim-config PYTHON=.venv/bin/python CONFIG=config/rv32im_dadda.yml
```

The reusable [configuration frontend](config_frontend.py) applies the shared RTL YAML validator and `config/selectors.json`. It resolves ISA/hart identity, the CorePerfDSL schedule and its external-model bindings from that one input. The inspection target writes `config.yml`, `resolved.json`, generated `uqu.corePerfDsl` and `external_models.inc` to `build/uquintus-<hw>/perfsim/config/`. Preset names such as `CONFIG=rv32im_dadda` and explicit YAML paths select the same entry point. Multiple compatible configurations use `PERFSIM_CONFIGS` as below.

`resolved.json` contains the complete hardware identity, encoded RTL parameter values, functional ISS settings, generated schedule identity, external-model implementation/parameters, coverage and environment settings. Actual model generation uses these same resolved model settings and C++ bindings; every execution retains its own snapshot. In the queue reference, `MUA_IF_BUFFER_WORDS` configures `frontendModel.buffer_words` and bypasses use the RTL bitmask. MAP-DSE configures the shared prefetch envelope with the same word capacity and bypass bitmask for none/static-not-taken/bimodal policies. Redirect transport is derived from that bitmask. Register-file FF/latch selection remains recorded as cycle-equivalent instead of inventing a simulated latency difference. Unsupported active features fail resolution explicitly.

Memory response latencies describe the simulation environment and remain in `PERFSIM_IMEM_LATENCY` / `PERFSIM_DMEM_LATENCY`; they are recorded alongside the resolved hardware parameters without adding simulation-only keys to the core YAML.

```sh
make sw PYTHON=.venv/bin/python CONFIG=rv32im_dadda SW=perfsim
make perfsim-model PYTHON=.venv/bin/python CONFIG=rv32im_dadda \
  PERFSIM_CONFIGS=rv32im_iterative,rv32im_dadda_mac
make perfsim PYTHON=.venv/bin/python CONFIG=rv32im_dadda \
  PERFSIM_CONFIGS=rv32im_iterative,rv32im_dadda_mac \
  ELF=build/uquintus-rv32im_dadda/sw/perfsim/program.elf PERFSIM_TRACE=1
make report PYTHON=.venv/bin/python
```

`perfsim-model` generates/compiles only; complete block generation also needs an ELF. `perfsim` reuses a content-addressed cache when its model set, source tree, generator packages and ETISS binaries match. For model inspection without compiling the native executable, omit `ETISS_ROOT` from `perfsim-model`. Execution requires it.

The primary `CONFIG` and comma-separated `PERFSIM_CONFIGS` must have identical ISA and integration parameters and distinct names. Each may change supported `MUA_` fields. Cyclic register dependencies, multiplier choice/unroll, divider unroll, individual forwarding paths, none/static-not-taken/bimodal branches and fixed memory latency drive generated schedules. FF/latch register implementation and the three compressed-decode strategies are recorded as cycle-equivalent. Operand retention is cycle-equivalent with full/global-disabled forwarding. With partial forwarding, retention captures ready DE sources across missed bypass windows and can change cycle counts; the shared reference calendar models this explicitly. Compressed instructions retain their original encodings. The queue reference models halfword assembly and applies `MUA_IF_BUFFER_WORDS`/`MUA_REDIRECT_BYPASS` to its queues; MAP-DSE uses a shared trace-driven queue envelope for no prediction and branch-boundary transport. MAC instructions/encoding remain outside this profile even when selecting the split `dadda_mac` multiplier for ordinary MUL instructions.

`PERFSIM_IMEM_LATENCY` and `PERFSIM_DMEM_LATENCY` default to one cycle. The queue reference uses ordered, immediate instruction-memory grants and fixed response latency. MAP-DSE models finite queues, ordered speculative requests and reference EX/MEM/WB occupancy on an independent trace-derived clock. Actual block timing remains in composed max-plus schedules. BPU lookup, capture and training use the reference IF/DE event order; different memory/backend clocks require separate histories and qualification. Its fetch latency is restricted to 1..254 cycles by upstream byte delay vectors. Data memory uses separate shared grant/response resources. `PERFSIM_MEMORY=config/perfsim/memory/variable.yml` selects periodic grants/address-based delays; `cache-stub.yml` enables minimal external tag-only I$/D$ placeholders. `PERFSIM_MAX_INSTRUCTIONS` defaults to 100 million and `PERFSIM_TIMEOUT` to 300 host seconds. Both bound functional execution. Active unknown features and unmodeled instruction types/CSR operations fail. Counter reads are restricted to the ELF's recognized measurement markers; workloads must not use their values to influence the measured path. Declared synchronous traps use the ELF manifest and WB recovery model; asynchronous interrupts, writable code and self-modifying code remain unsupported.

To run a benchmark, build it through the existing port and give its ELF to `perfsim`:

```sh
make benchmark-build PYTHON=.venv/bin/python CONFIG=rv32im_dadda \
  BENCHMARK=coremark BENCHMARK_PROFILE=performance
# Use the printed build directory:
make perfsim PYTHON=.venv/bin/python CONFIG=rv32im_dadda \
  PERFSIM_CONFIGS=rv32im_iterative,rv32im_dadda_mac \
  ELF=build/uquintus-rv32im_dadda/sw/benchmark/coremark/<build>/performance/program.elf
```

CoreMark CRCs and Embench self-check/logs use the existing validators. Printed timer values belong to the functional ISS and are used only to validate that output. Modeled cycles come from generated scheduling state. With markers the reported window is WB completion `(start, stop]`; without them it includes the whole program, pipeline fill and drain. Formatting timer values after the stop marker may execute a different instruction sequence from RTL, so benchmark trace comparison stops at that marker.

## Inspect and compare

Each configuration produces `build/uquintus-<hw>/perfsim/run-<id>/` with its report, complete hardware snapshot, model/coverage, build provenance, workload identity, logs and native estimates. `shared_execution` identifies the one functional run for the whole batch. Full memory, optional `trace.csv` and per-model `timing-<model-id>.csv` stage timestamps live there. Shared generated DSL/C++/trace schemas, upstream source manifests and build logs are retained under `build/perfsim-models/<hash>/`; `model_build` records the directory. Model generation/compilation and native execution time are recorded separately. The HTML report has a separate **Performance simulation (estimated)** category.

For a directed comparison, execute the same ELF with `make test COMPONENT=core_elf`, then pass the two printed run directories:

```sh
.venv/bin/python verif/perfsim/compare.py <perfsim-run> <rtl-run>
```

Enable `PERFSIM_TRACE=1` for ETISS and `BENCHMARK_TRACE=1` for fast RTL benchmarks. The comparison checks full hardware identity, ELF hash and exact PC/encoding sequence through the stop marker (or full execution without markers). It reads checked RVFI JSONL or the native RTL retirement stream. For successful benchmark runs with matching fixed memory latencies/windows, it also records signed, absolute and relative cycle error. `rtl-comparison.json` is evidence for that workload; it never changes model status to calibrated or compares every architectural register/memory effect.

Unit checks do not require ETISS or a cross-compiler:

```sh
.venv/bin/python -m unittest discover -s verif/sim/common/tests -p test_perfsim.py -v
make test-report PYTHON=.venv/bin/python
```

## Queue-reference frontend timing component

For the explicitly selected queue reference, [the CorePerfDSL source](models/uqu.corePerfDsl.in) defines the pipeline and connects `Pc`, `IfConsumed` and `DeAdvanced` to the external [FrontendModel](models/uqu_models.h). Generated callbacks supply the actual IF acceptance and DE advance timestamps, including downstream backpressure. Branch comparison readiness alone does not release a held branch: redirection waits for DE to advance.

[FrontendQueues](models/uqu_frontend.h) tracks the RTL's two outstanding/reserved response credits, two registered result slots, private request slot, ordered wrong-path responses and configurable word FIFO. It models independent result/word fall-through and same-cycle redirect requests. A live response does not release a request credit combinationally; registered result consumption does. With prediction disabled, new native requests stop while a branch occupies DE, but previously armed work and buffered instruction delivery retain their RTL behavior. Branch outcomes come from the functional next PC, without re-executing the ISA in the timing model.

Run the native component equivalence test with externally supplied Bender, Verilator and a C++17 compiler:

```sh
make perfsim-test-frontend PYTHON=.venv/bin/python JOBS=2
```

It compares IF valid/PC and OBI request/address against the actual `uqu_stage_if` on every edge. The default matrix covers eight bypass masks, depths 2/4 and response latencies 1/2/5, with consumer stalls, branch holds and consecutive redirects: 48 cases, 144,000 checked edges. Results feed the normal component report. Compressed assembly, variable grants/faults, predictor replay and integrated cycle accuracy are outside this component comparison.

See [the measured frontend comparison](../../docs/uqu_spec.perfsim.md#9-queue-reference-frontend-model-refinement) for workload-level errors. In particular, low aggregate error on one workload is not a bound on per-instruction timing error or on other configurations.

## Upstream adaptations and MAP-DSE scope

The lock selects the public `blockSched_dev` workspace and its pinned `dse_dev` generator/backend dependencies. All source licenses remain in the downloaded trees and generated outputs. Recorded patches are applied to disposable generator/backend copies, never to downloaded originals:

- Derive branch identity from ISA instruction names rather than hard-coded CV32E40P/CVA6 numeric IDs and variant-name checks.
- Emit `$code` as `ba.to_ulong()`. Streaming the bitset into a C assignment produces a binary-looking number with a leading zero, which C interprets as octal.
- Provide uqu matrix connector mappings, expose upstream block composition, and distinguish marker/completion boundaries from branches.
- Correct the static-connector row index used in matrix multiplication and treat unavailable optimizer reuse patterns as non-matches.
- Support channel slices, block-completion observation and schedule selection across structural variants; bound small dictionary lookup and reject missing blocks.

The harness also pre-includes `<cstdint>` because the pinned channel header uses `uint64_t` before including it.

The default backend uses upstream MAP-DSE composed-block scheduling and shared trace-driven models. The detailed queue/instruction model remains a separate accuracy reference. Area/Fmax and Pareto promotion still require the existing implementation flows.

## MAP-DSE block scheduling

The default Make/CLI backend is now `map_explorer`, following the pinned upstream MAP-DSE formulation. It uses one ETISS functional execution, shared trace-driven resource/branch models, independent timing-state vectors and composed max-plus block schedules:

```sh
make perfsim PYTHON=.venv/bin/python CONFIG=<hardware.yml> ELF=<program.elf> \
  PERFSIM_CONFIGS=<additional-compatible-configs> PERFSIM_VERIFY_SCHEDULING=1
```

`perfsim-model` without an ELF generates/compiles the CorePerfDSL instruction model and extractor. Supplying an ELF permits checked extraction and block compilation. The first block execution needs an additional functional extraction run; subsequent runs reuse hash-checked profiles under `build/perfsim-profiles/`. Generated sources, models, private patched upstream headers, native executables and manifests are under `build/perfsim-models/`.

This path uses the explicitly versioned `map_dse` timing contract. Fetch-service and operand-admission delays, plus branch outcomes, depend on the functional trace and component configuration. They never receive IF/DE scheduling timestamps. Pipeline, register availability/admission and CSR serialization remain in max-plus timing state. Shared models are evaluated once per required instruction/event and their delay vectors/prediction outcomes are reused across timing combinations. Sharing is inherent to this backend; `PERFSIM_SHARE_MODELS` controls only legacy queue-model caching.

The implementation reuses upstream `BlockExtractor`, `MatrixTransformer`, `Instruction.mulMatrix`, `BlockScheduleGenerator` and `MAPExplorer`, with small tracked compatibility/correctness patches applied only in private build copies. The runtime retains active blocks across channel batches. Control flow ends blocks; measurement markers and completion add non-branch boundaries. The upstream 100-entry delay-vector bound limits blocks to 50 instructions: each instruction contributes one fetch delay and one biased admission delay. Structural variants may select different composed functions while sharing external models.

The `uqu-map-dse-v7` model handles finite frontend queues for all supported branch policies. Its reference service calendar includes constant-latency EX operations, MEM/WB occupancy, registered load admission and CSR serialization. The calendar consumes only functional PC/encoding/register identities and configuration, never a timing vector's IF/DE timestamps. Different backend configurations may need distinct envelopes; neutral configurations share them. Exact idle skipping avoids stepping through backend-stall cycles in which no queue state can change.

Fine forwarding uses the ordinary core YAML: `MUA_FORWARDING` gates `MUA_FORWARD_EX_TO_DE`, `MUA_FORWARD_MEM_TO_DE`, `MUA_FORWARD_MEM_TO_EX` and `MUA_FORWARD_WB_TO_EX`. WB-to-DE follows the master and has no separate selector. Branch/JALR and CSR sources must be ready in DE; ordinary EX consumers may use the RTL's guaranteed MEM/WB bypass. Youngest pending writers block older values and RF fallback. Loads become RF-readable after successful WB; the live response never feeds a bypass. Split products become usable in MEM. `MUA_DE_OPERAND_RETENTION` preserves sources obtained while DE is held; continuous resolution revisits the current producer window instead.

An independent producer-lifetime calendar derives the extra admission wait. A shared `hazardModel` resource publishes that delay alongside the fetch resource, once per instruction and distinct reference envelope. CorePerfDSL and upstream max-plus composition still schedule the timing combinations at whole-block boundaries; there is no callback from scheduled timestamps into the calendar. Positive byte delays encode `wait+1`; the admission base is biased by minus one, so zero wait adds no pipeline cycle. Configurations with equal forwarding envelopes share both resources. Inactive subordinate path bits and cycle-equivalent retention choices do not create extra schedules.

Run `make perfsim-test-hazards JOBS=4` to compare all 16 route masks, both retention settings and master-off controls against the actual RTL hazard unit. `config/perfsim/forwarding-accuracy.yml` expands the same choices into complete normal core YAMLs for matched whole-core studies. Component equivalence alone does not qualify a DSE profile.

Shared BPU components model tagged two-bit counters, direct-mapped target tags, unconditional prediction, packed instruction-prefix fill/replay and reset/invalidation. Direction/target capacities and replay halfwords come from the hardware YAML. BPU histories share only with identical reference timing envelopes; equal direction/target parameters alone are insufficient. A DE update before an IF candidate becomes valid affects lookup; an update on its capture edge observes read-before-write semantics. IF predictions remain held through backpressure. A local predicted redirect permits the source to consume a registered result and release a request credit; a global correction masks that old-stream result. Prediction/replay changes PC candidates at IF; a correction uses DE timing. Normal and replayed instructions preserve original encodings and lengths, and native fetch resumes after the replay prefix. Source/target permissions are outside this unprotected execution profile.

The component's lookup/update/capture semantics are checked against actual BPU RTL on 64,000 edges with `make perfsim-test-bpu`. Full-core studies separately check functional prefixes, software self-checks, timing algebra and RTL cycle errors. The clocked IF/BPU/replay regression (`make perfsim-test-replay`) covers compressed/uncompressed encodings, replay capacities 0/2/6/8, memory latencies 1/2/5, bypass masks 0/7 and independent DE stalls: 48 cases / 288,000 edges. See [fine forwarding](investigations/fine-forwarding.md) for current whole-core qualification and [replay event ordering](investigations/replay-events.md) for the diagnosed v4 error and retained v5 qualification. In this no-trap integer pipeline, a DE correction suppresses IF acceptance, so wrong-path memory requests are modeled without inventing accepted wrong-path instruction captures. F/Zfinx, XIF, asynchronous interrupts and debug remain rejected; see the v7 platform profile for protection and synchronous traps.

`compare_map.py` checks a default 0.1% mean / 0.5% worst absolute relative cycle-error budget, recorded in each study; use `--max-mean-error` and `--max-error` to change it explicitly. These are acceptance gates for the measured matrix, not universal bounds. Optional `--queue-baseline <acceleration.json>` remeasures the earlier queue hybrid alongside MAP-DSE on the same CPU and identical ELFs, validating each contract against its own checked cycle results.

`PERFSIM_VERIFY_SCHEDULING=1` advances independent generated instruction schedules and compares complete timing state **at completed block boundaries**. It includes all five stages, entrance, register availability/admission, serialization and PC candidate/input times. Reference states never feed the block scheduler. With verification off, timing-state updates occur only at block boundaries. Native results expose `map_calls` for upstream block updates, scheduled instructions, unique shared models and actual model evaluations; `block_calls` remains the legacy project-adapter counter. Profile/runtime guards reject changed or unknown instruction identities without a hidden fallback. Missing monitor operand fields are zero initialized without replacing explicit ISA mappings.

Compare actual RTL accuracy and host cost with retained matched evidence:

```sh
.venv/bin/python verif/perfsim/compare_map.py \
  --accuracy build/investigations/perfsim-accuracy/<run> --jobs 4
# Optional: --workloads performance,crc32 --repeats 3 --warmups 1 --cpu 0
```

This checks functional prefixes and target cycles/CPI directly against RTL, verifies instruction/block equivalence within the new contract, then times instruction and MAPExplorer execution with fresh processes/JIT, tracing/checking off and one fixed CPU. Outputs under `build/investigations/perfsim-map/` include `accuracy.md`, `comparison.md`, `comparison.json`, source/tool/executable identities, checked runs and raw process samples. Preparation is reported separately. See [the integration investigation](investigations/map-dse-blocks.md).

## Detailed queue reference

The previous frontend queue model remains available as a separate reference:

```sh
make perfsim PYTHON=.venv/bin/python CONFIG=<hardware.yml> ELF=<program.elf> \
  PERFSIM_SCHEDULER=instruction
# CLI equivalent with an explicit contract:
.venv/bin/python verif/sim/common/perfsim.py run --config <hardware.yml> --elf <program.elf> \
  --scheduler instruction --model-contract queue
```

Its optional `block` adapter and `PERFSIM_SHARE_MODELS=1` transition cache remain legacy experiments. They retain per-instruction frontend timing feedback and are distinct from MAP-DSE's composed-block/shared-model path. Their [original block-adapter measurements](investigations/map-dse-acceleration.md) and [one-instruction MAPExplorer trial](investigations/map-explorer.md) remain historical evidence. `accelerate.py` still compares those queue-contract backends against the retained queue accuracy matrix.

For an instruction-scheduling oracle of the canonical contract, select `--scheduler instruction --model-contract map_dse`. Its cycle estimates must match MAPExplorer within the same contract, while both may differ from RTL and the queue reference.

## RTL accuracy sweeps

The reusable runner uses one generated CorePerfDSL model per distinct timing configuration and one ETISS execution per ELF. Each RTL run executes the **same ELF**, validates its CRC/self-check and retains its retirement stream. Comparisons check PC/original encoding through the stop marker, identical retired-instruction counts, memory timing and measurement windows before reporting cycle error. Fast RTL traces include four memory bytes at each PC; only the instruction's 16 bits are compared for a compressed instruction.

Build RV32IMC benchmark ELFs using a complete YAML with `ISA_C: 1`, `ISA_M: 1`, and the other functional settings matching `rv32im_dadda`. Reuse the exact ELF paths printed by `benchmark-build`:

```sh
.venv/bin/python verif/perfsim/calibrate.py \
  --matrix config/perfsim/rv32imc-accuracy.yml \
  --elf <coremark-performance.elf> <crc32.elf> <nsichneu.elf> <ud.elf> <matmult-int.elf> \
  --jobs 4
```

`--configs <complete.yml> ...` can replace `--matrix`. The matrix is an experiment definition, expanded into complete core YAMLs validated by the normal RTL configuration loader. The supplied matrix varies C-decode placement/type, all frontend bypasses, word-buffer depth, none/static-not-taken prediction, iterative MUL/DIV unrolling, split MUL, forwarding disable and operand retention. This historical matrix has no BTB. The additional `config/perfsim/bpu-accuracy.yml` matrix covers static/bimodal target prediction and packed replay. Floating point remains outside the profile. `ISA_F` is deferred in RTL; Zfinx is its separate floating-point target.

Results go to `build/investigations/perfsim-accuracy/<run>/accuracy.json` and `accuracy.md`, including CPI, signed/absolute cycle errors, mean absolute relative error, worst error and per-pair run provenance. Negative error means an underestimate. Failures remain visible; they do not contribute a fabricated accuracy value. This initial matrix is calibration evidence, not a calibrated accuracy guarantee or a Pareto search.

After revising a timing model, reuse the retained RTL runs:

```sh
.venv/bin/python verif/perfsim/calibrate.py --resimulate <accuracy-run-directory> --jobs 4
# Re-run just the comparison after changing a comparator:
.venv/bin/python verif/perfsim/calibrate.py --recompare <accuracy-run-directory>
```

Resimulation retains the previous summary before revising estimates. Shared instruction streams avoid per-model trace duplication. `perfsim.py run --instruction-trace` likewise records only the PC/encoding stream; `--trace` also records per-model stage timestamp CSVs for detailed diagnosis.

The first measured sweep and the schedule corrections are documented in [RV32IMC accuracy](investigations/rv32imc-accuracy.md).

## Host simulation cost

Benchmark the native execution cost using a completed, successful accuracy sweep:

```sh
make perfsim-cost PYTHON=.venv/bin/python \
  PERFSIM_ACCURACY=build/investigations/perfsim-accuracy/<run>
# Equivalent CLI, with sampling controls:
.venv/bin/python verif/perfsim/benchmark_cost.py --accuracy <accuracy-run> \
  --baseline rv32imc-baseline --repeats 3 --warmups 1 --sweep-repeats 1 --cpu 0
```

Use the same provisioned ETISS/generator environment as `perfsim`. The runner reuses hash-checked, previously validated RTL/batched-model executables and builds a separate single-model executable. RTL uses the compiled fast harness with its usual assertions and benchmark/BPU counters; cocotb, RVFI, waves and retirement tracing are absent. ETISS disables instruction and stage CSV traces. Every timed trial starts a fresh process/JIT, uses the same CPU affinity, and must retain its validated instruction/cycle counts and CRC/self-check result. Backend order rotates between single-configuration trials.

Elapsed time covers process startup, dynamic JIT, all software execution (including startup/warmup and completion formatting), memory loading and native final-output writes. Python preparation, validation, report generation, compiler/tool installation, software builds and simulator/model compilation are outside this runtime measurement. The workload window is identical across backends; formatting timer values after stop can execute slightly different instruction paths. This measures the existing native harnesses, not an instruction-only kernel, bare ETISS without scheduling, or complete Make/runner latency.

The single-configuration comparison uses medians of three timed trials after one discarded process run per backend/workload. The default RTL sweep uses one timed trial per configuration; increase `--sweep-repeats` for repeated matrix measurements. Sweep runtime is the sum of per-configuration medians versus one batched ISS execution evaluating all distinct timing states. Cycle-equivalent configurations share a perfsim timing state but still count as separate hardware candidates. Suite speedup divides sums of runtime medians. Report sample counts/ranges rather than treating a single matrix trial as a statistical guarantee.

Outputs under `build/investigations/perfsim-cost/<run>/` include portable `index.html`, `cost.md`, detailed `cost.json`, process samples, commands, native results and checked outputs. CPU time comes from per-child `wait4`; OS-reported peak RSS includes the pre-exec launcher address space and is retained as a diagnostic, not interpreted as a native working-set comparison. Host CPU, affinity, kernel/load, executable hashes and build provenance are retained. Single-model lookup/build time is measured explicitly with cache-hit status; RTL/batch build times are historical observations from the accuracy artifacts, separately labeled and excluded from runtime speedups.

The first measured [host-cost comparison](investigations/simulation-host-cost.md) records single-model and complete-matrix results alongside their sampling limits.


## Frontend and BPU extensions

```sh
make perfsim-test-bpu PYTHON=.venv/bin/python JOBS=4
make perfsim-test-replay PYTHON=.venv/bin/python JOBS=4
.venv/bin/python verif/perfsim/calibrate.py \
  --matrix config/perfsim/bpu-accuracy.yml --elf <coremark.elf> <nsichneu.elf> <ud.elf> --jobs 4
.venv/bin/python verif/perfsim/calibrate.py \
  --matrix config/perfsim/frontend-pressure.yml --elf <coremark.elf> \
  --imem-latency 5 --dmem-latency 3 --jobs 4
```

Latency overrides derive new harness metadata while preserving the exact ELF bytes, compiler and source identity, with a hash-linked parent record. No compiler rebuild or new software profile is implied. `--reuse-rtl <accuracy-directory>` reuses existing matching RTL runs only after checking hardware parameters, environment, every retained source hash and the retirement-trace hash. New hardware combinations still run RTL. `calibrate.py` acquires functional/timing evidence; use `compare_map.py --accuracy <directory>` for the default accuracy gates and matched native runtime measurements. A functional pass from evidence acquisition does not imply that its timing error passed qualification.

Native execution statistics distinguish shared fetch envelopes, shared/active BPU histories, their per-instruction evaluations, reference EX/WB pressure and replayed instructions. Counts summed across shared envelopes are component-work counts, not a single core's retired-window BPU metrics.


`config/perfsim/replay-pressure.yml` compares 0/2/6/8 replay halfwords and a factor-one iterative backend. Run it separately at the desired `--imem-latency` / `--dmem-latency`; memory is an execution environment, not a hardware YAML parameter.


## Memory and architectural-event validation

The core configuration stays the same entry point. Add an external environment only when needed:

```sh
make perfsim CONFIG=rv32e ELF=<ilp32e-program.elf> \
  PERFSIM_MEMORY=config/perfsim/memory/cache-stub.yml

.venv/bin/python verif/perfsim/validate_platform.py --config rv32e \
  --elf build/uquintus-rv32e/sw/perfsim_e/program.elf

.venv/bin/python verif/perfsim/validate_platform.py --config rv32i \
  --elf build/uquintus-rv32i/sw/perfsim/program.elf \
  --memory config/perfsim/memory/variable.yml
```

The validation command uses the same ETISS/tool Python environment variables as `make perfsim`; Bender, Verilator and a host C++ compiler must be on PATH. Build the directed programs with `make sw SW=perfsim_e CONFIG=rv32e`, `SW=perfsim_traps CONFIG=rv32i`, or `SW=perfsim_pmp CONFIG=rv32i_pmp`. The validation JSON and comparison artifacts live under `build/investigations/perfsim-platform/`; each contains exact native/RTL run paths and source hashes. The RTL reference is deliberately separate from the publication benchmark driver.

The [v7 specification](../../docs/uqu_spec.perfsim.md#17-memory-environments-rv32e-and-synchronous-architectural-events-v7) documents the deliberately limited cache policies, architectural counter contract, trap-event identity and PMP scope. These models add no synthesizable caches or new RTL interfaces.
