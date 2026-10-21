`default_nettype none
`include "uqu_ctrl.vh"

// Direct RV32C decode into execution controls; no intermediate 32-bit encoding.
module uqu_decoder_c #(parameter ISA_E = 0) (
    input  wire [15:0] instr_i,
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

    wire [15:0] c = instr_i;
    wire [4:0] rd = c[11:7];
    wire [4:0] rs2 = c[6:2];
    wire [4:0] rs2_prime = {2'b01, c[4:2]};
    wire [4:0] base = {2'b01, c[9:7]};
    wire [31:0] ci_imm = {{27{c[12]}}, c[6:2]};
    wire [31:0] spn_imm = {22'd0, c[10:7], c[12:11], c[5], c[6], 2'b00};
    wire [31:0] word_offset = {25'd0, c[5], c[12:10], c[6], 2'b00};
    wire [31:0] sp_imm = {{23{c[12]}}, c[4:3], c[5], c[2], c[6], 4'b0000};
    wire [31:0] jump_imm = {{21{c[12]}}, c[8], c[10:9], c[6], c[7],
                            c[2], c[11], c[5:3], 1'b0};
    wire [31:0] branch_imm = {{24{c[12]}}, c[6:5], c[2], c[11:10], c[4:3], 1'b0};
    reg native_match;
    reg [2:0] rs_used;
    reg [4:0] source0, source1, destination;
    reg rd_we;
    reg [31:0] immediate;
    reg [1:0] fu, a_select, b_select, branch;
    reg [4:0] operation;
    reg pass_link, lsu, mem_we, serialize;
    reg [2:0] branch_op, mem_op, wb_kind, system_op;

    always @* begin
        native_match = 1'b0;
        rs_used = `UQU_RS_NONE;
        source0 = 5'd0;
        source1 = 5'd0;
        destination = 5'd0;
        rd_we = 1'b0;
        immediate = 32'd0;
        fu = `UQU_FU_PASS;
        operation = {1'b0, `UQU_ALU_ADD};
        a_select = `UQU_A_ZERO;
        b_select = `UQU_B_ZERO;
        branch = `UQU_BR_NONE;
        branch_op = 3'd0;
        pass_link = 1'b0;
        lsu = 1'b0;
        mem_we = 1'b0;
        mem_op = 3'd0;
        wb_kind = `UQU_WB_RESULT;
        system_op = `UQU_SYS_NONE;
        serialize = 1'b0;
        case (c[1:0])
            `UQU_C_Q0: begin
                case (c[15:13])
                    `UQU_C_Q0_ADDI4SPN: begin
                        native_match = (spn_imm != 32'd0);
                        rs_used = `UQU_RS1;
                        source0 = 5'd2;
                        destination = rs2_prime;
                        rd_we = 1'b1;
                        fu = `UQU_FU_ALU;
                        a_select = `UQU_A_RS1;
                        b_select = `UQU_B_IMM;
                        immediate = spn_imm;
                    end
                    `UQU_C_Q0_LW, `UQU_C_Q0_SW: begin
                        native_match = 1'b1;
                        mem_we = (c[15:13] == `UQU_C_Q0_SW);
                        rs_used = mem_we ? `UQU_RS1_RS2 : `UQU_RS1;
                        source0 = base;
                        source1 = rs2_prime;
                        destination = rs2_prime;
                        rd_we = !mem_we;
                        fu = `UQU_FU_ALU;
                        a_select = `UQU_A_RS1;
                        b_select = `UQU_B_IMM;
                        immediate = word_offset;
                        lsu = 1'b1;
                        mem_op = `UQU_FUNCT3_LW;
                    end
                    default: begin end
                endcase
            end
            `UQU_C_Q1: begin
                case (c[15:13])
                    `UQU_C_Q1_ADDI, `UQU_C_Q1_LI: begin
                        native_match = 1'b1;
                        rs_used = `UQU_RS1;
                        source0 = (c[15:13] == `UQU_C_Q1_LI) ? 5'd0 : rd;
                        destination = rd;
                        rd_we = 1'b1;
                        fu = `UQU_FU_ALU;
                        a_select = `UQU_A_RS1;
                        b_select = `UQU_B_IMM;
                        immediate = ci_imm;
                    end
                    `UQU_C_Q1_JAL, `UQU_C_Q1_J: begin
                        native_match = 1'b1;
                        destination = (c[15:13] == `UQU_C_Q1_JAL) ? 5'd1 : 5'd0;
                        rd_we = 1'b1;
                        immediate = jump_imm;
                        branch = `UQU_BR_JAL;
                        pass_link = 1'b1;
                    end
                    `UQU_C_Q1_LUI_SP: begin
                        destination = rd;
                        rd_we = 1'b1;
                        fu = `UQU_FU_ALU;
                        b_select = `UQU_B_IMM;
                        if (rd == 5'd2) begin
                            native_match = (sp_imm != 32'd0);
                            source0 = 5'd2;
                            rs_used = `UQU_RS1;
                            a_select = `UQU_A_RS1;
                            immediate = sp_imm;
                        end else begin
                            native_match = (ci_imm != 32'd0);
                            immediate = {{15{c[12]}}, c[6:2], 12'd0};
                        end
                    end
                    `UQU_C_Q1_ALU: begin
                        native_match = 1'b1;
                        rs_used = `UQU_RS1;
                        source0 = base;
                        destination = base;
                        rd_we = 1'b1;
                        fu = `UQU_FU_ALU;
                        a_select = `UQU_A_RS1;
                        b_select = `UQU_B_IMM;
                        case (c[11:10])
                            `UQU_C_ALU_SRLI, `UQU_C_ALU_SRAI: begin
                                native_match = !c[12];
                                immediate = {27'd0, c[6:2]};
                                operation = c[10] ? {1'b0, `UQU_ALU_SRA} : {1'b0, `UQU_ALU_SRL};
                            end
                            `UQU_C_ALU_ANDI: begin
                                immediate = ci_imm;
                                operation = {1'b0, `UQU_ALU_AND};
                            end
                            `UQU_C_ALU_REG: begin
                                native_match = !c[12];
                                rs_used = `UQU_RS1_RS2;
                                source1 = rs2_prime;
                                b_select = `UQU_B_RS2;
                                case (c[6:5])
                                    `UQU_C_REG_SUB: operation = {1'b0, `UQU_ALU_SUB};
                                    `UQU_C_REG_XOR: operation = {1'b0, `UQU_ALU_XOR};
                                    `UQU_C_REG_OR: operation = {1'b0, `UQU_ALU_OR};
                                    `UQU_C_REG_AND: operation = {1'b0, `UQU_ALU_AND};
                                    default: begin end
                                endcase
                            end
                            default: begin end
                        endcase
                    end
                    `UQU_C_Q1_BEQZ, `UQU_C_Q1_BNEZ: begin
                        native_match = 1'b1;
                        rs_used = `UQU_RS1_RS2;
                        source0 = base;
                        immediate = branch_imm;
                        branch = `UQU_BR_COND;
                        branch_op = (c[15:13] == `UQU_C_Q1_BEQZ) ? `UQU_FUNCT3_BEQ : `UQU_FUNCT3_BNE;
                    end
                    default: begin end
                endcase
            end
            `UQU_C_Q2: begin
                case (c[15:13])
                    `UQU_C_Q2_SLLI: begin
                        native_match = !c[12];
                        rs_used = `UQU_RS1;
                        source0 = rd;
                        destination = rd;
                        rd_we = 1'b1;
                        fu = `UQU_FU_ALU;
                        a_select = `UQU_A_RS1;
                        b_select = `UQU_B_IMM;
                        operation = {1'b0, `UQU_ALU_SLL};
                        immediate = {27'd0, c[6:2]};
                    end
                    `UQU_C_Q2_LWSP: begin
                        native_match = (rd != 5'd0);
                        rs_used = `UQU_RS1;
                        source0 = 5'd2;
                        destination = rd;
                        rd_we = 1'b1;
                        fu = `UQU_FU_ALU;
                        a_select = `UQU_A_RS1;
                        b_select = `UQU_B_IMM;
                        immediate = {24'd0, c[3:2], c[12], c[6:4], 2'b00};
                        lsu = 1'b1;
                        mem_op = `UQU_FUNCT3_LW;
                    end
                    `UQU_C_Q2_CR: begin
                        native_match = 1'b1;
                        if (rs2 != 5'd0) begin
                            rs_used = `UQU_RS1_RS2;
                            source0 = c[12] ? rd : 5'd0;
                            source1 = rs2;
                            destination = rd;
                            rd_we = 1'b1;
                            fu = `UQU_FU_ALU;
                            a_select = `UQU_A_RS1;
                            b_select = `UQU_B_RS2;
                        end else if (c[12] && (rd == 5'd0)) begin
                            wb_kind = `UQU_WB_EBREAK;
                            system_op = `UQU_SYS_EBREAK;
                            serialize = 1'b1;
                        end else begin
                            native_match = (rd != 5'd0);
                            rs_used = `UQU_RS1;
                            source0 = rd;
                            destination = c[12] ? 5'd1 : 5'd0;
                            rd_we = 1'b1;
                            branch = `UQU_BR_JALR;
                            pass_link = 1'b1;
                        end
                    end
                    `UQU_C_Q2_SWSP: begin
                        native_match = 1'b1;
                        rs_used = `UQU_RS1_RS2;
                        source0 = 5'd2;
                        source1 = rs2;
                        fu = `UQU_FU_ALU;
                        a_select = `UQU_A_RS1;
                        b_select = `UQU_B_IMM;
                        immediate = {24'd0, c[8:7], c[12:9], 2'b00};
                        lsu = 1'b1;
                        mem_we = 1'b1;
                        mem_op = `UQU_FUNCT3_SW;
                    end
                    default: begin end
                endcase
            end
            default: begin end
        endcase
    end

    // The same actually-used-register rule as the native decoder, including HINTs.
    assign native_o = native_match;
    assign illegal_reg_o = native_match && (ISA_E == 1) &&
        ((rs_used[0] && source0[4]) || (rs_used[1] && source1[4]) || (rd_we && destination[4]));
    assign illegal_o = !native_match || illegal_reg_o;
    assign rs_used_o = illegal_o ? `UQU_RS_NONE : rs_used;
    assign rs1_o = !illegal_o && rs_used[0] ? source0 : 5'd0;
    assign rs2_o = !illegal_o && rs_used[1] ? source1 : 5'd0;
    assign rs3_o = 5'd0;
    assign rd_we_o = !illegal_o && rd_we;
    assign rd_o = rd_we_o ? destination : 5'd0;
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
    assign csr_addr_o = 12'd0;
    assign csr_op_o = 3'd0;
    assign csr_imm_o = 1'b0;
    assign rm_o = `UQU_RM_RNE;

    generate
        if ((ISA_E != 0) && (ISA_E != 1)) begin : gen_invalid
            uqu_decoder_c_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule
`default_nettype wire
