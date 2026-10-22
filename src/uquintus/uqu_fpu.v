`default_nettype none
`include "uqu_config.vh"

// Unimplemented scalar Zfinx endpoint for EX wiring. This stub never
// accepts work or produces a result. The configured CVFPU adapter will replace
// this stub; an enabled instance must not silently use this placeholder.
module uqu_fpu #(
    parameter ISA_ZFINX = 0,
    parameter MUA_FPU_PIPE_REGS_FMA = 2,
    parameter MUA_FPU_PIPE_REGS_DIVSQRT = 0,
    parameter MUA_FPU_PIPE_REGS_NONCOMP = 0,
    parameter MUA_FPU_PIPE_REGS_CONV = 1,
    parameter MUA_FPU_PIPE_CONFIG = `UQU_FPU_PIPE_DISTRIBUTED,
    parameter MUA_FPU_DIVSQRT = `UQU_FPU_DIVSQRT_PULP
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
    // Inputs are intentionally unused until a backend exists. Keeping both
    // channels inactive prevents false completion or architectural FP updates.
    assign req_ready_o = 1'b0;
    assign res_valid_o = 1'b0;
    assign res_data_o = 32'd0;
    assign res_fflags_o = 5'd0;

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
             (MUA_FPU_DIVSQRT != `UQU_FPU_DIVSQRT_THMULTI))) begin : gen_invalid_configuration
            uqu_fpu_invalid_configuration invalid_configuration ();
        end
        if (ISA_ZFINX != 0) begin : gen_unimplemented
            uqu_fpu_zfinx_not_implemented u_unimplemented ();
        end
    endgenerate
endmodule

`default_nettype wire
