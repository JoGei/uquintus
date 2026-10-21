`default_nettype none
`include "uqu_isa.vh"

// IF supplies an assembled instruction with its first halfword in bits 15:0.
// This block expands integer RV32C only; DE owns base-ISA/register legality.
module uqu_decompressor #(
    parameter ISA_C = 0
) (
    input  wire [31:0] instr_i,
    output wire [31:0] instr_o,
    output wire [31:0] original_instr_o,
    output wire        compressed_o,
    output wire        illegal_o,
    output wire        hint_o
);
    assign compressed_o = (ISA_C == 1) && (instr_i[1:0] != 2'b11);
    assign original_instr_o = compressed_o ? {16'd0, instr_i[15:0]} : instr_i;

    function [31:0] encode_i;
        input [11:0] immediate;
        input [4:0] rs1;
        input [2:0] funct3;
        input [4:0] rd;
        input [6:0] opcode;
        begin
            encode_i = {immediate, rs1, funct3, rd, opcode};
        end
    endfunction

    function [31:0] encode_r;
        input [6:0] funct7;
        input [4:0] rs2;
        input [4:0] rs1;
        input [2:0] funct3;
        input [4:0] rd;
        begin
            encode_r = {funct7, rs2, rs1, funct3, rd, `UQU_OPCODE_OP};
        end
    endfunction

    generate
        if (ISA_C == 1) begin : gen_compressed
            wire [15:0] c = instr_i[15:0];
            wire [4:0] rd = c[11:7];
            wire [4:0] rs2 = c[6:2];
            wire [4:0] rd_prime = {2'b01, c[4:2]};
            wire [4:0] rs1_prime = {2'b01, c[9:7]};
            wire [11:0] ci_imm = {{7{c[12]}}, c[6:2]};
            wire [11:0] spn_imm = {2'd0, c[10:7], c[12:11], c[5], c[6], 2'b00};
            wire [11:0] word_offset = {5'd0, c[5], c[12:10], c[6], 2'b00};
            wire [11:0] lwsp_offset = {4'd0, c[3:2], c[12], c[6:4], 2'b00};
            wire [11:0] swsp_offset = {4'd0, c[8:7], c[12:9], 2'b00};
            wire [11:0] sp_imm = {{3{c[12]}}, c[4:3], c[5], c[2], c[6], 4'b0000};
            wire [20:0] jump_imm = {{10{c[12]}}, c[8], c[10:9], c[6], c[7],
                                   c[2], c[11], c[5:3], 1'b0};
            wire [12:0] branch_imm = {{5{c[12]}}, c[6:5], c[2], c[11:10], c[4:3], 1'b0};
            wire [11:0] shift_imm = {7'd0, c[6:2]};
            reg [31:0] expanded;
            reg illegal;
            reg hint;

            always @* begin
                expanded = instr_i;
                illegal = 1'b0;
                hint = 1'b0;
                if (compressed_o) begin
                    expanded = 32'd0;
                    illegal = 1'b1;
                    case (c[1:0])
                        `UQU_C_Q0: begin
                            case (c[15:13])
                                `UQU_C_Q0_ADDI4SPN: begin
                                    expanded = encode_i(spn_imm, 5'd2, `UQU_FUNCT3_ADD_SUB,
                                                        rd_prime, `UQU_OPCODE_OP_IMM);
                                    illegal = (spn_imm == 12'd0);
                                end
                                `UQU_C_Q0_LW: begin
                                    expanded = encode_i(word_offset, rs1_prime, `UQU_FUNCT3_LW,
                                                        rd_prime, `UQU_OPCODE_LOAD);
                                    illegal = 1'b0;
                                end
                                `UQU_C_Q0_SW: begin
                                    expanded = {word_offset[11:5], rd_prime, rs1_prime,
                                        `UQU_FUNCT3_SW, word_offset[4:0], `UQU_OPCODE_STORE};
                                    illegal = 1'b0;
                                end
                                default: begin end
                            endcase
                        end
                        `UQU_C_Q1: begin
                            case (c[15:13])
                                `UQU_C_Q1_ADDI: begin
                                    expanded = encode_i(ci_imm, rd, `UQU_FUNCT3_ADD_SUB,
                                                        rd, `UQU_OPCODE_OP_IMM);
                                    illegal = 1'b0;
                                    hint = ((rd == 5'd0) && (ci_imm != 12'd0)) ||
                                           ((rd != 5'd0) && (ci_imm == 12'd0));
                                end
                                `UQU_C_Q1_JAL, `UQU_C_Q1_J: begin
                                    expanded = {jump_imm[20], jump_imm[10:1], jump_imm[11],
                                        jump_imm[19:12], (c[15:13] == `UQU_C_Q1_JAL ? 5'd1 : 5'd0),
                                        `UQU_OPCODE_JAL};
                                    illegal = 1'b0;
                                end
                                `UQU_C_Q1_LI: begin
                                    expanded = encode_i(ci_imm, 5'd0, `UQU_FUNCT3_ADD_SUB,
                                                        rd, `UQU_OPCODE_OP_IMM);
                                    illegal = 1'b0;
                                    hint = (rd == 5'd0);
                                end
                                `UQU_C_Q1_LUI_SP: begin
                                    if (rd == 5'd2) begin
                                        expanded = encode_i(sp_imm, 5'd2, `UQU_FUNCT3_ADD_SUB,
                                                            5'd2, `UQU_OPCODE_OP_IMM);
                                        illegal = (sp_imm == 12'd0);
                                    end else begin
                                        expanded = {{15{c[12]}}, c[6:2], rd, `UQU_OPCODE_LUI};
                                        illegal = (ci_imm == 12'd0);
                                        hint = (rd == 5'd0);
                                    end
                                end
                                `UQU_C_Q1_ALU: begin
                                    case (c[11:10])
                                        `UQU_C_ALU_SRLI, `UQU_C_ALU_SRAI: begin
                                            expanded = encode_i(
                                                {(c[10] ? `UQU_FUNCT7_SUB_SRA : `UQU_FUNCT7_BASE), c[6:2]},
                                                rs1_prime, `UQU_FUNCT3_SRL_SRA, rs1_prime, `UQU_OPCODE_OP_IMM);
                                            illegal = c[12];
                                            hint = (c[6:2] == 5'd0);
                                        end
                                        `UQU_C_ALU_ANDI: begin
                                            expanded = encode_i(ci_imm, rs1_prime, `UQU_FUNCT3_AND,
                                                                rs1_prime, `UQU_OPCODE_OP_IMM);
                                            illegal = 1'b0;
                                        end
                                        `UQU_C_ALU_REG: begin
                                            illegal = c[12]; // RV64 word operations are not RV32C.
                                            case (c[6:5])
                                                `UQU_C_REG_SUB: expanded = encode_r(`UQU_FUNCT7_SUB_SRA,
                                                    rd_prime, rs1_prime, `UQU_FUNCT3_ADD_SUB, rs1_prime);
                                                `UQU_C_REG_XOR: expanded = encode_r(`UQU_FUNCT7_BASE,
                                                    rd_prime, rs1_prime, `UQU_FUNCT3_XOR, rs1_prime);
                                                `UQU_C_REG_OR: expanded = encode_r(`UQU_FUNCT7_BASE,
                                                    rd_prime, rs1_prime, `UQU_FUNCT3_OR, rs1_prime);
                                                `UQU_C_REG_AND: expanded = encode_r(`UQU_FUNCT7_BASE,
                                                    rd_prime, rs1_prime, `UQU_FUNCT3_AND, rs1_prime);
                                                default: begin end
                                            endcase
                                        end
                                        default: begin end
                                    endcase
                                end
                                `UQU_C_Q1_BEQZ, `UQU_C_Q1_BNEZ: begin
                                    expanded = {branch_imm[12], branch_imm[10:5], 5'd0, rs1_prime,
                                        (c[15:13] == `UQU_C_Q1_BEQZ ? `UQU_FUNCT3_BEQ : `UQU_FUNCT3_BNE),
                                        branch_imm[4:1], branch_imm[11], `UQU_OPCODE_BRANCH};
                                    illegal = 1'b0;
                                end
                                default: begin end
                            endcase
                        end
                        `UQU_C_Q2: begin
                            case (c[15:13])
                                `UQU_C_Q2_SLLI: begin
                                    expanded = encode_i(shift_imm, rd, `UQU_FUNCT3_SLL,
                                                        rd, `UQU_OPCODE_OP_IMM);
                                    illegal = c[12];
                                    hint = (rd == 5'd0) || (c[6:2] == 5'd0);
                                end
                                `UQU_C_Q2_LWSP: begin
                                    expanded = encode_i(lwsp_offset, 5'd2, `UQU_FUNCT3_LW,
                                                        rd, `UQU_OPCODE_LOAD);
                                    illegal = (rd == 5'd0);
                                end
                                `UQU_C_Q2_CR: begin
                                    illegal = 1'b0;
                                    if (rs2 == 5'd0) begin
                                        if (!c[12]) begin
                                            expanded = encode_i(12'd0, rd, `UQU_FUNCT3_JALR,
                                                                5'd0, `UQU_OPCODE_JALR);
                                            illegal = (rd == 5'd0);
                                        end else if (rd == 5'd0) begin
                                            expanded = `UQU_INSTR_EBREAK;
                                        end else begin
                                            expanded = encode_i(12'd0, rd, `UQU_FUNCT3_JALR,
                                                                5'd1, `UQU_OPCODE_JALR);
                                        end
                                    end else begin
                                        expanded = encode_r(`UQU_FUNCT7_BASE, rs2,
                                            (c[12] ? rd : 5'd0), `UQU_FUNCT3_ADD_SUB, rd);
                                        hint = (rd == 5'd0);
                                    end
                                end
                                `UQU_C_Q2_SWSP: begin
                                    expanded = {swsp_offset[11:5], rs2, 5'd2, `UQU_FUNCT3_SW,
                                                swsp_offset[4:0], `UQU_OPCODE_STORE};
                                    illegal = 1'b0;
                                end
                                default: begin end
                            endcase
                        end
                        default: begin end
                    endcase
                end
            end
            assign instr_o = illegal ? 32'd0 : expanded;
            assign illegal_o = illegal;
            assign hint_o = hint && !illegal;
        end else begin : gen_bypass
            assign instr_o = instr_i;
            assign illegal_o = 1'b0;
            assign hint_o = 1'b0;
        end
        if ((ISA_C != 0) && (ISA_C != 1)) begin : gen_invalid
            uqu_decompressor_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
