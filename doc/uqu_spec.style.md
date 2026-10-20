# uquintus RTL Style Guide

**Status:** First specification draft finalized, 2026-10-20

## 1. Scope

This guide defines RTL language, coding, naming, and common interface
conventions. Use it alongside the
[specification index](uqu_spec.md#document-index) for the architecture,
interfaces, verification, and build requirements. Imported IP may retain its
upstream conventions under the exception in Section 2.

Only conventions explicitly marked **agreed** are requirements. **Proposed**
examples remain open, and **TBD** means no decision has been made. Moving a
rule into this guide does not change its agreement status or processor behavior.
Conventions and examples without an explicit agreement marker remain proposed;
they do not finalize additional parameter names, module boundaries, or OBI
signals.

## 2. Language and source files

**Status:** Agreed

All project-owned synthesizable design files shall use plain Verilog-2005
(IEEE 1364-2005).
Module source files shall use the `.v` extension; included Verilog headers may
use `.vh`. This requirement shall include the core, synthesizable
wrappers, and protocol adapters. SystemVerilog is allowed for verification and
testing. Imported third-party IP and its required dependencies may retain
synthesizable SystemVerilog, including upstream packages, types, and source
extensions. This exception shall not extend to project-owned RTL or wrappers.

Design builds shall parse project-owned RTL as Verilog-2005 without relying on
a SystemVerilog parser mode, and imported SystemVerilog with a suitable frontend.
Source/dependency metadata shall distinguish the language requirements.
Imported IP may retain its upstream coding and naming conventions; project-owned
integration logic shall follow this guide. Exact tool versions and the handling
of imported SystemVerilog in each flow remain TBD. Allowing its language shall
not imply that a particular IP implementation or tool combination is supported.

## 3. Identifiers and symbols

**Project short form:** Agreed. Use `uqu` as the short form of `uquintus` for
project-owned RTL identifiers and source-file prefixes. Module names shall use
`uqu_`, with matching filenames such as `uqu_core.v`. The uppercase form
`UQU_` shall prefix shared macros and include guards. The full project name
remains `uquintus`.

**Symbolic constant casing:** Agreed. Use `UPPER_SNAKE_CASE`, such as
`BP_NONE` and `CTRL_IDLE`.

**Shared selector constants:** Agreed. Use generated `.vh` headers containing
integer-valued `` `define `` macros and unique include guards. Shared macro and
guard names shall use the `UQU_` prefix, for example
`UQU_BP_NONE`, `UQU_BP_STATIC_NOT_TAKEN`, `UQU_RF_FF`, and
`UQU_RF_LATCH`. Modules shall include the header where those encodings
are needed, including parameter defaults and constant comparisons. Headers
shall be Verilog-2005 include files, not separately compiled modules or
SystemVerilog packages. Their constants are expanded during preprocessing and
shall be valid in synthesizable RTL. See the
[Yosys Verilog frontend documentation](https://yosyshq.readthedocs.io/projects/yosys/en/latest/cmd/index_frontends.html#read-verilog-read-modules-from-verilog-file).
The [shared-configuration specification](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets)
defines the canonical selector definition and mapping requirements.

**Parameter casing:** Agreed. All `parameter` and `localparam` names shall use
`UPPER_SNAKE_CASE`. The ISA configuration parameters include `ISA_E`, `ISA_M`, `ISA_C`, `ISA_ZFINX`, `ISA_F`,
`ISA_UMODE`, `ISA_ZIFENCEI`, and `ISA_PMP`.

**ISA parameter prefix:** Agreed. Prefix ISA and privilege configuration
parameters with `ISA_`, including `ISA_E`, `ISA_M`, `ISA_C`, `ISA_ZFINX`, `ISA_F`, `ISA_UMODE`,
`ISA_ZIFENCEI` and `ISA_PMP`. Use these names in RTL declarations,
named overrides, and the shared hardware configuration files. Architectural extension names,
privilege modes, and `misa` field names shall follow the standard ISA spelling.

**Microarchitecture parameter prefix:** Agreed. Prefix externally configurable
microarchitecture parameters with `MUA_` (Micro-Architecture). The supported
parameters, choices, and defaults are defined in the
[processor configuration catalog](uqu_spec.arch.md#22-microarchitecture-configuration-parameters).
Project-specific CV-X-IF configuration parameters shall use the `XIF_` prefix,
including `XIF_NUM_RS` and `XIF_DUALWRITE`; the feature-enable switch is `XIF`.
Other external-interface parameters retain their established names, including
`DEBUG`.

**Parameter roles:** Agreed. Use `parameter` for supported configuration options
and `localparam` for internal constants and derived values, including state and
mode encodings. A derived `localparam` may depend on configuration parameters;
its value shall follow those parameters without being directly overridable.

**Module instance prefix:** Agreed. Use `u_`, such as `u_decode` and
`u_gpregfile`.

**Module instantiation connections:** Agreed. RTL module instantiations shall
use explicit named port connections, such as `.clk_i(clk_i)`, and named parameter
overrides, such as `#(.ISA_M(1))`. Positional port connections and positional parameter
overrides shall not be used.

**Explicit net declarations:** Agreed. Each project RTL module source file shall begin
with the Verilog directive `` `default_nettype none `` and restore
`` `default_nettype wire `` at its end. All nets shall be explicitly declared;
implicit nets are prohibited. This complements the requirement for explicit
named module connections above.

**Signal and module casing:** Agreed. Use `lower_snake_case`, such as
`de_branch_taken` and `uqu_core`.

**Module and file naming:** Agreed. Prefix project RTL module names with
`uqu_`. Each synthesizable module shall reside in its own `.v` file whose
base name matches the module name, such as `uqu_decode` in
`uqu_decode.v`. Other conventions in the table remain proposed unless
explicitly agreed above or elsewhere in this guide or the processor specification.

| Category | Convention | Examples |
| --- | --- | --- |
| Modules and files | Lower snake case; project modules use `uqu_`; one synthesizable module per matching `.v` file. | `uqu_core`, `uqu_core.v` |
| Instances | Lower snake case with `u_` prefix. | `u_decode`, `u_gpregfile` |
| Signals and ports | Lower snake case; use stage or interface prefixes where they clarify ownership. | `de_branch_taken`, `dmem_addr_o` |
| Configuration parameters | Upper snake case; ISA/privilege parameters use `ISA_`, microarchitecture parameters use `MUA_`. | `ISA_E`, `ISA_M`, `ISA_C`, `ISA_ZFINX`, `ISA_F`, `ISA_UMODE`, `ISA_ZIFENCEI`, `MUA_FORWARDING`, `MUA_BRANCH_PREDICTOR`, `MUA_REGFILE_IMPL`, `XIF`, `DEBUG` |
| Symbolic constants | Upper snake case; group by function. Use Verilog `localparam` for state and mode constants. | `CTRL_IDLE`, `BP_NONE`, `BP_STATIC_NOT_TAKEN` |
| Loop and generate indices | Short local names for small loops; descriptive names for broader scope. | `i`, `reg_idx`, `gen_stage` |

Prefer familiar architectural terms such as `pc`, `instr`, `imm`, `rs1`, `rs2`,
`rd`, and `csr`. Avoid adding prefixes solely to distinguish Verilog `wire` and
`reg` declarations.

## 4. Port direction and polarity

**Port direction suffixes:** Agreed. Use `_i`, `_o`, and `_io`; combine an
active-low marker with the direction suffix as in `rst_ni`.

Directions are relative to the module declaring the port. Keep direction as the
final suffix; combine the active-low marker with the direction suffix.

| Meaning | Convention | Examples |
| --- | --- | --- |
| Input | `_i` | `clk_i`, `boot_addr_i` |
| Output | `_o` | `imem_req_o`, `dmem_wdata_o` |
| Bidirectional port, where required | `_io` | `pad_io` |
| Active-low input or output | `_ni`, `_no` | `rst_ni` |
| Active-low internal signal | `_n` | `request_n` |

Prefer active-high internal controls. An `_n` marker describes polarity, not
reset timing; the [reset specification](uqu_spec.interfaces.md#3-active-low-synchronous-reset)
defines `rst_ni` as synchronous.

Next state shall use `_d`; `_n` shall not denote next state. The polarity
convention proposed here reserves `_n` for active-low signals.

## 5. Pipeline stages and register state

**Pipeline-stage prefixes:** Agreed. Use `if_`, `de_`, `ex_`, `mem_`, and `wb_`
for fetch, decode, execute, memory, and write back, respectively. Use `de_`
consistently in RTL for the stage also called ID in the architecture description.

**Internal register-state suffixes:** Agreed. Use `_q` for the stored value and
exclusively `_d` for the next value presented to the register. These suffixes
correspond to a flip-flop's Q output and D input.

Use `imem_` and `dmem_` as the proposed prefixes for external memory interface
signals; these interface prefixes remain proposed.

| Meaning | Convention | Examples |
| --- | --- | --- |
| Stored internal state | `_q` | `ex_pc_q`, `mem_valid_q` |
| Next value of that state | `_d` | `ex_pc_d`, `mem_valid_d` |
| Combinational result or control | Descriptive name without a storage suffix. | `de_branch_taken`, `de_stall`, `if_flush` |

Stage prefixes describe where a value is used or stored. For example,
`ex_pc_q` is the PC stored for the instruction in EX, and `ex_pc_d` is the
next value loaded into that register. Use `_q` and `_d` for internal state;
module ports retain the direction suffix conventions above.

## 6. Handshakes and control events

**Accepted-transfer event suffix:** Agreed. Use `*_fire` for an accepted
handshake event.

**Internal handshake names:** Agreed. Use `*_valid` and `*_ready`. A transfer
occurs on a clock edge when both are high, with `*_fire` naming the corresponding
`valid && ready` condition. The condition may be asserted on consecutive cycles
when a transfer occurs on each cycle; it does not require a separate registered
pulse. A producer shall assert valid when
its payload is available without waiting for ready, and retain valid and a
stable payload while blocked, except when reset or a defined flush discards
it. Result valid shall not depend on result ready.

**Native execution-unit channels:** Agreed. Use these common signal stems;
module ports shall add the direction suffixes from Section 4.

| Channel | Valid | Ready | Accepted-transfer event | Payload |
| --- | --- | --- | --- | --- |
| Request | `req_valid` | `req_ready` | `req_fire = req_valid && req_ready` | Operation and required operands. |
| Result | `res_valid` | `res_ready` | `res_fire = res_valid && res_ready` | Computed result and applicable status. |

The [execution-unit contract](uqu_spec.arch.md#31-common-native-execution-unit-handshake)
defines instruction ownership, same-cycle completion, result retention, and
flush cancellation. Exact payload widths and status fields remain TBD.

**Pipeline control names:** Agreed. Use `*_stall` to hold a stage and `*_flush`
to discard its instruction.

**Pipeline control priority:** Agreed. Implement the reset/flush/stall priority
and instruction ownership rules in the
[pipeline specification](uqu_spec.arch.md#3-classical-five-stage-pipeline).
The [execution-unit cancellation contract](uqu_spec.arch.md#31-common-native-execution-unit-handshake)
and [memory completion contract](uqu_spec.interfaces.md#1-external-instruction-and-data-memories)
define how affected operations and accepted requests are handled.

At OBI ports, preserve protocol terminology with the `imem_` or `dmem_` prefix:

| Meaning | Proposed examples |
| --- | --- |
| Request and request acceptance | `imem_req_o`, `imem_gnt_i`; internal event `imem_req_fire` for `req && gnt`. |
| Response validity and read data | `imem_rvalid_i`, `imem_rdata_i`; corresponding `dmem_` signals. |
| Data request payload | `dmem_addr_o`, `dmem_we_o`, `dmem_be_o`, `dmem_wdata_o`. |
| Error status; tie low if absent on the connected bus | `imem_err_i`, `dmem_err_i`. |

The [memory-interface specification](uqu_spec.interfaces.md#1-external-instruction-and-data-memories)
defines request acceptance, response completion, optional bus-side error
reporting, and response handling without backpressure. OBI shall retain its
protocol-specific handshake terms. See the
[CORE-V OBI interface example](https://docs.openhwgroup.org/projects/cv32e40p-user-manual/en/latest/load_store_unit.html).

## 7. Assignments and combinational completeness

**Status:** Agreed

Edge-triggered state updates shall use nonblocking assignments (`<=`) in
`always @(posedge clk_i)` blocks. Combinational procedural logic shall use
blocking assignments (`=`) in `always @*` blocks. Continuous `assign` statements
are also permitted for combinational logic. SystemVerilog constructs such as
`always_comb` and `always_ff` shall not appear in project-owned synthesizable
files, consistent with the imported-IP exception in Section 2.

Every output of a combinational procedural block shall receive a value on every
execution path, using defaults or complete conditional assignments. Unintended
latches are prohibited. Assigning a next-state signal its corresponding stored
value as a default is permitted; the storage resides in the clocked register.

Intentional latch storage is permitted within the register-file backend
([register-file specification](uqu_spec.arch.md#17-integer-register-file-implementation)).
Such latch blocks or cell instances shall be explicitly identified and
documented as storage, rather than ordinary combinational
logic. This exception does not relax completeness requirements for combinational
datapath or control blocks. Synthesizable wrappers shall remain plain Verilog.

These rules do not require a separate combinational next-state block for every
register. A clocked block may express its state update directly using nonblocking
assignments.

## 8. Style decision record

Decision IDs are shared across the [specification set](uqu_spec.md#document-index).
Gaps in this record are intentional; IDs have not been renumbered.

| ID | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-009 | Require plain Verilog for all synthesizable files; allow SystemVerilog for verification and testing. | Establish the language boundary between synthesizable design and verification code. | Updated by D-238: imported IP and its dependencies may use synthesizable SystemVerilog |
| D-029 | Use direction suffixes for module ports, such as `clk_i`, `rst_ni`, and `imem_req_o`. | Place direction information at the end of port names. | Agreed |
| D-030 | Use `mem_` for the memory pipeline stage and `*_fire` for accepted handshake events. | Establish the memory-stage prefix and handshake-event naming. | Agreed |
| D-031 | Use `_q` for stored internal state and exclusively `_d` for its next value. | Match the Q output and D input of a flip-flop. | Agreed |
| D-032 | Use `UPPER_SNAKE_CASE` for symbolic constants. | Distinguish symbolic constants from other identifiers. | Agreed |
| D-033 | Prefix module instance names with `u_`, such as `u_decode` and `u_gpregfile`. | Identify module instances consistently. | Agreed |
| D-034 | Use `lower_snake_case` for signals and module names. | Keep RTL identifiers readable and consistent. | Agreed |
| D-035 | Use `if_`, `de_`, `ex_`, `mem_`, and `wb_` as the pipeline-stage prefixes. | Identify the stage associated with each pipeline signal consistently. | Agreed |
| D-036 | Use `*_valid` and `*_ready` for internal handshakes, with `*_fire = *_valid && *_ready`. | Name the offered data, acceptance capability, and accepted-transfer condition consistently. | Agreed |
| D-037 | Use `*_stall` to hold a pipeline stage and `*_flush` to discard its instruction. | Distinguish holding an instruction from invalidating it. | Agreed |
| D-039 | Prefix project RTL module names with `uquintus_` and place each synthesizable module in its own matching `.v` file. | Keep module ownership and source locations explicit. | Prefix superseded by D-253; matching module/file naming retained |
| D-040 | Use `UPPER_SNAKE_CASE` for all `parameter` and `localparam` names, including ISA parameters `ISA_E`, `ISA_M`, `ISA_C`, and `ISA_F`. | Apply a consistent naming convention to elaboration-time constants. | Agreed |
| D-041 | Use `parameter` for supported configuration options and `localparam` for internal constants and derived values. | Expose intentional configuration while preventing direct overrides of implementation constants. | Agreed |
| D-042 | Use explicit named port connections and named parameter overrides in RTL module instantiations. | Keep connections and configuration readable and independent of declaration order. | Agreed |
| D-043 | Require explicit net declarations with `default_nettype none` in project RTL files, restoring `default_nettype wire` at each file's end. | Catch undeclared or misspelled signal names and keep the directive's effect contained. | Agreed |
| D-044 | Use nonblocking assignments for edge-triggered state and blocking assignments in combinational procedural logic; allow continuous assignments and prohibit unintended latches. | Model synchronous state consistently and prevent unintended storage and assignment races. | Agreed; intentional register-file latch exception defined in D-102 |
| D-102 | Permit intentional register-file latch storage as an explicit coding-convention exception, isolated and documented with its timing and clock control. | Allow a latch backend while continuing to prohibit unintended storage in combinational logic. | Agreed |
| D-114 | Standardize all synthesizable design files on Verilog-2005 (IEEE 1364-2005), using `.v` files parsed in Verilog-2005 mode; permit SystemVerilog for verification and testing. | Make the agreed plain-Verilog language boundary explicit and checkable across implementation tools. | Project-owned RTL rule retained; imported-IP exception added by D-238; exact tool versions TBD |
| D-135 | Prefix microarchitecture configuration parameters with `MUA_`; name the initial controls `MUA_FORWARDING`, `MUA_BRANCH_PREDICTOR`, and `MUA_REGFILE_IMPL`. | Identify microarchitecture choices consistently within the hardware parameter set. | Agreed; predictor and register-file selector encodings TBD |
| D-136 | Prefix ISA and privilege configuration parameters with `ISA_`: `ISA_E`, `ISA_M`, `ISA_C`, `ISA_F`, `ISA_UMODE`, and `ISA_ZIFENCEI`. | Identify software-visible ISA and privilege selections consistently alongside the `MUA_` namespace. | Agreed; architectural extension and CSR field names retain their standard spelling |
| D-238 | Allow synthesizable SystemVerilog for imported third-party IP and its required dependencies while retaining plain Verilog-2005 for all project-owned RTL, wrappers, and adapters. | Permit reuse of units such as CVFPU without changing the language convention for uquintus-owned design code. | Agreed; IP selection and compatible tool frontend integration remain open |
| D-253 | Define uqu as the project short form; use uqu_ for project-owned RTL modules and matching source filenames, such as uqu_core.v, and UQU_ for shared macros and include guards. | Keep RTL names concise while retaining uquintus as the full project name. | Agreed; updates the earlier module prefix in D-039 |
