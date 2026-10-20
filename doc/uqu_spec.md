# uquintus Processor Specification

**Status:** First specification draft finalized, 2026-10-20

**Project:** uquintus, a configurable RV32 RISC-V processor

**Short form:** `uqu`; RTL naming is defined in the [style guide](uqu_spec.style.md#3-identifiers-and-symbols).

This overview records the project's scope, design principles, first implementation
milestone, and documentation index. The first-draft architectural baseline is
complete for implementation planning; remaining implementation and integration
work is explicitly tracked in the topic documents.

Only decisions explicitly marked **agreed** are requirements. Proposed principles
and layouts retain their proposal status. **TBD** means an unresolved follow-up;
it does not grant permission to change an agreed architectural contract.

The repository contains specifications and standalone
[register-file](../verif/sim/gpregfile/README.md),
[shared arithmetic](../verif/sim/arith/README.md),
[base integer ALU](../verif/sim/alu/README.md),
[EX stage](../verif/sim/ex/README.md), and
[native multiply/divide](../verif/sim/muldiv/README.md) components with a common
simulation/lint flow and a [shared-parent arithmetic fixture](../verif/sim/exec_arith/README.md).
A [parent-register fixture](../verif/sim/ex_pipeline/README.md) verifies EX
with DE/EX and EX/MEM registers outside the stage. Their guides describe
implementation and test scope.
The complete processor, full-core verification, and ASIC build flow
remain to be implemented.

## Document index

| Document | Authoritative scope |
| --- | --- |
| [Overview](uqu_spec.md) | Purpose, principles, scope, implementation milestones, and first-draft status. |
| [Architecture](uqu_spec.arch.md) | ISA and microarchitecture together: parameters, pipeline, arithmetic, hazards, privilege, PMP, traps, CSRs, and memory-instruction semantics. |
| [Interfaces](uqu_spec.interfaces.md) | Clock/reset, native OBI ports, interrupts, CV-X-IF, debug, fence handshakes, hart identity, and the baseline port index. |
| [Verification](uqu_spec.verif.md) | Pipeline visibility, trace/RVFI, Spike comparison, formal checking, randomized memory tests, and CI coverage. |
| [Build](uqu_spec.build.md) | Bender/Make, configurations, simulation backends, ORFS, environment provisioning, and project/file layout. |
| [RTL style](uqu_spec.style.md) | Language rules, imported-IP exception, names, coding conventions, and common handshakes. |

Each detailed requirement has one topic home; other documents link to it.
Decision IDs are globally unique across these files and retain their existing
numbers. Gaps in a document's local record are intentional. Superseded and
deferred decisions are retained as history, not active feature requirements.

## 1. Purpose and scope

| Topic | Current definition | Status |
| --- | --- | --- |
| Instruction set family | RISC-V | Agreed |
| Integer register width | RV32 only; fixed `XLEN = 32`. | Agreed |
| Base ISA | RV32I by default; optional RV32E selected through `ISA_E`; Zicsr 2.0 is always implemented, with additional ISA extensions selected through RTL parameters. | Agreed |
| Primary purpose | Serve as a useful reference core with a clear design and visibility into software execution. | Agreed |
| Additional purpose | Support architectural experimentation. | Agreed |
| Initial software environment | Bare-metal software with mandatory machine mode and optional user mode selected by `ISA_UMODE`; `ISA_UMODE = 1` by default. | Agreed |
| Intended applications and workloads | TBD | Open |
| Target implementation platform | ASIC | Agreed |
| Initial process targets | SkyWater SKY130 and IHP SG13G2 (130 nm). | Agreed |
| Possible later process targets | Predictive PDKs such as ASAP7. | Future option |
| Implementation flow | Open-source flows, including OpenROAD for physical implementation. | Agreed |
| Clocking | Single clock domain. | Agreed |
| Default reset | Active-low, synchronous; minimal documented coverage of architectural, control, and pipeline state. | Agreed |
| First implementation's scope | Default RV32I configuration with M/U privilege modes and forwarding; optional ISA extensions, XIF, and debug follow later ([overview, Section 3](uqu_spec.md#3-first-implementation-milestone)). | Agreed |
| Core boundary | Processor pipeline with separate external instruction and data memory interfaces and machine interrupt inputs; memories, timer, and interrupt controller are outside the core. | Agreed |
| Advanced interrupt support | CLIC/ACLIC support is outside this draft's scope; any future support requires a separate design decision ([interfaces, Section 4](uqu_spec.interfaces.md#4-external-machine-interrupt-sources)). | Agreed |
| Other explicit non-goals | TBD | Open |

## 2. Design principles

### 2.1. Prefer understandable designs

**Status:** Agreed

The core shall have a clear, understandable design suitable for reference use.
Prioritize a clear connection between executed software, pipeline behavior, and
the RTL that implements it.

Favor structures with clear responsibilities and explicit interfaces. Added
complexity should solve a documented problem and have a benefit we can evaluate.

### 2.2. Make correctness verifiable

**Status:** Agreed

Define observable behavior alongside each feature, including relevant corner
cases. Plan verification as part of the design, with clear criteria for deciding
when a feature works. Simulation, Spike comparison, formal checks, and CI
requirements are defined in the [verification specification](uqu_spec.verif.md).

### 2.3. Make architectural commitments explicit

**Status:** Proposed

Record the selected RISC-V specification versions, extensions, and execution
environment. Document unsupported features, implementation-defined behavior, and
any deliberate deviations.

### 2.4. Leave PPA optimization primarily to synthesis

**Status:** Agreed

Power, performance, and area (PPA) optimization should primarily be handled by
synthesis. The RTL should still account for the hardware cost of architectural
and coding choices, including resource duplication and long combinational paths.

Design clarity and visibility take priority over aggressive PPA optimization.
Specific PPA targets and implementation constraints remain TBD.

### 2.5. Build in useful increments

**Status:** Agreed

Define a small, coherent first implementation and extend it through verifiable
milestones. Each milestone should have an explicit scope and completion criteria.
The first milestone shall target the default configuration defined in [overview, Section 3](uqu_spec.md#3-first-implementation-milestone); optional ISA extensions, XIF, and hardware debug shall follow later.

### 2.6. Keep decisions and results reproducible

**Status:** Proposed

Document design rationale and the commands, tool versions, and configurations
needed to reproduce verification and implementation results.

### 2.7. Configure ISA extensions and microarchitecture

**Status:** Agreed

Support architectural experimentation within the same RTL design while retaining
clarity and visibility. Organize ISA parameters around software-visible RISC-V
features, such as selecting the complete M extension rather than independently
advertising its execution units. Microarchitecture settings shall preserve the
configured ISA's behavior. The authoritative parameter catalog and defaults are
in [architecture, Section 2](uqu_spec.arch.md#2-isa-and-microarchitecture-configuration-parameters); fixed RV32 width is defined in [architecture, Section 1](uqu_spec.arch.md#1-fixed-32-bit-architecture).

### 2.8. Make software execution observable

**Status:** Agreed

Make software execution observable through correlated pipeline waveforms and
architectural instruction traces. The instruction PC and validity, trace events,
SystemVerilog monitor boundary, and RVFI observation contract are defined in
the [verification specification](uqu_spec.verif.md#1-instruction-identity-and-architectural-trace).
Architectural measurement uses the counters defined in [architecture, Section 12](uqu_spec.arch.md#12-machine-cycle-and-instruction-retirement-counters).

### 2.9. RTL implementation conventions

**Status:** Agreed

Synthesizable RTL and verification sources shall follow the language, coding,
naming, and interface conventions in [uqu_spec.style.md](uqu_spec.style.md).

### 2.10. Support open-source flows and multiple process targets

**Status:** Agreed

Support for open-source ASIC implementation flows shall be a major design goal.
The primary implementation flow shall use open-source tools, including OpenROAD
for physical implementation, and shall not require proprietary tools.

The common RTL shall support implementation on SkyWater SKY130 and IHP SG13G2.
Predictive PDKs such as ASAP7 are possible later targets. Keep process-specific
libraries, constraints, physical configuration, and any required cell mappings
outside the common processor RTL.

Implementation choices, including reset strategy, shall be evaluated against
the selected libraries and flows. Area and timing conclusions shall identify
their target technology and implementation conditions.

ORFS integration, externally provisioned dependencies, and exact tool/PDK
selection are defined in the [build specification](uqu_spec.build.md).

## 3. First implementation milestone

**Status:** Default-configuration milestone and later optional features agreed;
detailed test plan and later milestone ordering TBD

The first implementation milestone shall deliver the default RV32I core with
mandatory Zicsr 2.0 (`rv32i_zicsr`), M-mode and U-mode privilege support, and
operand forwarding enabled. M-mode
privilege support shall not imply the integer multiplication/division extension:
the ISA parameter `ISA_M` shall remain `0` in this milestone.

| Configuration area | First milestone |
| --- | --- |
| ISA and privilege parameters | `ISA_E = 0`, `ISA_M = 0`, `ISA_C = 0`, `ISA_ZFINX = 0`, `ISA_F = 0` (deferred), `ISA_A = 0` (future feature disabled), `ISA_ZIFENCEI = 0`, `ISA_PMP = 0`, `ISA_UMODE = 1`. |
| Custom offload and hardware debug | `XIF = 0`, `DEBUG = 0`; default XIF settings have no active core functionality in this configuration. |
| Pipeline | Single-issue, in-order IF/DE/EX/MEM/WB; base integer ALU operations complete in one EX execution cycle. |
| Dependencies and control flow | `MUA_FORWARDING = 1`, `MUA_FORWARD_EX_TO_DE = 1`, `MUA_FORWARD_MEM_TO_DE = 1`, `MUA_FORWARD_MEM_TO_EX = 1`, and `MUA_FORWARD_WB_TO_EX = 1`; WB-to-DE bypass outside the register file, branch prediction `none`, branch/jump resolution in DE. |
| Instruction-fetch buffer | `MUA_IF_BUFFER_WORDS = 2`; continue filling during downstream stalls subject to capacity and control-flow restrictions; one outstanding fetch request independently of depth. |
| Register file | Default flip-flop backend with combinational DE reads. |
| Hardening | `MUA_HARDENED = 0`; OBI parity/checksum support is a future implementation feature. |
| Multiply/divide parameters | `MUA_MUL = iterative`, `MUA_DIV = iterative`, `MUA_MULDIV_ITERUNROLL = 8`; all explicitly set but inactive with `ISA_M = 0`. |
| Memory interfaces | Separate external 32-bit OBI v1.6.0 instruction/data interfaces, variable latency, one outstanding request per port, reserved response capacity with no response backpressure, blocking MEM, little-endian accesses. |
| External fence synchronization | `fence_req_o`/`fence_ack_i` for data/I/O ordering; retain inactive `fencei_req_o`/`fencei_ack_i` ports with `ISA_ZIFENCEI = 0`. Acknowledge immediately when integration already guarantees the required ordering ([architecture, Section 16](uqu_spec.arch.md#16-optional-instruction-fetch-fence) and [architecture, Section 19](uqu_spec.arch.md#19-conservative-data-memory-fence)). |
| Clock and reset | Single clock, active-low synchronous minimal reset, reset-entry address input. |
| Hart identification | 32-bit `hart_id_i` integration input, readable through `mhartid` ([interfaces, Section 9](uqu_spec.interfaces.md#9-hart-identification-input)). |

The applicable agreed baseline system behavior shall be included: precise traps,
machine interrupts, M/U privilege and CSR behavior, and the specified counters.
Native CSR instructions shall use uniform serialization and WB execution as
defined in [architecture, Section 18](uqu_spec.arch.md#18-native-csr-instruction-execution). `MRET` shall use the serialized WB return policy in
[architecture, Section 18.1](uqu_spec.arch.md#181-serialized-mret-at-wb). Base-ISA `FENCE` shall use the conservative full-barrier
policy in [architecture, Section 19](uqu_spec.arch.md#19-conservative-data-memory-fence). `misa` shall be hardwired to identify the elaborated ISA
as defined in [architecture, Section 2.1](uqu_spec.arch.md#21-hardwired-isa-identification).
The initial processor identification CSRs shall use the zero values defined in
[architecture, Section 20](uqu_spec.arch.md#20-initial-processor-identification-values).
The milestone shall satisfy the simulation and formal verification requirements
in [verification, Section 2](uqu_spec.verif.md#2-simulation-and-formal-verification): architectural comparison against Spike and applicable RV32I
`riscv-formal` checks using RVFI. Simulation shall exercise the baseline pipeline
and system behavior, including dependencies, variable memory latency, control
flow, reset, traps, interrupts, and privilege checks. Formal results shall state
their scope and assumptions; the initial RV32I check scope shall not be treated
as proof of all privileged behavior. The ISA baseline is fixed in [architecture, Section 1](uqu_spec.arch.md#1-fixed-32-bit-architecture)
and OBI v1.6.0 in [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories); the exact test plan, remaining memory-interface
profile, and synthesis/physical-implementation acceptance details remain TBD.

Optional ISA features, PMP, XIF, hardware debug, the latch register-file backend, and
non-default configurations shall follow this baseline. Their agreed overall
requirements remain in force; implementation order and later milestone
acceptance criteria remain TBD.
Atomic-extension support (`ISA_A`) and OBI integrity under `MUA_HARDENED` are
planned future options and shall not be first-milestone requirements.

## 4. First-draft follow-ups

The first draft fixes the baseline behavior and leaves the following work to
implementation or integration. Follow-ups shall preserve agreed behavior and
shall not silently enable a deferred feature.

| Work area | Follow-up home |
| --- | --- |
| Arithmetic algorithms, FPU selection/configuration, module wiring, CSR field mappings, and optional-feature milestone order | [Architecture follow-ups](uqu_spec.arch.md#21-implementation-follow-ups-and-deferred-scope) |
| External memory guarantees, optional IP/DM integration, reset conditioning, and exact optional interface declarations | [Interface follow-ups](uqu_spec.interfaces.md#12-integration-follow-ups) |
| Reference-model/checker revisions, tests, assumptions, RVFI profiles, and CI implementation | [Verification follow-ups](uqu_spec.verif.md#4-verification-follow-ups) |
| YAML schema, selectors, presets, concrete targets, versions, and provisioned environments | [Build follow-ups](uqu_spec.build.md#8-build-follow-ups) |
| Tool-compatible parsing of imported SystemVerilog and backend-specific latch timing | [RTL style guide](uqu_spec.style.md) |

The proposed reproducibility/architectural-commitment principles and directory
subdivisions remain proposals where explicitly marked. A finalized first draft
does not promote them to agreed requirements. Workload selection and quantitative
PPA targets remain open; no numerical target is invented by this revision.

Full F, atomic support, hardening, and the earlier shared-LSU/custom-trap XIF
plans remain deferred under their topic decisions. Packed FP8/FP16 and CLIC/ACLIC
are outside the current scope. The first implementation milestone remains the
default RV32I core; optional features follow later.

## 5. Overview decision record

Decision IDs are shared across the [specification set](uqu_spec.md#document-index).
Superseded and deferred rows preserve history; current topic requirements and
later decisions determine the active contract.

| ID | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-001 | Use the RISC-V instruction set family. | Project direction. | Agreed |
| D-004 | Prioritize a clear, observable reference core while also supporting experimentation. | Make software execution and pipeline behavior easy to inspect and provide a foundation for trying architectural ideas. | Agreed |
| D-005 | Leave PPA optimization primarily to synthesis while considering hardware cost in RTL. | Preserve clarity without ignoring the implementation consequences of design choices. | Agreed |
| D-007 | Select experimental features through RTL parameters within the same design. | Support architectural experimentation in a configurable reference core. | Agreed |
| D-008 | Target an ASIC implementation. | Selected implementation platform. | Agreed |
| D-025 | Target SkyWater SKY130 and IHP SG13G2 initially, with predictive PDKs such as ASAP7 as possible later targets. | Support implementation across multiple process technologies using common processor RTL. | Agreed |
| D-026 | Make open-source ASIC flows a major design goal, using OpenROAD for physical implementation without requiring proprietary tools. | Keep implementation accessible through open-source tooling. | Agreed |
| D-105 | Target the default RV32I configuration with M/U privilege modes, forwarding, and the flip-flop register file for the first implementation milestone; add optional features and non-default configurations afterward. | Establish a coherent baseline before extending the design, validated through the agreed Spike/RVFI simulation and initial RV32I formal checks. | Agreed; detailed test plan and later milestone ordering TBD |
| D-173 | Finalize the first specification draft before splitting it into overview, combined ISA/microarchitecture, interfaces, verification, and build documents alongside the existing style guide; retain decision IDs and agreement statuses. | Establish the documentation boundaries now while deferring file moves until the first draft is complete. | Agreed; first draft finalized and restructuring completed by D-252 |
| D-252 | Finalize the first specification draft and split requirements into overview, combined ISA/microarchitecture, interfaces, verification, build, and style documents, retaining decision IDs and explicit implementation follow-ups. | Make the agreed baseline ready for implementation planning without requiring premature IP, algorithm, wiring, or tool-version choices. | Agreed; implements D-173 |
