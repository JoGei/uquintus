# uquintus Build and Project Layout

**Status:** First specification draft finalized, 2026-10-20

Build/configuration contracts and project organization. A shared component
simulation/lint flow supports the register file, ALU, arithmetic datapath, native
multiply/divide, EX, MEM/LSU, WB, PMP checker, CSR register file, and shared-arithmetic/parent-register fixtures; full-core and ASIC flows remain to be implemented. See the
[shared simulation guide](../verif/sim/common/README.md).

[Specification index](uqu_spec.md) · [Architecture](uqu_spec.arch.md) · [Interfaces](uqu_spec.interfaces.md) · [Verification](uqu_spec.verif.md) · [Build](uqu_spec.build.md) · [Style](uqu_spec.style.md)

Agreed requirements remain binding. Explicit proposals retain their status, and
TBD items remain implementation or integration follow-ups. Finalizing this draft
does not imply that the documented hardware or build infrastructure exists.

## 1. Bender and GNU Make build structure

**Status:** Agreed; detailed targets and tool integration TBD

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
still to be defined.
Configuration schema, command/target names, directory layout, script
languages, exact tool versions, and technology-specific integration remain TBD.
The shared core-configuration and separate build-target requirements are
defined in [build, Section 2](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets).

For the selected tools' roles, see the
[Bender documentation](https://pulp-platform.github.io/bender/) and
[GNU Make manual](https://www.gnu.org/software/make/manual/html_node/Rule-Introduction.html).

## 2. Shared core configuration and separate build targets

**Status:** Agreed; YAML selected, schema and target details TBD

Each supported core configuration shall be defined once in a shared
YAML configuration file. Simulation, formal checking, synthesis, and CI shall
consume that definition for the selected hardware parameters. Tool-specific
parameter overrides and matching reference-model ISA settings shall be derived
from the shared definition rather than maintained independently for each flow.
The YAML schema and translation mechanism remain TBD. A project helper shall
validate the selected configuration and translate it into tool inputs. This
file shall describe core hardware parameters separately from Bender's source
and dependency manifest. Its parser shall be provided by the externally
provisioned build environment, consistent with [build, Section 5](uqu_spec.build.md#5-externally-provisioned-build-environment).

Enumerated hardware selectors shall use readable YAML labels. In particular,
`MUA_BRANCH_PREDICTOR` shall use `none` or `static_not_taken` for the currently
defined choices, and `MUA_REGFILE_IMPL` shall use `ff` or `latch`. Their default
YAML selections shall be `none` and `ff`, respectively. `MUA_MUL` shall use
`parallel`, `parallel+stages+2`, or `iterative` as defined in [architecture, Section 3](uqu_spec.arch.md#3-classical-five-stage-pipeline).
`MUA_DIV` shall use `iterative`. Both default YAML selections shall be
`iterative`, sharing the iterative arithmetic chain. The separate integer setting
`MUA_MULDIV_ITERUNROLL` shall use `1`, `2`, `4`, `8`, `16`, or `32`, defaulting
to `8`, and shall govern every selected iterative operation. Selector labels
containing the former `+unroll+<factor>` suffix shall fail configuration
validation.
The validated numeric `MUA_MULDIV_ITERUNROLL` factor shall be passed to RTL
unchanged.
Configuration helpers
shall validate the labels and translate them into integer RTL parameter values,
using a consistent mapping across simulation, formal, and synthesis flows.
Unknown or unsupported labels shall produce a clear configuration error.
The register-file encodings are `ff = 0` and `latch = 1`. Multiplier encodings
are `parallel = 0`, `parallel+stages+2 = 1`, and `iterative = 2`; divider
`iterative = 0`. Predictor encodings remain TBD. A single canonical selector
definition shall supply both the YAML-label translation and the RTL encoding constants.
The build shall generate guarded Verilog `.vh` macro headers from this
definition, following the
[shared-constant conventions](uqu_spec.style.md#3-identifiers-and-symbols).
Configuration helpers shall obtain their label-to-integer mappings from the
same definition rather than maintain an
independent copy. The register-file and MUL/DIV catalog is `config/selectors.json`,
with the shared generator in `verif/sim/common/hw_config.py`; predictor encoding
remains a follow-up. Complete initial presets are `config/rv32i.yml`,
`config/rv32im.yml`, and `config/rv32im_iterative.yml`. The baseline keeps M disabled; both M-enabled presets currently select the
shared iterative MUL/DIV chain with unroll factor eight.
Generated headers shall use the applicable build output directory
in [build, Section 6](uqu_spec.build.md#6-build-output-naming). Selector definitions shall not supply implicit hardware
configuration defaults: each configuration shall still set all parameters.

Core configuration files and simulation-target configuration shall remain under
the repository-root `config/` directory. Simulation-target configuration shall
not move into `verif/sim/`. The exact subdivision and configuration catalog
within `config/` remain to be defined.

The hardware configuration name `<hw>` shall be the selected YAML filename's
basename without its extension. For example, `rv32i_zifence.yml` shall select
`<hw> = rv32i_zifence`, and `rv32i-fast.yml` shall select `<hw> = rv32i-fast`.
Configuration names shall identify their profiles uniquely. Names may describe
ISA features or a preset's intended use; hardware settings shall be read from
the file rather than inferred from its name.

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
points for users to copy and adapt. Illustrative profile names include
`rv32i-fast` and `rv32e-minimal`; their exact parameter values and the initial
preset catalog remain TBD. Adapted configurations shall satisfy the same
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

For example, `make sim CONFIG=rv32i` and `make synth CONFIG=rv32i` could select
different build flows using the same core parameter definition. These command
and configuration names are illustrative; exact names, configuration-file
organization, and target/platform selection syntax remain TBD.

## 3. Selectable simulation backend

**Status:** Agreed; additional backends and detailed integration TBD

Simulation builds shall select their simulator backend through the GNU Make
argument `SIM`, defaulting to `verilator`. This selection shall be independent
of the shared core configuration and the simulation target/testbench. For
example, `make sim CONFIG=rv32i` shall use the default backend, equivalent to
`make sim CONFIG=rv32i SIM=verilator`; the surrounding command/configuration
names remain illustrative as noted in [build, Section 2](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets).

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
the simulation guide; additional backend and full-core integration remain TBD.

## 4. OpenROAD-flow-scripts ASIC backbone

**Status:** Agreed; detailed integration and versions TBD

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
`DESIGN_NAME`, `PLATFORM`, and `SDC_FILE` settings. The method for propagating
core parameter values remains TBD and shall preserve the shared-configuration
contract in [build, Section 2](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets).

Design-specific ORFS configuration and constraints shall remain in the uquintus
repository under `impl/asic/`, allowing a future `impl/fpga/` alongside it.
The integration shall use ORFS's external-design support and
documented configuration/hooks; the baseline shall not require a fork or copy
of its implementation scripts. Simulation and formal checking shall continue
to use their separate targets and tool integrations.

The detailed ORFS invocation, any future flow-selection argument, ORFS/tool/PDK
revisions, platform variants, and constraints remain TBD. Build-environment
provisioning and discovery shall follow [build, Section 5](uqu_spec.build.md#5-externally-provisioned-build-environment). Additional implementation
flows may be added later;
no alternative flow is required initially. Target platform availability shall
not by itself establish uquintus timing, area, or physical-verification results.

See the [ORFS overview and external-design instructions](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts),
[design configuration guide](https://openroad-flow-scripts.readthedocs.io/en/latest/user/AddingNewDesign.html),
and [flow stage definitions](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/blob/master/flow/Makefile).

## 5. Externally provisioned build environment

**Status:** Agreed; container details and launcher interface TBD

The project Makefile shall expect an already provisioned build environment.
It shall locate ORFS through an explicit `ORFS_ROOT` environment variable or an
`orfs` launcher available on `PATH`. `ORFS_ROOT` shall identify the installation
or checkout containing `flow/Makefile` and take precedence when supplied. The
`PATH` launcher shall be supplied by the environment and adapt invocation to
the installed ORFS flow; its exact command-line contract remains TBD.

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

**Status:** Agreed; target name catalog and internal artifact layout TBD

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
build/uquintus-rv32i_zifence/orfs_sky130/
build/uquintus-rv32i-fast/verilator/
```

The ORFS target name is illustrative; the exact supported target catalog remains
TBD. Netlists, reports, waveforms, software binaries, and translated build inputs
shall be kept within the applicable output directory. Tools may use internal
subdirectories as needed; this convention defines the project build root for
the selected pair. Exact internal artifact filenames and ignore rules remain
TBD.

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
      component_runner.py # Component simulation/lint entry point used by Make
      hw_config.py        # Shared configuration validation and header generation
      rv32_arithmetic.py  # Mathematical ALU and MUL/DIV reference models
      ex_model.py         # EX token and parent-pipeline scoreboard model
      lsu_model.py        # Byte memory/native access expectations for LSU/MEM
      mem_model.py        # MEM stage/parent fixture token and result model
      csregfile_model.py  # Architectural CSR words/events shared by CSR and WB
      wb_model.py         # WB commitment and CSR/GPR reference state
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
    core/           # Full-core simulation tests
  formal/           # Formal harnesses, properties, and riscv-formal integration
  common/           # Utilities shared across simulation and formal verification
  sw/               # Bare-metal programs and software execution tests
config/
  cores/            # Shared YAML core configurations
  sim/              # Component manifests and simulation-target configuration
impl/
  asic/
    common/         # Shared uquintus ORFS integration settings
    sky130/         # SKY130 target configuration and constraints
    ihp_sg13g2/     # IHP target configuration and constraints
  fpga/             # Possible future FPGA implementation setup
scripts/            # Configuration translation and tool integration helpers
docker/             # Dockerfiles and optional Docker Compose definitions
doc/
  uqu_spec.md            # Overview, principles, scope, and milestones
  uqu_spec.arch.md       # ISA and microarchitecture
  uqu_spec.interfaces.md # Core integration interfaces
  uqu_spec.verif.md      # Verification and observability
  uqu_spec.build.md      # Build and project layout
  uqu_spec.style.md      # RTL coding and handshake conventions
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

The repository-root `config/` directory shall hold shared core configurations
and simulation-target configuration. `config/sim/<component>.yml` shall describe
each component's top module, Bender target, test module, applicable parameters,
and available tests for the shared component runner. Bender shall retain HDL
source/dependency selection. The `cores/` subdivision shown above remains
proposed; simulation-target settings shall stay in `config/` even though their
testbench sources live under `verif/`.

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
[build, Section 6](uqu_spec.build.md#6-build-output-naming). Exact internal artifact paths and ignore rules remain TBD.
`make clean` shall remove the generated `build/` directory.
Directories could be added as their contents are implemented.

## 8. Build follow-ups

Define the complete YAML schema, canonical selector catalog and numeric
encodings, preset catalog, configuration translator, Bender targets, Make
targets, and concrete simulator/formal/ORFS invocations. Resolve exact source
frontends for imported SystemVerilog without changing project-owned RTL rules.

Pin tool/IP/PDK revisions, platform/library variants, operating corners,
constraints, and supported backends. Document the externally supplied ORFS
launcher contract, environment variables, Docker images and optional Compose
services, target naming, generated artifacts, ignore rules, and CI wiring.
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
| D-121 | Use Bender for HDL source/dependency management and GNU Make as the build entry point, with tool-specific scripts for integration. | Centralize HDL sources and dependency revisions while keeping verification and ASIC tool invocation explicit. | Agreed; YAML selected by D-126; detailed targets and tool integration remain follow-ups |
| D-122 | Define each supported core configuration once in a shared file, consumed across flows; distinguish simulation, formal, and synthesis/implementation targets from the selected hardware configuration. | Reuse consistent hardware parameters while allowing flow-specific sources, top levels, tests, constraints, and tool settings. | Agreed; YAML and explicit configuration requirements defined by D-126 and D-134; schema and targets remain follow-ups |
| D-123 | Select the simulation backend through the GNU Make argument `SIM`, defaulting to `verilator`, independently of core configuration and simulation target. | Support alternative simulator integrations while retaining a defined default and consistent hardware configuration. | Agreed; additional supported backends and integration details TBD |
| D-124 | Use OpenROAD-flow-scripts as the default ASIC build backbone, including its Yosys synthesis stage; invoke its stages through the project GNU Make interface with Bender-supplied sources. | Reuse a coordinated synthesis-to-layout flow and its platform configurations while keeping uquintus-specific setup in this repository. | Agreed; detailed integration, environment, and revisions TBD |
| D-125 | Keep the project Makefile independent of container execution and toolchain/PDK provisioning; discover externally provisioned ORFS through `ORFS_ROOT` or an environment-supplied `orfs` launcher on `PATH`, with dependency provisioning handled separately in containers. | Give the design build a consistent environment contract across container and compatible local environments. | Agreed; exact launcher interface, container setup, and full environment contract TBD |
| D-126 | Use YAML for the shared core hardware configuration files, validated and translated into tool inputs by project helpers. | Keep configurations readable and reusable across simulation, formal, synthesis, and CI, separately from Bender source/dependency metadata. | Agreed; schema and file layout TBD |
| D-127 | Place ASIC implementation setup under `impl/asic/`, allowing a future `impl/fpga/` sibling. | Group implementation targets under a shared directory while retaining separate technology-specific flows. | Agreed; FPGA implementation remains a future option |
| D-128 | Use `verif/` for verification collateral and place bare-metal verification programs and software execution tests under `verif/sw/`. | Group hardware verification and its software workloads in one project area. | Agreed; other verification subdirectories remain proposed |
| D-129 | Use `docker/` for dependency-provisioning Dockerfiles and optional Docker Compose definitions. | Make the selected container tooling explicit while retaining a container-independent project Makefile. | Agreed; exact images, services, and versions TBD |
| D-130 | Keep shared core and simulation-target configuration under the repository-root `config/` directory. | Retain a central configuration location across build flows while keeping verification sources under `verif/`. | Agreed; internal configuration-directory subdivision and filenames TBD |
| D-131 | Use `src/uquintus/core/` for common processor RTL, `src/uquintus/wrap/` for processor wrappers, and `src/uquintus/adapt/` for reusable protocol adapters. | Group uquintus source code under a project namespace with short functional subdirectory names. | Superseded by D-258 |
| D-132 | Place generated artifacts under `build/uquintus-<hw>-<target>/`, using the shared hardware-configuration name and concrete simulator or implementation target. | Keep build outputs separate with a simple two-field directory name. | Superseded by D-133 |
| D-133 | Use `build/uquintus-<hw>/<target>/`, grouping concrete target output directories under the selected hardware configuration. | Keep related hardware builds together while isolating target artifacts. | Agreed; target catalog and internal artifact layout TBD |
| D-134 | Derive `<hw>` from the YAML filename stem; require complete explicit hardware parameter values and provide predefined configurations for users to adapt. | Support descriptive and purpose-oriented profile names without hidden parameter inheritance or dependence on RTL defaults. | Agreed; schema, preset values, and catalog TBD |
| D-137 | Use readable YAML labels for enumerated hardware selectors and translate validated labels into integer RTL parameter values; initially use predictor labels `none`/`static_not_taken` and register-file labels `ff`/`latch`. | Keep hardware configurations readable while providing consistent numeric tool inputs across build flows. | Agreed; exact integer encodings TBD, declaration mechanism defined by D-138 |
| D-138 | Generate guarded Verilog-2005 `.vh` macro headers for shared selector encodings from one canonical definition also used by YAML configuration translation. | Keep synthesis-compatible RTL constants and build-tool mappings consistent without SystemVerilog packages in the synthesizable design. | Agreed; catalog format, numeric values, and generator details TBD |
| D-258 | Place common processor RTL directly in `src/uquintus/`, with `src/wrap/` for protocol-specific top levels and `src/adapt/` for reusable protocol adapters as sibling directories. | Keep common core files together without an extra directory level. | Agreed; replaces D-131 |
