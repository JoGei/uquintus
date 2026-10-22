`default_nettype none
`include "uqu_config.vh"
`include "uqu_ctrl.vh"

// Blocking scalar Zfinx adapter to the pinned CVFPU/FPnew backend.
// One request may be in flight; flags travel with its result to retirement.
module uqu_fpu #(
    parameter ISA_ZFINX = 0,
    parameter MUA_FPU_PIPE_REGS_FMA = 2,
    parameter MUA_FPU_PIPE_REGS_DIVSQRT = 0,
    parameter MUA_FPU_PIPE_REGS_NONCOMP = 0,
    parameter MUA_FPU_PIPE_REGS_CONV = 1,
    parameter MUA_FPU_PIPE_CONFIG = `UQU_FPU_PIPE_DISTRIBUTED,
    parameter MUA_FPU_DIVSQRT = `UQU_FPU_DIVSQRT_TH32
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        flush_i,
    input  wire        req_valid_i,
    output wire        req_ready_o,
    // Decoded scalar operation; encodings are in specification Section 3.3.1.
    input  wire [4:0]  req_op_i,
    input  wire [31:0] req_a_i,
    input  wire [31:0] req_b_i,
    input  wire [31:0] req_c_i,
    input  wire [2:0]  req_rm_i,
    output wire        res_valid_o,
    input  wire        res_ready_i,
    output wire [31:0] res_data_o,
    output wire [4:0]  res_fflags_o
);
    generate
        if ((MUA_FPU_PIPE_REGS_FMA < 0) || (MUA_FPU_PIPE_REGS_FMA > 32'h7fffffff) ||
            (MUA_FPU_PIPE_REGS_DIVSQRT < 0) || (MUA_FPU_PIPE_REGS_DIVSQRT > 32'h7fffffff) ||
            (MUA_FPU_PIPE_REGS_NONCOMP < 0) || (MUA_FPU_PIPE_REGS_NONCOMP > 32'h7fffffff) ||
            (MUA_FPU_PIPE_REGS_CONV < 0) || (MUA_FPU_PIPE_REGS_CONV > 32'h7fffffff) ||
            ((MUA_FPU_PIPE_CONFIG != `UQU_FPU_PIPE_BEFORE) &&
             (MUA_FPU_PIPE_CONFIG != `UQU_FPU_PIPE_AFTER) &&
             (MUA_FPU_PIPE_CONFIG != `UQU_FPU_PIPE_INSIDE) &&
             (MUA_FPU_PIPE_CONFIG != `UQU_FPU_PIPE_DISTRIBUTED)) ||
            ((MUA_FPU_DIVSQRT != `UQU_FPU_DIVSQRT_PULP) &&
             (MUA_FPU_DIVSQRT != `UQU_FPU_DIVSQRT_TH32) &&
             (MUA_FPU_DIVSQRT != `UQU_FPU_DIVSQRT_THMULTI)) ||
            ((ISA_ZFINX != 0) && (MUA_FPU_DIVSQRT == `UQU_FPU_DIVSQRT_PULP))) begin : gen_invalid_configuration
            uqu_fpu_invalid_configuration invalid_configuration ();
        end else if (ISA_ZFINX == 0) begin : gen_disabled
            assign req_ready_o = 1'b0;
            assign res_valid_o = 1'b0;
            assign res_data_o = 32'd0;
            assign res_fflags_o = 5'd0;
        end else begin : gen_enabled
            // Packed layouts and enum encodings are the ABI of the pinned
            // fpnew_pkg. Keep this boundary in Verilog-2005. Only FP32 and
            // INT32 exist; vectors, NaN boxing and other formats are disabled.
            localparam [42:0] FEATURES = {32'd32, 1'b0, 1'b0, 5'b10000, 4'b0010};
            localparam [31:0] PIPE_FMA = MUA_FPU_PIPE_REGS_FMA;
            localparam [31:0] PIPE_DIVSQRT = MUA_FPU_PIPE_REGS_DIVSQRT;
            localparam [31:0] PIPE_NONCOMP = MUA_FPU_PIPE_REGS_NONCOMP;
            localparam [31:0] PIPE_CONV = MUA_FPU_PIPE_REGS_CONV;
            localparam [1:0] PIPE_CONFIG = MUA_FPU_PIPE_CONFIG[1:0];
            localparam [1:0] DIVSQRT = MUA_FPU_DIVSQRT[1:0];
            localparam [681:0] IMPLEMENTATION = {
                (32'd0 + PIPE_FMA), 128'd0, (32'd0 + PIPE_DIVSQRT), 128'd0,
                (32'd0 + PIPE_NONCOMP), 128'd0, (32'd0 + PIPE_CONV), 128'd0,
                2'd1, 8'd0, 2'd2, 8'd0, 2'd1, 8'd0, 2'd2, 8'd0,
                PIPE_CONFIG
            };
            localparam [3:0] FP_FMADD = 4'd0, FP_FNMSUB = 4'd1, FP_ADD = 4'd2,
                FP_MUL = 4'd3, FP_DIV = 4'd4, FP_SQRT = 4'd5, FP_SGNJ = 4'd6,
                FP_MINMAX = 4'd7, FP_CMP = 4'd8, FP_CLASSIFY = 4'd9,
                FP_F2I = 4'd11, FP_I2F = 4'd12;

            reg [3:0] fp_op;
            reg fp_op_mod;
            reg [2:0] fp_rm;
            reg [95:0] fp_operands;
            reg active_q;
            reg backend_rst_n_q;
            wire fp_in_ready;
            wire fp_out_valid;
            wire [31:0] fp_result;
            wire [4:0] fp_status;
            wire rounding_used = (req_op_i <= `UQU_FPU_FNMADD_S) ||
                                 (req_op_i >= `UQU_FPU_FCVT_W_S);
            wire legal = (req_op_i <= `UQU_FPU_FCVT_S_WU) &&
                         (!rounding_used || (req_rm_i <= 3'd4));
            wire enabled = rst_ni && backend_rst_n_q && !flush_i;
            wire fp_in_valid = enabled && !active_q && req_valid_i && legal;
            wire req_fire = fp_in_valid && fp_in_ready;
            wire res_fire = res_valid_o && res_ready_i;

            // Adapt the imported asynchronous reset to the core's synchronous
            // reset policy. Reset changes at the backend only on a clock edge;
            // admission waits for this sampled reset to be released.
            always @(posedge clk_i) begin
                backend_rst_n_q <= rst_ni;
                if (!rst_ni || flush_i) begin
                    active_q <= 1'b0;
                end else if (res_fire) begin
                    active_q <= 1'b0;
                end else if (req_fire) begin
                    active_q <= 1'b1;
                end
            end

            always @* begin
                fp_op = FP_FMADD;
                fp_op_mod = 1'b0;
                fp_rm = req_rm_i;
                fp_operands = {req_c_i, req_b_i, req_a_i};
                case (req_op_i)
                    `UQU_FPU_FADD_S, `UQU_FPU_FSUB_S: begin
                        fp_op = FP_ADD;
                        fp_op_mod = (req_op_i == `UQU_FPU_FSUB_S);
                        // FPnew ADD computes 1.0 * operand[1] +/- operand[2].
                        fp_operands = {req_b_i, req_a_i, 32'd0};
                    end
                    `UQU_FPU_FMUL_S: fp_op = FP_MUL;
                    `UQU_FPU_FDIV_S: fp_op = FP_DIV;
                    `UQU_FPU_FSQRT_S: fp_op = FP_SQRT;
                    `UQU_FPU_FMADD_S, `UQU_FPU_FMSUB_S: begin
                        fp_op = FP_FMADD;
                        fp_op_mod = (req_op_i == `UQU_FPU_FMSUB_S);
                    end
                    `UQU_FPU_FNMSUB_S, `UQU_FPU_FNMADD_S: begin
                        fp_op = FP_FNMSUB;
                        fp_op_mod = (req_op_i == `UQU_FPU_FNMADD_S);
                    end
                    `UQU_FPU_FSGNJ_S: begin fp_op = FP_SGNJ; fp_rm = 3'd0; end
                    `UQU_FPU_FSGNJN_S: begin fp_op = FP_SGNJ; fp_rm = 3'd1; end
                    `UQU_FPU_FSGNJX_S: begin fp_op = FP_SGNJ; fp_rm = 3'd2; end
                    `UQU_FPU_FMIN_S: begin fp_op = FP_MINMAX; fp_rm = 3'd0; end
                    `UQU_FPU_FMAX_S: begin fp_op = FP_MINMAX; fp_rm = 3'd1; end
                    `UQU_FPU_FEQ_S: begin fp_op = FP_CMP; fp_rm = 3'd2; end
                    `UQU_FPU_FLT_S: begin fp_op = FP_CMP; fp_rm = 3'd1; end
                    `UQU_FPU_FLE_S: begin fp_op = FP_CMP; fp_rm = 3'd0; end
                    `UQU_FPU_FCLASS_S: fp_op = FP_CLASSIFY;
                    `UQU_FPU_FCVT_W_S, `UQU_FPU_FCVT_WU_S: begin
                        fp_op = FP_F2I;
                        fp_op_mod = (req_op_i == `UQU_FPU_FCVT_WU_S);
                    end
                    `UQU_FPU_FCVT_S_W, `UQU_FPU_FCVT_S_WU: begin
                        fp_op = FP_I2F;
                        fp_op_mod = (req_op_i == `UQU_FPU_FCVT_S_WU);
                    end
                    default: begin end
                endcase
            end

            assign req_ready_o = fp_in_ready && fp_in_valid;
            assign res_valid_o = enabled && fp_out_valid && (active_q || fp_in_valid);
            assign res_data_o = res_valid_o ? fp_result : 32'd0;
            // The pinned FMA can flag tininess before rounding. RISC-V
            // detects it after rounding: a normal result cannot underflow.
            // Invalid operations do not also
            // report divide-by-zero or inexact/overflow/underflow exceptions.
            assign res_fflags_o = !res_valid_o ? 5'd0 : fp_status[4] ? 5'b10000 :
                {fp_status[4:2], fp_status[1] && (fp_result[30:23] == 8'd0), fp_status[0]};

            fpnew_top #(
                .Features(FEATURES), .Implementation(IMPLEMENTATION),
                .DivSqrtSel(DIVSQRT)
            ) u_fpnew (
                .clk_i(clk_i), .rst_ni(backend_rst_n_q),
                .operands_i(fp_operands), .rnd_mode_i(fp_rm), .op_i(fp_op),
                .op_mod_i(fp_op_mod), .src_fmt_i(3'd0), .dst_fmt_i(3'd0),
                .int_fmt_i(2'd2), .vectorial_op_i(1'b0), .tag_i(1'b0),
                .simd_mask_i(1'b1), .in_valid_i(fp_in_valid),
                .in_ready_o(fp_in_ready), .flush_i(flush_i || !rst_ni),
                .result_o(fp_result), .status_o(fp_status), .tag_o(),
                .out_valid_o(fp_out_valid), .out_ready_i(enabled && res_ready_i),
                .busy_o(), .early_valid_o()
            );
        end
    endgenerate
endmodule

`default_nettype wire
