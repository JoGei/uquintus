`default_nettype none
`include "uqu_config.vh"
`include "uqu_ctrl.vh"

package uqu_bpu_stats_pkg;
    typedef enum integer {
        `define UQU_BPU_COUNTER(NAME) NAME,
        `include "uqu_bpu_counter_list.vh"
        `undef UQU_BPU_COUNTER
        COUNT
    } counter_t;
endpackage

// Passive verification state only. Copy prediction metadata with the same
// boundary controls as the core, and count it once when its instruction retires.
module uqu_bpu_monitor #(
    parameter MUA_BRANCH_PREDICTOR = `UQU_BP_NONE,
    parameter MUA_BTB = `UQU_BTB_NONE
) (
    input wire clk_i,
    input wire rst_ni,
    input wire if_valid_i,
    input wire if_ready_i,
    input wire if_flush_i,
    input wire [31:0] if_pc_i,
    input wire [31:0] if_predicted_next_pc_i,
    input wire if_btb_hit_i,
    input wire if_direction_taken_i,
    input wire if_effective_taken_i,
    input wire if_replay_i,
    // Order: DE, EX, MEM, WB. Bit zero identifies DE.
    input wire [3:0] stage_valid_i,
    input wire [3:0] stage_enable_i,
    input wire [3:0] stage_next_valid_i,
    input wire [31:0] de_pc_i,
    input wire [1:0] de_branch_kind_i,
    input wire de_taken_i,
    input wire [31:0] de_next_pc_i,
    input wire de_redirect_i,
    input wire de_compressed_i,
    input wire retire_i,
    input wire [31:0] retire_pc_i,
    output wire [64*uqu_bpu_stats_pkg::COUNT-1:0] counters_o,
    output wire [31:0] counter_count_o
);
    import uqu_bpu_stats_pkg::*;
    localparam PREDICTING = (MUA_BRANCH_PREDICTOR != `UQU_BP_NONE);
    localparam BTB_ACTIVE = PREDICTING && (MUA_BTB != `UQU_BTB_NONE);
    typedef struct packed {
        logic [31:0] pc;
        logic [31:0] predicted_next_pc;
        logic btb_hit;
        logic direction_taken;
        logic effective_taken;
        logic [1:0] kind;
        logic taken;
        logic wrong_next_pc;
        logic wrong_target;
        logic redirected;
        logic compressed;
        logic replayed;
    } token_t;
    token_t payload_q [0:3];
    token_t held_q;
    token_t incoming;
    token_t resolved;
    logic [3:0] valid_q;
    logic held_valid_q;
    logic [63:0] counts_q [0:COUNT-1];
    logic [COUNT-1:0] events;
    wire conditional = payload_q[3].kind == `UQU_BR_COND;
    wire control_flow = payload_q[3].kind != `UQU_BR_NONE;
    integer index;

    always @* begin
        incoming = '0;
        incoming.pc = if_pc_i;
        incoming.replayed = if_replay_i;
        incoming.predicted_next_pc = if_predicted_next_pc_i;
        incoming.btb_hit = held_valid_q ? held_q.btb_hit : if_btb_hit_i;
        incoming.direction_taken = held_valid_q ? held_q.direction_taken : if_direction_taken_i;
        incoming.effective_taken = held_valid_q ? held_q.effective_taken : if_effective_taken_i;
        resolved = payload_q[0];
        resolved.kind = de_branch_kind_i;
        resolved.taken = de_taken_i;
        resolved.wrong_next_pc = payload_q[0].predicted_next_pc != de_next_pc_i;
        resolved.wrong_target = de_taken_i && payload_q[0].effective_taken && resolved.wrong_next_pc;
        resolved.redirected = de_redirect_i;
        resolved.compressed = de_compressed_i;

        events = '0;
        events[IDATA_REPLAYED_INSTRUCTIONS] = payload_q[3].replayed;
        events[RETIRED_INSTRUCTIONS] = 1'b1;
        events[CONDITIONAL_BRANCHES] = conditional;
        events[DIRECT_JUMPS] = payload_q[3].kind == `UQU_BR_JAL;
        events[INDIRECT_JUMPS] = payload_q[3].kind == `UQU_BR_JALR;
        events[TAKEN_CONDITIONAL_BRANCHES] = conditional && payload_q[3].taken;
        events[TAKEN_CONTROL_FLOW] = control_flow && payload_q[3].taken;
        events[BTB_LOOKUPS] = BTB_ACTIVE;
        events[BTB_HITS] = BTB_ACTIVE && payload_q[3].btb_hit;
        events[BTB_CONTROL_FLOW_LOOKUPS] = BTB_ACTIVE && control_flow;
        events[BTB_CONTROL_FLOW_HITS] = BTB_ACTIVE && control_flow && payload_q[3].btb_hit;
        events[DIRECTION_PREDICTIONS] = PREDICTING && conditional;
        events[DIRECTION_MISPREDICTIONS] = PREDICTING && conditional &&
            (payload_q[3].taken != payload_q[3].direction_taken);
        events[EFFECTIVE_DIRECTION_MISPREDICTIONS] = PREDICTING && conditional &&
            (payload_q[3].taken != payload_q[3].effective_taken);
        events[TARGET_PREDICTIONS] = control_flow && payload_q[3].taken && payload_q[3].effective_taken;
        events[TARGET_MISPREDICTIONS] = control_flow && payload_q[3].wrong_target;
        events[CONTROL_FLOW_PREDICTIONS] = PREDICTING && control_flow;
        events[CONTROL_FLOW_MISPREDICTIONS] = PREDICTING && control_flow && payload_q[3].wrong_next_pc;
        events[DE_REDIRECTS] = payload_q[3].redirected;
        events[FALSE_BTB_HITS] = BTB_ACTIVE && !control_flow && payload_q[3].btb_hit;
        events[COMPRESSED_CONTROL_FLOW] = control_flow && payload_q[3].compressed;
    end

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            valid_q <= 4'd0;
            held_valid_q <= 1'b0;
            for (index = 0; index < COUNT; index = index + 1) counts_q[index] <= 64'd0;
        end else begin
            if (valid_q != stage_valid_i) $fatal(1, "BPU monitor occupancy mismatch");
            if (valid_q[0] && (payload_q[0].pc != de_pc_i)) $fatal(1, "BPU monitor DE PC mismatch");
            if (retire_i && (!valid_q[3] || (payload_q[3].pc != retire_pc_i)))
                $fatal(1, "BPU monitor retirement PC mismatch");
            if (if_flush_i || (if_valid_i && if_ready_i)) held_valid_q <= 1'b0;
            else if (if_valid_i && !held_valid_q) begin
                held_q <= incoming;
                held_valid_q <= 1'b1;
            end
            for (index = 0; index < 4; index = index + 1) begin
                if (stage_enable_i[index]) valid_q[index] <= stage_next_valid_i[index];
            end
            if (stage_enable_i[0] && stage_next_valid_i[0]) payload_q[0] <= incoming;
            if (stage_enable_i[1] && stage_next_valid_i[1]) payload_q[1] <= resolved;
            if (stage_enable_i[2] && stage_next_valid_i[2]) payload_q[2] <= payload_q[1];
            if (stage_enable_i[3] && stage_next_valid_i[3]) payload_q[3] <= payload_q[2];
            if (retire_i) begin
                for (index = 0; index < COUNT; index = index + 1)
                    if (events[index]) counts_q[index] <= counts_q[index] + 64'd1;
            end
        end
    end
    assign counter_count_o = COUNT;
    for (genvar counter = 0; counter < COUNT; counter = counter + 1) begin : gen_counter
        assign counters_o[64*counter +: 64] = counts_q[counter];
    end
endmodule

`default_nettype wire
