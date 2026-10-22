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
transaction identifiers required by interfaces such as CV-X-IF. The implemented
RVFI/CSR observation and JSONL encoding are defined in Sections 1.1–1.2 and the
[collector guide](../verif/common/README.md); initial XIF companion observations
are defined in Section 2.4.

Trace collection, formatting, and file writing shall be implemented in
SystemVerilog verification monitors, not in the synthesizable processor RTL.
The plain-Verilog RTL shall expose the instruction and state signals needed by
these monitors. The simulation wrapper isolates hierarchical references to the
core's existing signals, as described in Section 1.1.

**Verification interface:**
[RVFI](https://yosyshq.readthedocs.io/projects/riscv-formal/en/latest/rvfi.html)
shall be the observation contract for instruction tracing and `riscv-formal`
checking.
RVVI is not a required dependency. SystemVerilog verification instrumentation
shall provide the trace records from the core's exposed instruction/state
signals; formatting and file writing shall remain in simulation monitors.

The initial native profile and simulation connections are defined in Section 1.1.
The pinned formal-tool revision, formal core binding and checker integration
remain deferred under D-291. Native CSR observations and initial XIF companion
traces are implemented; floating-point/debug observations, RVFI_BUS and broader
memory-side-effect coverage remain open. Coverage shall be specified explicitly
rather than assumed from the base RVFI interface. Instrumentation used for formal checking must be compatible with the
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
formal proofs. Formal core signal binding, RVFI_BUS, complete
instruction proofs remain follow-ups. The initial pinned Spike adapter is
defined in Section 2.8.

### 1.2. Native CSR observation channels

The verification harness shall expose `rvfi_csr_<name>_rmask`, `_wmask`,
`_rdata` and `_wdata` for native implemented CSR state. The
[CSR channel profile](../verif/common/README.md) and canonical
`verif/common/uqu_rvfi_csr_list.vh` shall define channel names, widths and aliases.
The current catalog has 102 channels, covering machine identity/control/trap
state, optional U-mode configuration, PMP, counters and hardwired-zero HPM state.
Optional Zfinx includes `fflags`, `frm` and `fcsr` channels for explicit CSR
accesses, alias writes, dynamic rounding reads and retirement-qualified flag
read/modify/write accrual. Debug state remains outside the native core profile.

CSR observations shall use successful explicit access qualification and actual
architectural pre-/post-state. The adapter shall not predict WARL legalization,
PMP lock effects or implicit trap/MRET updates. A registered observation stage
shall align the RVFI instruction event with captured pre-state and actual
committed post-state. This changes verification timing only. Counter channels
shall be 64 bits with machine/user low/high address aliases and half masks;
autonomous increments shall not be reported as instruction CSR writes.

Synchronous traps and MRET shall report their implicit reads/writes. IRQ-entry
CSR effects shall be included in the separate diagnostic interrupt record,
without inventing an RVFI instruction. Illegal accesses shall not report explicit
CSR effects; legal writes to ignored or locked fields shall report their actual
unchanged state. Disabled features shall preserve their architectural CSR
availability, including legal zero-valued disabled PMP CSRs. Unreset PMP address
payload shall not acquire an assumed reset value from verification code.

The JSONL stream shall include sparse CSR channel objects on instruction and
interrupt events. Simulation shall check every active channel against the
independent CSR model and compare sampled channels with the saved stream.
Formal toolchain selection, core binding and proof execution remain deferred
under Section 2; adding channels does not select a formal backend.

## 2. Simulation and formal verification

**Status:** Formal verification planned; core binding/proof execution deferred
until an open-source formal toolchain is selected and its configuration pinned

Verification shall include both simulation and formal checks with
[`riscv-formal`](https://github.com/YosysHQ/riscv-formal), using the RVFI
observation contract defined in [verification, Section 1](uqu_spec.verif.md#1-instruction-identity-and-architectural-trace). The initial formal verification
scope shall be RV32I. Applicable instruction checks shall pass under documented
environment assumptions as part of verification acceptance for that scope.

`riscv-formal` remains the previously named framework. A complete working
open-source toolchain, including synthesis/formal frontends, orchestration,
solver and versions, has not yet been selected and validated for this core.
Defer implementation of the formal core binding and execution of instruction
proofs until that selection. Existing RVFI simulation and collector structural
checks may continue; they do not imply completion of formal verification.

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
simulation reference model. The initial adapter and exact external binary pin
are defined in Section 2.8. Its source revision is unknown and shall not be
inferred from its development-version banner. Future source-built references
shall pin the source revision and build identity for reproducibility.

Starting with the first implementation milestone, simulation shall include
randomized memory timing in addition to directed tests and architectural
comparison. Tests shall independently vary request-grant delays and response
latency on the instruction and data OBI ports while preserving the agreed
protocol. They shall exercise error responses, redirects, and reset with
transactions pending, respecting the existing reset integration contract.
Randomized tests shall accept an explicit seed and report the seed used so
failures can be reproduced. The shared runner exposes `SEED`, with component and
core agents implementing these scenarios; their guides document test selections
and retained artifacts.

Formal instrumentation and harnesses shall be compatible with the selected
formal tools. Trace formatting and file writing shall remain separate simulation
code. Project-owned synthesizable processor RTL shall remain plain Verilog;
imported IP and its dependencies may use SystemVerilog under the style-guide
exception, and verification collateral may use SystemVerilog.

Component manifests, core suites, ELF/riscv-tests execution and scoped Spike
comparison define the current simulation checks. Python package pins are in
`verif/requirements.txt`; the reference adapter records its qualified Spike
binary identity. The formal toolchain, proof assumptions/depth, broader coverage
and automated supported-configuration matrix remain open. Verification results
shall state the checks, configurations and assumptions used so that the
demonstrated scope is explicit.

The [shared build report](uqu_spec.build.md#61-shared-build-report) shall visualize
retained verification results across configurations and preserve drill-down to
cases, diagnostics and provenance. Its aggregation does not expand the scope of
a test or proof. Missing evidence, partial suites, failures, skipped checks and
changed/unknown inputs shall remain distinguishable from verification success.

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
Initial Spike comparison is defined in Section 2.8; formal integration and other
simulator backends remain open.

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
retirement/trap programs are described in Section 2.4; the initial deterministic
Spike/RVFI ELF adapter is defined in Section 2.8.

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

**Status:** Component, subsystem and core suites use the shared runner;
CI cadence and coverage targets open

Use component, subsystem, and full-core test levels, sharing protocol agents,
transactions, reference models, and checking utilities where applicable. For
example, an OBI memory agent could serve both an isolated LSU test and the
core-level environment. A component regression shall remain runnable without
executing the full-core regression. A small smoke suite and a larger multi-seed
regression are proposed; the runner already supports independent components,
named tests and explicit seeds. Exact CI cadence, the automated configuration
matrix and coverage targets remain open.

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
coverage. Native Zfinx execution and its component/core checks are implemented
under D-304 and Section 2.9. Core debug shall reject enabled elaboration until
its sequencing is implemented.

The initial XIF core regression shall use only standard coupled issue/register
and commit/result fields, with a behavioral coprocessor and an independent
custom-instruction retirement oracle. Exercise four accepted live offloads,
stable ID/operand presentation, sequential ID wrap/exhaustion, rejection and
cleanup, same-cycle and delayed results, third-source dependencies, no-write
completion, paired writes/ignored x0-x1, secondary destination hazards, malformed
result containment, late memory-fault flushes, precise IRQ eviction/reissue and
reset with unfinished work. Cover RV32E-aware rejection and defensive kill of
noncompliant acceptance, two-source operation, forwarding disabled and operand
retention. Disabled XIF shall ignore noisy inputs and produce inactive outputs.

Capture custom sources at actual issue handshakes. Standard RVFI shall report
the first two sources and primary write. A companion `xif.jsonl` shall retain all
three used operand values and both actual architectural writes, correlated with
the same RVFI epoch/order and one custom retirement. This diagnostic shall not
be presented as a standard formal RVFI multi-destination extension or custom
instruction proof. Retain protocol observations in `xif-agent.json`; software
fixtures and their behavioral model shall not advertise a new core ISA extension.
Spike custom comparison remains unsupported until an explicit reference contract
is selected; no custom event shall be silently excluded from a claimed comparison.

The interpreter consumes the RVFI testbed's retirement records and independently
checks operands, memory lanes, fault reporting and instruction sequence. It is
not the selected Spike reference. Section 2.8 adds an initial deterministic Spike
comparison; broader reference coverage, riscv-formal core binding/proofs,
software coverage and configuration CI remain required follow-ups.
Passing the initial native programs shall not be reported as
completion of the first milestone's acceptance criteria.

### 2.5. Formal RVFI integration goal

**Status:** Agreed goal; implementation and proof execution deferred under D-291

The project shall provide a core-specific formal integration following the
[`riscv-formal` core integrations](https://github.com/YosysHQ/riscv-formal/tree/main/cores)
and [verification procedure](https://yosyshq.readthedocs.io/projects/riscv-formal/en/latest/procedure.html).
RVFI is the shared observation contract; the current cocotb environment and
JSONL trace writer do not constitute this formal integration.

Reuse the passive instruction and CSR collectors in `verif/common/` across
simulation and formal verification. Observation logic shall report actual
execution, including consumed operands, committed results and memory effects;
it shall not substitute expected results. RVFI need not be generated inside the
processor RTL or added to production core ports. A formal-compatible connection
method shall be selected and validated with the chosen frontend; the current
simulation wrapper's hierarchical references are not assumed portable.

The formal integration shall provide:

- A core-specific wrapper connecting the actual processor and shared collectors
  to the framework's RVFI checkers, without cocotb or simulation file I/O.
- A symbolic OBI environment for instruction and data ports, with explicit
  protocol, memory-consistency, error and reset assumptions. Symbolic inputs
  represent permitted choices rather than seeded simulation stimulus. Any
  fairness assumptions needed for progress checks shall be documented separately
  from safety assumptions and shall not exclude permitted core behavior merely
  to obtain a passing result.
- A pinned `checks.cfg` or equivalent supported configuration defining the ISA,
  core parameters, enabled CSR channels, checks, assumptions, proof strategy
  and depths. GNU Make shall invoke the selected open-source toolchain and
  retain reproducible results and counterexample artifacts.
- Applicable instruction-semantic checks together with register, PC, ordering
  and causality checks. Add RVFI_BUS observations and applicable bus checks to
  connect the retirement trace to real instruction/data transactions, including
  fault reporting; a self-consistent RVFI trace alone does not establish this
  connection. CSR and privileged-state checks shall have an explicit scope.

The initial scope remains RV32I as defined in Section 2. Completion requires the
selected toolchain to run the documented check set successfully for the stated
core configuration. Reports shall distinguish bounded checks from unbounded
proofs and state all assumptions, depths, exclusions and remaining coverage.
Simulation regressions, collector structural checks and passing bounded checks
shall not be described as an unrestricted proof of the processor. Optional
extensions and configurations require their own coverage before being included
in a formal-verification claim.

### 2.6. ELF software execution

**Status:** Initial native ELF execution implemented; riscv-tests and deterministic
Spike comparison added in Sections 2.7 and 2.8

A reusable ELF execution environment shall load statically linked little-endian
RISC-V ELF32 `PT_LOAD` segments and zero their memory tails, including BSS, into
one shared instruction/data memory image. The independent instruction oracle
shall retain a separate image updated at architectural stores. A word-aligned
executable ELF entry shall drive `boot_addr_i`. Malformed images, unsupported
ABI flags, dynamic linking, overlapping segments and unsupported load/run
address mappings shall fail explicitly.

Bare-metal startup/linker files and programs shall live in `verif/sw/`, with
compiler ISA/ABI selection derived from hardware YAML. The initial environment
shall use an aligned, zero-initialized 8-byte `tohost` symbol in writable memory:
an aligned 32-bit store to its low word reports `1` for pass or
`(code << 1) | 1` for a nonzero failure code, keeping the upper word zero.
Completion shall be recognized only when that store successfully retires;
granted requests shall not imply completion. No production core ports are added
for test completion. Host syscalls and console communication remain deferred.

An ELF may declare an ordered sequence of expected synchronous traps in a kept
`.uqu.traps` section between global `uqu_expected_traps` and
`uqu_expected_traps_end` symbols. Each little-endian word triple shall specify
the faulting PC, cause and expected trap value. Validate aligned executable sites,
supported causes, mapped table bytes and consistent declarations per PC. With no
table, every trap remains unexpected. Declared trap sites shall fault on each
arrival; events must match the table order and count. Missing, extra or mismatched
traps fail the run. Completion shall also compare the bus-visible shared RAM
against the independent architectural image to detect unretired store effects.

The [ELF target](../verif/sim/core_elf/README.md) shall reuse native randomized
OBI timing, the actual core/RVFI wrapper and independent execution/CSR checks.
A configurable cycle watchdog, software failure or checker mismatch shall
produce a failed run and nonzero regression exit. Retain the input ELF snapshot
and hash, configuration, seed, execution status/cycle/PC diagnostics, logs and
RVFI trace, including on failure. Default limits and the initial sparse-memory
and software-initialization contracts are defined in the execution guide.

Verify initialized data, BSS, shared memory visibility, stack/calls and explicit
failure/timeout fixtures before integrating external instruction suites.
The initial `riscv-tests` adapter is defined in Section 2.7. Architectural tests
and broader Spike comparison remain follow-ups; ELF execution alone does not establish architectural compliance or
complete the first milestone's verification acceptance criteria.

### 2.7. Pinned riscv-tests instruction regression

**Status:** Initial RV32I/M/C adapter implemented; optional Spike comparison in
Section 2.8; architectural certification remains separate work

Consume unchanged instruction bodies and scalar macros from a checksum-pinned
`riscv-tests` archive without repository submodules. The
[source lock and adapter](../verif/sw/riscv_tests/README.md) define the exact
commit/archive hash and local bare-metal environment. Adapt startup/pass/fail
macros to the existing ELF runner and `tohost` contract; do not require the
upstream `env` submodule or its privileged runtime probing.

Select applicable `rv32ui`, `rv32um` and `rv32uc` cases from the pinned Makefrag
lists. Gate M/C/FENCE.I cases on the matching ISA parameters. Explicitly exclude
`ma_data`, which requires successful misaligned accesses rather than the agreed
traps, and reject RV32E for these upper-register-using tests. Other privileged,
virtual-memory and ISA families remain outside this initial adapter. Preserve
each exclusion reason and reject requests for unknown/excluded tests.

Freeze selected ELF hashes, full hardware parameters, compiler identity, source
pin and exclusions in a suite manifest. Execute each ELF in a fresh simulator
process through the existing RVFI/CSR checks, independent instruction oracle,
shared memory and seeded OBI timing. Reuse a compiled simulator only when all
recorded HDL/header/order/parameter/top/language/simulator/waveform inputs match.
Continue remaining selected cases after a failure and fail the command if any
required case fails. Keep per-ELF artifacts and suite JUnit/JSON summaries.

The shared report shall show the suite and independent ELF runs, including
compiler family/version/target and upstream revision. Declared incompatible
cases shall appear as skipped evidence rather than passes; all required cases
must succeed for the selected cohort to pass. Passing this adapted instruction
suite does not replace pipeline/error/reset regressions, Spike comparison or
architectural certification tests.

### 2.8. Initial Spike differential ELF checking

`REFERENCE=spike` shall add external reference checking to ELF tests and
riscv-tests suites, preserving the native Python oracle and randomized OBI
timing. Discovery shall use explicit `SPIKE`, then `$RISCV/bin/spike`, then
`PATH`. No dependency installation is implied. The exact qualified executable
hash, banner and adapter profile shall be pinned in
[`verif/reference/spike.lock.json`](../verif/reference/spike.lock.json).
Record source revision as unknown when unavailable, plus binary identity,
ISA/privilege configuration, command and memory settings in each run.

The initial adapter shall compare original instruction/PC/next-PC, privilege,
GPR destinations/results and consumed source operands, byte-lane memory effects
and explicitly supported deterministic CSR channels. Spike store observations
shall update an independent byte image for load-response comparison. Explicit
CSR writes shall match Spike effects; read values/masks shall match prior
deterministic state. Bootstrap removal shall validate a fixed known prefix,
never search for a matching trace position. One lookahead instruction shall
check the final next PC. Missing/extra commits and unknown log formats fail.

The [reference guide](../verif/reference/README.md) defines the native 64 KiB
RAM, I/E/M/C and M or M/U profile. Version 2 shall preserve synchronous trap
attempts in the event stream and sample PC, privilege and native CSRs directly
from Spike's read-only debugger after each bounded step. Require exact event and
snapshot alignment, cause, saved PC, handler/return target, privilege, handler-entry
marker and implicit CSR channel comparisons for trap entry and MRET. Check that
faulting instructions have no committed GPR or memory effects.

Supported causes shall include illegal instruction, M/U ECALL, EBREAK/C.EBREAK,
instruction-address misalignment and load/store address misalignment. Synchronous
entry shall use MTVEC.BASE even when its mode is vectored. Explicit and implicit
MSTATUS checks shall cover implemented native bits; software shall establish
common MSTATUS state before observing its implementation-dependent reset MPP.
For breakpoint MTVAL only, validate Spike's permitted zero-or-fault-PC choice and
the native zero choice. Reject direct MTVAL reads while those values differ;
do not rewrite GPR outcomes. Other trap values shall match exactly. The guide
documents zero-only model-side MRET CSR effects absent from the native profile.

The `SW=traps` program shall exercise these cases, preserving a destination
register sentinel and RAM guard against faulting and younger flushed effects,
including the sequential path after MRET. Cover M-only and M/U execution, both
IALIGN settings, 16-bit illegal/EBREAK instructions when C is enabled, and a
return from U ECALL into M mode. Report observed trap/MRET counts and modes.
Other unsupported implementation-dependent CSR accesses, PMP, host services and
unsupported features shall still fail explicitly. Broader bus/PMP fault
coverage and full CSR/WARL coverage remain
follow-ups. The initial interrupt synchronization profile is defined below.

Profile v3 shall support ELF-bound level-sensitive machine software, timer and
external interrupt stimuli. A kept `.uqu.irqs` table between global
`uqu_interrupts` and `uqu_interrupts_end` symbols shall declare ordered four-word
rows: trigger kind, trigger PC, pending-line mask and a zero reserved word.
Triggers shall support retirement at a specified PC, an outstanding data-memory
response and active multi-cycle arithmetic at a specified PC. Masks use bits
3, 7 and 11 only. Hold each mask until every declared source is serviced,
acknowledging only the accepted source. Validate the table and require all
triggers/entries to complete; no table means no injected IRQs.

Native simulation shall independently derive interrupt eligibility from driven
pins and the prior architectural CSR/privilege model. Each cycle shall check
global/source masking, external > software > timer priority, blocked DE admission,
EX/MEM/WB drain and LSU idle, entry timing and saved architectural PC. These checks
shall not consume DUT eligibility or priority outputs as their expected values.
Exercise masked pending sources, simultaneous sources, direct/vectored entry,
memory and division stalls, pending lower-priority service across MRET and
U-mode delivery with MSTATUS.MIE clear. Retain assertion/acceptance cycles,
instruction orders, trigger context and full pending masks in `interrupts.json`.

Replay shall validate this evidence against the copied ELF declaration and RVFI
interrupt records, then drive the full pending mask into Spike at each accepted
architectural boundary. Spike shall independently select the cause and produce
actual trap state. Compare saved PC, cause, direct/vectored target, privilege,
implicit CSR effects and handler/return behavior. IRQ entry shall not invent an
instruction or increment RVFI order. The reference inputs shall remain low during
ordinary replay so admitted native instructions may finish before aligned delivery.
Profile v4 shall reconcile MIP reads with event-clock pin samples as defined below;
native MIP shall still match pins every cycle.

For counters, compare actual native 64-bit `mcycle`, `minstret` and inhibit state
against the independent clock/retirement CSR model before and after every active
edge, including stalls, plus reset post-state. Check previous-edge inhibition,
32/64-bit rollover, explicit half-write precedence, successful retirement only,
and counter-enable/alias permissions. Preserve reset edge, checked-edge count and
event pre/post model values in `timing.json`; replay shall recompute progression
from clock gaps and explicit instructions before accepting any sample.

Supply the verified counter pre-state to Spike before each original event,
preserving its CSR implementation, privilege checks and instruction execution.
Compare resulting GPRs and full counter CSR channels, including the preserved
half of explicit writes. Native cycle timing shall be verified against native
clock edges, not Spike's autonomous counter increments. This policy shall not
claim that Spike models the pipeline timing or measures its performance.

Reconstruct software-visible MIP from declared pin assertion/acknowledgement
clocks, separately from the reference delivery mask. A verification-only CSR
view may expose this sample while retaining original privilege checks and the
native hardware-owned, write-ignored pending bits. Actual interrupt selection
shall continue using Spike's own input storage and trap mechanism at the checked
delivery boundary. Do not rewrite GPR results, instructions, PC or privilege.

Retain ordered counter/MIP inputs in `spike-inputs.txt`, verify sequence
acknowledgements, and sample actual Spike pre/post state around each attempt.
Record native-oracle/reference input hashes and report checked-edge/counter/MIP
metrics. The reference may enable Zicntr to expose this build's counter facility;
TIME shall remain rejected and no additional core ISA feature is implied.
`SW=counters` shall exercise these contracts, including memory/multi-cycle stalls,
synchronous trap exclusion and optional U-mode permissions. `SW=interrupts` shall
exercise masked pending reads and ignored MIP writes. Full CSR/WARL coverage and
Spike WFI comparison remain follow-ups; native WFI behavior is already implemented.

A verification-only Spike device may use its platform external-input API via
bounded debugger commands. This helper shall not add target instructions or
production core ports, change architectural PC/privilege, or fabricate a trap.
Require checked pin acknowledgements and record local source, matching external
SDK header/library hashes, host compiler/command and output identity. The matching
Spike SDK and C++ compiler remain external dependencies, with explicit SPIKE_ROOT
and CXX overrides; no install or Spike dependency build is implied. The reference
guide defines SDK discovery, the restricted host-device address and artifacts.

Keep raw reference/process logs, ELF/RVFI evidence and a JSON summary with the
first mismatch index/field and both observations. A mismatch shall fail JUnit,
the run and its containing suite; later suite cases shall still run. Reporting
shall distinguish reference binary identities and checked/unchecked runs, link
retained evidence, and reject passed metadata with absent or failed reference
evidence. Report comparison context shall include both the executable identity
and adapter profile so earlier and later checker versions cannot replace each
other's outcomes. Tooling tests shall deliberately corrupt observations,
including implicit trap/MRET state, and exercise missing/extra/reordered
declarations, unsupported events, log formats and process timeout.

### 2.9. Native Zfinx arithmetic and lifecycle regression

The [FPU component guide](../verif/sim/fpu/README.md) defines the executable
`fpu` target and the real CVFPU adapter's supported configuration scope.
Arithmetic and per-instruction flags shall be checked against an independent
exact-rational binary32 oracle, including fused operations and square root,
without host floating-point rounding. The enabled suite compares 21,027
operations across all 22 normalized operations, five rounding modes,
special values, rounding boundaries and randomized inputs. An optional external
Berkeley SoftFloat check cross-validates 27,080 oracle results and flags,
including targeted normal/subnormal boundaries for both signs and all modes;
HDL tests shall not require that library.

The component regression shall exercise held results/flags, changes to live
inputs after acceptance, malformed direct controls, reset, flush during
execution or held output, recovery and disabled behavior. Configuration checks
shall cover four placements and zero/nonzero staging. TH32 is the default and
THMULTI has scalar simulation coverage. The pinned PULP backend remains rejected
for enabled Zfinx after exception-flag failures; its selector does not establish
support. No imported-source patch or approximate FP behavior is permitted.

EX and parent-pipeline regressions shall preserve one start/completion per
instruction and result/status association under backpressure. The core `fpu`
program shall check all scalar instructions, all three FMA source dependencies,
dynamic rounding and reserved-mode traps, FP CSR aliases, x0 flag accrual,
older-memory-fault cancellation and interrupt drain. FP CSR observation shall
sample actual retired state, not speculative FPU output. These native checks
are complemented by Section 2.10. Formal FP models and physical-flow
qualification remain open.

### 2.10. Independent Zfinx ISA execution

Spike profile `spike-commit-rv32-v5` shall support scalar RV32I/E Zfinx using
the existing external binary pin, ELF runner and integer ABI. Decode ISA fields
independently of native decoder/arithmetic helpers. Expected GPR results and FP
CSR state shall come from Spike execution and pre/post snapshots, never DUT
values or the native arithmetic oracle. Preserve all existing integer, trap,
memory, privilege, counter and interrupt checks. Include MISA in snapshots.

Check `fflags`, `frm` and `fcsr` values, read/write masks, explicit aliases and
accrued flags. Check FS remains Off and MISA F/D/Q remain absent. Standard RVFI
has two source operands; a simulation-only `fpu.jsonl` companion shall follow
actual EX consumption to retirement, recording the third source and effective
rounding mode with epoch/order/PC/instruction identity. Check these against
prior Spike GPR writes and Spike FRM. Missing, extra or malformed events fail.
This adds no production-core ports or nonstandard RVFI ports.

`SW=zfinx` shall exercise all 22 scalar instructions, all 13 rounding-capable
instructions in each static and dynamic mode, every available source/destination
register, overlap and x0, FMA's independent third source, ten FCLASS categories,
canonical versus payload-preserving NaNs, signed zero, rounding boundaries,
all five exception flags and sticky accrual. Include all six FP CSR access
forms/aliases, illegal/reserved encodings and modes, excluded FLW/FSW/FMV,
M/U execution. Native-only `SW=zfinx_ereg` shall check RV32E high-register
traps: the pinned Spike executes those reserved encodings, so its adapter shall
reject these probes explicitly. With Zfinx disabled, probe illegal
FP instructions and FP CSR access. Expected-trap declarations and poison stores
shall check precise exceptions and suppression of younger effects.

Retain independent snapshots/logs and `zfinx-coverage.json` only after successful
comparison. The report shall expose FP instruction/CSR counts and the coverage
artifact. Coverage describes executed operations, register roles, privilege
modes, static/dynamic modes, CSR forms and trap causes; it is not certification.
Corruption tests shall reject incorrect GPR/source/third-source values, effective
rounding, FP CSR masks/pre/post state and companion identity/completeness.

Independent comparison exposed incorrect UF suppression shared by the initial
adapter and native oracle. Correct tininess uses destination precision with
unbounded exponent range, so `0x00800000 * 0x3f7fffff`, RNE, produces
`0x00800000` with UF|NX. Keep this directed case and cross-check boundary
arithmetic against external SoftFloat. See the
[SoftFloat FAQ](https://www.jhauser.us/arithmetic/SoftFloat-3/doc/SoftFloat-FAQ.html).
Broader generated ISA programs, upstream architectural-test integration and
formal FP proofs remain future work.

### 2.11. Branch-prediction regression

The IF-owned predictor shall have an independently selectable
`COMPONENT=bpu` regression using the shared cocotb/pyuvm runner
and an abstract target/direction oracle. Cover cold lookup, both conditional
allocation directions, saturating counter transitions, unconditional and
changed indirect targets, tag replacement, C-dependent indexing, stale-entry
removal, lookup/update collision, validity-only reset and invalidation priority.
Exercise baseline modes and several table capacities independently of core
execution. Vary direction and target capacities independently, including 2/32
and 32/2 combinations. Cover disabled BTB, inactive BTB under prediction mode
`none`, and static-not-taken direction with an enabled BTB for jumps. The
[component guide](../verif/sim/bpu/README.md)
defines the implemented tests and parameters.

IF tests shall check stable carried predictions during stalls/table updates,
accepted target steering, ordinary core-owned PMP faults, held OBI requests,
discarded responses and external-recovery priority. Parent IF/DE tests shall
carry the actual prediction metadata and use real DE corrections. Core directed
programs shall verify correct predictions, loop-exit mispredictions, changing
JALR targets, compressed branches in all three C strategies and cold lookup
after FENCE.I. Retain architectural retirement/RVFI and precise-event checks;
wrong-path instructions shall not acquire architectural effects.

CoreMark cycle comparisons shall reuse the same executable and memory context,
validate the workload output and retain mode/validation scope. They shall not
replace instruction-level regression or establish Pareto optimality. Broader
workload coverage and predictor PPA evaluation remain follow-ups.

The passive retirement-scoped statistics contract is defined in
[benchmark statistics](uqu_spec.bench.md#31-passive-branch-prediction-statistics).
`COMPONENT=bpu_monitor` shall check first-presentation retention during IF
stalls, independent boundary stalls, DE squash, faulting WB exclusion, held
lookup invalidation and reset. Core prediction programs shall independently
check retired branch/JALR and compressed-control-flow counts against their
architectural execution. Counter snapshots, measurement windows, undefined
rates and report evidence consistency shall have shared Python regression.
Both harnesses shall use the same passive observer and counter ordering.
The core `bpu_statistics` case shall exercise real timer markers around a
branch/JAL loop; optional `UQU_BPU_NATIVE` qualification shall compare both
marker points and complete statistics against a matching native driver.

## 3. Supported-configuration CI coverage

**Status:** CI requirement agreed; simulation flow implemented, synthesis flow
and CI automation open

CI shall at least elaborate and synthesize every configuration explicitly marked
as supported by the project. The supported configuration set shall be documented
and checked as it expands across implementation milestones. Unsupported
configurations shall fail configuration validation as required in [architecture, Section 2](uqu_spec.arch.md#2-isa-and-microarchitecture-configuration-parameters).

The initial deeper simulation and formal verification scope shall follow
[verification, Section 2](uqu_spec.verif.md#2-simulation-and-formal-verification) and the default first milestone in [overview, Section 3](uqu_spec.md#3-first-implementation-milestone). Successful
elaboration and synthesis alone shall not imply full functional verification of
a configuration; the demonstrated verification scope shall remain explicit.

The current Bender/Make simulation and lint commands, complete hardware YAML,
Verilator backend and retained run/report artifacts are defined in the
[build specification](uqu_spec.build.md). ORFS synthesis integration, the CI
configuration matrix/environment, broader tool-version pins and automated
publication/retention remain to be implemented.

## 4. Verification follow-ups

Maintain the Spike binary pin and extend its initial profile; pin its source
revision when available, plus RVFI/riscv-formal, tools, solvers and library models.
The shared runner, pinned cocotb/pyuvm stack, component/subsystem/core suites,
seed controls, RVFI/CSR monitors, ELF/riscv-tests execution and scoped Spike
retirement/trap/interrupt/counter comparison are implemented. Preserve the
separation between passive observations and simulation file I/O. Extend coverage
and define the automated supported-configuration matrix, coverage targets,
remaining tool-version pins and CI environment/retention.
After selecting the formal toolchain under D-291, implement the shared-collector
formal wrapper, symbolic OBI environment, RVFI_BUS observations and checker
configuration specified in Section 2.5.

Existing privilege, CSR, memory, interrupt and paired-XIF checks shall retain
their documented scope. Broader CSR/WARL/PMP/bus-fault reference comparison,
Spike WFI support, a custom-instruction reference contract and eventual FPU/debug
verification remain open. Initial RV32I formal checking shall not be presented
as proof of those additional features. Randomized memory-latency and error/reset
tests are implemented and remain first-milestone requirements.

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
| D-070 | Use RVFI as the verification observation contract; do not require RVVI. | Connect tracing and open-source `riscv-formal` checks through a shared observation contract; define the required profile separately. | Implemented simulation RVFI/CSR profile and XIF companion trace under D-290/D-292/D-301; formal profile/binding deferred under D-291 |
| D-071 | Require simulation and formal checks with `riscv-formal`, starting with RV32I. | Establish both execution-based testing and formal instruction checks as verification requirements, with explicit scope and assumptions. | Simulation implemented with explicit scope; formal core binding/proofs deferred under D-291 pending toolchain selection |
| D-072 | Require simulation comparison of standard-instruction retirement and trap outcomes against an independent software RISC-V reference model. | Check architectural execution independently of pipeline implementation; configure the model and adapter separately. | Agreed; Spike selected in D-073 |
| D-073 | Use Spike as the simulation reference model. | Provide an independent executable ISA reference for architectural comparison. | Initial binary-pinned adapter in D-297; broader comparison remains open |
| D-120 | Require CI to elaborate and synthesize every explicitly supported configuration; define the build flow before implementing this requirement. | Check supported configurations as the design grows while keeping deeper functional-verification coverage explicit. | Agreed; build tools selected by D-121, detailed flow and CI implementation TBD |
| D-218 | Require randomized OBI grant/response timing tests from the first milestone, alongside directed tests and Spike comparison; exercise errors, redirects, and reset with pending transactions, and accept/report explicit random seeds. | Exercise variable-latency memory interactions and make randomized failures reproducible. | Implemented component/subsystem/core OBI agents and directed/randomized timing/error/redirect/reset tests with explicit seeds |
| D-254 | Propose cocotb for Python-to-simulator interaction and pyuvm for reusable verification environments, retaining Verilator as the default simulator and the existing SV trace/RVFI and formal contracts. | Support Python verification with a reusable UVM structure while preserving the existing build and observation boundaries. | Finalized by D-256; shared runner and pinned Python environment implemented in Section 2.1 |
| D-255 | Support independently selectable, self-checking component regressions using actual RTL dependencies, configuration-derived parameters, reproducible seeds, explicit failure/skip reporting, and isolated run artifacts. | Verify meaningful RTL blocks before full-core integration and reproduce failures without rerunning unrelated tests. | Implemented manifests, component/test selection, isolated run artifacts and shared reporting; CI cadence/matrix open |
| D-256 | Use cocotb and pyuvm project-wide for component, subsystem, and full-core simulation testbenches, including simple leaf tests; allow lightweight tests without unnecessary UVM component hierarchies. | Keep one shared testbench structure while scaling verification complexity to the DUT. | Implemented project-wide stack, shared runner and version pins; Section 2.1; finalizes D-254 |
| D-257 | Place component simulation tests in `verif/sim/<component>/` and full-core tests in `verif/sim/core/`, initially using `test_<module>.py`; keep local environments and HDL wrappers beside their tests and shared utilities in `verif/common/`. | Make tests easy to locate and run independently while growing their structure only as needed. | Agreed; simulation-specific shared helper/wrapper placement refined by D-259 |
| D-259 | Put shared component-testing Make helpers, simulation utilities, and reusable HDL wrappers in `verif/sim/common/`; use `config/sim/<component>.yml` for DUT/test metadata and shared configuration helpers rather than separate component runner scripts. | Make invocation responsibilities explicit and reuse the flow as components are added. | Agreed; utilities shared with formal verification may remain in `verif/common/` |
| D-290 | Add a verification-only single-channel RV32 RVFI collector, simulation core wrapper and separate SV JSONL writer; preserve actual consumed operands and raw memory responses, with explicit fault/handler/reset semantics. | Establish architectural observations without changing core RTL/ports or hiding forwarding errors; reuse the collector for later formal binding. | Implemented; Section 1.1; CSR channels added under D-292; formal core binding/proofs remain deferred; initial Spike adapter in D-297 |
| D-291 | Defer formal core binding and proof execution until a working open-source formal toolchain and configuration are selected; retain the planned riscv-formal direction and current RVFI simulation checks. | Avoid implementing a tool-specific formal harness before selecting its actual frontend, orchestration and solver; distinguish simulation/structural checks from proofs. | Deferred pending toolchain selection; qualifies implementation timing under D-071 |
| D-292 | Add native per-CSR RVFI channels with actual pre-/post-state, registered event alignment, 64-bit counter aliases, implicit trap/MRET updates and sparse JSONL diagnostics checked against the CSR model. | Observe CSR behavior without duplicating WARL/locking logic or changing processor RTL; preserve the formal deferral under D-291. | Implemented; Section 1.2; native simulation coverage and structural checks; formal binding/proofs remain deferred |
| D-293 | Make a reusable RVFI formal integration a verification goal: shared passive collectors, a formal-compatible core wrapper, symbolic OBI environment, RVFI_BUS observations and documented riscv-formal checker configuration. | Reuse execution observations across simulation and formal verification while checking their connection to actual core and bus behavior and stating the demonstrated proof scope. | Agreed goal; Section 2.5; implementation and proof execution remain deferred under D-291 |
| D-294 | Add reusable ELF32 software execution with shared instruction/data RAM, PT_LOAD zero-fill, bare-metal startup/linker files, retired-store tohost completion, configurable watchdog and preserved ELF/RVFI diagnostics. | Establish a compiler-built software execution foundation reusable by later ISA suites without adding test-completion ports to the processor. | Implemented initial native environment; Section 2.6; riscv-tests added under D-296; architectural tests and broader Spike coverage remain follow-ups; initial adapter in D-297 |
| D-296 | Integrate checksum/commit-pinned riscv-tests without submodules, using adapted bare-metal instruction tests, explicit ISA/misalignment exclusions, independent ELF runs, compatible simulator-build reuse and compiler family/version/target discovery from RISCV_CC, RISCV or PATH. | Add reproducible external instruction coverage while preserving the chosen core behavior, externally supplied tools and honest cross-configuration reporting. | Initial RV32I/M/C adapter implemented; Section 2.7; build contract in build Section 1.2; initial Spike checking in D-297; other ISA/privileged families and architectural certification remain separate |
| D-297 | Add optional external Spike differential checking for native ELF/riscv-tests runs, with an exact qualified binary pin, strict bounded commit-log parsing, original instruction/PC/GPR/source/memory checks, deterministic CSR checks and retained first-mismatch/JUnit/report evidence. | Add the selected independent ISA reference without silently ignoring unsupported traps, interrupts, counters or implementation-dependent state; preserve external tools and native timing/error checks. | Implemented initial native profile; trap/MRET, IRQ and counter/MIP support extended under D-298–D-300; broader CSR/WARL/PMP/bus-fault coverage and source-revision pin open |
| D-298 | Add ELF-bound ordered expected-trap declarations and Spike v2 synchronous-trap/MRET comparison using independent read-only state snapshots; test M-only/M-U transitions, illegal/ECALL/EBREAK and alignment faults, implicit CSRs, suppressed effects and explicit breakpoint-MTVAL reconciliation. | Verify precise exception behavior end to end while preserving strict no-trap defaults and distinguishing permitted implementation choices from architectural mismatches. | Implemented; Sections 2.6 and 2.8; IRQ synchronization added under D-299/D-300; broader CSR/bus/PMP comparison open |
| D-299 | Add ELF-bound deterministic IRQ stimuli, independent native masking/priority/drain checks and Spike v3 delivery alignment through a qualified verification device; retain full input/entry evidence and check architectural state without inventing retirement. | Compare asynchronous behavior at valid instruction boundaries while checking native timing independently; keep platform MMIO controllers outside the core and SDK/tool provenance explicit. | Implemented initial software/timer/external IRQ profile; Section 2.8; MIP/counters extended by D-300; Spike WFI comparison remains open |
| D-300 | Check native counters on every clock edge and use verified model pre-state plus sampled MIP inputs for Spike v4 CSR execution; retain validated timing/replay evidence and counter/MIP metrics. | Verify native timing independently while comparing instruction semantics across different execution timing; preserve original target instructions/results and independently checked interrupt delivery. | Implemented; Section 2.8; counter software/IRQ regressions and corruption checks; full CSR/WARL and Spike WFI comparison remain follow-ups |
| D-305 | Extend pinned Spike ELF checking to scalar RV32I/E Zfinx, independent FP CSR snapshots and observed third-source/effective-rounding companions; add directed ISA programs and descriptive coverage/report artifacts. Correct boundary underflow in the adapter and exact oracle. | Check instruction semantics independently of the native arithmetic model and expose shared assumptions. | Implemented; Section 2.10; native E high-register probes remain separate due to pinned Spike behavior; certification/formal FP proofs open |
