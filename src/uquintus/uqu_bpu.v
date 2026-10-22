`default_nettype none
`include "uqu_config.vh"

// IF-owned composition of independent direction prediction and target storage.
// Only accepted nonfaulting DE instructions train the components.
module uqu_bpu #(
    parameter ISA_C = 0,
    parameter MUA_BRANCH_PREDICTOR = `UQU_BP_NONE,
    parameter MUA_BP_ENTRIES = 16,
    parameter MUA_BTB = `UQU_BTB_NONE,
    parameter MUA_BTB_ENTRIES = 16,
    parameter MUA_BTB_IDATA_DEPTH = 0
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        invalidate_i,
    input  wire        lookup_valid_i,
    input  wire [31:0] lookup_pc_i,
    output wire        hit_o,
    output wire        taken_o,
    output wire [31:0] target_o,
    input  wire        update_valid_i,
    input  wire [31:0] update_pc_i,
    input  wire        update_control_flow_i,
    input  wire        update_conditional_i,
    input  wire        update_taken_i,
    input  wire [31:0] update_target_i,
    input  wire        stream_flush_i,
    input  wire        capture_valid_i,
    input  wire [31:0] capture_pc_i,
    input  wire [31:0] capture_instr_i,
    output wire [31:0] idata_count_o,
    output wire [31:0] idata_next_pc_o,
    output wire [32*((MUA_BTB_IDATA_DEPTH > 0) ? MUA_BTB_IDATA_DEPTH : 1)-1:0] idata_o
);
    localparam EFFECTIVE_BTB = (MUA_BRANCH_PREDICTOR == `UQU_BP_NONE) ? `UQU_BTB_NONE : MUA_BTB;
    wire btb_hit, btb_conditional, direction_hit, direction_taken;
    wire [31:0] btb_target;
    wire target_aligned = (ISA_C == 1) ? !update_target_i[0] : !(|update_target_i[1:0]);

    uqu_btb #(.ISA_C(ISA_C), .MUA_BTB(EFFECTIVE_BTB), .MUA_BTB_ENTRIES(MUA_BTB_ENTRIES),
        .MUA_BTB_IDATA_DEPTH(MUA_BTB_IDATA_DEPTH)) u_btb (
        .clk_i(clk_i), .rst_ni(rst_ni), .invalidate_i(invalidate_i),
        .lookup_valid_i(lookup_valid_i), .lookup_pc_i(lookup_pc_i),
        .hit_o(btb_hit), .conditional_o(btb_conditional), .target_o(btb_target),
        .update_valid_i(update_valid_i), .update_pc_i(update_pc_i),
        .update_control_flow_i(update_control_flow_i), .update_conditional_i(update_conditional_i),
        .update_target_i(update_target_i), .update_taken_i(update_taken_i),
        .stream_flush_i(stream_flush_i), .capture_valid_i(capture_valid_i),
        .capture_pc_i(capture_pc_i), .capture_instr_i(capture_instr_i),
        .idata_count_o(idata_count_o), .idata_next_pc_o(idata_next_pc_o), .idata_o(idata_o)
    );
    generate
        if (MUA_BRANCH_PREDICTOR == `UQU_BP_BIMODAL) begin : gen_bimodal
            uqu_bp_bimodal #(.ISA_C(ISA_C), .MUA_BP_ENTRIES(MUA_BP_ENTRIES)) u_direction (
                .clk_i(clk_i), .rst_ni(rst_ni), .invalidate_i(invalidate_i),
                .lookup_valid_i(lookup_valid_i), .lookup_pc_i(lookup_pc_i),
                .hit_o(direction_hit), .taken_o(direction_taken),
                .update_valid_i(update_valid_i), .update_pc_i(update_pc_i),
                .update_control_flow_i(update_control_flow_i && target_aligned),
                .update_conditional_i(update_conditional_i), .update_taken_i(update_taken_i)
            );
        end else begin : gen_static
            assign direction_hit = 1'b0;
            assign direction_taken = 1'b0;
        end
        if (((ISA_C != 0) && (ISA_C != 1)) ||
            ((MUA_BRANCH_PREDICTOR != `UQU_BP_NONE) &&
             (MUA_BRANCH_PREDICTOR != `UQU_BP_STATIC_NOT_TAKEN) &&
             (MUA_BRANCH_PREDICTOR != `UQU_BP_BIMODAL)) ||
            ((MUA_BTB != `UQU_BTB_NONE) && (MUA_BTB != `UQU_BTB_DIRECT_MAPPED)) ||
            (MUA_BP_ENTRIES < 2) || (MUA_BP_ENTRIES > 1024) ||
            ((MUA_BP_ENTRIES & (MUA_BP_ENTRIES - 1)) != 0)) begin : gen_invalid
            uqu_bpu_invalid_configuration invalid_configuration ();
        end
    endgenerate
    assign hit_o = btb_hit;
    assign taken_o = btb_hit && (!btb_conditional || (direction_hit && direction_taken));
    assign target_o = taken_o ? btb_target : 32'd0;
endmodule

`default_nettype wire
