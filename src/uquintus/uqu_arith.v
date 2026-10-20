`default_nettype none

// Shared extended add/sub datapath for the ALU and iterative MUL/DIV slices.
// carry_i is the raw adder carry-in in both modes:
//   sub_i = 0: A + B + carry_i
//   sub_i = 1: A - B - (1 - carry_i)
// For ordinary subtraction, drive carry_i high. Subtraction carry-out means
// no borrow; borrow_o is meaningful only in subtraction mode and zero in add.
module uqu_arith (
    input  wire [32:0] a_i,
    input  wire [32:0] b_i,
    input  wire        sub_i,
    input  wire        carry_i,
    output wire [32:0] result_o,
    output wire        carry_o,
    output wire        borrow_o
);
    wire [32:0] b_operand;
    wire [33:0] sum;

    assign b_operand = b_i ^ {33{sub_i}};
    assign sum = {1'b0, a_i} + {1'b0, b_operand} + {33'd0, carry_i};

    assign result_o = sum[32:0];
    assign carry_o = sum[33];
    assign borrow_o = sub_i && !sum[33];
endmodule

`default_nettype wire
