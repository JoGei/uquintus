`default_nettype none
`include "uqu_ctrl.vh"

// One-cycle RV32I/E ALU. EX owns the external uqu_arith instance and
// reserves it for this instruction; arithmetic has no separate handshake.
module uqu_alu (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        flush_i,
    input  wire        req_valid_i,
    output wire        req_ready_o,
    input  wire [3:0]  req_op_i,
    input  wire [31:0] req_a_i,
    input  wire [31:0] req_b_i,
    output wire        res_valid_o,
    input  wire        res_ready_i,
    output wire [31:0] res_data_o,

    output wire        arith_use_o,
    output wire [32:0] arith_a_o,
    output wire [32:0] arith_b_o,
    output wire        arith_sub_o,
    output wire        arith_carry_in_o,
    input  wire [32:0] arith_result_i,
    input  wire        arith_carry_out_i
);
    // Low three bits match funct3; bit three distinguishes SUB and SRA.
    // Decode normalizes this modifier; it is not raw instruction bit 30
    // for immediate operations or unrelated funct3 values.
    localparam [3:0] OP_ADD  = `UQU_ALU_ADD;
    localparam [3:0] OP_SLL  = `UQU_ALU_SLL;
    localparam [3:0] OP_SLT  = `UQU_ALU_SLT;
    localparam [3:0] OP_SLTU = `UQU_ALU_SLTU;
    localparam [3:0] OP_XOR  = `UQU_ALU_XOR;
    localparam [3:0] OP_SRL  = `UQU_ALU_SRL;
    localparam [3:0] OP_OR   = `UQU_ALU_OR;
    localparam [3:0] OP_AND  = `UQU_ALU_AND;
    localparam [3:0] OP_SUB  = `UQU_ALU_SUB;
    localparam [3:0] OP_SRA  = `UQU_ALU_SRA;

    reg held_valid_q;
    reg [31:0] held_result_q;
    reg [31:0] computed_result;
    wire enabled = rst_ni && !flush_i;
    wire req_fire = req_valid_i && req_ready_o;
    wire res_fire = res_valid_o && res_ready_i;
    wire subtract = (req_op_i == OP_SUB) || (req_op_i == OP_SLT) ||
                    (req_op_i == OP_SLTU);
    wire signed_compare = (req_op_i == OP_SLT);
    wire left_shift = (req_op_i == OP_SLL);
    wire arithmetic_shift = (req_op_i == OP_SRA);
    wire [31:0] reversed_a;
    wire [31:0] reversed_shift;
    wire [31:0] shift_operand = left_shift ? reversed_a : req_a_i;
    wire signed [32:0] shift_input = {arithmetic_shift && req_a_i[31], shift_operand};
    wire signed [32:0] shift_result = shift_input >>> req_b_i[4:0];

    assign req_ready_o = enabled && !held_valid_q;
    assign arith_use_o = req_fire && ((req_op_i == OP_ADD) || subtract);
    // Signed subtraction has a 33-bit signed result, including overflow of
    // the ordinary 32-bit difference. Unsigned subtraction uses no-borrow.
    assign arith_a_o = arith_use_o ?
        {signed_compare && req_a_i[31], req_a_i} : 33'd0;
    assign arith_b_o = arith_use_o ?
        {signed_compare && req_b_i[31], req_b_i} : 33'd0;
    assign arith_sub_o = arith_use_o && subtract;
    assign arith_carry_in_o = arith_sub_o;

    // Reversing wires around one right barrel shifter also implements SLL.
    genvar bit_idx;
    generate
        for (bit_idx = 0; bit_idx < 32; bit_idx = bit_idx + 1) begin : gen_reverse
            assign reversed_a[bit_idx] = req_a_i[31-bit_idx];
            assign reversed_shift[bit_idx] = shift_result[31-bit_idx];
        end
    endgenerate

    always @* begin
        computed_result = 32'd0;
        case (req_op_i)
            OP_ADD, OP_SUB: computed_result = arith_result_i[31:0];
            OP_SLL: computed_result = reversed_shift;
            OP_SLT: computed_result = {31'd0, arith_result_i[32]};
            OP_SLTU: computed_result = {31'd0, !arith_carry_out_i};
            OP_XOR: computed_result = req_a_i ^ req_b_i;
            OP_SRL, OP_SRA: computed_result = shift_result[31:0];
            OP_OR: computed_result = req_a_i | req_b_i;
            OP_AND: computed_result = req_a_i & req_b_i;
            default: computed_result = 32'd0;
        endcase
    end

    assign res_valid_o = enabled && (held_valid_q || req_fire);
    assign res_data_o = !res_valid_o ? 32'd0 :
                       held_valid_q ? held_result_q : computed_result;

    always @(posedge clk_i) begin
        if (!rst_ni || flush_i) begin
            held_valid_q <= 1'b0;
        end else if (held_valid_q) begin
            if (res_fire) begin
                held_valid_q <= 1'b0;
            end
        end else if (req_fire && !res_ready_i) begin
            held_valid_q <= 1'b1;
            held_result_q <= computed_result;
        end
    end
endmodule

`default_nettype wire
