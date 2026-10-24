// Shared internal control encodings; not architectural instruction fields.
`ifndef UQU_CTRL_VH
`define UQU_CTRL_VH
`include "uqu_isa.vh"

`define UQU_FU_ALU    2'd0
`define UQU_FU_MULDIV 2'd1
`define UQU_FU_FPU    2'd2
`define UQU_FU_PASS   2'd3

// Source-use masks: bits 0/1/2 denote rs1/rs2/rs3.
`define UQU_RS_NONE        3'b000
`define UQU_RS1            3'b001
`define UQU_RS1_RS2        3'b011
`define UQU_RS1_RS2_RS3    3'b111

`define UQU_A_RS1  2'd0
`define UQU_A_PC   2'd1
`define UQU_A_ZERO 2'd2
`define UQU_B_RS2  2'd0
`define UQU_B_IMM  2'd1
`define UQU_B_ZERO 2'd2

`define UQU_BR_NONE  2'd0
`define UQU_BR_COND  2'd1
`define UQU_BR_JAL   2'd2
`define UQU_BR_JALR  2'd3

`define UQU_WB_RESULT 3'd0
`define UQU_WB_CSR    3'd1
`define UQU_WB_MRET   3'd2
`define UQU_WB_XIF    3'd3
`define UQU_WB_DRET   3'd4
`define UQU_WB_EBREAK 3'd5

`define UQU_SYS_NONE   3'd0
`define UQU_SYS_ECALL  3'd1
`define UQU_SYS_EBREAK 3'd2
`define UQU_SYS_MRET   3'd3
`define UQU_SYS_DRET   3'd4
`define UQU_SYS_WFI    3'd5
`define UQU_SYS_FENCE  3'd6
`define UQU_SYS_FENCEI 3'd7

// ALU's low three operation bits match integer funct3.
`define UQU_ALU_ADD  {1'b0, `UQU_FUNCT3_ADD_SUB}
`define UQU_ALU_SLL  {1'b0, `UQU_FUNCT3_SLL}
`define UQU_ALU_SLT  {1'b0, `UQU_FUNCT3_SLT}
`define UQU_ALU_SLTU {1'b0, `UQU_FUNCT3_SLTU}
`define UQU_ALU_XOR  {1'b0, `UQU_FUNCT3_XOR}
`define UQU_ALU_SRL  {1'b0, `UQU_FUNCT3_SRL_SRA}
`define UQU_ALU_OR   {1'b0, `UQU_FUNCT3_OR}
`define UQU_ALU_AND  {1'b0, `UQU_FUNCT3_AND}
`define UQU_ALU_SUB  {1'b1, `UQU_FUNCT3_ADD_SUB}
`define UQU_ALU_SRA  {1'b1, `UQU_FUNCT3_SRL_SRA}

// Experimental execution control only; no architectural MAC encoding is assigned.
`define UQU_MDU_MAC 5'd8

`define UQU_FPU_FADD_S    5'd0
`define UQU_FPU_FSUB_S    5'd1
`define UQU_FPU_FMUL_S    5'd2
`define UQU_FPU_FDIV_S    5'd3
`define UQU_FPU_FSQRT_S   5'd4
`define UQU_FPU_FMADD_S   5'd5
`define UQU_FPU_FMSUB_S   5'd6
`define UQU_FPU_FNMSUB_S  5'd7
`define UQU_FPU_FNMADD_S  5'd8
`define UQU_FPU_FSGNJ_S   5'd9
`define UQU_FPU_FSGNJN_S  5'd10
`define UQU_FPU_FSGNJX_S  5'd11
`define UQU_FPU_FMIN_S    5'd12
`define UQU_FPU_FMAX_S    5'd13
`define UQU_FPU_FEQ_S     5'd14
`define UQU_FPU_FLT_S     5'd15
`define UQU_FPU_FLE_S     5'd16
`define UQU_FPU_FCLASS_S  5'd17
`define UQU_FPU_FCVT_W_S  5'd18
`define UQU_FPU_FCVT_WU_S 5'd19
`define UQU_FPU_FCVT_S_W  5'd20
`define UQU_FPU_FCVT_S_WU 5'd21

`endif
