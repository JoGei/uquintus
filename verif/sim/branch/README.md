# DE branch resolution unit

[uqu_branch.v](../../../src/uquintus/uqu_branch.v) is a stateless DE component
for six integer branch conditions, JAL and JALR target calculation, jump links
and target-alignment diagnostics. It uses the shared
[control](../../../src/uquintus/uqu_ctrl.vh) and
[ISA](../../../src/uquintus/uqu_isa.vh) macros. There is no clock, handshake,
pipeline storage, prediction, BTB, architectural update or redirect event.

## Inputs

| Port | Contract |
| --- | --- |
| `branch_i[1:0]` | Decoder branch selector: UQU_BR_NONE, UQU_BR_COND, UQU_BR_JAL or UQU_BR_JALR. |
| `branch_op_i[2:0]` | Conditional branch funct3: BEQ/BNE/BLT/BGE/BLTU/BGEU. Ignored for NONE and jumps. |
| `pc_i[31:0]` | Current instruction's PC, retained by the parent. |
| `imm_i[31:0]` | Fully expanded, sign-extended byte offset from the decoder. B/J offsets already contain their low zero bit; do not shift them again. |
| `rs1_i[31:0]`, `rs2_i[31:0]` | Resolved/forwarded source values. Conditional comparisons use both; JALR uses rs1 as the target base. |
| `compressed_i` | Original instruction was two bytes, even though the decoder saw an expanded 32-bit encoding. With ISA_C=1 selects a two-byte link/fallthrough increment; otherwise increment is four bytes. |

ISA_C is the sole parameter, default 0. Nonboolean settings fail elaboration.
A compressed length flag with ISA_C=0 reports an illegal normalized control.
IF/decompression owns validation of the original encoding and incoming PC;
this unit does not re-decode instructions or check the current PC's alignment.

## Results

| Port | Contract |
| --- | --- |
| `taken_o` | Requested control transfer: condition true, JAL or JALR. Zero for NONE/illegal controls. Remains true on target misalignment; it is branch intent, not permission to redirect. |
| `target_o[31:0]` | PC+offset for a conditional branch/JAL; (rs1+offset) with bit 0 cleared for JALR. Retained for a non-taken conditional branch and for a misaligned target. Zero for NONE/illegal controls. |
| `next_pc_o[31:0]` | Nonfaulting taken target or sequential PC+instruction length. Holds pc_i on illegal/misaligned controls. This is a candidate, not an architectural PC update. |
| `link_o[31:0]` | PC+original instruction length for nonfaulting JAL/JALR; otherwise zero. DE selects it as EX pass_data when decoder pass_link is set. Register destination/write intent remains in the decoder/parent. |
| `illegal_o` | Reserved conditional funct3 (2/3), or a compressed length flag when C is disabled. No jump/NONE fault solely because of an unused branch_op value. |
| `misaligned_o` | A non-illegal taken transfer has a target violating IALIGN: four-byte alignment with C disabled, two-byte alignment with C enabled. Never set for a non-taken conditional branch. |

All additions wrap modulo 2^32. JALR clears bit 0 **after** adding the signed
offset and before checking alignment; bit 1 is preserved. With ISA_C=1 a 32-bit
instruction may start/target a halfword boundary and still has a four-byte link
increment. A compressed jump has a two-byte link increment. No GPR address is
needed: x0 destination suppression belongs downstream.

One target adder selects PC or rs1 as base. A separate constant-increment path
computes fallthrough/link. One unsigned magnitude comparison plus a sign-bit
selection provides both signed and unsigned less-than; equality is shared by
BEQ/BNE. None of this arithmetic borrows the EX ALU, since DE and EX may process
different instructions simultaneously.

## DE/core integration

The decoder's branch_o, branch_op_o and imm_o connect directly. The parent
provides PC/original length and the hazard/forwarding-selected source values.
The combinational unit can evaluate while DE is stalled. DE must wait for all
required operands and consume resolution only once with the instruction's
accepted DE-to-EX transfer, subject to global arbitration and older fault
priority. A continuously asserted taken_o must not repeatedly redirect fetch.

DE converts misaligned_o into instruction-address-misaligned metadata (cause 0),
with the instruction PC for mepc and target_o for tval. It converts illegal_o
into illegal-instruction metadata (cause 2), using the original instruction
bits for tval. Existing fetch/decode exceptions retain priority. Either fault
prevents ordinary jump writeback/redirect and follows the normal WB trap path;
this unit does not directly update CSR state. The held next-PC/link outputs on
fault are defensive values, not substitutes for checking the flags.

Frontend prediction/BTB state belongs in IF. The core/DE integration may compare
the carried predicted next PC with this unit's nonfaulting next_pc_o and request
correction. Predictor training, misprediction handling and validity/transfer
qualification remain outside this unit. Serialized trap/debug returns use their
WB redirect path rather than treating BR_NONE's sequential result as a return
address. The enclosing uqu_stage_de remains to be implemented.

## Verification

```sh
make test COMPONENT=branch CONFIG=rv32i
make lint COMPONENT=branch CONFIG=rv32i
```

Repeat with a complete hardware YAML configuration setting ISA_C: 1 for the
compressed-enabled profile. No predictor configuration is needed.

The [manifest](../../../config/sim/branch.yml) uses the common Make/Bender and
cocotb/pyuvm flow. The local [wrapper](uqu_branch_tb.v) tests one direct instance
and a sibling fed by the real decoder; it is verification-only logic. The
[test model](test_uqu_branch.py) uses mathematical signed comparisons, modulo
arithmetic and alignment division independently of RTL comparator sharing.

- `directed`: all comparison conditions, signed/unsigned boundaries, reserved
  funct3, ignored jump/NONE fields, negative offsets, address wrap and repeated
  evaluation while a parent would be holding DE.
- `alignment`: target low bits, taken/non-taken cases, JALR clearing order,
  four-/two-byte alignment, original instruction lengths and invalid C metadata.
- `randomized`: 32,768 independently varied branch controls, PCs, offsets,
  source words and compressed flags.
- `decoder`: actual B/J/I immediate decoding, all branch funct3 values,
  jump destination variants, compressed-length metadata and non-control tokens.

All four suites run with C disabled/enabled. Yosys checks retain no state,
latches or memories in the branch unit, with one magnitude comparator and two
addition paths. Lint uses Verilog-2005.

Semantics: [RV32I control transfers and instruction alignment](https://docs.riscv.org/reference/isa/v20260120/unpriv/rv32.html),
[compressed control transfers](https://docs.riscv.org/reference/isa/v20260120/unpriv/c-st-ext.html),
and [project DE resolution contract](../../../doc/uqu_spec.arch.md#6-resolve-branches-and-jumps-in-decode).
