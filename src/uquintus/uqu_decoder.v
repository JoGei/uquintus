`default_nettype none
`include "uqu_isa.vh"
`include "uqu_ctrl.vh"

// Stateless native instruction decoder. The strategy adapter supplies 32-bit instructions;
// DE/core own operands, runtime permissions, hazards, XIF and exception events.
module uqu_decoder #(
    parameter ISA_E = 0,
    parameter ISA_M = 0,
    parameter ISA_ZFINX = 0,
    parameter ISA_ZIFENCEI = 0,
    parameter ISA_F = 0,
    parameter ISA_A = 0,
    parameter DEBUG = 0
) (
    input  wire [31:0] instr_i,
    output wire        native_o,
    output wire        illegal_o,
    output wire        illegal_reg_o,
    output wire [2:0]  rs_used_o,
    output wire [4:0]  rs1_o,
    output wire [4:0]  rs2_o,
    output wire [4:0]  rs3_o,
    output wire        rd_we_o,
    output wire [4:0]  rd_o,
    output wire [31:0] imm_o,
    output wire [1:0]  fu_o,
    output wire [4:0]  op_o,
    output wire [1:0]  a_sel_o,
    output wire [1:0]  b_sel_o,
    output wire        pass_link_o,
    output wire [1:0]  branch_o,
    output wire [2:0]  branch_op_o,
    output wire        lsu_o,
    output wire        mem_we_o,
    output wire [2:0]  mem_op_o,
    output wire [2:0]  wb_kind_o,
    output wire [2:0]  system_o,
    output wire        serialize_o,
    output wire [11:0] csr_addr_o,
    output wire [2:0]  csr_op_o,
    output wire        csr_imm_o,
    output wire [2:0]  rm_o
);
    wire [2:0] funct3 = instr_i[14:12];
    wire [6:0] funct7 = instr_i[31:25];
    wire [31:0] imm_i = {{20{instr_i[31]}}, instr_i[31:20]};
    wire [31:0] imm_s = {{20{instr_i[31]}}, instr_i[31:25], instr_i[11:7]};
    wire [31:0] imm_b = {{19{instr_i[31]}}, instr_i[31], instr_i[7],
                         instr_i[30:25], instr_i[11:8], 1'b0};
    wire [31:0] imm_u = {instr_i[31:12], 12'd0};
    wire [31:0] imm_j = {{11{instr_i[31]}}, instr_i[31], instr_i[19:12],
                         instr_i[20], instr_i[30:21], 1'b0};
    wire rounding_valid = (funct3 <= `UQU_RM_RMM) || (funct3 == `UQU_RM_DYN);
    reg native_match;
    reg [2:0] rs_used;
    reg rd_we;
    reg [31:0] immediate;
    reg [1:0] fu;
    reg [4:0] operation;
    reg [1:0] a_select;
    reg [1:0] b_select;
    reg pass_link;
    reg [1:0] branch;
    reg [2:0] branch_op;
    reg lsu;
    reg mem_we;
    reg [2:0] mem_op;
    reg [2:0] wb_kind;
    reg [2:0] system_op;
    reg serialize;
    reg [2:0] rm;

    always @* begin
        native_match = 1'b0;
        rs_used = `UQU_RS_NONE;
        rd_we = 1'b0;
        immediate = 32'd0;
        fu = `UQU_FU_PASS;
        operation = {1'b0, `UQU_ALU_ADD};
        a_select = `UQU_A_ZERO;
        b_select = `UQU_B_ZERO;
        pass_link = 1'b0;
        branch = `UQU_BR_NONE;
        branch_op = 3'd0;
        lsu = 1'b0;
        mem_we = 1'b0;
        mem_op = 3'd0;
        wb_kind = `UQU_WB_RESULT;
        system_op = `UQU_SYS_NONE;
        serialize = 1'b0;
        rm = `UQU_RM_RNE;
        case (instr_i[6:0])
            `UQU_OPCODE_LUI, `UQU_OPCODE_AUIPC: begin // LUI / AUIPC
                native_match = 1'b1;
                rd_we = 1'b1;
                immediate = imm_u;
                fu = `UQU_FU_ALU;
                a_select = (instr_i[6:0] == `UQU_OPCODE_AUIPC) ? `UQU_A_PC : `UQU_A_ZERO;
                b_select = `UQU_B_IMM;
            end
            `UQU_OPCODE_JAL: begin // JAL: target/link computation belongs to DE.
                native_match = 1'b1;
                rd_we = 1'b1;
                immediate = imm_j;
                branch = `UQU_BR_JAL;
                pass_link = 1'b1;
            end
            `UQU_OPCODE_JALR: begin // JALR
                native_match = (funct3 == `UQU_FUNCT3_JALR);
                rs_used = `UQU_RS1;
                rd_we = 1'b1;
                immediate = imm_i;
                branch = `UQU_BR_JALR;
                pass_link = 1'b1;
            end
            `UQU_OPCODE_BRANCH: begin
                native_match = (funct3 == `UQU_FUNCT3_BEQ) || (funct3 == `UQU_FUNCT3_BNE) ||
                               (funct3 == `UQU_FUNCT3_BLT) || (funct3 == `UQU_FUNCT3_BGE) ||
                               (funct3 == `UQU_FUNCT3_BLTU) || (funct3 == `UQU_FUNCT3_BGEU);
                rs_used = `UQU_RS1_RS2;
                immediate = imm_b;
                branch = `UQU_BR_COND;
                branch_op = funct3;
            end
            `UQU_OPCODE_LOAD, `UQU_OPCODE_STORE: begin // Integer loads/stores, effective address in EX.
                mem_we = (instr_i[6:0] == `UQU_OPCODE_STORE);
                native_match = mem_we ?
                    ((funct3 == `UQU_FUNCT3_SB) || (funct3 == `UQU_FUNCT3_SH) ||
                     (funct3 == `UQU_FUNCT3_SW)) :
                    ((funct3 == `UQU_FUNCT3_LB) || (funct3 == `UQU_FUNCT3_LH) ||
                     (funct3 == `UQU_FUNCT3_LW) || (funct3 == `UQU_FUNCT3_LBU) ||
                     (funct3 == `UQU_FUNCT3_LHU));
                rs_used = mem_we ? `UQU_RS1_RS2 : `UQU_RS1;
                rd_we = !mem_we;
                immediate = mem_we ? imm_s : imm_i;
                fu = `UQU_FU_ALU;
                a_select = `UQU_A_RS1;
                b_select = `UQU_B_IMM;
                lsu = 1'b1;
                mem_op = funct3;
            end
            `UQU_OPCODE_OP_IMM: begin
                native_match = 1'b1;
                rs_used = `UQU_RS1;
                rd_we = 1'b1;
                immediate = imm_i;
                fu = `UQU_FU_ALU;
                a_select = `UQU_A_RS1;
                b_select = `UQU_B_IMM;
                operation = {2'd0, funct3};
                if (funct3 == `UQU_FUNCT3_SLL) begin
                    native_match = (funct7 == `UQU_FUNCT7_BASE);
                    immediate = {27'd0, instr_i[24:20]};
                end
                if (funct3 == `UQU_FUNCT3_SRL_SRA) begin
                    native_match = (funct7 == `UQU_FUNCT7_BASE) || (funct7 == `UQU_FUNCT7_SUB_SRA);
                    immediate = {27'd0, instr_i[24:20]};
                    operation = instr_i[30] ? {1'b0, `UQU_ALU_SRA} : {1'b0, `UQU_ALU_SRL};
                end
            end
            `UQU_OPCODE_OP: begin
                native_match = (funct7 == `UQU_FUNCT7_BASE) ||
                    ((funct7 == `UQU_FUNCT7_SUB_SRA) &&
                     ((funct3 == `UQU_FUNCT3_ADD_SUB) || (funct3 == `UQU_FUNCT3_SRL_SRA))) ||
                    ((ISA_M == 1) && (funct7 == `UQU_FUNCT7_M));
                rs_used = `UQU_RS1_RS2;
                rd_we = 1'b1;
                fu = (funct7 == `UQU_FUNCT7_M) ? `UQU_FU_MULDIV : `UQU_FU_ALU;
                a_select = `UQU_A_RS1;
                b_select = `UQU_B_RS2;
                operation = {1'b0, (funct7 == `UQU_FUNCT7_SUB_SRA), funct3};
            end
            `UQU_OPCODE_MISC_MEM: begin
                // Reserved fm/rd/rs1 fields do not denote register operands.
                native_match = (funct3 == `UQU_FUNCT3_FENCE) ||
                               ((ISA_ZIFENCEI == 1) && (funct3 == `UQU_FUNCT3_FENCEI));
                serialize = 1'b1;
                system_op = (funct3 == `UQU_FUNCT3_FENCEI) ? `UQU_SYS_FENCEI : `UQU_SYS_FENCE;
            end
            `UQU_OPCODE_SYSTEM: begin
                if ((funct3 == `UQU_FUNCT3_CSRRW) || (funct3 == `UQU_FUNCT3_CSRRS) ||
                    (funct3 == `UQU_FUNCT3_CSRRC) || (funct3 == `UQU_FUNCT3_CSRRWI) ||
                    (funct3 == `UQU_FUNCT3_CSRRSI) || (funct3 == `UQU_FUNCT3_CSRRCI)) begin
                    native_match = 1'b1;
                    rd_we = 1'b1;
                    rs_used = funct3[2] ? `UQU_RS_NONE : `UQU_RS1;
                    immediate = funct3[2] ? {27'd0, instr_i[19:15]} : 32'd0;
                    wb_kind = `UQU_WB_CSR;
                    serialize = 1'b1;
                end else begin
                    case (instr_i)
                        `UQU_INSTR_ECALL: begin
                            native_match = 1'b1;
                            system_op = `UQU_SYS_ECALL;
                            serialize = 1'b1;
                        end
                        `UQU_INSTR_EBREAK: begin
                            native_match = 1'b1; system_op = `UQU_SYS_EBREAK;
                            wb_kind = `UQU_WB_EBREAK; serialize = 1'b1;
                        end
                        `UQU_INSTR_MRET: begin
                            native_match = 1'b1; system_op = `UQU_SYS_MRET;
                            wb_kind = `UQU_WB_MRET; serialize = 1'b1;
                        end
                        `UQU_INSTR_DRET: begin
                            native_match = (DEBUG == 1); system_op = `UQU_SYS_DRET;
                            wb_kind = `UQU_WB_DRET; serialize = 1'b1;
                        end
                        `UQU_INSTR_WFI: begin
                            native_match = 1'b1;
                            system_op = `UQU_SYS_WFI;
                        end
                        default: begin end
                    endcase
                end
            end
            `UQU_OPCODE_MADD, `UQU_OPCODE_MSUB,
            `UQU_OPCODE_NMSUB, `UQU_OPCODE_NMADD: begin // FP32 fused operations.
                native_match = (ISA_ZFINX == 1) && (instr_i[26:25] == `UQU_FP_FMT_S) && rounding_valid;
                fu = `UQU_FU_FPU;
                rd_we = 1'b1;
                rs_used = `UQU_RS1_RS2_RS3;
                case (instr_i[6:0])
                    `UQU_OPCODE_MADD: operation = `UQU_FPU_FMADD_S;
                    `UQU_OPCODE_MSUB: operation = `UQU_FPU_FMSUB_S;
                    `UQU_OPCODE_NMSUB: operation = `UQU_FPU_FNMSUB_S;
                    default: operation = `UQU_FPU_FNMADD_S;
                endcase
                a_select = `UQU_A_RS1;
                b_select = `UQU_B_RS2;
                rm = funct3;
            end
            `UQU_OPCODE_OP_FP: begin
                fu = `UQU_FU_FPU;
                rd_we = 1'b1;
                rs_used = `UQU_RS1_RS2;
                a_select = `UQU_A_RS1;
                b_select = `UQU_B_RS2;
                case (funct7)
                    `UQU_FUNCT7_FADD_S, `UQU_FUNCT7_FSUB_S,
                    `UQU_FUNCT7_FMUL_S, `UQU_FUNCT7_FDIV_S: begin
                        native_match = (ISA_ZFINX == 1) && rounding_valid;
                        case (funct7)
                            `UQU_FUNCT7_FADD_S: operation = `UQU_FPU_FADD_S;
                            `UQU_FUNCT7_FSUB_S: operation = `UQU_FPU_FSUB_S;
                            `UQU_FUNCT7_FMUL_S: operation = `UQU_FPU_FMUL_S;
                            default: operation = `UQU_FPU_FDIV_S;
                        endcase
                        rm = funct3;
                    end
                    `UQU_FUNCT7_FSQRT_S: begin
                        native_match = (ISA_ZFINX == 1) &&
                                       (instr_i[24:20] == `UQU_FP_RS2_ZERO) && rounding_valid;
                        operation = `UQU_FPU_FSQRT_S;
                        rs_used = `UQU_RS1;
                        rm = funct3;
                    end
                    `UQU_FUNCT7_FSGNJ_S: begin
                        native_match = (ISA_ZFINX == 1) &&
                            ((funct3 == `UQU_FUNCT3_FSGNJ) || (funct3 == `UQU_FUNCT3_FSGNJN) ||
                             (funct3 == `UQU_FUNCT3_FSGNJX));
                        case (funct3)
                            `UQU_FUNCT3_FSGNJ: operation = `UQU_FPU_FSGNJ_S;
                            `UQU_FUNCT3_FSGNJN: operation = `UQU_FPU_FSGNJN_S;
                            default: operation = `UQU_FPU_FSGNJX_S;
                        endcase
                    end
                    `UQU_FUNCT7_FMINMAX_S: begin
                        native_match = (ISA_ZFINX == 1) &&
                            ((funct3 == `UQU_FUNCT3_FMIN) || (funct3 == `UQU_FUNCT3_FMAX));
                        operation = (funct3 == `UQU_FUNCT3_FMAX) ? `UQU_FPU_FMAX_S : `UQU_FPU_FMIN_S;
                    end
                    `UQU_FUNCT7_FCMP_S: begin
                        native_match = (ISA_ZFINX == 1) &&
                            ((funct3 == `UQU_FUNCT3_FEQ) || (funct3 == `UQU_FUNCT3_FLT) ||
                             (funct3 == `UQU_FUNCT3_FLE));
                        operation = (funct3 == `UQU_FUNCT3_FEQ) ? `UQU_FPU_FEQ_S :
                                    (funct3 == `UQU_FUNCT3_FLT) ? `UQU_FPU_FLT_S : `UQU_FPU_FLE_S;
                    end
                    `UQU_FUNCT7_FCLASS_S: begin
                        // FCLASS only: FMV.X.W is excluded by Zfinx.
                        native_match = (ISA_ZFINX == 1) && (funct3 == `UQU_FUNCT3_FCLASS) &&
                                       (instr_i[24:20] == `UQU_FP_RS2_ZERO);
                        operation = `UQU_FPU_FCLASS_S;
                        rs_used = `UQU_RS1;
                    end
                    `UQU_FUNCT7_FCVT_W_S, `UQU_FUNCT7_FCVT_S_W: begin
                        native_match = (ISA_ZFINX == 1) &&
                            ((instr_i[24:20] == `UQU_FP_INT_W) ||
                             (instr_i[24:20] == `UQU_FP_INT_WU)) && rounding_valid;
                        if (funct7 == `UQU_FUNCT7_FCVT_W_S)
                            operation = (instr_i[24:20] == `UQU_FP_INT_WU) ?
                                        `UQU_FPU_FCVT_WU_S : `UQU_FPU_FCVT_W_S;
                        else
                            operation = (instr_i[24:20] == `UQU_FP_INT_WU) ?
                                        `UQU_FPU_FCVT_S_WU : `UQU_FPU_FCVT_S_W;
                        rs_used = `UQU_RS1;
                        rm = funct3;
                    end
                    default: begin end
                endcase
            end
            default: begin end
        endcase
    end

    // E restricts only actually used register fields. CSR zimm, fence reserved
    // fields, shift amounts and conversion selectors are not GPR addresses.
    assign native_o = native_match;
    assign illegal_reg_o = native_match && (ISA_E == 1) &&
        ((rs_used[0] && instr_i[19]) || (rs_used[1] && instr_i[24]) ||
         (rs_used[2] && instr_i[31]) || (rd_we && instr_i[11]));
    assign illegal_o = !native_match || illegal_reg_o;
    assign rs_used_o = illegal_o ? `UQU_RS_NONE : rs_used;
    assign rs1_o = !illegal_o && rs_used[0] ? instr_i[19:15] : 5'd0;
    assign rs2_o = !illegal_o && rs_used[1] ? instr_i[24:20] : 5'd0;
    assign rs3_o = !illegal_o && rs_used[2] ? instr_i[31:27] : 5'd0;
    assign rd_we_o = !illegal_o && rd_we;
    assign rd_o = rd_we_o ? instr_i[11:7] : 5'd0;
    assign imm_o = illegal_o ? 32'd0 : immediate;
    assign fu_o = illegal_o ? `UQU_FU_PASS : fu;
    assign op_o = illegal_o ? 5'd0 : operation;
    assign a_sel_o = illegal_o ? `UQU_A_ZERO : a_select;
    assign b_sel_o = illegal_o ? `UQU_B_ZERO : b_select;
    assign pass_link_o = !illegal_o && pass_link;
    assign branch_o = illegal_o ? `UQU_BR_NONE : branch;
    assign branch_op_o = illegal_o ? 3'd0 : branch_op;
    assign lsu_o = !illegal_o && lsu;
    assign mem_we_o = !illegal_o && mem_we;
    assign mem_op_o = illegal_o ? 3'd0 : mem_op;
    assign wb_kind_o = illegal_o ? `UQU_WB_RESULT : wb_kind;
    assign system_o = illegal_o ? `UQU_SYS_NONE : system_op;
    assign serialize_o = !illegal_o && serialize;
    assign csr_addr_o = !illegal_o && (wb_kind == `UQU_WB_CSR) ? instr_i[31:20] : 12'd0;
    assign csr_op_o = !illegal_o && (wb_kind == `UQU_WB_CSR) ? funct3 : 3'd0;
    assign csr_imm_o = !illegal_o && (wb_kind == `UQU_WB_CSR) && funct3[2];
    assign rm_o = illegal_o ? `UQU_RM_RNE : rm;

    generate
        if (((ISA_E != 0) && (ISA_E != 1)) || ((ISA_M != 0) && (ISA_M != 1)) ||
            ((ISA_ZFINX != 0) && (ISA_ZFINX != 1)) ||
            ((ISA_ZIFENCEI != 0) && (ISA_ZIFENCEI != 1)) ||
            ((DEBUG != 0) && (DEBUG != 1)) || (ISA_F != 0) || (ISA_A != 0)) begin : GEN_UNSUPPORTED
            uqu_decoder_unsupported_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
