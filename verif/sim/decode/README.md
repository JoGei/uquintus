# Native instruction decoder

[uqu_decoder.v](../../../src/uquintus/uqu_decoder.v) is a combinational component
for the future DE stage. It accepts an expanded 32-bit instruction and emits
native recognition, register use, immediate values and normalized execution
controls. There is no clock, reset, handshake, instruction storage or branch
execution. Stable input produces stable output.

## Ownership and integration

| Block | Responsibility |
| --- | --- |
| DE-owned decoder | Instruction recognition, static encoding/configuration legality, register-use/destination intent, immediate extraction, EX/MEM/WB and system controls. |
| DE operand selection | Read GPR values through core-owned storage; select forwarded values, register/immediate/PC operands, CSR source and effective rounding mode. |
| DE branch/target unit | Compare conditional branches; calculate branch/JAL/JALR targets and PC+instruction-length link; check target alignment. Implemented separately by [uqu_branch](../branch/README.md). |
| DE XIF issue logic | Parallel extension recognition, source delivery, acceptance and per-slot issue tracking; interpret native decode alongside extension responses. Not implemented here. |
| Core parent | GPR file, current privilege/Debug Mode, pipeline boundary registers/identity, shared hazards/forwarding, controller/draining and redirects. |
| WB/CSR unit | CSR address/access checks and precise updates, native/custom retirement and architectural debug state. |

A test fixture is a verification-only enclosing module; it is not the production
core. The future DE stage will own neither IF/DE nor DE/EX boundary registers.

## Native legality

`native_o` means the instruction's encoding belongs to a configured native
operation. `illegal_o` means it cannot execute as a legal native operation.
`illegal_reg_o` identifies E-mode register violations on a recognized native
encoding. Thus native=1/illegal=1 is possible and must remain a core exception;
it must not become an opportunity to override a native instruction through XIF.

When native=0, illegal=1 expresses the native decoder's outcome; with XIF enabled
DE must combine it with the coprocessor response before declaring an instruction
illegal. Extension recognition runs in parallel, independently of the native
unsupported result/issue-valid signal. The decoder has no XIF channel or ID
state. DE must also validate registers actually used by an extension before
accepting offload.

All operational outputs are deterministic inactive controls on illegal input:
FU_PASS, zero operands, no source/destination intent, LSU access, branch, CSR
or system action. Native recognition/register-error reports remain visible.
The parent must retain original instruction bits separately for exception tval.
Decode alone does not initiate execution, retire or raise an architectural trap.

Parameters are ISA_E, ISA_M, ISA_ZFINX, ISA_ZIFENCEI, ISA_F, ISA_A and DEBUG.
Full-F/atomic support remains deferred; nonzero ISA_F/ISA_A and invalid boolean
parameters fail elaboration. M, Zfinx, FENCE.I and DRET recognition require their
feature switches. Zicsr and base FENCE are mandatory. ECALL/EBREAK/MRET/WFI use
canonical SYSTEM encodings. Disabled/unsupported encodings report non-native.

RV32E checks only fields used as registers, including rd even when its value
would otherwise be discarded. CSR immediate bits, shift amounts, conversion
selectors, and ignored fence fields do not count as GPR operands. Source-use
bits include used x0 operands; hazards must exclude x0 separately. Destination
intent likewise remains set for instructions with rd=x0; WB suppresses storage
writes without suppressing load faults, FP flags or other required effects.

## Shared encodings

[uqu_isa.vh](../../../src/uquintus/uqu_isa.vh) is the canonical architectural
header: major opcodes, funct3/funct7 values, canonical SYSTEM words and FP
format/rounding selectors. [uqu_ctrl.vh](../../../src/uquintus/uqu_ctrl.vh)
defines internal FU, operand/source-use, branch, WB/system, ALU and FPU codes.
Names use the UQU_ prefix and explicit widths; both headers have include guards
and use synthesizable Verilog-2005 macros. EX, WB and ALU consume the relevant
shared control definitions, preventing independent numeric copies.

The decoder uses symbolic encoding tests and named FP operation selection.
Bit slices, zero padding, booleans and inactive zero payloads remain literals.
The independent mask/match test model intentionally keeps its own ISA values
so an incorrect RTL macro cannot silently change the expected answer.

Bender declares the common header directory. The Make runner obtains include
paths from Bender's selected source tree for both lint and simulation and records
header hashes with each run. Headers are included, not compiled as modules.
Hardware configuration selectors still use the separately generated
uqu_config.vh from config/selectors.json.

## Outputs and selectors

| Ports | Meaning |
| --- | --- |
| `rs_used_o[2:0]`, `rs1_o[4:0]`, `rs2_o[4:0]`, `rs3_o[4:0]` | Bit 0/1/2 selects native rs1/rs2/rs3. Unused addresses are zero. Native third source is the R4 bits 31:27 of Zfinx fused operations. |
| `rd_we_o`, `rd_o[4:0]` | Native destination intent and address; address zero for nonwriters. |
| `imm_o[31:0]` | Sign-extended I/S/B/J or upper U immediate. Shift immediates are zero-extended shamt; CSR immediate forms produce unsigned zimm. |
| `fu_o[1:0]`, `op_o[4:0]` | EX-compatible FU and normalized operation below. |
| `a_sel_o[1:0]` | 0=rs1, 1=PC, 2=zero; selector 3 reserved. |
| `b_sel_o[1:0]` | 0=rs2, 1=immediate, 2=zero; selector 3 reserved. |
| `pass_link_o` | For JAL/JALR, DE supplies PC+original instruction length as EX pass_data. Other pass tokens need no result. |
| `branch_o[1:0]`, `branch_op_o[2:0]` | 0=none, 1=conditional, 2=JAL, 3=JALR. Conditional operation is the instruction funct3; otherwise zero. |
| `lsu_o`, `mem_we_o`, `mem_op_o[2:0]` | Integer load/store intent and funct3. EX computes base+offset with ADD; rs2 store data remains a separate operand. |
| `wb_kind_o[2:0]` | Existing WB classes: 0=result/nonwriter, 1=CSR, 2=MRET, 4=DRET, 5=EBREAK. DE selects 3 separately for accepted XIF instructions. |
| `system_o[2:0]` | 0=none, 1=ECALL, 2=EBREAK, 3=MRET, 4=DRET, 5=WFI, 6=FENCE, 7=FENCE.I. |
| `serialize_o` | CSR, fences, returns and ECALL/EBREAK require serialization/younger-execution containment. WFI remains a baseline no-op subject to runtime permissions. |
| `csr_addr_o[11:0]`, `csr_op_o[2:0]`, `csr_imm_o` | CSR address, original funct3 and immediate-source flag. Zero for other instructions. |
| `rm_o[2:0]` | Static FP rounding mode or 7=dynamic. DE resolves dynamic frm before EX issue; non-rounding operations use zero. |

FU codes are ALU=0, MULDIV=1, FPU=2, PASS=3, matching
[EX](../ex/README.md). ALU operation codes match the
[ALU table](../alu/README.md); bit 30 of a non-shift immediate never selects SUB.
MULDIV operation equals funct3. FPU codes match the
[scalar FPU table](../../../doc/uqu_spec.arch.md#331-unimplemented-fpu-interface).
LUI/AUIPC and LSU addresses use ALU ADD; branches/jumps and system/CSR tokens
use FU_PASS. Nonwriters never acquire an accidental rd from immediate bits.

With ISA_ZFINX=1 all 22 scalar computation/compare/classify/conversion encodings
are recognized, including the four three-source fused forms. FLW/FSW and both
FMV transfer encodings are excluded. Static rounding codes 5/6 and non-FP32
formats are rejected. Decoder support does not implement an FPU: the existing
EX endpoint still refuses enabled Zfinx elaboration until a backend is supplied.

## Work remaining in DE/core

The decoder takes no PC, privilege, debug, CSR data or register values. DE/core
must apply ECALL privilege-specific causes, MRET/DRET permission checks,
WFI/TW policy, dynamic frm validation and fetch/decompression faults. The
[branch unit](../branch/README.md) supplies target-alignment diagnostics; DE
converts them into precise exception metadata. CSR address/privilege/read-only checks remain in the CSR unit at WB;
even an unmapped CSR address is structurally a native CSR instruction.
EBREAK reaches WB as its own class so debug-break controls can select debug
entry versus a breakpoint trap. No interrupt/debug entry is generated here.

IF must expand compressed instructions first and retain original bits and
length for faults/link computation. Raw compressed or longer instruction
encodings are not supported by this 32-bit decoder. ISA_C therefore does not
change its interface or decoding rules.

## Component verification

```sh
make test COMPONENT=decode CONFIG=rv32i
make test COMPONENT=decode CONFIG=rv32im
make lint COMPONENT=decode CONFIG=rv32i
```

The [manifest](../../../config/sim/decode.yml) uses the existing Make/Bender
runner and cocotb/pyuvm stack. The local [ISA model](decode_model.py) uses an
independent mask/match table rather than the RTL opcode-case structure.

- `directed`: every supported native operation, register/ignored-field
  boundaries, fixed-bit mutations, sign/shamt/zimm distinctions and excluded
  Zfinx transfer instructions; checks that every enabled variant is exercised.
- `encodings`: complete funct7/funct3 sweeps of eight instruction families,
  every opcode/funct3, unary/conversion subcodes, fused format/rm/third-source
  combinations and immediate-layout bits.
- `randomized`: 32,768 mixed uniform, instruction-shaped and mutated words,
  checking every output with reproducible stimulus.

Development regressions exercise I/E, M on/off, independent Zfinx/control
features and combined feature profiles. Lint parses Verilog-2005. Yosys checks
that the decoder has no flops, latches or inferred memories.

Encoding references: [RISC-V opcode definitions](https://github.com/riscv/riscv-opcodes/tree/master/extensions),
[Zfinx 1.0](https://docs.riscv.org/reference/isa/v20260120/unpriv/zfinx.html),
and [Zicsr 2.0](https://docs.riscv.org/reference/isa/v20260120/unpriv/zicsr.html).
