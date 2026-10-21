// Architectural RV32 encodings. Keep independent of internal execution codes.
`ifndef UQU_ISA_VH
`define UQU_ISA_VH

// Seven-bit major opcodes.
`define UQU_OPCODE_LOAD     7'h03
`define UQU_OPCODE_MISC_MEM 7'h0f
`define UQU_OPCODE_OP_IMM   7'h13
`define UQU_OPCODE_AUIPC    7'h17
`define UQU_OPCODE_STORE    7'h23
`define UQU_OPCODE_OP       7'h33
`define UQU_OPCODE_LUI      7'h37
`define UQU_OPCODE_MADD     7'h43
`define UQU_OPCODE_MSUB     7'h47
`define UQU_OPCODE_NMSUB    7'h4b
`define UQU_OPCODE_NMADD    7'h4f
`define UQU_OPCODE_OP_FP    7'h53
`define UQU_OPCODE_BRANCH   7'h63
`define UQU_OPCODE_JALR     7'h67
`define UQU_OPCODE_JAL      7'h6f
`define UQU_OPCODE_SYSTEM   7'h73

// Integer funct3/funct7 fields (shared by register and immediate forms).
`define UQU_FUNCT3_ADD_SUB 3'b000
`define UQU_FUNCT3_SLL     3'b001
`define UQU_FUNCT3_SLT     3'b010
`define UQU_FUNCT3_SLTU    3'b011
`define UQU_FUNCT3_XOR     3'b100
`define UQU_FUNCT3_SRL_SRA 3'b101
`define UQU_FUNCT3_OR      3'b110
`define UQU_FUNCT3_AND     3'b111
`define UQU_FUNCT7_BASE    7'h00
`define UQU_FUNCT7_SUB_SRA 7'h20
`define UQU_FUNCT7_M       7'h01
`define UQU_FUNCT3_JALR    3'b000

`define UQU_FUNCT3_BEQ  3'b000
`define UQU_FUNCT3_BNE  3'b001
`define UQU_FUNCT3_BLT  3'b100
`define UQU_FUNCT3_BGE  3'b101
`define UQU_FUNCT3_BLTU 3'b110
`define UQU_FUNCT3_BGEU 3'b111

`define UQU_FUNCT3_LB  3'b000
`define UQU_FUNCT3_LH  3'b001
`define UQU_FUNCT3_LW  3'b010
`define UQU_FUNCT3_LBU 3'b100
`define UQU_FUNCT3_LHU 3'b101
`define UQU_FUNCT3_SB  3'b000
`define UQU_FUNCT3_SH  3'b001
`define UQU_FUNCT3_SW  3'b010

`define UQU_FUNCT3_FENCE   3'b000
`define UQU_FUNCT3_FENCEI  3'b001
`define UQU_FUNCT3_CSRRW   3'b001
`define UQU_FUNCT3_CSRRS   3'b010
`define UQU_FUNCT3_CSRRC   3'b011
`define UQU_FUNCT3_CSRRWI  3'b101
`define UQU_FUNCT3_CSRRSI  3'b110
`define UQU_FUNCT3_CSRRCI  3'b111

// Canonical SYSTEM instructions, including required reserved zero fields.
`define UQU_INSTR_ECALL  32'h00000073
`define UQU_INSTR_EBREAK 32'h00100073
`define UQU_INSTR_MRET   32'h30200073
`define UQU_INSTR_DRET   32'h7b200073
`define UQU_INSTR_WFI    32'h10500073

// FP encoding fields. Zfinx uses these encodings with integer registers.
`define UQU_FP_FMT_S 2'b00
`define UQU_FUNCT7_FADD_S    7'h00
`define UQU_FUNCT7_FSUB_S    7'h04
`define UQU_FUNCT7_FMUL_S    7'h08
`define UQU_FUNCT7_FDIV_S    7'h0c
`define UQU_FUNCT7_FSQRT_S   7'h2c
`define UQU_FUNCT7_FSGNJ_S   7'h10
`define UQU_FUNCT7_FMINMAX_S 7'h14
`define UQU_FUNCT7_FCMP_S    7'h50
`define UQU_FUNCT7_FCLASS_S  7'h70
`define UQU_FUNCT7_FCVT_W_S  7'h60
`define UQU_FUNCT7_FCVT_S_W  7'h68
`define UQU_FUNCT3_FSGNJ  3'b000
`define UQU_FUNCT3_FSGNJN 3'b001
`define UQU_FUNCT3_FSGNJX 3'b010
`define UQU_FUNCT3_FMIN   3'b000
`define UQU_FUNCT3_FMAX   3'b001
`define UQU_FUNCT3_FEQ    3'b010
`define UQU_FUNCT3_FLT    3'b001
`define UQU_FUNCT3_FLE    3'b000
`define UQU_FUNCT3_FCLASS 3'b001
`define UQU_FP_RS2_ZERO  5'd0
`define UQU_FP_INT_W     5'd0
`define UQU_FP_INT_WU    5'd1
`define UQU_RM_RNE 3'b000
`define UQU_RM_RTZ 3'b001
`define UQU_RM_RDN 3'b010
`define UQU_RM_RUP 3'b011
`define UQU_RM_RMM 3'b100
`define UQU_RM_DYN 3'b111

`endif
