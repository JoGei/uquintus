`default_nettype none
`include "uqu_config.vh"

// Blocking native M-extension unit. Operation values match instruction funct3.
// Arithmetic slice zero is owned by the parent EX stage, combinationally.
module uqu_muldiv #(
    parameter ISA_M = 0,
    parameter MUA_MUL = `UQU_MUL_ITERATIVE,
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

    output wire        arith_use_o,
    output wire [32:0] arith_a_o,
    output wire [32:0] arith_b_o,
    output wire        arith_sub_o,
    output wire        arith_carry_in_o,
    input  wire [32:0] arith_result_i,
    input  wire        arith_carry_out_i
);
    localparam CONFIG_VALID =
        ((MUA_MUL == `UQU_MUL_PARALLEL) ||
         (MUA_MUL == `UQU_MUL_PARALLEL_2) ||
         (MUA_MUL == `UQU_MUL_ITERATIVE)) &&
        (MUA_DIV == `UQU_DIV_ITERATIVE) &&
        ((MUA_MULDIV_ITERUNROLL == 1) || (MUA_MULDIV_ITERUNROLL == 2) ||
         (MUA_MULDIV_ITERUNROLL == 4) || (MUA_MULDIV_ITERUNROLL == 8) ||
         (MUA_MULDIV_ITERUNROLL == 16) || (MUA_MULDIV_ITERUNROLL == 32));

    generate
        if (ISA_M == 0) begin : gen_disabled
            assign req_ready_o = 1'b0;
            assign res_valid_o = 1'b0;
            assign res_data_o = 32'd0;
            assign arith_use_o = 1'b0;
            assign arith_a_o = 33'd0;
            assign arith_b_o = 33'd0;
            assign arith_sub_o = 1'b0;
            assign arith_carry_in_o = 1'b0;
        end else if ((ISA_M == 1) && CONFIG_VALID) begin : gen_enabled
            localparam F = MUA_MULDIV_ITERUNROLL;
            localparam [5:0] STEP_INCREMENT = MUA_MULDIV_ITERUNROLL[5:0];
            localparam [5:0] LAST_GROUP = 6'd32 - STEP_INCREMENT;
            localparam [2:0] ST_IDLE = 3'd0;
            localparam [2:0] ST_MUL = 3'd1;
            localparam [2:0] ST_DIV_PREP_B = 3'd2;
            localparam [2:0] ST_DIV = 3'd3;
            localparam [2:0] ST_DIV_FINISH = 3'd4;
            localparam [2:0] ST_MUL_PARALLEL_2 = 3'd5;
            localparam [2:0] ST_HOLD = 3'd6;

            reg [2:0] state_q;
            reg [2:0] op_q;
            reg [5:0] step_q;
            reg [32:0] accum_q;
            reg [31:0] bits_q;
            reg [32:0] multiplicand_q;
            reg [32:0] divisor_q;
            reg [31:0] original_a_q;
            reg [31:0] original_b_q;
            reg signed_a_q;
            reg signed_b_q;
            reg negative_a_q;
            reg negative_b_q;
            reg divide_zero_q;
            reg [31:0] held_result_q;

            wire enabled = rst_ni && !flush_i;
            wire req_fire = req_valid_i && req_ready_o;
            wire res_fire = res_valid_o && res_ready_i;
            wire start = (state_q == ST_IDLE) && req_fire;
            wire [2:0] op = start ? req_op_i : op_q;
            wire request_signed_a = (req_op_i == 3'b001) || (req_op_i == 3'b010);
            wire request_signed_b = (req_op_i == 3'b001);
            wire request_div_signed = !req_op_i[0];
            wire request_negative_a = request_div_signed && req_a_i[31];
            wire request_negative_b = request_div_signed && req_b_i[31];
            wire signed_a = start ? request_signed_a : signed_a_q;
            wire signed_b = start ? request_signed_b : signed_b_q;
            wire [5:0] step = start ? 6'd0 : step_q;
            wire last_group = (step == LAST_GROUP);
            wire [32:0] multiplicand = start ?
                {request_signed_a && req_a_i[31], req_a_i} : multiplicand_q;
            wire phase_mul = enabled && (MUA_MUL == `UQU_MUL_ITERATIVE) &&
                ((start && !req_op_i[2]) || (state_q == ST_MUL));
            wire phase_prep_a = start && req_op_i[2];
            wire phase_prep_b = enabled && (state_q == ST_DIV_PREP_B);
            wire phase_div = enabled && (state_q == ST_DIV);
            wire phase_finish = enabled && (state_q == ST_DIV_FINISH);
            wire phase_parallel_1 = start && !req_op_i[2] &&
                (MUA_MUL == `UQU_MUL_PARALLEL);
            wire phase_parallel_2 = enabled && (state_q == ST_MUL_PARALLEL_2);

            wire [32:0] selected_magnitude = op_q[1] ? accum_q : {1'b0, bits_q};
            wire [32:0] prepared_b;
            wire [32:0] first_result;
            wire [32:0] next_mul_accum;
            wire [31:0] next_mul_bits;
            wire [32:0] next_div_rem;
            wire [31:0] next_div_bits;
            wire negate_result = op_q[1] ? negative_a_q :
                                                       (negative_a_q ^ negative_b_q);

            assign req_ready_o = enabled && (state_q == ST_IDLE);
            assign arith_use_o = phase_mul || phase_prep_a || phase_prep_b ||
                                 phase_div || phase_finish;
            if (F == 1) begin : gen_serial_preparation
                assign prepared_b = 33'd0;
            end

            genvar slice_idx;
            for (slice_idx = 0; slice_idx < F; slice_idx = slice_idx + 1) begin : gen_slice
                wire [32:0] mul_accum_in;
                wire [31:0] mul_bits_in;
                wire [32:0] div_rem_in;
                wire [31:0] div_bits_in;
                wire [32:0] mul_accum_next;
                wire [31:0] mul_bits_next;
                wire [32:0] div_rem_next;
                wire [31:0] div_bits_next;
                wire [32:0] a;
                wire [32:0] b;
                wire subtract;
                wire [32:0] result;
                wire carry;
                wire last_bit = last_group && (slice_idx == F - 1);
                wire [32:0] shifted_rem = {div_rem_in[31:0], div_bits_in[31]};
                wire shift_sign = (signed_a || (signed_b && last_bit)) && result[32];
                wire prepare_a = phase_prep_a && (slice_idx == 0);
                wire prepare_b = (phase_prep_a && (F >= 2) && (slice_idx == 1)) ||
                                 (phase_prep_b && (slice_idx == 0));
                wire negative_b = phase_prep_a ? request_negative_b : negative_b_q;
                wire [31:0] raw_b = phase_prep_a ? req_b_i : original_b_q;

                // Separate nets per generated step keep the feed-forward chain
                // explicit to synthesis and simulation dependency analysis.
                if (slice_idx == 0) begin : gen_first
                    assign arith_a_o = a;
                    assign arith_b_o = b;
                    assign arith_sub_o = subtract;
                    assign arith_carry_in_o = subtract;
                    assign first_result = result;
                    assign mul_accum_in = start ? 33'd0 : accum_q;
                    assign mul_bits_in = start ? req_b_i : bits_q;
                    assign div_rem_in = accum_q;
                    assign div_bits_in = bits_q;
                    assign result = arith_result_i;
                    assign carry = arith_carry_out_i;
                end else begin : gen_following
                    assign mul_accum_in = gen_slice[slice_idx-1].mul_accum_next;
                    assign mul_bits_in = gen_slice[slice_idx-1].mul_bits_next;
                    assign div_rem_in = gen_slice[slice_idx-1].div_rem_next;
                    assign div_bits_in = gen_slice[slice_idx-1].div_bits_next;
                    uqu_arith u_arith (
                        .a_i(a),
                        .b_i(b),
                        .sub_i(subtract),
                        .carry_i(subtract),
                        .result_o(result),
                        .carry_o(carry),
                        .borrow_o()
                    );
                end

                if (slice_idx == 1) begin : gen_prepare_b
                    assign prepared_b = result;
                end
                if (slice_idx == F - 1) begin : gen_last
                    assign next_mul_accum = mul_accum_next;
                    assign next_mul_bits = mul_bits_next;
                    assign next_div_rem = div_rem_next;
                    assign next_div_bits = div_bits_next;
                end

                assign a = phase_mul ? mul_accum_in : phase_div ? shifted_rem : 33'd0;
                assign b = phase_mul ? (mul_bits_in[0] ? multiplicand : 33'd0) :
                    phase_div ? divisor_q :
                    prepare_a ? {request_negative_a, req_a_i} :
                    prepare_b ? {negative_b, raw_b} :
                    (phase_finish && (slice_idx == 0)) ? selected_magnitude : 33'd0;
                assign subtract = phase_mul ? (signed_b && last_bit) :
                    phase_div ? 1'b1 :
                    prepare_a ? request_negative_a :
                    prepare_b ? negative_b :
                    (phase_finish && (slice_idx == 0)) ? negate_result : 1'b0;

                // A signed multiplier's final (negative-weight) bit subtracts
                // the multiplicand. Sign filling then preserves the full product
                // without setup negations or a separate correction cycle.
                assign mul_accum_next = {shift_sign, result[32:1]};
                assign mul_bits_next = {result[0], mul_bits_in[31:1]};
                // Restore by selection after the trial subtraction; no second
                // adder is needed when the trial remainder would be negative.
                assign div_rem_next = carry ? result : shifted_rem;
                assign div_bits_next = {div_bits_in[30:0], carry};
            end

            wire [31:0] iterative_product = (op == 3'b000) ?
                next_mul_bits : next_mul_accum[31:0];
            wire [31:0] parallel_product;
            wire [31:0] parallel_product_2;

            if (MUA_MUL == `UQU_MUL_PARALLEL) begin : gen_parallel
                wire signed [32:0] operand_a = {request_signed_a && req_a_i[31], req_a_i};
                wire signed [32:0] operand_b = {request_signed_b && req_b_i[31], req_b_i};
                wire signed [65:0] product = operand_a * operand_b;
                assign parallel_product = (req_op_i == 3'b000) ?
                                            product[31:0] : product[63:32];
                assign parallel_product_2 = 32'd0;
            end else if (MUA_MUL == `UQU_MUL_PARALLEL_2) begin : gen_parallel_2
                // Stage 1 computes the low partial product. Stage 2 computes
                // the high partial product and combines them after a real
                // internal register boundary; this is not a delayed full product.
                wire signed [32:0] operand_b = {request_signed_b && req_b_i[31], req_b_i};
                wire signed [16:0] low_a = {1'b0, req_a_i[15:0]};
                wire signed [49:0] low_product = low_a * operand_b;
                reg signed [49:0] low_product_q;
                reg signed [16:0] high_a_q;
                reg signed [32:0] operand_b_q;
                wire signed [49:0] high_product = high_a_q * operand_b_q;
                wire [65:0] combined_product =
                    {{16{low_product_q[49]}}, low_product_q} +
                    {high_product, 16'd0};
                always @(posedge clk_i) begin
                    if (enabled && start && !req_op_i[2]) begin
                        low_product_q <= low_product;
                        high_a_q <= {request_signed_a && req_a_i[31], req_a_i[31:16]};
                        operand_b_q <= operand_b;
                    end
                end
                assign parallel_product = 32'd0;
                assign parallel_product_2 = (op_q == 3'b000) ?
                    combined_product[31:0] : combined_product[63:32];
            end else begin : gen_no_parallel
                assign parallel_product = 32'd0;
                assign parallel_product_2 = 32'd0;
            end

            wire complete = phase_parallel_1 || phase_parallel_2 ||
                            (phase_mul && last_group) || phase_finish;
            wire [31:0] completed_result = phase_parallel_1 ? parallel_product :
                phase_parallel_2 ? parallel_product_2 :
                phase_mul ? iterative_product :
                divide_zero_q ? (op_q[1] ? original_a_q : 32'hffffffff) :
                first_result[31:0];
            assign res_valid_o = enabled && (complete || (state_q == ST_HOLD));
            assign res_data_o = !res_valid_o ? 32'd0 :
                (state_q == ST_HOLD) ? held_result_q : completed_result;

            always @(posedge clk_i) begin
                if (!rst_ni || flush_i) begin
                    state_q <= ST_IDLE;
                end else begin
                    if (complete && !res_ready_i) begin
                        held_result_q <= completed_result;
                    end
                    case (state_q)
                        ST_IDLE: begin
                            if (req_fire) begin
                                op_q <= req_op_i;
                                original_a_q <= req_a_i;
                                original_b_q <= req_b_i;
                                signed_a_q <= request_signed_a;
                                signed_b_q <= request_signed_b;
                                negative_a_q <= request_negative_a;
                                negative_b_q <= request_negative_b;
                                divide_zero_q <= (req_b_i == 32'd0);
                                multiplicand_q <= {request_signed_a && req_a_i[31], req_a_i};
                                if (req_op_i[2]) begin
                                    accum_q <= 33'd0;
                                    bits_q <= first_result[31:0];
                                    step_q <= 6'd0;
                                    if (F == 1) begin
                                        state_q <= ST_DIV_PREP_B;
                                    end else begin
                                        divisor_q <= prepared_b;
                                        state_q <= ST_DIV;
                                    end
                                end else if (MUA_MUL == `UQU_MUL_PARALLEL) begin
                                    state_q <= res_fire ? ST_IDLE : ST_HOLD;
                                end else if (MUA_MUL == `UQU_MUL_PARALLEL_2) begin
                                    state_q <= ST_MUL_PARALLEL_2;
                                end else if (last_group) begin
                                    state_q <= res_fire ? ST_IDLE : ST_HOLD;
                                end else begin
                                    accum_q <= next_mul_accum;
                                    bits_q <= next_mul_bits;
                                    step_q <= STEP_INCREMENT;
                                    state_q <= ST_MUL;
                                end
                            end
                        end
                        ST_MUL: begin
                            if (last_group) begin
                                state_q <= res_fire ? ST_IDLE : ST_HOLD;
                            end else begin
                                accum_q <= next_mul_accum;
                                bits_q <= next_mul_bits;
                                step_q <= step_q + STEP_INCREMENT;
                            end
                        end
                        ST_DIV_PREP_B: begin
                            divisor_q <= first_result;
                            state_q <= ST_DIV;
                        end
                        ST_DIV: begin
                            accum_q <= next_div_rem;
                            bits_q <= next_div_bits;
                            if (last_group) begin
                                state_q <= ST_DIV_FINISH;
                            end else begin
                                step_q <= step_q + STEP_INCREMENT;
                            end
                        end
                        ST_DIV_FINISH, ST_MUL_PARALLEL_2: begin
                            state_q <= res_fire ? ST_IDLE : ST_HOLD;
                        end
                        ST_HOLD: begin
                            if (res_fire) begin
                                state_q <= ST_IDLE;
                            end
                        end
                        default: state_q <= ST_IDLE;
                    endcase
                end
            end
        end else begin : gen_invalid_configuration
            uqu_muldiv_invalid_configuration u_invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
