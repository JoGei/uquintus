`default_nettype none
module uqu_daddamul_rows_tb (
    input wire [31:0] a_i,
    input wire [31:0] b_i,
    input wire signed_a_i,
    input wire signed_b_i,
    output wire [63:0] product_o
);
    wire [63:0] row_a, row_b;
    uqu_daddamul_rows u_rows (
        .a_i(a_i), .b_i(b_i), .signed_a_i(signed_a_i), .signed_b_i(signed_b_i),
        .row_a_o(row_a), .row_b_o(row_b)
    );
    uqu_mul_finish u_low (
        .row_a_i(row_a), .row_b_i(row_b), .high_i(1'b0),
        .accumulate_i(1'b0), .addend_i(32'd0), .result_o(product_o[31:0])
    );
    uqu_mul_finish u_high (
        .row_a_i(row_a), .row_b_i(row_b), .high_i(1'b1),
        .accumulate_i(1'b0), .addend_i(32'd0), .result_o(product_o[63:32])
    );
endmodule
`default_nettype wire
