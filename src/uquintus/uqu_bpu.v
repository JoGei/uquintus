`default_nettype none
`include "uqu_config.vh"

// IF-owned composition of independent direction prediction and target storage.
// Accepted DE updates and IF captures train one edge after acceptance.
module uqu_bpu #(
    parameter ISA_C = 0,
    parameter MUA_BRANCH_PREDICTOR = `UQU_BP_NONE,
    parameter MUA_BP_ENTRIES = 16,
    parameter MUA_BTB = `UQU_BTB_NONE,
    parameter MUA_BTB_ENTRIES = 16,
    parameter MUA_BTB_IDATA_HWORDS = 0
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
    output wire [31:0] idata_hwords_o,
    output wire [31:0] idata_next_pc_o,
    output wire [16*((MUA_BTB_IDATA_HWORDS > 0) ? MUA_BTB_IDATA_HWORDS : 1)-1:0] idata_o
);
    localparam EFFECTIVE_BTB = (MUA_BRANCH_PREDICTOR == `UQU_BP_NONE) ? `UQU_BTB_NONE : MUA_BTB;
    wire btb_hit, btb_conditional, direction_hit, direction_taken;
    wire [31:0] btb_target;
    wire train_valid, train_control_flow, train_conditional, train_taken;
    wire [31:0] train_pc, train_target;
    wire fill_flush, fill_valid;
    wire [31:0] fill_pc, fill_instr;
    wire target_aligned = (ISA_C == 1) ? !train_target[0] : !(|train_target[1:0]);

    generate
        if (EFFECTIVE_BTB == `UQU_BTB_DIRECT_MAPPED) begin : gen_events
            reg update_valid_q;
            reg [31:0] update_pc_q, update_target_q;
            reg update_control_flow_q, update_conditional_q, update_taken_q;
            assign train_valid = update_valid_q;
            assign train_pc = update_pc_q;
            assign train_target = update_target_q;
            assign train_control_flow = update_control_flow_q;
            assign train_conditional = update_conditional_q;
            assign train_taken = update_taken_q;
            always @(posedge clk_i) begin
                if (!rst_ni || invalidate_i) begin
                    update_valid_q <= 1'b0;
                end else begin
                    update_valid_q <= update_valid_i;
                    if (update_valid_i) begin
                        update_pc_q <= update_pc_i;
                        update_target_q <= update_target_i;
                        update_control_flow_q <= update_control_flow_i;
                        update_conditional_q <= update_conditional_i;
                        update_taken_q <= update_taken_i;
                    end
                end
            end
            if (MUA_BTB_IDATA_HWORDS > 0) begin : gen_capture
                reg capture_valid_q, stream_flush_q;
                reg [31:0] capture_pc_q, capture_instr_q;
                assign fill_valid = capture_valid_q;
                assign fill_pc = capture_pc_q;
                assign fill_instr = capture_instr_q;
                assign fill_flush = stream_flush_q;
                always @(posedge clk_i) begin
                    if (!rst_ni || invalidate_i) begin
                        capture_valid_q <= 1'b0;
                        stream_flush_q <= 1'b0;
                    end else begin
                        capture_valid_q <= capture_valid_i;
                        stream_flush_q <= stream_flush_i;
                        if (capture_valid_i) begin
                            capture_pc_q <= capture_pc_i;
                            capture_instr_q <= capture_instr_i;
                        end
                    end
                end
            end else begin : gen_no_capture
                assign fill_valid = 1'b0;
                assign fill_pc = 32'd0;
                assign fill_instr = 32'd0;
                assign fill_flush = 1'b0;
            end
        end else begin : gen_no_events
            assign train_valid = 1'b0;
            assign train_pc = 32'd0;
            assign train_target = 32'd0;
            assign train_control_flow = 1'b0;
            assign train_conditional = 1'b0;
            assign train_taken = 1'b0;
            assign fill_valid = 1'b0;
            assign fill_pc = 32'd0;
            assign fill_instr = 32'd0;
            assign fill_flush = 1'b0;
        end
    endgenerate

    uqu_btb #(.ISA_C(ISA_C), .MUA_BTB(EFFECTIVE_BTB), .MUA_BTB_ENTRIES(MUA_BTB_ENTRIES),
        .MUA_BTB_IDATA_HWORDS(MUA_BTB_IDATA_HWORDS)) u_btb (
        .clk_i(clk_i), .rst_ni(rst_ni), .invalidate_i(invalidate_i),
        .lookup_valid_i(lookup_valid_i), .lookup_pc_i(lookup_pc_i),
        .hit_o(btb_hit), .conditional_o(btb_conditional), .target_o(btb_target),
        .update_valid_i(train_valid), .update_pc_i(train_pc),
        .update_control_flow_i(train_control_flow), .update_conditional_i(train_conditional),
        .update_target_i(train_target), .update_taken_i(train_taken),
        .stream_flush_i(fill_flush), .capture_valid_i(fill_valid),
        .capture_pc_i(fill_pc), .capture_instr_i(fill_instr),
        .idata_hwords_o(idata_hwords_o), .idata_next_pc_o(idata_next_pc_o), .idata_o(idata_o)
    );
    generate
        if (MUA_BRANCH_PREDICTOR == `UQU_BP_BIMODAL) begin : gen_bimodal
            uqu_bp_bimodal #(.ISA_C(ISA_C), .MUA_BP_ENTRIES(MUA_BP_ENTRIES)) u_direction (
                .clk_i(clk_i), .rst_ni(rst_ni), .invalidate_i(invalidate_i),
                .lookup_valid_i(lookup_valid_i), .lookup_pc_i(lookup_pc_i),
                .hit_o(direction_hit), .taken_o(direction_taken),
                .update_valid_i(train_valid), .update_pc_i(train_pc),
                .update_control_flow_i(train_control_flow && target_aligned),
                .update_conditional_i(train_conditional), .update_taken_i(train_taken)
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
