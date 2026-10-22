// Verification bridge for harnesses whose processor instance is named u_core.
uqu_bpu_monitor #(.MUA_BRANCH_PREDICTOR(MUA_BRANCH_PREDICTOR), .MUA_BTB(MUA_BTB)) u_bpu_monitor (
    .clk_i(clk_i), .rst_ni(rst_ni),
    .if_valid_i(u_core.if_valid), .if_ready_i(u_core.if_ready), .if_flush_i(u_core.if_flush),
    .if_pc_i(u_core.if_pc), .if_predicted_next_pc_i(u_core.if_predicted_next_pc),
    .if_btb_hit_i(u_core.u_if.u_bpu.btb_hit),
    .if_direction_taken_i(u_core.u_if.u_bpu.direction_taken),
    .if_effective_taken_i(u_core.u_if.prediction_taken),
    .if_replay_i(u_core.u_if.replay_active),
    .stage_valid_i({u_core.wb_valid_q, u_core.mem_valid_q, u_core.ex_valid_q, u_core.de_valid_q}),
    .stage_enable_i({u_core.wb_enable, u_core.mem_enable, u_core.ex_enable, u_core.de_enable}),
    .stage_next_valid_i({u_core.wb_next_valid, u_core.mem_next_valid, u_core.ex_next_valid, u_core.de_next_valid}),
    .de_pc_i(u_core.de_pc_q),
    .de_branch_kind_i(u_core.de_control_flow ? u_core.u_de.dec_branch : 2'd0),
    .de_taken_i(u_core.de_branch_taken), .de_next_pc_i(u_core.de_next_pc),
    .de_redirect_i(u_core.de_redirect), .de_compressed_i(u_core.de_compressed_q),
    .retire_i(u_core.wb_retire), .retire_pc_i(u_core.wb_pc_q),
    .counters_o(bpu_counters_o), .counter_count_o(bpu_counter_count_o)
);
