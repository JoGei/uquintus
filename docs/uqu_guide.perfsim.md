# Performance simulation and design-space exploration

Use perfsim to compare execution cycles across complete core configurations before spending time on RTL simulation and physical implementation. ETISS executes the ELF using CoreDSL-derived ISA behavior; CorePerfDSL and upstream MAPExplorer schedule multiple timing configurations from that functional stream. Area and frequency still come from synthesis and implementation.

The [perfsim specification](uqu_spec.perfsim.md) defines the model contract. The [implementation guide](uqu_guide.impl.md) explains how to combine cycle estimates with physical timing and area. Treat estimates as experimental until the particular hardware, workload and memory environment have passed a matched RTL comparison.

## Set up the tools

Supply Linux, Python 3.12+, a C++17 compiler, CMake 3.16+, Make, `patch`, Boost development packages and the project's Python environment. RTL comparisons additionally need Bender and Verilator. Compiler discovery follows the normal `RISCV_CC`, `$RISCV/bin`, then `PATH` order.

Fetch the archive-pinned research stack explicitly; ordinary execution does not download dependencies or initialize submodules:

```sh
make perfsim-fetch PYTHON=.venv/bin/python
```

Pins and checksums live in [upstream.lock.json](../config/perfsim/upstream.lock.json). Sources go to `build/deps/perfsim-upstream`; archives go to `build/deps/perfsim-archives`. For offline acquisition use `.venv/bin/python verif/sim/common/perfsim.py fetch --offline`. `PERFSIM_ROOT` can select another provisioned tree.

The ISA and performance generators require separate ANTLR environments:

```sh
python3 -m venv build/perfsim-tools/isa-python
python3 -m venv build/perfsim-tools/model-python
build/perfsim-tools/isa-python/bin/python -m pip install -r verif/perfsim/requirements-isa.txt
build/perfsim-tools/model-python/bin/python -m pip install -r verif/perfsim/requirements-model.txt
export PERFSIM_ISA_PYTHON="$PWD/build/perfsim-tools/isa-python/bin/python"
export PERFSIM_MODEL_PYTHON="$PWD/build/perfsim-tools/model-python/bin/python"

export ETISS_ROOT="$PWD/build/perfsim-tools/etiss-install"
cmake -S build/deps/perfsim-upstream/etiss-perf-sim/etiss \
  -B build/perfsim-tools/etiss-build -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$ETISS_ROOT" -DENABLE_JIT_LLVM=OFF \
  -DETISS_BUILD_MANUAL_DOC=ON -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --build build/perfsim-tools/etiss-build --parallel 2 --target install
```

The installation must contain the `RV32IMACFD` and `TCCJIT` plugins. The harness restricts that superset ISA to the selected core profile. If CMake selects an incompatible Boost installation, pass the intended `Boost_DIR` to ETISS and through `PERFSIM_CMAKE_ARGS` for the native harness. Make expects provisioned tools; it does not manage containers or tool installation.

## Run the same core configuration as RTL

Inspect a complete core YAML without installing ETISS:

```sh
make perfsim-config PYTHON=.venv/bin/python CONFIG=rv32im_dadda
```

The output under `build/uquintus-<hw>/perfsim/config/` contains the hardware snapshot, `resolved.json`, generated `uqu.corePerfDsl` and `external_models.inc`. Check `coverage` and `approximations` in the resolved plan before sweeping a setting. Configuration selectors and validation are shared with RTL.

Build a directed program, then compare compatible arithmetic implementations:

```sh
make sw PYTHON=.venv/bin/python CONFIG=rv32im_dadda SW=perfsim
make perfsim PYTHON=.venv/bin/python CONFIG=rv32im_dadda \
  PERFSIM_CONFIGS=rv32im_iterative,rv32im_dadda_mac \
  ELF=build/uquintus-rv32im_dadda/sw/perfsim/program.elf
make report PYTHON=.venv/bin/python
```

The primary `CONFIG` and comma-separated `PERFSIM_CONFIGS` may vary supported `MUA_` fields, but must have identical ISA and integration settings and distinct configuration names. Equivalent settings can share a timing model. RV32E needs separately compiled `rv32e...` / `ilp32e` software; it cannot share an execution with RV32I.

For a benchmark, build through the existing [benchmark ports](../verif/sw/benchmark/README.md), then pass the printed ELF path:

```sh
make benchmark-build PYTHON=.venv/bin/python CONFIG=rv32im_dadda \
  BENCHMARK=coremark BENCHMARK_PROFILE=performance
make perfsim PYTHON=.venv/bin/python CONFIG=rv32im_dadda ELF=<printed-program.elf>
```

`perfsim-model` prepares the instruction model without executing software. Whole-block preparation also needs an ELF. Generated models and extracted block profiles are cached by content; installation, compilation and first-use extraction costs should be separated from repeated execution cost.

## Choose an experiment

| Question | Change | Observe | Interpretation |
|---|---|---|---|
| Is arithmetic throughput worth more hardware? | `MUA_MUL`, `MUA_MULDIV_ITERUNROLL` | Cycles, dependency-heavy workloads, EX pressure | A faster arithmetic unit may be hidden by frontend or memory waits. Split products also change dependent-use latency. |
| Which bypass paths matter? | Forwarding master and individual path bits | Cycles per workload, hazard wait, DE/EX consumers | Youngest-writer priority and finite bypass windows matter; one register-ready timestamp cannot describe every partial-forwarding case. |
| Does retaining operands help? | `MUA_DE_OPERAND_RETENTION` with partial forwarding | A branch waiting for two producers; cycle delta | Retention can save a missed bypass window. Full forwarding or longer memory waits may hide the benefit. |
| Does replay justify its capacity? | Direction/BTB entries and `MUA_BTB_IDATA_HWORDS` | Cycles, replay activity, a separate RTL BPU trace | More payload cannot fix missing target hits. Test collisions, cold starts, compressed targets and slower memory together. |
| Which frontend boundary is expensive? | `MUA_REDIRECT_BYPASS`, `MUA_IF_BUFFER_WORDS` | Redirect-heavy workloads and cycle delta | Queue occupancy can hide a bypass benefit. A cycle-equivalent result does not mean the physical paths are equivalent. |
| Is a working set memory limited? | External memory profile | Cycles, MEM/WB pressure, sensitivity to grants and response delays | Pressure counters overlap other waits; summing them is not a lost-cycle breakdown. |
| Can a smaller register file serve the workload? | `ISA_E` and a separate `ilp32e` build | Correctness, cycles, code footprint, later RTL area | Compiler/register-allocation changes are part of the comparison. Keep them separate from same-ELF microarchitecture sweeps. |

FF/latch register-file selection and compressed-decode placement/type are currently treated as cycle-equivalent by perfsim. Evaluate their area/frequency differences in RTL implementation. Native `MUA_DIV: parallel` translates to one EX computation cycle; its description remains uncalibrated until matched RTL validation for the chosen workload/environment. Hardware MAC encoding, F/Zfinx, XIF and debug are outside the current performance profile.

Use several workloads. CoreMark does not cover every arithmetic or control-flow feature. Keep integer and software-floating-point Embench workloads identifiable. For suite comparisons, use the geometric mean of candidate/reference cycle ratios with a fixed workload set; report per-workload CPI alongside it. The [benchmark specification](uqu_spec.bench.md) defines the aggregation and eventual Greek-profile policy.

## Vary memory without changing the core YAML

Fixed, independent, immediate-grant ports default to next-cycle responses:

```sh
make perfsim CONFIG=rv32im_dadda ELF=<program.elf> \
  PERFSIM_IMEM_LATENCY=5 PERFSIM_DMEM_LATENCY=3
```

For periodic grants, address-dependent response times or cache placeholders, select an external environment:

```sh
make perfsim CONFIG=rv32e ELF=<ilp32e-program.elf> \
  PERFSIM_MEMORY=config/perfsim/memory/variable.yml
make perfsim CONFIG=rv32e ELF=<ilp32e-program.elf> \
  PERFSIM_MEMORY=config/perfsim/memory/cache-stub.yml
```

Each `imem` and `dmem` entry supplies `grant_pattern`, `response_cycles` and `cache` fields. Grant patterns begin at slot zero on the first post-reset edge. Without a cache, the word address indexes the response-delay list. Responses remain ordered. See the [profiles](../config/perfsim/memory/) and [memory contract](uqu_spec.perfsim.md#memory-environments).

The optional I$/D$ stubs are cold, direct-mapped, blocking tag arrays. Read misses allocate; stores update backing memory at grant and do not allocate on misses. They have no data arrays, dirty lines, bursts, MSHRs or coherence. Use them for basic locality sensitivity, not cache PPA or a cache implementation claim. Longer service and different grant patterns require their own accuracy checks.

## Validate before using a new DSE dimension

For one ELF/core/environment, run matched MAPExplorer and RTL execution:

```sh
.venv/bin/python verif/perfsim/validate_platform.py --config rv32i \
  --elf build/uquintus-rv32i/sw/perfsim/program.elf \
  --memory config/perfsim/memory/variable.yml
```

Useful directed programs are `SW=perfsim_e CONFIG=rv32e`, `SW=perfsim_traps CONFIG=rv32i`, `SW=perfsim_csr CONFIG=rv32i` and `SW=perfsim_pmp CONFIG=rv32i_pmp`. Build them with `make sw` first. The validator checks software completion, original instruction encodings, retired counts, declared traps and the cycle window, with same-contract instruction/block equivalence enabled. Its default cycle-error gate is 0.5%, with an explicit one-cycle allowance for short tests. A successful case does not qualify all combinations.

For a workload/configuration matrix with fixed memory latencies:

```sh
.venv/bin/python verif/perfsim/calibrate.py \
  --matrix config/perfsim/forwarding-accuracy.yml \
  --elf <coremark.elf> <crc32.elf> <nsichneu.elf> --jobs 4
.venv/bin/python verif/perfsim/compare_map.py --accuracy <printed-accuracy-directory> --jobs 4
```

Other supplied matrices cover [integer frontend/arithmetic choices](../config/perfsim/rv32imc-accuracy.yml), [BPU capacity/replay](../config/perfsim/bpu-accuracy.yml), [backend pressure](../config/perfsim/frontend-pressure.yml) and [replay under slower memory](../config/perfsim/replay-pressure.yml). `--configs <complete.yml> ...` can replace a matrix. Keep the same ELF, software settings, memory environment and measurement boundaries within a comparison.

Acquiring an accuracy study is separate from passing its gates. `compare_map.py` enforces mean/worst absolute relative cycle-error budgets of 0.1%/0.5% by default, then measures native scheduling cost. Passing instruction/block equivalence proves schedule implementation consistency; passing RTL comparison tests the timing model itself. Neither replaces the software self-check or ISA verification.

Reuse retained evidence with `calibrate.py --reuse-rtl <study>` or revisit it with `--resimulate <study>` / `--recompare <study>`. Reuse checks the recorded inputs and trace identities. Preserve failed comparisons; do not remove difficult workloads or fit benchmark-specific correction factors.

## Inspect results and diagnose differences

Run `make report` for the separate **Performance simulation (estimated)** category. A per-configuration run lives under `build/uquintus-<hw>/perfsim/run-<id>/`. `shared_execution` identifies the functional run shared by a batch; `model_build` points to the generated sources and executable.

| Observation point | Use |
|---|---|
| `resolved.json`, `model.json`, `config.yml` | Confirm actual selectors, inactive/cycle-equivalent fields, supported scope and memory settings. |
| `report.json` metrics | Compare modeled window cycles, retired instructions and CPI. With markers, the window is WB completion `(start, stop]`; without markers it includes fill/drain. |
| `rtl-comparison.json` | Read signed/absolute cycle error and the matched stream/window contract. Negative error means underestimation. |
| `trace.csv` | Compare ordinal, PC and original encoding. Fault events are present but do not retire. Post-stop timer formatting may legitimately diverge. |
| `timing-<model-id>.csv` | Diagnose stage timing. MAPExplorer observations are at completed block boundaries; use the same-contract instruction scheduler for instruction-level detail. |
| `traps.csv` | Compare ordered fault PC, cause and `mtval`; a handler PC alone does not establish correct recovery timing. |
| `native.json` execution counters | Distinguish functional instructions, composed updates (`map_calls`), scheduled model-instructions, shared model counts and resource evaluations. |
| `accuracy.md` / `comparison.json` | Inspect per-workload/configuration CPI, cycle error, preparation cost and native process samples. |

Enable `PERFSIM_TRACE=1` for instruction and timing traces. The CLI `--instruction-trace` retains only PC/encoding records. For detailed same-contract scheduling:

```sh
.venv/bin/python verif/sim/common/perfsim.py run \
  --config rv32im_dadda --elf <program.elf> \
  --scheduler instruction --model-contract map_dse --trace
```

Start with the first PC/encoding mismatch before investigating cycle error. If streams match, check marker boundaries and retired counts, then memory timing, load-use waits, branch release, arithmetic occupancy and serialization. A constant window offset suggests boundary accounting; errors that accumulate with redirects suggest event ordering; errors exposed by slower memory suggest queue ownership or overlapped waits.

For prediction-heavy workloads, separate direction hits, target hits and usable replay prefixes. An unlimited target table is an opportunity model, not a perfect direction predictor or a cycle model. Repeated benchmark kernels can become warm after their first pass even if the timed window started cold. Compare first-pass and steady-state behavior, not only a whole-window hit rate. The [benchmark diagnosis workflow](uqu_guide.impl.md#diagnose-high-cpi) explains the RTL trace counterpart.

## Check model components

```sh
make perfsim-test-frontend PYTHON=.venv/bin/python
make perfsim-test-bpu PYTHON=.venv/bin/python
make perfsim-test-replay PYTHON=.venv/bin/python
make perfsim-test-hazards PYTHON=.venv/bin/python
.venv/bin/python -m unittest discover -s verif/sim/common/tests
```

These compare native components against real RTL and independently check matrix algebra, CSR/PMP policy and memory behavior. For the variable-memory and cache-stub IF policies, use `verif/perfsim/test_frontend.py --masks 0,7 --depths 2 --latencies 1 --memory-profile 1`, then `--memory-profile 2`.

Replay checks should cover simultaneous DE training/IF capture, a lookup held under backpressure, local prediction clear versus global flush, straddling C32 instructions and outstanding killed responses. Hazard checks should cover youngest writers, disappearing bypass windows, x0, registered load visibility and operand retention. Component correctness alone does not establish whole-core timing accuracy.

The BPU registers accepted training/capture/ordinary-flush events and applies
them one edge later. Its native clock model uses the same pending bundle;
the MAP-DSE reference model merges update and capture events by commit timestamp
in a sparse calendar, preserving long-wait skipping. Reset/invalidation discard
pending events. Model contract `uqu-map-dse-v8` identifies this visibility rule;
older calibrated results do not qualify the new contract. Revalidate the
matched RTL workload/profile before promoting new DSE candidates.

## Measure the cost of exploration

Use `compare_map.py --accuracy <study>` to compare MAPExplorer with instruction scheduling of the same contract. Add `--repeats`, `--warmups` and `--cpu` for controlled native trials. To compare RTL and ISS execution cost from a completed accuracy study:

```sh
make perfsim-cost PYTHON=.venv/bin/python PERFSIM_ACCURACY=<accuracy-directory>
```

Keep tracing and reference checking disabled during timed trials. Use fresh processes, common CPU affinity and repeated samples; validate every trial's software outcome and expected counts. Separate dependency setup, software compilation, model generation, extraction, JIT/process startup and native runtime. A cached single-workload run and a batch of many timing states answer different cost questions. Compute suite speedup from summed runtimes, not averaged per-program speedups.

Shared external models may still evaluate each instruction. MAP-DSE's saving is reuse across compatible timing states and composed timing-vector updates at block boundaries. Different memory/backend/forwarding histories can require separate frontend/BPU envelopes; matching table capacities alone does not authorize sharing them. Observe evaluation counts rather than inferring sharing from elapsed time.

## Scope and troubleshooting

The normal backend is `map_explorer`. `PERFSIM_VERIFY_SCHEDULING=1` enables the independent instruction-schedule oracle and should be disabled for performance measurements. The legacy `queue` contract and its `block`/history-cache adapter remain explicit reference modes. `PERFSIM_SCHEDULER=instruction` through Make selects that queue reference; use the explicit CLI contract above when comparing instruction and MAPExplorer schedules.

PMP/trap timing currently requires prediction disabled; PMP also requires the default one-cycle, immediate-grant, uncached instruction port. The directed PMP test has a known one-cycle discrepancy in local fetch-fault transport. Arbitrary protection changes affecting prefetched words are not qualified. Asynchronous interrupts, external bus-error injection, XIF, F/Zfinx, debug and writable/self-modifying code remain unsupported.

CSR policy includes WARL, permissions, suppression and M/U trap state. Functional cycle values are not modeled pipeline cycles: uninhibited cycle reads are limited to measurement markers and must not steer the measured path. Initialize unreset PMP address payloads before reading them. The MAPExplorer dictionary requires immutable instruction/event identity per PC, so retrying the same PC first as a fault and later successfully is not supported.

Unknown instructions/profiles, stale executable/profile identities and byte-delay overflow fail explicitly. Per-response delays are 1..254 cycles; combined fetch, hazard and grant waits are checked too. Do not silently switch contracts or raise accuracy gates to make a failed case pass. Detailed run IDs, hashes and raw tables belong in generated build artifacts, not source-tree guides.
