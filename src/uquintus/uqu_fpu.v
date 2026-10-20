`default_nettype none

// Unimplemented scalar Zfinx endpoint for EX wiring. This stub never
// accepts work or produces a result. Replace the implementation when selecting
// an FPU backend; an enabled instance must not silently use this placeholder.
module uqu_fpu #(
    parameter ISA_ZFINX = 0
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
        if (ISA_ZFINX != 0) begin : gen_unimplemented
            uqu_fpu_zfinx_not_implemented u_unimplemented ();
        end
    endgenerate
endmodule

`default_nettype wire
