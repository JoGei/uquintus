`default_nettype none
`include "uqu_config.vh"

// EX execution/control only. The parent owns DE/EX and EX/MEM registers,
// including instruction validity, payload, identity, and downstream capacity.
module uqu_ex #(
    parameter ISA_M = 0,
    parameter ISA_ZFINX = 0,
    parameter MUA_MUL = `UQU_MUL_ITERATIVE,
    parameter MUA_DIV = `UQU_DIV_ITERATIVE,
    parameter MUA_MULDIV_ITERUNROLL = 8
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        flush_i,
    input  wire        valid_i,
    output wire        ready_o,
    output wire        valid_o,
    input  wire        ready_i,
    input  wire [1:0]  fu_i,
    input  wire [4:0]  op_i,
    input  wire        operands_ready_i,
    input  wire [31:0] a_i,
    input  wire [31:0] b_i,
    input  wire [31:0] c_i,
    input  wire [2:0]  rm_i,
    input  wire [31:0] pass_data_i,
    input  wire [31:0] store_data_i,
    input  wire [31:0] instr_i,
    input  wire        exception_valid_i,
    input  wire [4:0]  exception_cause_i,
    input  wire [31:0] exception_tval_i,
    output wire [31:0] result_o,
    output wire [31:0] store_data_o,
    output wire        fflags_valid_o,
    output wire [4:0]  fflags_o,
    output wire        exception_valid_o,
    output wire [4:0]  exception_cause_o,
    output wire [31:0] exception_tval_o
);
    localparam [1:0] FU_ALU = 2'd0;
    localparam [1:0] FU_MULDIV = 2'd1;
    localparam [1:0] FU_FPU = 2'd2;
    localparam [1:0] FU_PASS = 2'd3;
    localparam [4:0] CAUSE_ILLEGAL_INSTRUCTION = 5'd2;

    // Tracks unit request acceptance or pass-through operand qualification,
    // not ownership of a pipeline slot.
    reg issued_q;
    wire enabled = rst_ni && !flush_i;
    wire active = enabled && valid_i;
    wire alu_selected = (fu_i == FU_ALU);
    wire muldiv_selected = (fu_i == FU_MULDIV);
    wire fpu_selected = (fu_i == FU_FPU);
    wire pass_selected = (fu_i == FU_PASS);
    wire alu_op_valid = !op_i[4] && ((!op_i[3]) ||
                        (op_i[3:0] == 4'd8) || (op_i[3:0] == 4'd13));
    wire illegal_control = (alu_selected && !alu_op_valid) ||
        (muldiv_selected && ((ISA_M == 0) || (op_i[4:3] != 2'b00))) ||
        (fpu_selected && ((ISA_ZFINX == 0) || (op_i > 5'd21)));
    wire fault = exception_valid_i || illegal_control;
    wire request_valid = active && !fault && !issued_q && operands_ready_i;
    wire result_ready = active && !fault && ready_i;
    wire ex_fire = valid_o && ready_i;

    wire alu_req_ready;
    wire alu_res_valid;
    wire [31:0] alu_result;
    wire alu_arith_use;
    wire [32:0] alu_arith_a;
    wire [32:0] alu_arith_b;
    wire alu_arith_sub;
    wire alu_arith_carry_in;
    wire muldiv_req_ready;
    wire muldiv_res_valid;
    wire [31:0] muldiv_result;
    wire muldiv_arith_use;
    wire [32:0] muldiv_arith_a;
    wire [32:0] muldiv_arith_b;
    wire muldiv_arith_sub;
    wire muldiv_arith_carry_in;
    wire fpu_req_ready;
    wire fpu_res_valid;
    wire [31:0] fpu_result;
    wire [4:0] fpu_fflags;
    wire [32:0] arith_result;
    wire arith_carry_out;
    wire fu_req_fire = request_valid &&
        ((alu_selected && alu_req_ready) || (muldiv_selected && muldiv_req_ready) ||
         (fpu_selected && fpu_req_ready));
    wire fu_res_valid = (alu_selected && alu_res_valid) ||
        (muldiv_selected && muldiv_res_valid) || (fpu_selected && fpu_res_valid);

    // Empty DE/EX can be filled even when the downstream register is occupied.
    // An occupied slot is replaced only when its instruction transfers onward.
    assign valid_o = active && (fault || (pass_selected && (operands_ready_i || issued_q)) ||
                               (!fault && fu_res_valid));
    assign ready_o = enabled && (!valid_i || (valid_o && ready_i));
    assign exception_valid_o = valid_o && fault;
    assign exception_cause_o = !exception_valid_o ? 5'd0 :
        exception_valid_i ? exception_cause_i : CAUSE_ILLEGAL_INSTRUCTION;
    assign exception_tval_o = !exception_valid_o ? 32'd0 :
        exception_valid_i ? exception_tval_i : instr_i;
    assign result_o = !valid_o || fault ? 32'd0 :
        alu_selected ? alu_result : muldiv_selected ? muldiv_result :
        fpu_selected ? fpu_result : pass_data_i;
    assign store_data_o = valid_o && !fault ? store_data_i : 32'd0;
    assign fflags_valid_o = valid_o && !fault && fpu_selected;
    assign fflags_o = fflags_valid_o ? fpu_fflags : 5'd0;

    always @(posedge clk_i) begin
        if (!rst_ni || flush_i) begin
            issued_q <= 1'b0;
        end else if (ex_fire) begin
            issued_q <= 1'b0;
        end else if (fu_req_fire || (request_valid && pass_selected)) begin
            issued_q <= 1'b1;
        end
    end

    uqu_alu u_alu (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i),
        .req_valid_i(request_valid && alu_selected), .req_ready_o(alu_req_ready),
        .req_op_i(op_i[3:0]), .req_a_i(a_i), .req_b_i(b_i),
        .res_valid_o(alu_res_valid), .res_ready_i(result_ready && alu_selected),
        .res_data_o(alu_result), .arith_use_o(alu_arith_use),
        .arith_a_o(alu_arith_a), .arith_b_o(alu_arith_b), .arith_sub_o(alu_arith_sub),
        .arith_carry_in_o(alu_arith_carry_in), .arith_result_i(arith_result),
        .arith_carry_out_i(arith_carry_out)
    );

    uqu_muldiv #(
        .ISA_M(ISA_M), .MUA_MUL(MUA_MUL), .MUA_DIV(MUA_DIV),
        .MUA_MULDIV_ITERUNROLL(MUA_MULDIV_ITERUNROLL)
    ) u_muldiv (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i),
        .req_valid_i(request_valid && muldiv_selected), .req_ready_o(muldiv_req_ready),
        .req_op_i(op_i[2:0]), .req_a_i(a_i), .req_b_i(b_i),
        .res_valid_o(muldiv_res_valid), .res_ready_i(result_ready && muldiv_selected),
        .res_data_o(muldiv_result), .arith_use_o(muldiv_arith_use),
        .arith_a_o(muldiv_arith_a), .arith_b_o(muldiv_arith_b),
        .arith_sub_o(muldiv_arith_sub), .arith_carry_in_o(muldiv_arith_carry_in),
        .arith_result_i(arith_result), .arith_carry_out_i(arith_carry_out)
    );

    uqu_fpu #(.ISA_ZFINX(ISA_ZFINX)) u_fpu (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i),
        .req_valid_i(request_valid && fpu_selected), .req_ready_o(fpu_req_ready),
        .req_op_i(op_i), .req_a_i(a_i), .req_b_i(b_i), .req_c_i(c_i), .req_rm_i(rm_i),
        .res_valid_o(fpu_res_valid), .res_ready_i(result_ready && fpu_selected),
        .res_data_o(fpu_result), .res_fflags_o(fpu_fflags)
    );

    // EX owns slice zero. Return wires fan out; only the owning unit consumes
    // them. No iteration can be stalled or arbitrated independently.
    uqu_arith u_arith (
        .a_i(muldiv_arith_use ? muldiv_arith_a : alu_arith_a),
        .b_i(muldiv_arith_use ? muldiv_arith_b : alu_arith_b),
        .sub_i(muldiv_arith_use ? muldiv_arith_sub : alu_arith_sub),
        .carry_i(muldiv_arith_use ? muldiv_arith_carry_in : alu_arith_carry_in),
        .result_o(arith_result), .carry_o(arith_carry_out), .borrow_o()
    );
endmodule

`default_nettype wire
