`default_nettype none
`include "uqu_config.vh"

// Compressed-decode strategy adapter owned by DE. IF supplies expanded words
// only for decompress/if; original bits and length remain authoritative.
module uqu_decoder_select #(
    parameter ISA_E = 0,
    parameter ISA_M = 0,
    parameter ISA_ZFINX = 0,
    parameter ISA_ZIFENCEI = 0,
    parameter ISA_F = 0,
    parameter ISA_A = 0,
    parameter DEBUG = 0,
    parameter ISA_C = 0,
    parameter MUA_C_IMPL = `UQU_C_IMPL_DECOMPRESS,
    parameter MUA_C_DECOMPRESS_STAGE = `UQU_C_DECOMPRESS_IF
) (
    input  wire [31:0] instr_i,
    input  wire [31:0] original_instr_i,
    input  wire        compressed_i,
    input  wire        xif_force_i,
    output wire        illegal_c_o,
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
    wire raw_c = (ISA_C == 1) && compressed_i && !xif_force_i;
    wire [31:0] native_instr;
    wire n_native;
    wire n_illegal;
    wire n_illegal_reg;
    wire [2:0] n_rs_used;
    wire [4:0] n_rs1;
    wire [4:0] n_rs2;
    wire [4:0] n_rs3;
    wire n_rd_we;
    wire [4:0] n_rd;
    wire [31:0] n_imm;
    wire [1:0] n_fu;
    wire [4:0] n_op;
    wire [1:0] n_a_sel;
    wire [1:0] n_b_sel;
    wire n_pass_link;
    wire [1:0] n_branch;
    wire [2:0] n_branch_op;
    wire n_lsu;
    wire n_mem_we;
    wire [2:0] n_mem_op;
    wire [2:0] n_wb_kind;
    wire [2:0] n_system;
    wire n_serialize;
    wire [11:0] n_csr_addr;
    wire [2:0] n_csr_op;
    wire n_csr_imm;
    wire [2:0] n_rm;
    uqu_decoder #(
        .ISA_E(ISA_E), .ISA_M(ISA_M), .ISA_ZFINX(ISA_ZFINX),
        .ISA_ZIFENCEI(ISA_ZIFENCEI), .ISA_F(ISA_F), .ISA_A(ISA_A), .DEBUG(DEBUG)
    ) u_decoder (
        .instr_i(native_instr),
        .native_o(n_native),
        .illegal_o(n_illegal),
        .illegal_reg_o(n_illegal_reg),
        .rs_used_o(n_rs_used),
        .rs1_o(n_rs1),
        .rs2_o(n_rs2),
        .rs3_o(n_rs3),
        .rd_we_o(n_rd_we),
        .rd_o(n_rd),
        .imm_o(n_imm),
        .fu_o(n_fu),
        .op_o(n_op),
        .a_sel_o(n_a_sel),
        .b_sel_o(n_b_sel),
        .pass_link_o(n_pass_link),
        .branch_o(n_branch),
        .branch_op_o(n_branch_op),
        .lsu_o(n_lsu),
        .mem_we_o(n_mem_we),
        .mem_op_o(n_mem_op),
        .wb_kind_o(n_wb_kind),
        .system_o(n_system),
        .serialize_o(n_serialize),
        .csr_addr_o(n_csr_addr),
        .csr_op_o(n_csr_op),
        .csr_imm_o(n_csr_imm),
        .rm_o(n_rm)
    );
    generate
        if ((ISA_C == 1) && (MUA_C_IMPL == `UQU_C_IMPL_DECODE_COMPRESSED)) begin : gen_direct
            assign native_instr = instr_i;
            wire c_native;
            wire c_illegal;
            wire c_illegal_reg;
            wire [2:0] c_rs_used;
            wire [4:0] c_rs1;
            wire [4:0] c_rs2;
            wire [4:0] c_rs3;
            wire c_rd_we;
            wire [4:0] c_rd;
            wire [31:0] c_imm;
            wire [1:0] c_fu;
            wire [4:0] c_op;
            wire [1:0] c_a_sel;
            wire [1:0] c_b_sel;
            wire c_pass_link;
            wire [1:0] c_branch;
            wire [2:0] c_branch_op;
            wire c_lsu;
            wire c_mem_we;
            wire [2:0] c_mem_op;
            wire [2:0] c_wb_kind;
            wire [2:0] c_system;
            wire c_serialize;
            wire [11:0] c_csr_addr;
            wire [2:0] c_csr_op;
            wire c_csr_imm;
            wire [2:0] c_rm;
            uqu_decoder_c #(.ISA_E(ISA_E)) u_decoder_c (
                .instr_i(original_instr_i[15:0]),
                .native_o(c_native),
                .illegal_o(c_illegal),
                .illegal_reg_o(c_illegal_reg),
                .rs_used_o(c_rs_used),
                .rs1_o(c_rs1),
                .rs2_o(c_rs2),
                .rs3_o(c_rs3),
                .rd_we_o(c_rd_we),
                .rd_o(c_rd),
                .imm_o(c_imm),
                .fu_o(c_fu),
                .op_o(c_op),
                .a_sel_o(c_a_sel),
                .b_sel_o(c_b_sel),
                .pass_link_o(c_pass_link),
                .branch_o(c_branch),
                .branch_op_o(c_branch_op),
                .lsu_o(c_lsu),
                .mem_we_o(c_mem_we),
                .mem_op_o(c_mem_op),
                .wb_kind_o(c_wb_kind),
                .system_o(c_system),
                .serialize_o(c_serialize),
                .csr_addr_o(c_csr_addr),
                .csr_op_o(c_csr_op),
                .csr_imm_o(c_csr_imm),
                .rm_o(c_rm)
            );
            assign illegal_c_o = raw_c && !c_native;
            assign native_o = raw_c ? c_native : n_native;
            assign illegal_o = raw_c ? c_illegal : n_illegal;
            assign illegal_reg_o = raw_c ? c_illegal_reg : n_illegal_reg;
            assign rs_used_o = raw_c ? c_rs_used : n_rs_used;
            assign rs1_o = raw_c ? c_rs1 : n_rs1;
            assign rs2_o = raw_c ? c_rs2 : n_rs2;
            assign rs3_o = raw_c ? c_rs3 : n_rs3;
            assign rd_we_o = raw_c ? c_rd_we : n_rd_we;
            assign rd_o = raw_c ? c_rd : n_rd;
            assign imm_o = raw_c ? c_imm : n_imm;
            assign fu_o = raw_c ? c_fu : n_fu;
            assign op_o = raw_c ? c_op : n_op;
            assign a_sel_o = raw_c ? c_a_sel : n_a_sel;
            assign b_sel_o = raw_c ? c_b_sel : n_b_sel;
            assign pass_link_o = raw_c ? c_pass_link : n_pass_link;
            assign branch_o = raw_c ? c_branch : n_branch;
            assign branch_op_o = raw_c ? c_branch_op : n_branch_op;
            assign lsu_o = raw_c ? c_lsu : n_lsu;
            assign mem_we_o = raw_c ? c_mem_we : n_mem_we;
            assign mem_op_o = raw_c ? c_mem_op : n_mem_op;
            assign wb_kind_o = raw_c ? c_wb_kind : n_wb_kind;
            assign system_o = raw_c ? c_system : n_system;
            assign serialize_o = raw_c ? c_serialize : n_serialize;
            assign csr_addr_o = raw_c ? c_csr_addr : n_csr_addr;
            assign csr_op_o = raw_c ? c_csr_op : n_csr_op;
            assign csr_imm_o = raw_c ? c_csr_imm : n_csr_imm;
            assign rm_o = raw_c ? c_rm : n_rm;
        end else begin : gen_native
            assign native_o = n_native;
            assign illegal_o = n_illegal;
            assign illegal_reg_o = n_illegal_reg;
            assign rs_used_o = n_rs_used;
            assign rs1_o = n_rs1;
            assign rs2_o = n_rs2;
            assign rs3_o = n_rs3;
            assign rd_we_o = n_rd_we;
            assign rd_o = n_rd;
            assign imm_o = n_imm;
            assign fu_o = n_fu;
            assign op_o = n_op;
            assign a_sel_o = n_a_sel;
            assign b_sel_o = n_b_sel;
            assign pass_link_o = n_pass_link;
            assign branch_o = n_branch;
            assign branch_op_o = n_branch_op;
            assign lsu_o = n_lsu;
            assign mem_we_o = n_mem_we;
            assign mem_op_o = n_mem_op;
            assign wb_kind_o = n_wb_kind;
            assign system_o = n_system;
            assign serialize_o = n_serialize;
            assign csr_addr_o = n_csr_addr;
            assign csr_op_o = n_csr_op;
            assign csr_imm_o = n_csr_imm;
            assign rm_o = n_rm;
            if ((ISA_C == 1) && (MUA_C_DECOMPRESS_STAGE == `UQU_C_DECOMPRESS_DE)) begin : gen_expand_de
                wire [31:0] expanded;
                wire is_compressed, is_illegal;
                uqu_decompressor #(.ISA_C(1)) u_decompressor (
                    .instr_i(original_instr_i), .instr_o(expanded), .original_instr_o(),
                    .compressed_o(is_compressed), .illegal_o(is_illegal), .hint_o()
                );
                assign native_instr = raw_c ? (is_compressed ? expanded : 32'd0) : instr_i;
                assign illegal_c_o = raw_c && (is_illegal || !is_compressed);
            end else begin : gen_expand_if
                assign native_instr = instr_i;
                assign illegal_c_o = 1'b0;
            end
        end
        if (((ISA_C != 0) && (ISA_C != 1)) ||
            ((MUA_C_IMPL != `UQU_C_IMPL_DECOMPRESS) && (MUA_C_IMPL != `UQU_C_IMPL_DECODE_COMPRESSED)) ||
            ((MUA_C_DECOMPRESS_STAGE != `UQU_C_DECOMPRESS_IF) &&
             (MUA_C_DECOMPRESS_STAGE != `UQU_C_DECOMPRESS_DE))) begin : gen_invalid
            uqu_decoder_select_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule
`default_nettype wire
