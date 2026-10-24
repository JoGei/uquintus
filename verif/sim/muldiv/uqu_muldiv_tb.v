`default_nettype none
`include "uqu_config.vh"

// The parent owns the shared first arithmetic instance, as EX will. The DUT contains only the remaining F-1 arithmetic instances.
module uqu_muldiv_tb #(
    parameter ISA_M = 0,
    parameter MUA_MUL = `UQU_MUL_DADDA_MAC,
    parameter MUA_DIV = `UQU_DIV_ITERATIVE,
    parameter MUA_MULDIV_ITERUNROLL = 8
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        flush_i,
    input  wire        req_valid_i,
    output wire        req_ready_o,
    input  wire [2:0]  req_op_i,
    input  wire [31:0] req_a_i,
    input  wire [31:0] req_b_i,
    output wire        res_valid_o,
    input  wire        res_ready_i,
    output wire [31:0] res_data_o,
    output wire        arith_use_o
);
    wire [32:0] arith_a;
    wire [32:0] arith_b;
    wire arith_sub;
    wire arith_carry_in;
    wire [32:0] arith_result;
    wire arith_carry_out;

    uqu_arith u_shared_arith (
        .a_i(arith_a),
        .b_i(arith_b),
        .sub_i(arith_sub),
        .carry_i(arith_carry_in),
        .result_o(arith_result),
        .carry_o(arith_carry_out),
        .borrow_o()
    );

    uqu_muldiv #(
        .ISA_M(ISA_M),
        .MUA_MUL(MUA_MUL),
        .MUA_DIV(MUA_DIV),
        .MUA_MULDIV_ITERUNROLL(MUA_MULDIV_ITERUNROLL)
    ) u_muldiv (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .flush_i(flush_i),
        .req_valid_i(req_valid_i),
        .req_ready_o(req_ready_o),
        .req_op_i(req_op_i),
        .req_a_i(req_a_i),
        .req_b_i(req_b_i),
        .res_valid_o(res_valid_o),
        .res_ready_i(res_ready_i),
        .res_data_o(res_data_o),
        .arith_use_o(arith_use_o),
        .arith_a_o(arith_a),
        .arith_b_o(arith_b),
        .arith_sub_o(arith_sub),
        .arith_carry_in_o(arith_carry_in),
        .arith_result_i(arith_result),
        .arith_carry_out_i(arith_carry_out)
    );
endmodule

`default_nettype wire
