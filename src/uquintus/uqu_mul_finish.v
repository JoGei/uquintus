// SPDX-License-Identifier: Unlicense
`default_nettype none

// MEM/EX2: fuse late C with the two registered product rows before one CPA.
// The behavioral final addition uses the established Yosys Brent-Kung mapping.
// Parent-owned payload and tags remain stable until the instruction transfers.
module uqu_mul_finish (
    input  wire [63:0] row_a_i,
    input  wire [63:0] row_b_i,
    input  wire        high_i,
    input  wire        accumulate_i,
    input  wire [31:0] addend_i,
    output wire [31:0] result_o
);
    wire [63:0] c = {32'd0, accumulate_i ? addend_i : 32'd0};
    wire [63:0] final_a = row_a_i ^ row_b_i ^ c;
    wire [63:0] final_b = ((row_a_i & row_b_i) |
        (row_a_i & c) | (row_b_i & c)) << 1;
    wire [63:0] product = final_a + final_b;
    assign result_o = high_i ? product[63:32] : product[31:0];
endmodule

`default_nettype wire
