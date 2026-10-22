# Shared simulation infrastructure

`component_runner.py` is the GNU Make helper behind `make test`, `make sim`, and
`make lint`. It selects a component using `config/sim/<component>.yml` and owns
the common Bender/Verilator invocation, cocotb execution, artifact directories,
metadata, and pass/fail checking. It collects selected include directories from
Bender's structured source tree, passes them to both lint and simulation, and
records the source tree/include paths and Verilog-header hashes with run
metadata. The generated configuration-header directory is also included. `hw_config.py` provides shared hardware YAML
validation, parameter selection/encoding, Verilog selector generation, and the
shared `configuration_label(config)` function for a validated configuration.
Print the descriptive hardware label with `make config-label CONFIG=rv32i` or
`python3 verif/sim/common/hw_config.py --config path/to/hardware.yml`.
This command requires only Python/PyYAML, without HDL tools or cocotb/pyuvm.
The [label convention](../../../doc/uqu_spec.build.md#21-generated-hardware-configuration-label)
defines field ordering and inactive settings. Labels supplement the YAML preset
name and complete parameter fingerprint; build directory names stay unchanged.
The runner keeps `.v` files in Verilog-2005 mode and permits SystemVerilog-2017
for `.sv` verification/imported-IP files, recording these language options in run metadata.
`rvfi_trace.py` reads the full-core JSONL stream and checks its schema, reset
epochs, order, PC continuity, handler markers and basic RVFI invariants.
`rvfi_csrs.py` reads the native CSR channel catalog and uses the shared CSR model
to check pre-/post-state, access masks, counter aliases and implicit updates.
`elf_image.py` loads and validates static little-endian RV32 ELF segments,
zero-fill tails, symbols and the test completion encoding without simulator or
ELF-library dependencies. `software_build.py` is the shared Make helper behind
`make sw`, deriving compiler ISA/ABI arguments from the hardware YAML. See the
[ELF execution guide](../core_elf/README.md).
`toolchain.py` discovers external GCC/Clang and records its family, version,
RV32 target and ISA/ABI. `riscv_tests.py` handles explicit pinned archive fetching
and adapted ISA builds; `elf_suite.py` executes their frozen manifest through
the common runner, sharing only a compatible compiled simulator. Each execution
retains a fresh process and artifact directory. See the
[riscv-tests guide](../../sw/riscv_tests/README.md).

`benchmark.py` builds and runs ports declared under
[`verif/sw/benchmark/`](../../sw/benchmark/README.md). `pinned_archive.py` handles
checksum-pinned archive caches without submodules. `benchmark_measure.py`
validates executable timer markers, retirement-edge windows and CoreMark RAM
diagnostics. The common runner supports paired `--imem-latency` and
`--dmem-latency` options for deterministic ELF memory timing; `--benchmark`
additionally requires matching build metadata and produces native benchmark
reports. Ordinary tests retain the existing random waits. Benchmark runs keep
the same instruction, RVFI, CSR and cycle-counter checks as other ELF tests when
`BENCHMARK_MODE=checked` is selected. The default `BENCHMARK_MODE=fast` instead
uses `benchmark_fast.py` and the [native C++ harness](../benchmark/README.md).
It uses Bender's RTL sources and Verilator's native build API without importing
cocotb/pyuvm or using VPI, and validates the final workload/window after execution.
The core fixture also exposes a passive active-channel bitmap and 256-bit
snapshot per CSR to reduce individual VPI reads. The checker still compares
every asserted channel against the independent model on each edge; the
individual RVFI ports and JSONL trace are unchanged. The model advances cycle
and retirement counters on every edge, taking CSR snapshots only for CSR,
trap/return or floating-point CSR events.

`bpu_model.py` supplies the abstract independent target/direction oracle shared
by the standalone predictor and IF regressions. It tracks target replacement
and signed direction confidence independently of RTL bit slicing.

`rv32_arithmetic.py` supplies mathematical ALU and M-extension models to the
standalone and shared-parent scoreboards. `decode_model.py` supplies the shared
mask/match ISA oracle to decoder and DE tests; `de_model.py` adds DE runtime,
readiness, compressed strategy selection, control-flow and local XIF issue
behavior. `compressed_model.py` independently assembles RV32C semantics for
the decompressor/strategy, direct decoder and DE regressions. `ex_model.py` provides instruction-level
EX outcomes to the stage and parent-register fixture scoreboards.
`lsu_model.py` provides byte-addressed memory and native load/store expectations
shared by LSU and MEM tests. `mem_model.py` adds MEM token/result expectations
shared by the standalone stage and parent-register fixture.
`ifetch_model.py` describes aligned word/error outcomes for the instruction
fetch engine and shared-PMP fixture. `pmp_model.py` provides the independent
byte-interval permission model shared by standalone PMP and concurrent IF/LSU
tests; protection implementation remains in the one core-owned RTL checker.
`if_aligner_model.py` supplies byte-window selection and fault-portion expectations
to standalone alignment and real fetch/buffer/aligner integration tests.
`csregfile_model.py` supplies architectural CSR words/events to both CSR and WB
tests. `wb_model.py` adds commitment, fault and architectural GPR expectations
shared by the WB stage and its parent-register/GPR fixture.

Simulation-specific reusable agents, models, Python helpers, and HDL wrappers
belong here when shared by multiple testbenches. A wrapper used by one component
stays beside that component's tests. Utilities shared with formal verification
may live in `verif/common/`.

To add a component:

1. Put its tests and local environment in `verif/sim/<component>/`.
2. Add its HDL sources and any shared HDL wrappers to the appropriate Bender
   source group. Bender remains the source/dependency authority.
3. Add `config/sim/<component>.yml`, listing `top_module`, `bender_target`,
   `test_module`, `parameters`, and `tests`. Parameters name the subset of the
   complete hardware configuration consumed by that DUT; `parameters: []` is
   valid for a component without configurable parameters.
   The optional boolean `requires_elf: true` declares an ELF-consuming target;
   the runner then requires `ELF=<path>`, validates it before simulator build,
   snapshots it and records its hash/entry/segments and `MAX_CYCLES` watchdog.
   Tests receive `UQU_ELF` and `UQU_MAX_CYCLES` alongside resolved parameters.
   Native manifests default to Bender `--no-deps`; use boolean
   `bender_dependencies: true` when the DUT always instantiates imported HDL,
   or `bender_dependencies_if: ISA_ZFINX` for a declared boolean DUT parameter.
   Integer-only runs then retain `--no-deps`. Source
   ordering and include directories still come from Bender, and `.vh`/`.svh`
   hashes are recorded. Imported-IP runs also snapshot/hash `Bender.lock`.
   The runner adds the simulator target; optional `bender_targets: [...]` adds
   package-specific source selections. Verilator `.vlt` controls are read first,
   preserving the relative order of HDL files. The CVFPU profile selects
   `tech_cells_generic_exclude_deprecated` and `cvfpu_verilator` for compatible
   dependency sources and scoped imported-IP/language-boundary controls.
   See the [CVFPU dependency contract](../../../doc/uqu_spec.build.md#13-pinned-cvfpu-dependency-without-git-submodules)
   for the Git/lockfile cache and disabled upstream submodule checkout.
4. Run `make test COMPONENT=<component> CONFIG=<hardware-config>`.

The runner needs no component-specific Python branch. See
[the register-file manifest](../../../config/sim/gpregfile.yml) for an example.
Testbenches receive resolved DUT parameters as JSON in `UQU_COMPONENT_PARAMS`.
`TEST=all` selects the manifest's test suite; `TEST=<name>` selects one entry.
The result file must contain exactly the selected tests, all passing.

`make test-runner` runs Python tooling checks without an HDL simulator. Provide
Python dependencies from `verif/requirements.txt` externally; no target installs
dependencies or invokes containers.

`spike.py` supplies the optional, binary-pinned external reference adapter for
ELF runs. Select `REFERENCE=spike`; discovery uses `SPIKE`, `$RISCV/bin/spike`,
then `PATH`. The [reference guide](../../reference/README.md) defines the initial
comparison scope, unsupported-event policy and retained mismatch diagnostics.
