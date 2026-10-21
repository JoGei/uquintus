`default_nettype none

// Direct branch tests plus a decoder-fed sibling, all combinational.
module uqu_branch_tb #(
    parameter ISA_C = 0
) (
    input wire [1:0] branch_i,
    input wire [2:0] branch_op_i,
    input wire [31:0] pc_i,
    input wire [31:0] imm_i,
    input wire [31:0] rs1_i,
    input wire [31:0] rs2_i,
    input wire compressed_i,
    output wire taken_o,
    output wire [31:0] target_o,
    output wire [31:0] next_pc_o,
    output wire [31:0] link_o,
    output wire illegal_o,
    output wire misaligned_o,
    input wire [31:0] instr_i,
    output wire dec_illegal_o,
    output wire [1:0] dec_branch_o,
    output wire [2:0] dec_branch_op_o,
    output wire [31:0] dec_imm_o,
    output wire dec_pass_link_o,
    output wire dec_taken_o,
    output wire [31:0] dec_target_o,
    output wire [31:0] dec_next_pc_o,
    output wire [31:0] dec_link_o,
    output wire dec_control_illegal_o,
    output wire dec_misaligned_o
);
    uqu_branch #(.ISA_C(ISA_C)) u_branch (
        .branch_i(branch_i), .branch_op_i(branch_op_i), .pc_i(pc_i), .imm_i(imm_i),
        .rs1_i(rs1_i), .rs2_i(rs2_i), .compressed_i(compressed_i),
        .taken_o(taken_o), .target_o(target_o), .next_pc_o(next_pc_o), .link_o(link_o),
        .illegal_o(illegal_o), .misaligned_o(misaligned_o)
    );

    uqu_decoder u_decoder (
        .instr_i(instr_i), .native_o(), .illegal_o(dec_illegal_o), .illegal_reg_o(),
        .rs_used_o(), .rs1_o(), .rs2_o(), .rs3_o(), .rd_we_o(), .rd_o(),
        .imm_o(dec_imm_o), .fu_o(), .op_o(), .a_sel_o(), .b_sel_o(),
        .pass_link_o(dec_pass_link_o), .branch_o(dec_branch_o), .branch_op_o(dec_branch_op_o),
        .lsu_o(), .mem_we_o(), .mem_op_o(), .wb_kind_o(), .system_o(), .serialize_o(),
        .csr_addr_o(), .csr_op_o(), .csr_imm_o(), .rm_o()
    );

    uqu_branch #(.ISA_C(ISA_C)) u_decoded_branch (
        .branch_i(dec_branch_o), .branch_op_i(dec_branch_op_o), .pc_i(pc_i), .imm_i(dec_imm_o),
        .rs1_i(rs1_i), .rs2_i(rs2_i), .compressed_i(compressed_i),
        .taken_o(dec_taken_o), .target_o(dec_target_o), .next_pc_o(dec_next_pc_o),
        .link_o(dec_link_o), .illegal_o(dec_control_illegal_o), .misaligned_o(dec_misaligned_o)
    );
endmodule

`default_nettype wire
