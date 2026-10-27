# uquintus Build and Project Layout

**Status:** First specification draft finalized, 2026-10-20

Build/configuration contracts and project organization. A shared component
simulation/lint flow supports the register file, ALU, arithmetic datapath, native
multiply/divide, native decoder, DE branch unit, DE/EX hazard unit, pipeline
controller, IF, DE, EX,
MEM/LSU, instruction-word fetch/buffer/aligner, WB, PMP checker, CSR register file, and shared-arithmetic/prefetch/parent-register
fixtures, native full-core regression and ELF software execution. ORFS mapped
synthesis and preplacement timing are implemented for core/FPU targets;
placement and timing repair are available through `make impl`; CTS and routing
remain open. See the
[shared simulation guide](../verif/sim/common/README.md).

[Specification index](uqu_spec.md) · [Architecture](uqu_spec.arch.md) · [Interfaces](uqu_spec.interfaces.md) · [Verification](uqu_spec.verif.md) · [Build](uqu_spec.build.md) · [Style](uqu_spec.style.md)

Agreed requirements remain binding. Explicit proposals retain their status, and
TBD items remain implementation or integration follow-ups. Finalizing this draft
does not imply that the documented hardware or build infrastructure exists.

## 1. Bender and GNU Make build structure

**Status:** Bender/Make simulation, lint, software, reporting and ORFS synthesis
and placement implemented; formal, CTS and routing open

The project shall use Bender for HDL source/dependency management and GNU Make
as the build entry point. The responsibilities shall be:

| Component | Responsibility |
| --- | --- |
| `Bender.yml` | Declare HDL sources, dependencies, include paths, defines, and target-specific source groups. |
| `Bender.lock` | Record resolved HDL dependency revisions for reproducible builds; keep the lockfile under version control. |
| GNU Make | Coordinate build steps and invoke the selected tools and project scripts. |
| OpenROAD-flow-scripts | Coordinate the default ASIC synthesis and physical implementation stages ([build, Section 4](uqu_spec.build.md#4-openroad-flow-scripts-asic-backbone)). |
| Tool-specific scripts | Translate selected sources and core configuration into simulator, formal, synthesis, and ASIC implementation inputs. |

Build scripts shall consume Bender-generated source information rather than
maintain independent copies of the HDL source/dependency lists. The source
selection shall preserve the project-owned Verilog-2005, imported-IP
SystemVerilog exception, and verification language rules in [overview, Section 2.9](uqu_spec.md#29-rtl-implementation-conventions).
ISA selection shall continue to use RTL parameters;
Bender source-group selection shall not replace their architectural meanings.

The flow shall accommodate the agreed simulation/reference-model checks,
`riscv-formal` verification, supported-configuration CI coverage, and ASIC
implementation targets. Simulator selection is defined in [build, Section 3](uqu_spec.build.md#3-selectable-simulation-backend);
ORFS integration is defined in [build, Section 4](uqu_spec.build.md#4-openroad-flow-scripts-asic-backbone), with detailed PDK-specific setup
described in the [ASIC guide](../impl/asic/README.md).
The current configuration schema, simulation/software commands, Python helpers
and output layout are implemented below and in the shared simulation guide.
Formal and post-placement target definitions, broader tool-version pins and additional
technology-specific integration remain open.
The shared core-configuration and separate build-target requirements are
defined in [build, Section 2](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets).

For the selected tools' roles, see the
[Bender documentation](https://pulp-platform.github.io/bender/) and
[GNU Make manual](https://www.gnu.org/software/make/manual/html_node/Rule-Introduction.html).

### 1.1. Bare-metal software build and execution

`make sw CONFIG=<hw> SW=<program> RISCV_CC=<compiler>` shall build the program
under `verif/sw/` with an externally supplied RISC-V GCC or Clang/LLD, deriving
ISA/ABI flags from the validated hardware configuration. The common helper
shall live under `verif/sim/common/`; outputs shall use
`build/uquintus-<hw>/sw/<program>/` and record compiler version, command, input
hashes, ELF, map and build diagnostics. No target shall install dependencies.

`make test COMPONENT=core_elf CONFIG=<hw> ELF=<path>` shall execute a supplied
ELF through the existing Bender/Verilator/RVFI flow. `MAX_CYCLES` shall control
the simulation watchdog; it shall not introduce a processor timeout. The
[execution guide](../verif/sim/core_elf/README.md) defines commands, artifacts and
the loader/completion contract specified in
[verification, Section 2.6](uqu_spec.verif.md#26-elf-software-execution).

`make benchmark CONFIG=<hw>` builds and executes ports/configurations under
`verif/sw/benchmark/<suite>/`. `BENCHMARK_MODE=fast` defaults to a compiled
Verilator C++ driver; `BENCHMARK_MODE=checked` uses the cocotb/pyuvm ELF harness.
These are execution/validation settings, not hardware parameters or simulator
selectors. Both modes use the same memory/timing contract and final workload self-checks;
their distinct scopes remain explicit in report metadata. See the
[benchmark specification](uqu_spec.bench.md#3-rtl-workload-measurements).
Use `BENCHMARK=embench/embench-iot` for the pinned 19-workload Embench 1.0
suite and `BENCHMARK_PROFILE=all|<name>[,<name>...]` to select its workloads.
For microarchitecture-only comparisons, `make benchmark-run
BENCHMARK_REUSE_SUITE=<software-suite.json>` shall reuse the exact pinned
executables after checking workload settings and software-visible hardware
compatibility, recording the source suite and both parameter snapshots.

`make perfsim-fetch`, `make perfsim-model` and `make perfsim ELF=<path>` provide the separate experimental ETISS/CorePerfDSL flow. Its [specification](uqu_spec.perfsim.md) and [tool setup guide](../verif/perfsim/README.md) define pinned archive dependencies, externally provisioned tools, generated-model caching, multi-configuration execution and supported coverage. `PERFSIM_MEMORY=<YAML>` optionally selects an external memory timing/cache-stub environment independently of the core YAML. Its estimated-cycle artifacts use `build/uquintus-<hw>/perfsim/` and their own report category; they do not replace either RTL benchmark backend.

### 1.2. Pinned instruction suites and external compiler identity

The initial `riscv-tests` adapter shall consume the commit and archive SHA-256
recorded in `verif/sw/riscv_tests/lock.json`, without adding a Git submodule or
tracked upstream source tree. `make riscv-tests-fetch` shall explicitly fetch
and verify the archive, or accept a matching offline archive, into `build/deps/`.
Build/run targets shall require that cache and shall not fetch implicitly.

`make riscv-tests-build` shall compile the selected applicable tests;
`make riscv-tests-run` shall execute the last successfully built manifest.
`make riscv-tests` shall combine those steps. `RISCV_TESTS` shall select all
applicable tests or comma-separated full upstream names. The
[adapter guide](../verif/sw/riscv_tests/README.md) defines source integrity,
selection, output paths and simulator-build reuse.

Both native software and instruction-suite builds shall discover an externally
supplied compiler through explicit `RISCV_CC`, then the installation root
`$RISCV/bin`, then `PATH`. Automatic discovery shall support RV32/RV64-prefixed
bare-metal GCC, `riscv-none-elf-gcc`, and Clang with an explicit RISC-V target and external LLD. Derive
ISA/ABI options from hardware YAML and probe that the compiler actually targets
RV32. Invalid explicit tools or unsupported targets shall fail clearly.

Report the compiler executable/resolved path, GCC/Clang family, numeric version
from predefined macros, complete version banner, effective target, ISA/ABI and
exact command. Build and execution artifacts shall preserve that identity and
the test-suite revision for the shared report. No compiler installation,
dependency build or container invocation shall become implicit in Make.

`REFERENCE=spike` shall optionally compare native ELF and instruction-suite runs
against the qualified external binary, discovered through `SPIKE`, `$RISCV/bin`
or `PATH`. The [reference contract](uqu_spec.verif.md#28-initial-spike-differential-elf-checking)
defines pinning, supported events and retained JUnit/report diagnostics. The
default `REFERENCE=none` preserves native-only checking.

Native software programs shall provide exactly one `main.c` or `main.S`.
Both shall receive the configured `UQU_HART_ID`, `UQU_ISA_ZFINX` and `UQU_ISA_UMODE`
values for identity expectations and conditional ISA/M/U
scenarios. The linker shall retain the optional embedded expected-trap table
described in [verification Section 2.6](uqu_spec.verif.md#26-elf-software-execution).

For IRQ/MIE reference tests, compile the local verification-only Spike device
against externally supplied matching headers and `lib/libriscv.so`, located
beside the executable or through `SPIKE_ROOT`. Use external host `CXX` (default
`c++`) and record SDK/source hashes, compiler identity, command, log and output
hash per run. This builds the project helper, not Spike or its dependencies.
Retain the optional ELF `.uqu.irqs` table; its stimulus contract is defined in
[verification Section 2.8](uqu_spec.verif.md#28-initial-spike-differential-elf-checking).

### 1.3. Pinned CVFPU dependency without Git submodules

CVFPU and FPnew are the same backend; its Bender package name is `FPnew`
(dependency key `fpnew`). `Bender.yml` pins Git revision
`77811635cb7e8649f1d9484733ee6a0bdb44a0e6`; `Bender.lock` records exact revisions
for it and all transitive packages, including `common_cells` and
`fpu_div_sqrt_mvp`. The graph also contains `common_verification` and
`tech_cells_generic`; Bender target selection determines their applicable HDL.
The lockfile is version-controlled. These are dependency checkouts in ignored
`.bender/`, with no `.gitmodules` entry or Git submodule in uquintus.

Project `.bender.yml` sets `git_submodules: false`. Upstream CVFPU's legacy
submodules are not needed by its Bender RTL manifest: Bender supplies those RTL
dependencies independently, and its FlexFloat testbench is not part of this
integration. An initial checkout may report warning W36 for these intentionally
unpopulated paths. No source list shall reference them.

```sh
bender checkout                         # Fetch exact locked dependencies
bender packages                         # Inspect the resolved graph
bender path fpnew                       # Locate its checkout
bender script flist -t fpu              # Include backend/dependency sources
bender script flist -t ex --no-deps     # Owned RTL only
```

Changing a dependency is a deliberate manifest/lockfile update with
`bender update`; ordinary runs shall reuse the recorded revisions. Bender may
fetch missing checkouts when generating sources/scripts, so prepare the cache
before offline runs. It manages Git downloads and ordered source/include lists,
not compiler installation or an RTL build of the dependency.

The shared runner defaults to `--no-deps` for existing native component manifests.
A component that always instantiates imported IP shall set boolean
`bender_dependencies: true`. A conditional dependency shall instead declare
`bender_dependencies_if: <boolean hardware parameter>`, which must name one of
its DUT parameters. EX, its parent fixture, core and ELF manifests select
`ISA_ZFINX`; integer-only configurations retain `--no-deps`. Both the flat
source list and structured include tree use the same resolved dependency choice. HDL header provenance covers `.vh` and `.svh`;
imported-IP runs retain a lockfile snapshot and its hash with source provenance.
The runner also selects the simulator's Bender target (`verilator` currently).
Optional `bender_targets` selects additional upstream/project source groups.
The CVFPU Verilator import profile uses:

```yaml
bender_dependencies: true
bender_targets:
  - tech_cells_generic_exclude_deprecated
  - cvfpu_verilator
```

The first target excludes obsolete generic pad models with unsupported
transistor primitives. The second selects `verif/sim/common/uqu_cvfpu.vlt`,
which scopes controls to the pinned imported arithmetic's packed ranges,
width conversions, disjoint pipeline-array drivers and generated arbiter/tree
settling under Verilator 5.020 with public cocotb visibility. A separate
`ENUMVALUE` waiver covers only the Verilog adapter's checked two-bit backend
parameter, because Verilog-2005 cannot spell an SV enum cast. Controls precede
HDL compilation without changing HDL dependency order; other project RTL
diagnostics stay enabled. These controls are not patches to upstream source. Do not add
the generic `simulation` target for this Verilator profile: it selects upstream
randomized SV test utilities that this simulator version does not support.
Import parsing/lint qualification is separate from executing FPU instructions.

The FPU adapter now instantiates the imported backend for enabled Zfinx.
The [FPU guide](../verif/sim/fpu/README.md) describes the real arithmetic and
lifecycle checks, qualified TH32/THMULTI choices, rejected PULP selector and
remaining physical-flow qualification. The `rv32i_zfinx` preset enables it.

References: [Bender dependency workflow](https://pulp-platform.github.io/bender/workflow/dependencies.html),
[project configuration](https://pulp-platform.github.io/bender/configuration.html),
and the [pinned CVFPU manifest](https://github.com/openhwgroup/cvfpu/blob/77811635cb7e8649f1d9484733ee6a0bdb44a0e6/Bender.yml).

## 2. Shared core configuration and separate build targets

**Status:** Strict YAML validation, selector generation, presets and simulation
target manifests implemented; ORFS synthesis consumes the shared configuration;
placement shares that consumer; formal and post-placement consumers remain open

Each supported core configuration shall be defined once in a shared
YAML configuration file. Simulation, formal checking, synthesis, and CI shall
consume that definition for the selected hardware parameters. Tool-specific
parameter overrides and matching reference-model ISA settings shall be derived
from the shared definition rather than maintained independently for each flow.
`verif/sim/common/hw_config.py` validates the complete parameter set, types,
selector labels and supported combinations, and translates it into tool inputs. This
file shall describe core hardware parameters separately from Bender's source
and dependency manifest. Its parser shall be provided by the externally
provisioned build environment, consistent with [build, Section 5](uqu_spec.build.md#5-externally-provisioned-build-environment).

Enumerated hardware selectors shall use readable YAML labels. In particular,
`MUA_BRANCH_PREDICTOR` shall use `none`, `static_not_taken` or `bimodal` for the currently
defined choices, and `MUA_REGFILE_IMPL` shall use `ff` or `latch`. Their default
YAML selections shall be `none` and `ff`, respectively. `MUA_MUL` shall use
`dadda_mac` (default), `dadda`, or `iterative`, as defined in [architecture, Section 3](uqu_spec.arch.md#3-classical-five-stage-pipeline). MEM/EX2 is the canonical second execution region. The split has a fixed two-row payload; `MUA_MUL_SPLIT` and historical multiplier labels are rejected, without compatibility aliases.

`MUA_DIV` shall use `iterative` (default) or native one-cycle `parallel`. All hardware presets shall
also explicitly set `MUA_BP_ENTRIES`, a power of two from 2 through 1024,
defaulting to 16 and inactive outside bimodal mode. Independently select target
storage with `MUA_BTB: none | direct_mapped` (default `none`) and explicit
`MUA_BTB_ENTRIES` (power of two from 2 through 1024, default 16). Direction and
target capacities may differ. `MUA_BTB_IDATA_HWORDS` explicitly selects `0` through
`2048` halfwords per target entry; default zero removes the payload path.
Without C the count must be even, giving an integral number of 32-bit words.
With C, payloads and the active replay snapshot automatically pack original
16-/32-bit encodings, stopping before an instruction would exceed capacity.
`rv32i_bimodal_idata` selects eight halfwords for four I32 instructions;
`rv32ic_bimodal_idata` selects six halfwords (96 bits) with variable instruction coverage.
The former instruction-depth parameter is replaced without an alias; convert
old depth `D` to `H=2*D` to preserve its byte budget, then tune the packed budget
explicitly. Historical artifacts retain their original parameter names and units.
Prediction mode `none` disables target steering
and makes BTB settings inactive. The `rv32i_bimodal` preset explicitly enables
the direct-mapped BTB. These selectors use the same canonical catalog and
generated constants. The separate integer setting
`MUA_MULDIV_ITERUNROLL` shall use `1`, `2`, `4`, `8`, `16`, or `32`, defaulting
to `8`, and shall govern every selected iterative operation. Selector labels
containing the former `+unroll+<factor>` suffix shall fail configuration
validation.
The validated numeric `MUA_MULDIV_ITERUNROLL` factor shall be passed to RTL
unchanged.
Compressed decoding shall use `MUA_C_IMPL: decompress` or `decode_compressed`, and
`MUA_C_DECOMPRESS_STAGE: if` or `de`. Defaults are `decompress` and `if`.
Both selectors remain mandatory in every hardware YAML file even when C is
disabled; placement is inactive for `decode_compressed`. Their canonical encodings in
`config/selectors.json` are `decompress = 0`, `decode_compressed = 1`, `if = 0` and
`de = 1`, with corresponding generated Verilog macros. No nested YAML settings
or string-valued RTL parameters are required. The comparison presets are
`rv32ic.yml`, `rv32ic_decompress_de.yml` and `rv32ic_decoder_c.yml`.
Configuration helpers
shall validate the labels and translate them into integer RTL parameter values,
using a consistent mapping across simulation, formal, and synthesis flows.
Unknown or unsupported labels shall produce a clear configuration error.
The register-file encodings are `ff = 0` and `latch = 1`. Multiplier encodings
are `iterative = 2`, `dadda = 3`, and `dadda_mac = 13`; removed encodings remain unused. Divider
`iterative = 0`. Predictor encodings are `none = 0`, `static_not_taken = 1` and
`bimodal = 2`.
A single canonical selector
definition shall supply both the YAML-label translation and the RTL encoding constants.
The build shall generate guarded Verilog `.vh` macro headers from this
definition, following the
[shared-constant conventions](uqu_spec.style.md#3-identifiers-and-symbols).
Configuration helpers shall obtain their label-to-integer mappings from the
same definition rather than maintain an
independent copy. The register-file, MUL/DIV, compressed-decoding and predictor
catalog is `config/selectors.json`, with the shared generator in
`verif/sim/common/hw_config.py`. Complete initial presets are `config/rv32i.yml`,
`config/rv32im.yml`, and `config/rv32im_iterative.yml`. The baseline keeps M disabled; both M-enabled presets currently select the
shared iterative MUL/DIV chain with unroll factor eight.
FPU selector labels and four explicit register counts follow
[architecture Section 3.3.2](uqu_spec.arch.md#332-cvfpu-implementation-configuration).
All presets state these settings even with `ISA_ZFINX = 0`; the configuration
helper validates counts and labels before encoding the two selectors for RTL.
All hardware presets explicitly set boolean `MUA_DE_OPERAND_RETENTION`,
defaulting to zero for continuous DE source resolution. The additional
`config/rv32i_retained.yml` preset enables optional hazard-unit DE operand
retention; it otherwise matches `rv32i`.
Generated headers shall use the applicable build output directory
in [build, Section 6](uqu_spec.build.md#6-build-output-naming). Selector definitions shall not supply implicit hardware
configuration defaults: each configuration shall still set all parameters.

Core configuration files and simulation-target configuration shall remain under
the repository-root `config/` directory. Simulation-target configuration shall
not move into `verif/sim/`. Hardware presets use `config/<hw>.yml`;
component/fixture manifests use `config/sim/<component>.yml`, and shared selector
encodings use `config/selectors.json`.

The hardware configuration name `<hw>` shall be the selected YAML filename's
basename without its extension. For example, `rv32i_zifence.yml` shall select
`<hw> = rv32i_zifence`, and `rv32i-fast.yml` shall select `<hw> = rv32i-fast`.
Configuration names shall identify their profiles uniquely. Names may describe
ISA features or a preset's intended use; hardware settings shall be read from
the file rather than inferred from its name.

Selected Pareto-optimal configurations shall eventually use Greek-letter codes
as profile names with stable selection goals, with complete presets such as
`config/uquintus-alpha.yml`, `config/uquintus-beta.yml` and
`config/uquintus-gamma.yml`. Their initial selection goals shall be lowest
normalized suite cycle cost (geometric mean of candidate/reference cycle ratios),
lowest area and highest estimated maximum frequency, respectively, as defined
in the [Pareto-profile policy](uqu_spec.bench.md#4-pareto-optimal-configuration-profiles).
These names shall supplement the generated hardware label and complete
parameter fingerprint; they shall not encode or determine parameter values.
Their parameter sets may be revised as the benchmark suite, eligible features
and measurement flows evolve. Retain each selection's suite/reference context,
parameter snapshot and evidence so earlier results remain identifiable after
the same preset name is updated.
Parameter search and selection of the actual profile contents are deferred.
No placeholder YAML shall imply that an optimum has already been established.

Each hardware configuration file shall explicitly set every supported,
externally configurable core hardware parameter, including parameters that
are inactive under the selected parent feature. Derived `localparam` values
shall remain internal and shall not be configuration-file settings. Missing
required parameters shall cause a clear configuration error. Builds shall not
fill missing hardware values from shared configuration defaults, inherited
presets, or RTL parameter defaults. Documented RTL defaults shall remain part
of the module interface, but project configuration files shall state those
values explicitly when selecting them.

The project shall provide complete predefined configuration files as starting
points for users to copy and adapt. Existing presets include `rv32i`, `rv32im`,
the three compressed strategies, `rv32i_pmp`, `rv32i_zifencei`,
`rv32i_retained`, `rv32i_bimodal` and `rv32i_xif`. The `rv32i_xif_debug` profile exercises
component-level debug support; it is not an enabled-debug core configuration.
Adapted configurations shall satisfy the same
completeness and supported-combination checks as supplied presets. Adding a
new configurable hardware parameter shall require updating the supported
configuration files to include an explicit value. Simulator, implementation,
and environment settings shall remain separate from these hardware parameters.

Core configuration and build target shall be separate selections. Simulation
and synthesis shall have distinct targets, source selections, top levels, and
tool settings as needed:

| Selection | Contents |
| --- | --- |
| Core configuration | ISA/privilege parameters, forwarding/prediction selection, register-file backend, XIF/debug settings, and other elaborated hardware choices. |
| Simulation target | Testbench top, verification sources and models, tests, and waveform/trace options; the simulator backend is selected separately through `SIM` ([build, Section 3](uqu_spec.build.md#3-selectable-simulation-backend)). |
| Formal target | Formal harness and instrumentation, property/check selection, assumptions, and solver settings. |
| Synthesis/implementation target | Synthesizable processor top or wrapper, synthesis settings, technology/cell mappings, timing constraints, and applicable physical implementation setup. |

The same core configuration shall be reusable across these targets. Changing a
target shall not silently change the configured hardware features. Verification
sources and instrumentation shall be selected for their respective targets;
simulation testbenches and file-writing monitors shall not enter the
synthesizable design source set. Technology-specific setup shall remain part
of the synthesis/implementation target rather than redefine the ISA.

`make sim COMPONENT=core CONFIG=rv32i` selects the integrated core simulation;
`make test` is its alias, with `COMPONENT` defaulting to `gpregfile`.
`make lint COMPONENT=core CONFIG=rv32i` checks the corresponding source set.
`make synth ASIC_FLOW=orfs TOP=core|fpu CONFIG=<hw> PLATFORM=sky130hd|ihp-sg13g2`
selects the implementation flow, synthesizable top and technology independently.
`ASIC_FLOW` defaults to `orfs`; unsupported selections shall fail explicitly.
`make impl` uses the same selection and continues through placement and timing
repair, before CTS and routing. `TOP` defaults to `core`; `CLOCK_PERIOD_NS=20`
and `JOBS=4` are flow settings. `SDC=<file>` selects supplied integration
constraints in either target. Formal and post-placement commands remain open.

### 2.1. Generated hardware configuration label

**Status:** Shared label generator and CLI implemented; report integration pending

In addition to the YAML preset name, the build shall derive a descriptive
hardware configuration label from the validated parameter values. The YAML
shall remain the source of truth; the label shall not be parsed as configuration
input. Preset names and the `build/uquintus-<hw>/<target>/` layout shall retain
their existing meanings. Reports and artifact metadata shall expose the label
alongside the preset name and complete parameter fingerprint.

`make config-label CONFIG=<hw>` shall print just the generated label. It shall
also accept `CONFIG=<path/to/hardware.yml>`. The implementation shall reuse the
shared hardware YAML validation and selector catalog, requiring no HDL tools
or simulator. Its direct command is:

```sh
python3 verif/sim/common/hw_config.py --config rv32i
python3 verif/sim/common/hw_config.py --config config/rv32ic.yml
```

The reusable `configuration_label(config)` function in that module shall accept
the validated, label-valued mapping returned by `load_configuration`, before
encoding selectors into RTL integers. Invalid YAML, missing parameters and
unsupported choices shall fail the command without printing a label.

Labels shall use lowercase tokens and the following fixed field order. Square
brackets denote optional fields; braces denote alternatives. An optional
feature's token shall appear only when that feature is enabled. Selectors for
disabled features shall be omitted even though their values remain mandatory
in the YAML and included in the complete parameter fingerprint.
Microarchitecture selections shall use `mua-<feature>:<selection>`, with `+`
joining combined selections and `_` separating fields. The optional enabled-only
`mua-opret` flag shall retain its short form.

| Field | Label form | Parameter selection |
| --- | --- | --- |
| ISA | `uqu_rv32{i,e}[m][c]_zicsr[_zifencei][_zfinx]` | `ISA_E` chooses `e` instead of `i`; the remaining optional tokens follow their corresponding ISA parameters. Zicsr is always present. |
| Coprocessor | `[_xif-{2rs,3rs}[-dw]]` | `XIF`, `XIF_NUM_RS`, `XIF_DUALWRITE`. |
| User mode | `[_umode]` | `ISA_UMODE`. |
| Physical memory protection | `[_pmp]` | `ISA_PMP`. |
| Debug | `[_dbg]` | `DEBUG`. |
| General-purpose register file | `_mua-gpr:{ff,latch}` | `MUA_REGFILE_IMPL`. |
| Forwarding | `_mua-fw:none` or `_mua-fw:[ex2de+][mem2de+][mem2ex+][wb2ex+]wb2de` | Master `MUA_FORWARDING`, followed by enabled individual forwarding paths in the displayed order and the fixed WB-to-DE path. |
| DE operand retention | `[_mua-opret]` | `MUA_DE_OPERAND_RETENTION`; this describes operand retention rather than an instruction buffer. |
| Compressed handling | `[_mua-c:{decompr-if,decompr-de,decode}]` | Present only for `ISA_C=1`; `MUA_C_IMPL` and, for decompression, `MUA_C_DECOMPRESS_STAGE`. |
| Branch prediction | `_mua-bp:{none,stnt,bimodal+entries<N>}` | `MUA_BRANCH_PREDICTOR`: `none`, `static_not_taken` or `bimodal`. Include `MUA_BP_ENTRIES` only for bimodal mode. |
| Branch target storage | `_mua-btb:{none,direct+entries<N>[+idata-hw<H>]}` | `MUA_BTB`, independent `MUA_BTB_ENTRIES` and halfword capacity `MUA_BTB_IDATA_HWORDS`; omit `+idata-hw` at zero. Use `none` when disabled or when prediction mode is `none`; omit inactive capacity. |
| Instruction buffer | `_mua-ifbuf:<words>` | `MUA_IF_BUFFER_WORDS`. |
| Redirect/refill bypass | `[_mua-rb:<policies>]` | Omit for `none`; otherwise join enabled policies in canonical order with `+`: `ifbuf` for `if_buffer`, `redirect` for `redirect_request`, `result` for `ifetch_result`. All eight selector values are supported, e.g. `mua-rb:ifbuf+redirect+result`. |
| Multiplier | `[_mua-mul:{iter,dadda,dadda-mac}]` | Present only for `ISA_M=1`; `iterative`, EX1 product-only `dadda`, or canonical split `dadda_mac`. |
| Divider | `[_mua-div:{iter,parallel}]` | Present only for `ISA_M=1`; `MUA_DIV` selects iterative arithmetic or native combinational quotient/remainder logic. |
| Shared iterative arithmetic | `[_mua-mdu:unroll<factor>]` | `MUA_MULDIV_ITERUNROLL`, when M is enabled and at least one MUL/DIV implementation is iterative. |
| FPU implementation | `[_mua-fpu:<backend>+pipe-<placement>+fma<N>+divsqrt<N>+noncomp<N>+conv<N>]` | Present only for `ISA_ZFINX=1`; `MUA_FPU_DIVSQRT`, `MUA_FPU_PIPE_CONFIG`, then the four `MUA_FPU_PIPE_REGS_*` counts in the displayed order. Use the validated YAML labels for backend and placement. |

`mua-fw:none` shall mean that the master forwarding switch is disabled,
irrespective of the inactive individual path settings. With the master enabled,
WB-to-DE forwarding shall always be listed explicitly as `wb2de`. Consequently,
disabling all four individually configurable paths shall produce
`mua-fw:wb2de`, distinct from `mua-fw:none`.

Direct compressed decoding shall use `mua-c:decode`; the inactive decompressor
placement shall not appear. MUL and DIV shall share the single
`mua-mdu:unroll<factor>` field; it shall not imply independently configurable
unroll factors. Factor 32 remains a three-cycle unrolled iterative divider;
`mua-div:parallel` instead identifies native one-cycle `/` and `%` logic. With
non-iterative MUL and DIV, omit the inactive unroll field. Future ISA or implementation
choices shall extend this convention when supported; reserving a parameter
shall not make that feature selectable or qualify it for reporting as enabled.

For the current `config/rv32i.yml`, the label shall be:

```text
uqu_rv32i_zicsr_umode_mua-gpr:ff_mua-fw:ex2de+mem2de+mem2ex+wb2ex+wb2de_mua-bp:none_mua-btb:none_mua-ifbuf:2
```

Enabling C with decompression in DE shall insert `c` in the ISA token and
`_mua-c:decompr-de` after the optional operand-retention field. Enabling M with
iterative MUL/DIV and factor eight shall append the arithmetic fields
`_mua-mul:iter_mua-div:iter_mua-mdu:unroll8`, before any FPU field.

The descriptive label shall not replace the complete parameter fingerprint as
configuration identity. Inactive settings and compile-time integration
identity such as `HART_ID` may differ without changing the label. The existing
fingerprint over the complete parameter snapshot shall distinguish these
configurations. Artifact filenames shall use the preset name and/or a compact
fingerprint rather than require the potentially long label as a directory or
filename component. Simulator, compiler, technology, timing constraints and
benchmark execution mode shall remain separate report context.

## 3. Selectable simulation backend

**Status:** Verilator integration implemented; additional backends open

Simulation builds shall select their simulator backend through the GNU Make
argument `SIM`, defaulting to `verilator`. This selection shall be independent
of the shared core configuration and the simulation target/testbench. For
example, `make sim COMPONENT=core CONFIG=rv32i` uses the default backend,
equivalent to adding `SIM=verilator` to the same command.

The build structure shall allow additional simulator backends to be integrated
with their own tool invocation and settings. The set of additional supported
backends and their versions remains TBD; selecting an unsupported backend shall
fail with a clear diagnostic rather than fall back silently. A backend's
supported targets and verification features shall be documented.

Simulator-specific harness or foreign-language integration may differ, but
selecting a backend shall preserve the selected core parameters and the
verification contract applicable to the selected target. Simulation backend
selection shall not determine the synthesis tool or alter the synthesizable
RTL language requirement.

Simulation testbenches shall use the project-wide cocotb/pyuvm stack defined in
the [verification specification](uqu_spec.verif.md#21-python-simulation-framework).
The shared component flow uses the pinned cocotb Python runner described in
the simulation guide for component, subsystem and full-core tests. Additional
simulator backends remain open.

## 4. OpenROAD-flow-scripts ASIC backbone

**Status:** Mapped synthesis, placement/timing repair and scoped timing reporting
implemented; CTS, routing and broader configuration qualification open

OpenROAD-flow-scripts (ORFS) shall provide the default ASIC build backbone,
including its Yosys synthesis stage and subsequent physical implementation
stages. The project-level GNU Make interface shall invoke the applicable ORFS
stages for synthesis-only or full implementation runs. Initial support shall
not require a separate project-maintained synthesis flow or an independently
selectable synthesis engine.

Bender shall supply the design's HDL source/dependency information. Project
integration scripts shall combine that information with the shared hardware
configuration, selected synthesizable top, constraints, and platform settings
to produce ORFS inputs. These shall include the applicable `VERILOG_FILES`,
`DESIGN_NAME`, `PLATFORM`, and `SDC_FILE` settings. Propagate integer-encoded top
parameters through `VERILOG_TOP_PARAMS`, preserving the shared-configuration
contract in [build, Section 2](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets).

Design-specific ORFS configuration and constraints shall remain in the uquintus
repository under `impl/asic/orfs/`, allowing other ASIC flows alongside `orfs/`
and a future `impl/fpga/` alongside `impl/asic/`. Each flow shall own its scripts
and platform adapters. The flow-independent `impl/asic/targets.yml` shall define
synthesis tops, Bender source targets and parameter selection. Hardware presets
and the report format shall remain shared across flows.
The integration shall use ORFS's external-design support and
documented configuration/hooks; the baseline shall not require a fork or copy
of its implementation scripts. Simulation and formal checking shall continue
to use their separate targets and tool integrations.

The [ASIC guide](../impl/asic/README.md) defines the executable Make interface,
source/top selection, constraints, tools and artifacts. `impl/asic/orfs/common/synth.py`
generates an external-design configuration and invokes ORFS `make synth`.
`make impl` continues that run through ORFS `place` and `place_repair_timing`.
Its fixed evaluation footprint defaults to `DIE_AREA="0 0 1240 1240"`,
`CORE_AREA="20 20 1220 1220"` in micrometers and `PLACE_DENSITY=0.65`.
These settings are overridable and recorded, with actual geometry and pin
locations retained. Pins use the native ORFS automatic placer. Require legal
placement, nonnegative setup/hold slack and zero reported slew, capacitance and
fanout violations to pass implementation; retain measurements on a missed target.
Both clocks and parasitics remain explicitly labeled ideal/pre-CTS and
placement-estimated, respectively.
The baseline uses ORFS's native Verilog frontend; enabled Zfinx uses its Slang
frontend for imported SystemVerilog. Canonicalization checks reject structural
errors and unintended latches. A thin synthesis wrapper retains ORFS mapping
and saves mapped statistics/JSON; a post-synthesis hook runs ORFS's own timing
report in OpenROAD. Every final cell shall be a Liberty cell and counts shall
agree before success is recorded.

Use a single-clock SDC: non-clock input/output delays of 20% of the period,
0.1 ns input transition, 0.01 pF output load and 0.1 ns clock uncertainty.
Constrain synchronous reset as data. Pass ABC's target explicitly in ps.
An optional `RESET_INPUT_DELAY_NS` override shall set reset's maximum input
delay independently, with a 0 ns minimum; when omitted, preserve the original
20%-of-period data-input budget. Record both resolved reset delays with the run.
The [implementation guide](uqu_guide.impl.md#run-synthesis-and-repaired-placement) explains how to supply and interpret this integration budget.
Report cell count, summed cell area, buffer count/area, setup slack/TNS and estimated maximum
frequency. Negative slack means the target was missed, not that mapping failed.
The [benchmarking measurement definition](uqu_spec.bench.md#1-minimum-clock-period-and-maximum-frequency)
defines `T_min`, its relationship to setup slack and estimated maximum frequency,
and the timing context required for comparisons.
These are preplacement estimates with ideal interconnect, not physical timing
closure or extracted area/power. Default-activity power is not a qualified metric.
Workload power shall use the repaired netlist's cell-pin activity and the same
Liberty, SDC, clock period and placement RC as its recorded implementation.
`make power IMPL_RUN=<run> ELF=<benchmark.elf>` runs a verified native benchmark
with a functional gate shadow, compares qualified bus outputs, captures only
the measured retirement window and checks activity duration and pin coverage.
The default minimum measured coverage is 99%; missing activity shall not silently
qualify an assumed-toggle estimate. Retain internal/switching/leakage power,
annotation diagnostics, input hashes and benchmark identity. See the
[power guide](uqu_guide.impl.md#estimate-workload-power-and-energy) for scope and usage.
The baseline shall explicitly select the installed ORFS speed script
(`ABC_AREA=0`) with wire-load estimates enabled in its `buffer`, `stime`,
`upsize` and `dnsize` commands. Qualify those commands and verify that synthesis
executed the qualified script; fail on incompatible scripts or conflicting
resolved settings. Retain the script snapshot, SHA-256 and wire-load policy with
the result. Supplying `-D` alone does not establish that the script consumes it.

The generated design configuration shall set `REMOVE_ABC_BUFFERS=1` for
floorplanning and `GPL_TIMING_DRIVEN=1` for placement. OpenROAD shall rebuild
buffering with placement-estimated parasitics. These are flow settings,
independent of hardware YAML and RTL `MUA_` parameters. The synthesis target
stops before these physical stages; its reported mapped area includes ABC
buffers. Record the resolved settings and intended placement policy separately
from the stage actually executed. Disabling wire-load estimates remains an
explicit investigation case rather than a baseline option.

Record tool/ABC/plugin binary hashes, ORFS revision, full configuration,
sources/includes, Bender lock, flow/platform/library hashes, constraints and
raw outputs per run. Publish them through the shared `report.json` schema.
The production `make impl` target shall start from RTL and run the qualified ORFS sequence with automatic pin placement, retaining separate mapped and `placed_pre_cts` observations. These measurements do not establish post-CTS/routed closure. CTS/routing, broader parameter qualification and default tool/PDK lock policies remain open. See the [implementation guide](uqu_guide.impl.md) for controlled comparisons and result interpretation.
Build-environment
provisioning and discovery shall follow [build, Section 5](uqu_spec.build.md#5-externally-provisioned-build-environment). Additional implementation
flows may be added later;
no alternative flow is required initially. Target platform availability shall
not by itself establish uquintus timing, area, or physical-verification results.

See the [ORFS overview and external-design instructions](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts),
[design configuration guide](https://openroad-flow-scripts.readthedocs.io/en/latest/user/AddingNewDesign.html),
and [flow stage definitions](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/blob/master/flow/Makefile).

### 4.1. Interface timing scope

**Status:** Generic standalone and supplied integration SDC selection plus
separate internal/interface path summaries implemented

The generated SDC shall be treated as a standalone evaluation profile. Its
20%-of-period port delays, slew, load and clock assumptions describe an
exploratory environment; they shall not promise compatibility with a particular
SRAM, bus fabric or coprocessor. Defer detailed per-signal budgets until a
concrete integration is selected.

`SDC=<file>` shall select an integration-supplied SDC in place of the generated
profile. It shall not be combined with `RESET_INPUT_DELAY_NS`. The current
consumer requires exactly one ideal clock, whose period matches `CLOCK_PERIOD_NS`.
Use the original file in place, retain its snapshot/hash and STA-resolved
constraints, and allow a caller-selected clock name. External Tcl dependencies
are not recursively discovered and remain the integrator's responsibility.
Retain the selected profile, full constraints and hashes with its measurements.
For flat SoC implementation, the SoC shall own the final constraints and timing
analysis across the core, interconnect, memories and coprocessors. Standalone
core port delays shall not be reapplied at internal connections and count the
external delay twice. Use actual SRAM Liberty timing arcs, wrapper logic and
physical interconnect. Separately implemented blocks or macros shall instead
have explicit interface timing contracts that both sides meet.

Integration budgets shall cover request and response paths, input minimum and
maximum arrivals, output requirements, slew, load and clock relationships.
Same-cycle request/response paths through an external coprocessor shall fit
the combined core/interconnect/coprocessor budget. Variable operation or bus
latency shall not by itself authorize false-path or multicycle exceptions.

Report internal and interface critical paths separately, identifying their
endpoints and scope, while retaining the full-interface result defined in the
[benchmarking specification](uqu_spec.bench.md#12-required-scope-and-qualification).
Detailed SRAM/coprocessor evaluation harnesses and constraints shall follow
their selected integrations. These are implementation-flow settings and shall
not become RTL `MUA_` parameters.

### 4.2. Pipeline register-region timing diagnostics

Mapped synthesis and post-placement timing repair shall additionally report
worst setup and hold paths into the IF, DE, EX, MEM and WB register regions,
plus a CORE region for shared or unclassified state. Each region's incoming
summary shall consider all internal register launch points. Retain the worst
path for every launch/capture region pair, including intra-region paths, so
forwarding and control dependencies remain visible across stage boundaries.
Each timed result shall include slack in ns, startpoint, endpoint and a detailed
STA path report. An absent constrained path shall be `no_paths`, never zero
slack or an inferred stage frequency. Existing full/interface path summaries
and the full-path frequency reference shall remain unchanged.

Regions shall describe register ownership, not claim to partition combinational
logic into isolated stages. Parent-owned `de_*`, `ex_*`, `mem_*` and `wb_*`
pipeline input registers belong to the receiving stage. Local sequential state
under `u_if`, `u_de`, `u_ex`, `u_mem` and `u_wb` belongs to that stage; retained
top-level `if_*` state belongs to IF. CORE includes core-owned architectural
state such as the GPR file, centralized control/hazard state, unmatched mapped
names and mixed-region aliases. Flattening/optimization can merge or lose
names; retain the actual mapped register-cell/output-net inventory and counts
so attribution can be audited. Do not preserve hierarchy or inhibit
optimization solely to improve these diagnostic labels.

The ORFS producer shall emit these diagnostics under each existing
`timing/<flow-stage>/` directory: `regions.tsv`, `register_regions.tsv`, scoped
entries in `paths.tsv`/`summary.json`, and `stage_<capture>_<max|min>.rpt` plus
`stage_<launch>_to_<capture>_<max|min>.rpt`. Stage incoming slack metrics shall
be available for configuration comparisons in both synthesis and implementation
reports. The HTML run page shall display the region summaries and an expandable
launch/capture table. Non-core tops shall mark the region report not applicable;
historical records without it shall remain explicitly unrecorded.

These queries shall not add path groups, false paths or multicycle exceptions,
or change mapping/placement optimization. Slack comparisons shall retain the
same clock, constraints, timing corner and interconnect model; preplacement and
placed results remain separate observations.

## 5. Externally provisioned build environment

**Status:** External ORFS/tool discovery implemented; container provisioning open

The project Makefile shall expect an already provisioned build environment.
It shall locate ORFS through an explicit `ORFS_ROOT` environment variable or an
`orfs` launcher available on `PATH`. `ORFS_ROOT` shall identify the installation
or checkout containing `flow/Makefile` and take precedence when supplied. The
`PATH` launcher shall be supplied by the environment: `orfs --flow-dir` shall
print the absolute directory containing the flow Makefile. The helper then
invokes that Makefile directly. Select executables through `YOSYS_EXE` and
`OPENROAD_EXE`, `PATH`, or conventional ORFS installation paths, in that order.
Enabled Zfinx requires a compatible installed Slang plugin, optionally found
through `YOSYS_PLUGIN_PATH`. No project target builds or installs it.

Other required executables and platform resources shall likewise be available
through documented environment settings or tool search paths. A missing or
invalid required dependency shall produce a clear diagnostic. The Makefile
shall not install or build toolchain dependencies or PDKs, nor build images or
launch a container runtime.

Dependency provisioning shall be handled separately using Docker, with Docker
Compose where useful. Dockerfiles and any Compose definitions shall live under
`docker/`. Those containers shall expose the same build-environment contract so the project
Makefile requires no container-specific commands or execution branches. The
same Makefile shall also be usable in a compatible externally provisioned
environment. Exact Dockerfiles, Compose services, image/version pinning, and
the complete environment-variable contract remain TBD.

Normal HDL dependency/source management shall continue through Bender as
defined in [build, Section 1](uqu_spec.build.md#1-bender-and-gnu-make-build-structure); this separation concerns provisioning the tools and
platform environment used to build the design.

## 6. Build output naming

**Status:** Simulation, software, synthesis, placement and reporting layouts
implemented; post-placement and formal target layouts open

Generated build artifacts shall live under
`build/uquintus-<hw>/<target>/` for each selected hardware configuration and
concrete build target. Targets for the same hardware configuration shall share
the `build/uquintus-<hw>/` parent, with a separate child directory per target.

`<hw>` shall be the selected YAML configuration filename without its extension,
as defined in [build, Section 2](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets). For example, `rv32i_zifence.yml` produces
`uquintus-rv32i_zifence/`, while `rv32e-minimal.yml` produces
`uquintus-rv32e-minimal/`. `<target>` shall identify the concrete simulator or
implementation target, for example `verilator`. Where needed, an implementation
target name shall distinguish its platform within the same naming scheme.

Illustrative output paths are:

```text
build/uquintus-rv32i_zifence/verilator/
build/uquintus-rv32i_zifence/orfs_sky130hd/
build/uquintus-rv32i-fast/verilator/
```

Mapped synthesis uses `orfs_<platform>/synth-<top>-<timestamp>-<id>/`.
Implementation through timing repair uses `orfs_<platform>/impl-<top>-<timestamp>-<id>/`.
Post-placement and formal target names remain open. Netlists, reports, waveforms, software binaries and translated build inputs
shall be kept within the applicable output directory. Current simulation runs use
`build/uquintus-<hw>/verilator/<component>/<run>/`; `<run>` includes action,
test selection, seed and a unique run suffix. Runs retain metadata, logs,
results and requested traces/waveforms. Software builds use
`build/uquintus-<hw>/sw/<program>/`. The shared report uses `build/report/`,
and fetched dependency caches use `build/deps/`. The execution guides document
artifact filenames; repository-root `.gitignore` excludes generated `build/`
and local `.venv/` outputs.

The component flow uses Bender's file list for compilation sources and its
structured selected source tree for include directories. Both simulation and
lint shall receive the same declared header directories. Shared RTL headers
uqu_isa.vh/uqu_ctrl.vh live beside the core modules and are included, not
separately compiled. Run metadata records Verilog-header hashes alongside source
hashes so header-only changes remain identifiable.

### 6.1. Shared build report

**Status:** Initial artifact aggregation implemented; publication and future
flow adapters remain follow-ups

`make report` shall collect retained artifacts across hardware configurations
and flows into `build/report/`, alongside the per-configuration output roots.
This is the shared reporting exception to the per-configuration layout above.
Reporting shall consume existing results without launching design builds or
tests. Raw run artifacts remain authoritative; regenerating the report updates
the view from the artifacts still retained.

Use `index.html` as the primary landing page, with local static assets, category
pages, run details, configuration matrices and parameter comparison. Generate a
compact `index.md` summary and a versioned `data.json` dataset from the same
normalized records. Relative links and bundled supporting files shall allow the
whole directory to work locally and later on GitHub Pages without a runtime
service or frontend package dependencies. Publishing is a separate future step.

The reporter collects component/core regressions, lint, software builds,
synthesis/placement results and cycle-only RTL benchmarks. Formal verification
pages shall show absent evidence explicitly until corresponding producers exist.
Future producers shall integrate through a versioned per-run `report.json`
record with outcome, full hardware configuration, target/component/scenario,
timestamps, provenance, metrics with units, comparison context and artifact
references. The [reporting guide](../scripts/README.md) defines the initial
record contract and generated layout.

Keep different parameter snapshots under the same configuration name distinct.
The configurations view and parameter selectors shall include current core
presets and snapshots from core-level flows. Keep component-only experiments
accessible in their regression/run pages without adding them to that view.
Custom producers may declare their configuration scope explicitly. Explain run
outcomes separately from input-hash evidence in a shared HTML legend and badge
tooltips; changed inputs shall not be presented as a test failure.
Retain failures and history; latest-per-scenario aggregation shall not let a
passing partial suite or different seed hide an independent failure. Distinguish
not-reported, skipped, running, failed, error and passed outcomes. Collection
errors and inconsistent successful metadata shall remain visible. Legacy input
hashes and timestamps shall identify their limited scope; unrecorded revisions
or inputs shall remain unknown rather than be attributed to the workspace HEAD.

Quantitative comparisons shall retain units and matching declared comparison
contexts. PPA context shall identify platform/library/corner, constraints, stage
and tools; benchmark context shall identify workload/input, compiler/flags and
measurement conditions. Missing context shall prevent automatic comparison
plots. Test wall time and incidental ELF cycle counts shall not become benchmark
claims. Formal results shall retain the property/assumption/tool/bound scope.
Frequency and minimum-period terminology shall follow the
[benchmarking and PPA measurement specification](uqu_spec.bench.md).

Only generated report directories shall be replaced, after successful rendering;
concurrent report writers shall serialize. Selected small logs/metadata/results
shall be bundled, while oversized raw traces, binaries and waveforms may stay in
their original run directories with an explicit omission label. Artifact
retention across CI jobs and deployment remain separate follow-ups.

## 7. Project directory layout proposal

**Status:** Overall layout proposed; `src/uquintus/`, `src/wrap/`, `src/adapt/`,
repository-root `config/`, `impl/asic/`, `verif/`, `verif/sim/<component>/`,
`verif/sim/core/`, `verif/sim/common/`, `verif/common/`, `verif/sw/`, and `docker/`
placement and `build/uquintus-<hw>/<target>/` output naming agreed

The following layout would separate reusable processor RTL, verification,
software, core configurations, and ASIC implementation setup. Root build files
would include `Makefile`, `Bender.yml`, and `Bender.lock`. The proposed tree is
organizational guidance, not a list of files already present or implemented:

```text
src/
  uquintus/         # Common pipeline, execution, CSR, and register-file logic
  wrap/             # Protocol-specific processor top levels
  adapt/            # Reusable bus protocol converters
verif/
  sim/              # Component and full-core simulation tests
    common/         # Shared Make helper, simulation utilities, and HDL wrappers
      component_runner.py # Make entry point; Bender sources/include paths and run metadata
      hw_config.py        # Shared configuration validation and header generation
      rv32_arithmetic.py  # Mathematical ALU and MUL/DIV reference models
      ex_model.py         # EX token and parent-pipeline scoreboard model
      lsu_model.py        # Byte memory/native access expectations for LSU/MEM
      mem_model.py        # MEM stage/parent fixture token and result model
      csregfile_model.py  # Architectural CSR words/events shared by CSR and WB
      wb_model.py         # WB commitment and CSR/GPR reference state
    branch/         # Branch targets/conditions/alignment and decoder-fed fixture
    hazard/         # Shared DE/EX hazards, forwarding and optional DE retention
    pipeline_ctrl/  # Stage movement, age barriers, interrupts and fence protocol
    pipeline_ctrl_parent/ # Real parent slots, controller, MEM/LSU and WB/CSR
    decode/         # Native encoding/operand/control tests; ISA oracle in common/
    de/             # Decode-stage control, runtime faults and coupled XIF issue
    de_pipeline/    # Parent IF/DE + DE/EX, real GPRs and shared hazard integration
    gpregfile/      # General-purpose register-file tests
    csregfile/      # Decoded CSR state, access, counters, and event tests
    arith/          # Shared extended arithmetic tests
    muldiv/         # Native MUL/DIV tests and local arithmetic wrapper
    alu/            # Base integer ALU tests and external arithmetic fixture
    exec_arith/     # ALU/MUL/DIV sharing a parent-owned arithmetic instance
    ex/             # EX execution/control component tests
    ex_pipeline/    # EX with parent-owned DE/EX and EX/MEM register fixture
    lsu/            # Native OBI LSU tests
    mem/            # MEM routing, transaction, fault, and flush tests
    mem_pipeline/   # MEM with parent-owned EX/MEM, MEM/WB, and PMP fixture
    wb/             # WB commitment, fault, CSR, and retirement tests
    wb_pipeline/    # WB with parent-owned MEM/WB and sibling GPR storage
    pmp/            # Concurrent IF/MEM PMP checks and bytewise reference
    core/           # Core + SV RVFI wrapper/writer, native memory agents and oracle
  formal/           # Formal harnesses, properties, and riscv-formal integration
  common/           # Shared RVFI collector; utilities for simulation/formal reuse
  sw/               # Bare-metal programs and software execution tests
  perfsim/          # ETISS/CorePerfDSL models, runners and checks
config/
  *.yml             # Shared complete core configurations
  sim/              # Component manifests and simulation-target configuration
impl/
  asic/
    README.md       # Flow selection, environment contract and artifacts
    targets.yml     # Shared top/source/parameter selection
    orfs/
      common/       # ORFS runner and Yosys/OpenROAD hooks
      explore/      # Reusable sweeps and controlled timing comparisons
      platforms/
        sky130hd/   # Project settings for the external ORFS platform
        ihp-sg13g2/ # Project settings for the external ORFS platform
  fpga/             # Possible future FPGA implementation setup
scripts/            # Configuration translation and tool integration helpers
docker/             # Dockerfiles and optional Docker Compose definitions
docs/
  uqu_spec.md            # Overview, principles, scope, and milestones
  uqu_spec.arch.md       # ISA and microarchitecture
  uqu_spec.interfaces.md # Core integration interfaces
  uqu_spec.verif.md      # Verification and observability
  uqu_spec.build.md      # Build and project layout
  uqu_spec.style.md      # RTL coding and handshake conventions
  uqu_spec.perfsim.md    # Performance-model contract and qualification
  uqu_guide.perfsim.md   # Performance exploration, diagnostics and use cases
  uqu_guide.impl.md      # Implementation, benchmarking and timing diagnosis
build/              # uquintus-<hw>/<target>/ generated output directories
```

Verification collateral shall use `verif/`, including testbenches, monitors,
reference models, formal harnesses, properties, and supporting utilities.
Bare-metal verification programs and software execution tests shall live in
`verif/sw/`. Component simulation tests shall use `verif/sim/<component>/`,
full-core tests `verif/sim/core/`, and simulation-specific shared helpers,
agents, models, and wrappers `verif/sim/common/`. Utilities shared across
simulation and formal verification may use `verif/common/`, following the
[testbench organization](uqu_spec.verif.md#23-testbench-organization).
The `formal/` subdivision shown above remains proposed.
Dockerfiles and any Docker Compose definitions shall use `docker/`.
ASIC implementation setup shall use `impl/asic/`; `impl/fpga/` is reserved as a
possible later sibling and shall not imply a requirement to implement FPGA
support now.
ASIC flows shall use `impl/asic/<flow>/`, with flow-specific platform adapters
under `platforms/`. Only ORFS is currently implemented. Add shared technology
collateral when actual reuse across flows requires it; no alternative flow or
empty placeholder directory is required initially.

The repository-root `config/` directory shall hold shared core configurations
and simulation-target configuration. `config/sim/<component>.yml` shall describe
each component's top module, Bender target, test module, applicable parameters,
and available tests for the shared component runner. Bender shall retain HDL
source/dependency selection. Complete core presets currently live directly in `config/`; simulation-target settings shall stay in `config/` even though their testbench sources live under `verif/`.

Common processor RTL shall live in `src/uquintus/`, protocol-specific
processor wrappers in `src/wrap/`, and reusable protocol adapters in
`src/adapt/`. Pipeline modules shall share `src/uquintus/` without
requiring a directory per stage. Module and file naming shall follow the
[RTL style guide](uqu_spec.style.md#3-identifiers-and-symbols).
Technology-specific cell wrappers and mappings would live with the applicable ASIC setup, outside common
processor RTL.

Simulation and formal sources would remain separate Bender source groups while
sharing applicable verification utilities. Software programs in `verif/sw/` would be
inputs to execution tests, distinct from the testbench and verification models.
The `impl/asic/` directories would hold project-specific settings and references to
externally provisioned platforms, rather than copies of ORFS or the PDKs.

Generated artifacts shall use `build/uquintus-<hw>/<target>/` as defined in
[build, Section 6](uqu_spec.build.md#6-build-output-naming), which records the implemented
simulation/software/synthesis/placement/report layouts and ignore rules.
Post-placement and formal artifact layouts remain to be defined with those flows.
`make clean` shall remove the generated `build/` directory.
Directories could be added as their contents are implemented.

## 8. Build follow-ups

Strict hardware YAML validation, canonical selector encodings/header generation,
complete presets, Bender source groups and Make simulation/lint/software/report
targets are implemented. Extend those shared definitions when adding features.
The ORFS synthesis consumer reuses the shared schema and uses Slang for imported
SystemVerilog while preserving owned Verilog RTL. Implement formal and full
post-placement consumers without creating separate hardware schemas.

Extend the recorded per-run tool/platform provenance into default tool/PDK
lock policies and broader supported-configuration matrices. ORFS discovery and
synthesis constraints are defined above; Docker images/Compose services,
post-placement/formal target names and artifacts, and CI wiring remain open. Additional
simulator backends still require integration; Verilator is the current backend.
Integration-supplied SDC selection and separate internal/interface critical-path
summaries are implemented under Section 4.1. Qualify concrete SRAM/XIF
integrations separately.
No container build or dependency installation shall become implicit in Make.

The directory tree retains its explicit proposed subdivisions. Add directories
and files as their contents are implemented; the tree is not a claim that the
infrastructure already exists. Quantitative PPA targets and representative
software workloads remain future project decisions.

## 9. Decision record

Decision IDs are shared across the [specification set](uqu_spec.md#document-index).
Superseded and deferred rows preserve history; current topic requirements and
later decisions determine the active contract.

| ID | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-121 | Use Bender for HDL source/dependency management and GNU Make as the build entry point, with tool-specific scripts for integration. | Centralize HDL sources and dependency revisions while keeping verification and ASIC tool invocation explicit. | Implemented Bender/Make simulation, lint, software, reporting and ORFS synthesis; formal/physical integration remains open |
| D-122 | Define each supported core configuration once in a shared file, consumed across flows; distinguish simulation, formal, and synthesis/implementation targets from the selected hardware configuration. | Reuse consistent hardware parameters while allowing flow-specific sources, top levels, tests, constraints, and tool settings. | Implemented strict shared YAML, complete presets and simulation/synthesis consumers; formal/physical consumers remain open |
| D-123 | Select the simulation backend through the GNU Make argument `SIM`, defaulting to `verilator`, independently of core configuration and simulation target. | Support alternative simulator integrations while retaining a defined default and consistent hardware configuration. | Agreed; additional supported backends and integration details TBD |
| D-124 | Use OpenROAD-flow-scripts as the default ASIC build backbone, including its Yosys synthesis stage; invoke its stages through the project GNU Make interface with Bender-supplied sources. | Reuse a coordinated synthesis-to-layout flow and its platform configurations while keeping uquintus-specific setup in this repository. | Mapped synthesis implemented under D-306; full physical flow and broader qualification open |
| D-125 | Keep the project Makefile independent of container execution and toolchain/PDK provisioning; discover externally provisioned ORFS through `ORFS_ROOT` or an environment-supplied `orfs` launcher on `PATH`, with dependency provisioning handled separately in containers. | Give the design build a consistent environment contract across container and compatible local environments. | External discovery implemented; Section 5; container setup and physical provisioning remain open |
| D-126 | Use YAML for the shared core hardware configuration files, validated and translated into tool inputs by project helpers. | Keep configurations readable and reusable across simulation, formal, synthesis, and CI, separately from Bender source/dependency metadata. | Implemented validation/translation in verif/sim/common/hw_config.py and root config/ layout |
| D-127 | Place ASIC implementation setup under `impl/asic/`, allowing a future `impl/fpga/` sibling. | Group implementation targets under a shared directory while retaining separate technology-specific flows. | Agreed; FPGA implementation remains a future option |
| D-128 | Use `verif/` for verification collateral and place bare-metal verification programs and software execution tests under `verif/sw/`. | Group hardware verification and its software workloads in one project area. | Implemented simulation/common/software layout; formal subdivision remains proposed |
| D-129 | Use `docker/` for dependency-provisioning Dockerfiles and optional Docker Compose definitions. | Make the selected container tooling explicit while retaining a container-independent project Makefile. | Agreed; exact images, services, and versions TBD |
| D-130 | Keep shared core and simulation-target configuration under the repository-root `config/` directory. | Retain a central configuration location across build flows while keeping verification sources under `verif/`. | Implemented config/<hw>.yml, config/sim/<component>.yml and config/selectors.json |
| D-131 | Use `src/uquintus/core/` for common processor RTL, `src/uquintus/wrap/` for processor wrappers, and `src/uquintus/adapt/` for reusable protocol adapters. | Group uquintus source code under a project namespace with short functional subdirectory names. | Superseded by D-258 |
| D-132 | Place generated artifacts under `build/uquintus-<hw>-<target>/`, using the shared hardware-configuration name and concrete simulator or implementation target. | Keep build outputs separate with a simple two-field directory name. | Superseded by D-133 |
| D-133 | Use `build/uquintus-<hw>/<target>/`, grouping concrete target output directories under the selected hardware configuration. | Keep related hardware builds together while isolating target artifacts. | Implemented simulation/software/synthesis/report layouts in Section 6; full physical/formal layout open |
| D-134 | Derive `<hw>` from the YAML filename stem; require complete explicit hardware parameter values and provide predefined configurations for users to adapt. | Support descriptive and purpose-oriented profile names without hidden parameter inheritance or dependence on RTL defaults. | Implemented explicit schema, complete presets and filename-stem selection; extend catalog with supported features |
| D-137 | Use readable YAML labels for enumerated hardware selectors and translate validated labels into integer RTL parameter values; initially use predictor labels `none`/`static_not_taken` and register-file labels `ff`/`latch`. | Keep hardware configurations readable while providing consistent numeric tool inputs across build flows. | Implemented canonical encodings in config/selectors.json and shared configuration translator; Section 2 |
| D-138 | Generate guarded Verilog-2005 `.vh` macro headers for shared selector encodings from one canonical definition also used by YAML configuration translation. | Keep synthesis-compatible RTL constants and build-tool mappings consistent without SystemVerilog packages in the synthesizable design. | Implemented canonical JSON catalog and guarded-header generator in verif/sim/common/hw_config.py; Section 2 |
| D-258 | Place common processor RTL directly in `src/uquintus/`, with `src/wrap/` for protocol-specific top levels and `src/adapt/` for reusable protocol adapters as sibling directories. | Keep common core files together without an extra directory level. | Agreed; replaces D-131 |
| D-295 | Generate a shared static report under build/report with an HTML landing page, category/run pages, configuration comparison, Markdown summary and versioned JSON data; collect existing flow artifacts and accept a common per-run record for future flows. | Visualize evidence across configurations without losing failures, provenance or comparison conditions, and produce a portable artifact suitable for later website publication. | Initial aggregation implemented; Section 6.1; synthesis producer implemented under D-306; benchmark producer under D-313; formal producer, CI retention and deployment remain follow-ups |
| D-303 | Fetch commit-pinned CVFPU/FPnew through Bender with exact transitive revisions in Bender.lock, disable upstream Git submodule checkout in project configuration, and opt imported HDL into component builds through a manifest flag. | Reuse upstream source/dependency metadata without adding repository submodules or compiling unused IP into native tests. | Implemented dependency/configuration preparation; Section 1.3; real execution adapter under architecture D-304; physical qualification remains open |
| D-306 | Implement external ORFS mapped synthesis for core/FPU targets using shared hardware YAML and Bender, Slang for imported SV, latch/mapping checks, preplacement STA and provenance-rich report records. | Qualify open-source ASIC frontend/mapping compatibility and expose measured cell area/timing without conflating mapped synthesis with physical closure. | Implemented; Section 4 and impl/asic/README.md; six default core/FPU runs on SKY130 HD and IHP SG13G2; full physical flow and broader parameter matrices open |
| D-309 | Organize ASIC integrations under impl/asic/<flow>/ with flow-owned scripts, platform adapters and investigations; keep targets.yml shared at the ASIC root and select the backend through ASIC_FLOW, defaulting to orfs. | Allow future ASIC flows without treating ORFS-specific files as technology-independent collateral. | Implemented; Sections 2, 4 and 7; unsupported flow selections fail explicitly |
| D-310 | Keep ABC wire-load estimates enabled in the qualified ORFS speed script, remove synthesis buffers before placement, and use timing-driven physical buffering. Record the resolved policy and script hash; retain estimates disabled for explicit experiments. | Preserve the measured baseline's setup advantage while allowing OpenROAD to replace synthesis buffering using placement parasitics. | Implemented policy and provenance; Section 4 and ASIC guide; full physical flow remains open |
| D-311 | Keep the generic core SDC as a standalone evaluation profile; let concrete integrations supply constraints and the SoC own final timing. Defer detailed SRAM/XIF budgets until integration and report internal/interface paths separately. | Preserve useful standalone PPA evidence without assuming an unknown memory or coprocessor environment or counting external delay twice during SoC timing. | Implemented; Section 4.1; concrete SRAM/XIF integration profiles remain deferred |
| D-312 | Add make impl through ORFS placement and post-placement timing repair, reusing RTL/configuration/provenance and optional supplied SDC. Retain physical cell/geometry evidence and scoped critical paths; require legality, setup/hold and electrical checks to pass. | Establish a reproducible current-core physical baseline before CTS/routing or RTL timing optimization. | Implemented; Section 4 and ASIC guide; initial qualification on IHP; CTS and routing remain open |

The shipped `rv32im` and `rv32imc_bimodal_idata` baselines select `dadda_mac`; `rv32im_iterative` retains the explicit shared iterative baseline. `rv32im_dadda` and `rv32imc_bimodal_idata_dadda_div1` select EX1-only multiplication. Their `dadda_mac` counterparts preserve all other parameters for comparisons. Frontend bypass presets formerly named `parallel_div1_*` are now `dadda_div1_*`; historical build artifacts retain their original names and source fingerprints.
