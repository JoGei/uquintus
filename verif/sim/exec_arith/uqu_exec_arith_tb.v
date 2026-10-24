`default_nettype none
`include "uqu_config.vh"

// Verification fixture for EX-owned arithmetic. select_muldiv_i represents
// the owning EX instruction and must remain stable until result transfer or
// cancellation. This is not the processor's future EX-stage implementation.
module uqu_exec_arith_tb #(
    parameter ISA_M = 0,
    parameter MUA_MUL = `UQU_MUL_DADDA_MAC,
    parameter MUA_DIV = `UQU_DIV_ITERATIVE,
    parameter MUA_MULDIV_ITERUNROLL = 8
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        flush_i,
    input  wire        select_muldiv_i,
    input  wire        req_valid_i,
    output wire        req_ready_o,
    input  wire [3:0]  req_op_i,
    input  wire [31:0] req_a_i,
    input  wire [31:0] req_b_i,
    output wire        res_valid_o,
    input  wire        res_ready_i,
    output wire [31:0] res_data_o,
    output wire        alu_arith_use_o,
    output wire        muldiv_arith_use_o
);
    wire alu_req_ready;
    wire alu_res_valid;
    wire [31:0] alu_res_data;
    wire [32:0] alu_arith_a;
    wire [32:0] alu_arith_b;
    wire alu_arith_sub;
    wire alu_arith_carry_in;
    wire muldiv_req_ready;
    wire muldiv_res_valid;
    wire [31:0] muldiv_res_data;
    wire [32:0] muldiv_arith_a;
    wire [32:0] muldiv_arith_b;
    wire muldiv_arith_sub;
    wire muldiv_arith_carry_in;
    wire [32:0] arith_result;
    wire arith_carry_out;

    assign req_ready_o = select_muldiv_i ? muldiv_req_ready : alu_req_ready;
    assign res_valid_o = select_muldiv_i ? muldiv_res_valid : alu_res_valid;
    assign res_data_o = select_muldiv_i ? muldiv_res_data : alu_res_data;

    uqu_alu u_alu (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i),
        .req_valid_i(req_valid_i && !select_muldiv_i), .req_ready_o(alu_req_ready),
        .req_op_i(req_op_i), .req_a_i(req_a_i), .req_b_i(req_b_i),
        .res_valid_o(alu_res_valid), .res_ready_i(res_ready_i && !select_muldiv_i),
        .res_data_o(alu_res_data),
        .arith_use_o(alu_arith_use_o), .arith_a_o(alu_arith_a), .arith_b_o(alu_arith_b),
        .arith_sub_o(alu_arith_sub), .arith_carry_in_o(alu_arith_carry_in),
        .arith_result_i(arith_result), .arith_carry_out_i(arith_carry_out)
    );

    uqu_muldiv #(
        .ISA_M(ISA_M), .MUA_MUL(MUA_MUL), .MUA_DIV(MUA_DIV),
        .MUA_MULDIV_ITERUNROLL(MUA_MULDIV_ITERUNROLL)
    ) u_muldiv (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i),
        .req_valid_i(req_valid_i && select_muldiv_i), .req_ready_o(muldiv_req_ready),
        .req_op_i(req_op_i[2:0]), .req_a_i(req_a_i), .req_b_i(req_b_i),
        .res_valid_o(muldiv_res_valid), .res_ready_i(res_ready_i && select_muldiv_i),
        .res_data_o(muldiv_res_data),
        .arith_use_o(muldiv_arith_use_o), .arith_a_o(muldiv_arith_a),
        .arith_b_o(muldiv_arith_b), .arith_sub_o(muldiv_arith_sub),
        .arith_carry_in_o(muldiv_arith_carry_in),
        .arith_result_i(arith_result), .arith_carry_out_i(arith_carry_out)
    );

    uqu_arith u_arith (
        .a_i(select_muldiv_i ? muldiv_arith_a : alu_arith_a),
        .b_i(select_muldiv_i ? muldiv_arith_b : alu_arith_b),
        .sub_i(select_muldiv_i ? muldiv_arith_sub : alu_arith_sub),
        .carry_i(select_muldiv_i ? muldiv_arith_carry_in : alu_arith_carry_in),
        .result_o(arith_result), .carry_o(arith_carry_out), .borrow_o()
    );
endmodule

`default_nettype wire
