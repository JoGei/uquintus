# uquintus Verification Specification

**Status:** First specification draft finalized, 2026-10-20

Observability and verification requirements for the agreed processor behavior.

[Specification index](uqu_spec.md) · [Architecture](uqu_spec.arch.md) · [Interfaces](uqu_spec.interfaces.md) · [Verification](uqu_spec.verif.md) · [Build](uqu_spec.build.md) · [Style](uqu_spec.style.md)

Agreed requirements remain binding. Explicit proposals retain their status, and
TBD items remain implementation or integration follow-ups. Finalizing this draft
does not imply that the documented hardware or build infrastructure exists.

## 1. Instruction identity and architectural trace

**Status:** Agreed

Execution visibility shall include cycle-by-cycle waveforms and an architectural
instruction trace, allowing software behavior to be correlated with all five
pipeline stages.

Each instruction shall carry its original 32-bit instruction PC through IF,
decode (`de_`), EX, MEM, and WB. Every stage shall expose instruction validity
alongside that PC so waveforms distinguish an instruction from a bubble or stale
payload. In fetch, the instruction PC shall be distinguished from the aligned
memory-request address, including when a C-enabled instruction spans two words.

The PC shall travel with its instruction on an accepted stage transfer and
remain stable while that instruction is held by a stall. A flush shall invalidate
the discarded instruction's metadata; it need not zero the stored PC payload.
Metadata shall remain associated with the correct native or custom operation
through variable-latency execution and memory waits.

The architectural instruction trace shall report retired instructions and
synchronous traps in program order, once per architectural completion event.
Each event shall identify the instruction PC and whether it retired or trapped,
with relevant register, memory, and trap information. A faulting instruction
shall not also be reported as successfully retired. Per-stage waveforms shall
retain visibility into stalled and subsequently discarded instructions.

Pipeline visibility shall use the instruction PC and validity without an
additional per-instruction sequence tag. This does not remove operation or
transaction identifiers required by interfaces such as CV-X-IF. Trace encoding
and other trace metadata remain TBD.

Trace collection, formatting, and file writing shall be implemented in
SystemVerilog verification monitors, not in the synthesizable processor RTL.
The plain-Verilog RTL shall expose the instruction and state signals needed by
these monitors; the exact connection method remains TBD.

**Verification interface:**
[RVFI](https://yosyshq.readthedocs.io/projects/riscv-formal/en/latest/rvfi.html)
shall be the observation contract for instruction tracing and `riscv-formal`
checking.
RVVI is not a required dependency. SystemVerilog verification instrumentation
shall provide the trace records from the core's exposed instruction/state
signals; formatting and file writing shall remain in simulation monitors.

The initial native profile and simulation connections are defined in Section 1.1.
The pinned formal-tool revision, formal core binding and checker integration
remain TBD. CSR, floating-point, custom-instruction, and memory-side-effect
coverage shall be specified explicitly rather than assumed from the base RVFI
interface. Instrumentation used for formal checking must be compatible with the
chosen formal tools; simulation file-writing code is separate from that logic.

An RVFI event-order counter may be generated in verification instrumentation
without adding sequence tags to the pipeline. Formal verification requirements
are defined in [verification, Section 2](uqu_spec.verif.md#2-simulation-and-formal-verification); Spike is the simulation reference model.

### 1.1. Initial native RVFI testbed

`verif/common/uqu_rvfi.sv` shall provide a passive, single-channel RV32 collector
using actual accepted core transfers and consumed operands. The
[native RVFI profile](../verif/common/README.md) defines the implemented fields
and limitations. `verif/sim/core/uqu_core_tb.sv` shall isolate simulation
hierarchy references and expose RVFI without changing synthesizable core ports.
The separate `uqu_rvfi_trace.sv` writer shall emit JSONL instruction, interrupt
and reset records in the isolated run directory.

Instruction order shall count successful retirement and accepted synchronous
traps, with no records for killed instructions or bubbles. IRQ entry shall not
invent an instruction; the first handler instruction shall carry `rvfi_intr`.
Verification metadata shall preserve consumed source values through holds and
flushes. It shall not reconstruct them from a shadow register file that could
hide operand-selection errors. Raw load responses shall remain distinguishable
from the extended GPR result. The initial memory profile shall use aligned
addresses/lane masks and the RVFI memory-fault fields.

Simulation shall compare RVFI with independent execution expectations and check
the saved trace against sampled records. Reset epochs shall distinguish repeated
order values after reset. The collector shall contain no simulation I/O or
environment constraints; simulation formatting/file writing stays in its own
SV module. Collector tool-compatibility checks shall not be described as core
formal proofs. Per-CSR channels, formal core signal binding, RVFI_BUS, complete
instruction proofs and the pinned Spike adapter remain follow-ups.

## 2. Simulation and formal verification

**Status:** Agreed; detailed coverage and tool configuration TBD

Verification shall include both simulation and formal checks with
[`riscv-formal`](https://github.com/YosysHQ/riscv-formal), using the RVFI
observation contract defined in [verification, Section 1](uqu_spec.verif.md#1-instruction-identity-and-architectural-trace). The initial formal verification
scope shall be RV32I. Applicable instruction checks shall pass under documented
environment assumptions as part of verification acceptance for that scope.

Simulation verification shall compare standard-instruction retirement and trap
outcomes against an independent software RISC-V reference model, using the
observations defined in [verification, Section 1](uqu_spec.verif.md#1-instruction-identity-and-architectural-trace). The comparison shall cover applicable PC
transitions, register results, memory operations, CSR effects, and trap outcomes.
Comparison shall follow architectural events; a functional reference model is
not required to reproduce the core's pipeline cycles or memory latency.

The reference model shall use matching ISA and privilege settings, initial
architectural state, memory contents, and external inputs. The checker shall
define how interrupts, I/O, and cycle-dependent CSR reads are synchronized or
reconciled; timing-sensitive core behavior shall also receive appropriate
independent checks. Custom operations require an explicit behavioral model or
checking contract, with coverage recorded separately.

[Spike](https://github.com/riscv-software-src/riscv-isa-sim) shall be the
simulation reference model. The Spike revision and comparison adapter remain TBD;
the verification configuration shall pin the selected revision for reproducibility.

Starting with the first implementation milestone, simulation shall include
randomized memory timing in addition to directed tests and architectural
comparison. Tests shall independently vary request-grant delays and response
latency on the instruction and data OBI ports while preserving the agreed
protocol. They shall exercise error responses, redirects, and reset with
transactions pending, respecting the existing reset integration contract.
Randomized tests shall accept an explicit seed and report the seed used so
failures can be reproduced. Exact testbench structure and seed controls remain
verification implementation details.

Formal instrumentation and harnesses shall be compatible with the selected
formal tools. Trace formatting and file writing shall remain separate simulation
code. Project-owned synthesizable processor RTL shall remain plain Verilog;
imported IP and its dependencies may use SystemVerilog under the style-guide
exception, and verification collateral may use SystemVerilog.

The exact check set, core configuration matrix, solver and tool versions, proof
strategy and depth, simulation tests and reference-model integration, and coverage for
privileged state, optional extensions, custom operations, and memory protocols
remain TBD. Verification results shall state the checks, configurations, and
assumptions used so that the demonstrated scope is explicit.

### 2.1. Python simulation framework

**Status:** Agreed; shared runner and native full-core RVFI testbed implemented

The project-wide simulation testbench stack shall use cocotb for driving/observing
RTL and scheduling simulation activity, with pyuvm for testbench organization
at component, subsystem, and full-core levels. pyuvm
uses cocotb to communicate with the simulator and provides Python UVM components,
phases, sequences, drivers, monitors, and scoreboards. See the
[pyuvm documentation](https://github.com/pyuvm/pyuvm) and
[cocotb simulator support](https://docs.cocotb.org/en/stable/simulator_support.html).
Verilator shall remain the default simulator under the existing build policy;
the simulator is separate from the Python testbench framework.

Simple leaf-component tests shall also use the shared pyuvm test structure;
they may drive signals and check results directly using cocotb coroutines
within that structure. Small tests need not introduce separate agents,
sequences, monitors, or scoreboards unless those abstractions help their checks
or reuse. All levels shall support the independently selectable regressions
below. SystemVerilog UVM classes shall not be required in the simulator.

Existing SystemVerilog architectural trace/RVFI instrumentation and formal
checking shall retain their contracts in Section 1. Python environments may
consume those observations and coordinate checking; framework selection shall
not implicitly replace the agreed trace-monitor or formal boundaries.
The shared component environment pins Python dependencies in
`verif/requirements.txt` and uses the cocotb 1.9.2 Python runner through
the GNU Make helper `verif/sim/common/component_runner.py`, with explicit
cocotb entry points invoking pyuvm test phases. The runner API is experimental
and isolated in that shared helper. Component settings come from
`config/sim/<component>.yml`; configuration validation, DUT parameter selection,
and header generation are shared through `verif/sim/common/hw_config.py`.
See the [shared simulation guide](../verif/sim/common/README.md) for invocation
and manifests, and the [register-file](../verif/sim/gpregfile/README.md) and
[arithmetic](../verif/sim/arith/README.md) guides for test scope. The
[core guide](../verif/sim/core/README.md) describes native RVFI integration;
Spike/formal integration and other simulator backends remain open.

### 2.2. Independently selectable component regressions

**Status:** Agreed; layout defined in Section 2.3, exact suite catalog and command syntax open

Verification shall support self-checking regressions for individual meaningful
RTL components, independently of full-core software execution tests. Selecting
a component shall select its DUT top, applicable HDL dependencies, verification
harness, and tests without requiring compilation or execution of unrelated core
logic. Bender shall remain the HDL source/dependency authority; test wrappers
shall instantiate the actual component RTL rather than duplicate its logic.

Component targets shall be introduced alongside their RTL. Candidate boundaries
include the register file, ALU, decoder/decompressor, MUL/DIV units, fetch buffer,
hazard/forwarding logic, LSU/OBI interface, and CSR/PMP blocks, as those features
are implemented. This list shall guide test organization without prematurely
fixing module partitioning or requiring tests of every implementation detail.
Tests shall check specified behavior using independent expected results or
protocol/architectural invariants, rather than mirror internal implementation.

The flow shall support selecting a component, test or suite, hardware
configuration, simulator, and random seed. Component parameter values shall be
derived from the validated shared hardware configuration using only parameters
applicable to that DUT. A DUT-specific setup shall not silently change the
requested ISA or microarchitecture settings. Tests for unimplemented or disabled
features shall report their unsupported/skipped status explicitly, not count
as successful functional coverage.

Each component regression shall include directed normal/corner cases and
appropriate randomized stimulus. Stateful or handshaking components shall cover
applicable reset, stalls/backpressure, flush, result retention, and fault
behavior under their existing contracts. Combinational leaf tests need not
invent irrelevant pipeline or protocol scenarios. Full-core tests shall retain
Spike comparison; an isolated component shall use a suitable component model
or checker rather than require Spike for every unit test.

Compressed-instruction verification shall cover all three microarchitecture
strategies: `decompress/if`, `decompress/de` and `decode_compressed`. Leaf tests shall
exhaust 16-bit encoding space, including HINTs, unsupported encodings and RV32E
register restrictions. Integration fixtures shall place the real decompressor
on the selected side of actual IF/DE storage, rather than substitute a software
expansion before that boundary. Direct mode shall instantiate `uqu_decoder_c`
and check its normalized controls against equivalent base semantics.
Placement coverage shall include mixed 16-/32-bit tokens, stalls/backpressure,
permission, flush, earlier fetch-fault priority, original PC/bits/length and
PC+2 versus PC+4 links. See the
[placement fixture](../verif/sim/de_pipeline/README.md) and
[direct decoder tests](../verif/sim/decode_c/README.md). The
[production IF tests](../verif/sim/if/README.md) and
[IF/DE parent fixture](../verif/sim/if_pipeline/README.md) add real bus fetching,
word-boundary stitching, capacity reservation, accepted branch redirects and
discarded fault responses across all three compressed paths. Initial full-core
retirement/trap programs are described in Section 2.4; Spike/RVFI integration
remains separate work.

The [pipeline-controller tests](../verif/sim/pipeline_ctrl/README.md) shall
separately exercise stage movement, age-qualified fault barriers, older-safety
memory permission, live IRQ masks/priority, serial barriers, accepted redirects
and retained fence handshakes. The
[controller parent fixture](../verif/sim/pipeline_ctrl_parent/README.md) shall
connect real boundary storage, MEM/LSU and WB/CSR rather than substitute the
controller's own expected booleans for those units. Coverage shall include
late CSR/MEM faults, younger cancellation with older progress, CSR/MRET-driven
interrupt re-evaluation, a DE exception preempted at the EX-entry boundary and
fence acknowledgement while WB is held. Lint and flattened combinational-loop
checks shall ensure that WB ready and external interrupt entry have no
combinational dependence on WB result completion or its accepted redirect.

Runs shall report the selected component, test/suite, configuration, simulator
and tool versions, and seed needed to reproduce a failure. Simulation failures,
checker mismatches, and watchdog expiry shall cause a failed run and nonzero
regression exit status. Test watchdog limits shall be verification settings;
they shall not introduce architectural bus timeouts. Logs, machine-readable
pass/fail/skip results, and requested waveforms shall be retained under the
existing build-output root, isolated by DUT and run identity so regressions do
not overwrite one another's artifacts. Exact formats and subdirectory naming
remain implementation choices.

### 2.3. Testbench organization

**Status:** Test layout agreed; suite organization and runner integration open

Use component, subsystem, and full-core test levels, sharing protocol agents,
transactions, reference models, and checking utilities where applicable. For
example, an OBI memory agent could serve both an isolated LSU test and the
core-level environment. A component regression shall remain runnable without
executing the full-core regression. A small smoke suite and a larger multi-seed
regression are proposed; exact CI cadence, test matrix, coverage targets, and
runner integration remain open.

Keep verification sources under `verif/`, bare-metal programs under `verif/sw/`,
and simulation-target configuration under repository-root `config/`.
Simulation tests shall live under `verif/sim/<component>/`, grouped by the DUT
they verify; full-core tests shall use `verif/sim/core/`. For example:

```text
src/uquintus/
  uqu_alu.v
verif/
  sim/
    common/
      component_runner.py # Shared Make helper for component simulation/lint
      hw_config.py        # Shared hardware configuration and selector helpers
    alu/
      test_uqu_alu.py
    lsu/
      test_uqu_lsu.py
    core/
      test_uqu_core.py
  common/             # Utilities shared across simulation and formal checks
  sw/                 # Programs for core-level execution tests
```

Start a component's tests in a single `test_<module>.py` file. As needed, split
its environment into local files such as `env.py`, `sequences.py`, and `model.py`.
Move simulation-specific reusable agents, models, invocation helpers, and HDL
wrappers into `verif/sim/common/` when multiple environments share them. Utilities
shared with formal verification may live in `verif/common/`. A verification-only
HDL wrapper used by one component shall live alongside that component's tests;
use the RTL module directly as the DUT when no wrapper is needed.
The shared Make helper shall select each DUT's top module, Bender target,
applicable hardware parameters, test module, and tests from
`config/sim/<component>.yml`, without component-specific Python dispatch.
Testbenches shall receive resolved DUT parameters through `UQU_COMPONENT_PARAMS`.
Generated results shall remain under `build/uquintus-<hw>/<target>/`, isolated
by component and run as required in Section 2.2. This layout defines where
collateral belongs, not a requirement to create empty directories or tests for
unimplemented components.

GNU Make shall remain the project entry point; pytest or another outer
regression runner remains an implementation proposal rather than a selected
dependency.

### 2.4. Initial native full-core regression

[`verif/sim/core/`](../verif/sim/core/README.md) shall exercise the actual
`uqu_core`, using the common runner and `config/sim/core.yml`. Independent
instruction/data memory agents shall vary grant and response latency, check
request persistence and transaction limits, inject access faults and coordinate
discard of pending work on reset.

An initial instruction interpreter shall check original instruction identity,
retirement order, GPR results, memory effects, selected CSR state and precise
trap PC/cause/value. Programs shall exercise integer dependencies, branches,
subword accesses, serialization, synchronous faults, M/U transitions, IRQ drain
and vectored restart, configured M/C/PMP/fences, and reset during pending data
access. Configurations shall distinguish disabled behavior from enabled-feature
coverage. FPU and core XIF/debug adapters shall reject enabled elaboration
until implemented.

The interpreter consumes the RVFI testbed's retirement records and independently
checks operands, memory lanes, fault reporting and instruction sequence. It is
not the selected Spike reference. Spike comparison, CSR RVFI channels,
riscv-formal core binding/proofs, broader software coverage and configuration CI
remain required follow-ups. Passing the initial native programs shall not be reported as
completion of the first milestone's acceptance criteria.

## 3. Supported-configuration CI coverage

**Status:** CI requirement agreed; detailed build flow TBD

CI shall at least elaborate and synthesize every configuration explicitly marked
as supported by the project. The supported configuration set shall be documented
and checked as it expands across implementation milestones. Unsupported
configurations shall fail configuration validation as required in [architecture, Section 2](uqu_spec.arch.md#2-isa-and-microarchitecture-configuration-parameters).

The initial deeper simulation and formal verification scope shall follow
[verification, Section 2](uqu_spec.verif.md#2-simulation-and-formal-verification) and the default first milestone in [overview, Section 3](uqu_spec.md#3-first-implementation-milestone). Successful
elaboration and synthesis alone shall not imply full functional verification of
a configuration; the demonstrated verification scope shall remain explicit.

The detailed build flow shall be defined before implementing this CI requirement.
Bender and GNU Make are selected in [build, Section 1](uqu_spec.build.md#1-bender-and-gnu-make-build-structure). Configuration representation,
exact build targets, elaboration and synthesis tools and settings, tool/version
management, CI execution environment, and result artifacts remain TBD.

## 4. Verification follow-ups

Pin Spike, RVFI/riscv-formal, tools, solvers, and any library reference models.
Define the first supported configuration matrix, tests, formal assumptions and
proof scope/depth, coverage, seeds, CI environment, and result artifacts.
Extend the shared component runner and pinned cocotb/pyuvm environment in
Section 2.1 with additional component DUT manifests and independently runnable
suites under Section 2.2; define full-core integration and supported tool versions.
Implement the retirement/trap comparison and verification monitors, separating
simulation file I/O from formal-compatible observation logic.

Coverage for privilege, CSRs, memory side effects, Zfinx, custom instructions,
paired writeback, and debug must be explicit. Initial RV32I formal checking
shall not be presented as proof of those additional features. The agreed
randomized memory-latency and error/reset scenarios remain first-milestone
requirements rather than optional follow-ups.

## 5. Decision record

Decision IDs are shared across the [specification set](uqu_spec.md#document-index).
Superseded and deferred rows preserve history; current topic requirements and
later decisions determine the active contract.

| ID | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-006 | Support both cycle-by-cycle waveforms and an instruction trace. | Connect software execution and its visible effects to behavior in the five-stage pipeline. | Agreed |
| D-066 | Emit architectural instruction-trace events for retired instructions and synchronous traps, in program order. | Correlate architectural outcomes without treating discarded instructions as retired or faulting instructions as successful. | Agreed |
| D-067 | Carry each instruction's original PC and validity through all five stages and preserve their association during stalls, transfers, and flushes. | Make instruction flow identifiable in waveforms and correlate pipeline activity with architectural trace events. | Agreed |
| D-068 | Use PC and validity for pipeline visibility without an additional per-instruction sequence tag. | Keep observability metadata simple while retaining any identifiers required by functional interfaces. | Agreed |
| D-069 | Implement trace collection, formatting, and file writing in SystemVerilog verification monitors outside the synthesizable core. | Keep trace processing in verification code while retaining plain-Verilog processor RTL and visible instruction/state signals. | Agreed |
| D-070 | Use RVFI as the verification observation contract; do not require RVVI. | Connect tracing and open-source `riscv-formal` checks through a shared observation contract; define the required profile separately. | Agreed; profile TBD |
| D-071 | Require simulation and formal checks with `riscv-formal`, starting with RV32I. | Establish both execution-based testing and formal instruction checks as verification requirements, with explicit scope and assumptions. | Agreed; detailed coverage TBD |
| D-072 | Require simulation comparison of standard-instruction retirement and trap outcomes against an independent software RISC-V reference model. | Check architectural execution independently of pipeline implementation; configure the model and adapter separately. | Agreed; Spike selected in D-073 |
| D-073 | Use Spike as the simulation reference model. | Provide an independent executable ISA reference for architectural comparison. | Agreed; pinned revision and adapter TBD |
| D-120 | Require CI to elaborate and synthesize every explicitly supported configuration; define the build flow before implementing this requirement. | Check supported configurations as the design grows while keeping deeper functional-verification coverage explicit. | Agreed; build tools selected by D-121, detailed flow and CI implementation TBD |
| D-218 | Require randomized OBI grant/response timing tests from the first milestone, alongside directed tests and Spike comparison; exercise errors, redirects, and reset with pending transactions, and accept/report explicit random seeds. | Exercise variable-latency memory interactions and make randomized failures reproducible. | Agreed; testbench implementation deferred |
| D-254 | Propose cocotb for Python-to-simulator interaction and pyuvm for reusable verification environments, retaining Verilator as the default simulator and the existing SV trace/RVFI and formal contracts. | Support Python verification with a reusable UVM structure while preserving the existing build and observation boundaries. | Proposal finalized by D-256; runner and versions remain TBD |
| D-255 | Support independently selectable, self-checking component regressions using actual RTL dependencies, configuration-derived parameters, reproducible seeds, explicit failure/skip reporting, and isolated run artifacts. | Verify meaningful RTL blocks before full-core integration and reproduce failures without rerunning unrelated tests. | Agreed; exact suite catalog, command syntax, artifact formats, and CI cadence remain open |
| D-256 | Use cocotb and pyuvm project-wide for component, subsystem, and full-core simulation testbenches, including simple leaf tests; allow lightweight tests without unnecessary UVM component hierarchies. | Keep one shared testbench structure while scaling verification complexity to the DUT. | Agreed; finalizes D-254, with runner and compatible versions TBD |
| D-257 | Place component simulation tests in `verif/sim/<component>/` and full-core tests in `verif/sim/core/`, initially using `test_<module>.py`; keep local environments and HDL wrappers beside their tests and shared utilities in `verif/common/`. | Make tests easy to locate and run independently while growing their structure only as needed. | Agreed; simulation-specific shared helper/wrapper placement refined by D-259 |
| D-259 | Put shared component-testing Make helpers, simulation utilities, and reusable HDL wrappers in `verif/sim/common/`; use `config/sim/<component>.yml` for DUT/test metadata and shared configuration helpers rather than separate component runner scripts. | Make invocation responsibilities explicit and reuse the flow as components are added. | Agreed; utilities shared with formal verification may remain in `verif/common/` |
| D-290 | Add a verification-only single-channel RV32 RVFI collector, simulation core wrapper and separate SV JSONL writer; preserve actual consumed operands and raw memory responses, with explicit fault/handler/reset semantics. | Establish architectural observations without changing core RTL/ports or hiding forwarding errors; reuse the collector for later formal binding. | Implemented; Section 1.1; native simulation checks and trace reader available; CSR channels, formal core binding/proofs and Spike adapter remain unfinished |
