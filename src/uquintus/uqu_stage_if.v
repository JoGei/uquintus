`default_nettype none
`include "uqu_config.vh"

// Frontend control/storage, not an IF/DE pipeline register. The core supplies
// accepted redirects, global permits and shared PMP fetch/replay results.
module uqu_stage_if #(
    parameter ISA_C = 0,
    parameter MUA_C_IMPL = `UQU_C_IMPL_DECOMPRESS,
    parameter MUA_C_DECOMPRESS_STAGE = `UQU_C_DECOMPRESS_IF,
    parameter MUA_BRANCH_PREDICTOR = `UQU_BP_NONE,
    parameter MUA_BP_ENTRIES = 16,
    parameter MUA_BTB = `UQU_BTB_NONE,
    parameter MUA_BTB_ENTRIES = 16,
    parameter MUA_BTB_IDATA_DEPTH = 0,
    parameter MUA_IF_BUFFER_WORDS = 2
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire [31:0] boot_addr_i,
    input  wire        flush_i,
    input  wire        redirect_valid_i,
    input  wire [31:0] redirect_addr_i,
    input  wire        fetch_enable_i,
    input  wire        request_permit_i,
    input  wire        branch_pending_i,
    input  wire        predictor_invalidate_i,
    input  wire        predictor_update_valid_i,
    input  wire [31:0] predictor_update_pc_i,
    input  wire        predictor_update_control_flow_i,
    input  wire        predictor_update_conditional_i,
    input  wire        predictor_update_taken_i,
    input  wire [31:0] predictor_update_target_i,
    input  wire        permit_i,
    output wire        valid_o,
    input  wire        ready_i,
    output wire [31:0] pc_o,
    output wire [31:0] instr_o,
    output wire [31:0] original_instr_o,
    output wire        compressed_o,
    output wire [31:0] next_pc_o,
    output wire [31:0] predicted_next_pc_o,
    output wire        exception_valid_o,
    output wire [4:0]  exception_cause_o,
    output wire [31:0] exception_tval_o,
    output wire        misaligned_o,
    output wire        fetch_busy_o,
    input  wire        priv_m_i,
    output wire        pmp_valid_o,
    output wire [31:0] pmp_addr_o,
    output wire [1:0]  pmp_size_o,
    output wire        pmp_priv_m_o,
    input  wire        pmp_allow_i,
    output wire [31:0] replay_pmp_addr_o,
    output wire        replay_pmp_priv_m_o,
    input  wire [1:0]  replay_pmp_allow_i,
    output wire        imem_req_o,
    output wire [31:0] imem_addr_o,
    input  wire        imem_gnt_i,
    input  wire        imem_rvalid_i,
    input  wire [31:0] imem_rdata_i,
    input  wire        imem_err_i
);
    localparam integer IDATA_DEPTH = ((MUA_BRANCH_PREDICTOR != `UQU_BP_NONE) &&
        (MUA_BTB != `UQU_BTB_NONE)) ? MUA_BTB_IDATA_DEPTH : 0;
    localparam [4:0] CAUSE_ILLEGAL = 5'd2;
    reg [31:0] pc_q;
    reg [31:0] fetch_addr_q;
    reg running_q;
    reg fault_hold_q;
    reg prediction_held_q;
    reg [31:0] prediction_pc_q;
    wire replay_recover = (IDATA_DEPTH > 0) && predictor_invalidate_i;
    wire invalidate = flush_i || redirect_valid_i || replay_recover;
    wire active = rst_ni && !invalidate && running_q && !fault_hold_q;
    wire branch_hold = (MUA_BRANCH_PREDICTOR == `UQU_BP_NONE) && branch_pending_i;
    wire fetch_ready;
    wire push_ready;
    wire fetch_valid = active && fetch_enable_i && !branch_hold && !misaligned_o &&
                       !candidate_fault && push_ready;
    wire start_permit = fetch_enable_i && request_permit_i && !branch_hold &&
                        active && !candidate_fault && !misaligned_o;
    wire fetch_fire = fetch_valid && fetch_ready;
    wire result_valid;
    wire [31:0] result_addr, result_data;
    wire result_error;
    wire word0_valid, word1_valid;
    wire [31:0] word0_data, word1_data;
    wire word0_error, word1_error;
    wire selected_valid, selected_compressed, drop_word;
    wire [31:0] selected_instr, selected_next_pc;
    wire access_fault;
    wire [4:0] access_cause;
    wire [31:0] access_tval;
    wire [31:0] normalized_instr;
    wire expansion_fault;
    wire candidate_fault = access_fault || expansion_fault;
    wire prediction_taken;
    wire [31:0] prediction_target;
    wire [31:0] predicted_pc = prediction_held_q ? prediction_pc_q :
                              prediction_taken ? prediction_target : selected_next_pc;
    wire transfer = valid_o && ready_i;
    wire prediction_redirect = transfer && !candidate_fault && (predicted_pc != selected_next_pc);
    wire pop_word = transfer && !candidate_fault && !replay_active && drop_word;
    wire fetched_valid, fetched_compressed, fetched_fault;
    wire [31:0] fetched_instr, fetched_next_pc, fetched_tval;
    wire [4:0] fetched_cause;
    wire replay_active;
    wire [31:0] replay_instr, idata_count, idata_next_pc;
    wire [32*((IDATA_DEPTH > 0) ? IDATA_DEPTH : 1)-1:0] idata;
    wire replay_short = (ISA_C == 1) && (replay_instr[1:0] != 2'b11);
    wire replay_cross = (ISA_C == 1) && pc_q[1] && !replay_short;
    wire replay_fault = !replay_pmp_allow_i[0] || (replay_cross && !replay_pmp_allow_i[1]);
    wire replay_start = prediction_redirect && prediction_taken &&
                        (prediction_target == predicted_pc) && (idata_count != 0);
    assign replay_pmp_addr_o = replay_active ? {pc_q[31:2],2'b00} : 32'd0;
    assign replay_pmp_priv_m_o = replay_active && priv_m_i;
    assign selected_valid = replay_active ? active : fetched_valid;
    assign selected_instr = replay_active ? (replay_fault ? 32'd0 : replay_instr) : fetched_instr;
    assign selected_compressed = replay_active ? (!replay_fault && replay_short) : fetched_compressed;
    assign selected_next_pc = replay_active ? pc_q + (replay_short ? 32'd2 : 32'd4) : fetched_next_pc;
    assign access_fault = replay_active ? replay_fault : fetched_fault;
    assign access_cause = replay_active ? 5'd1 : fetched_cause;
    assign access_tval = replay_active ?
        ((!replay_pmp_allow_i[0] || !replay_cross) ? pc_q : pc_q + 32'd2) : fetched_tval;

    uqu_if_replay #(.MUA_BTB_IDATA_DEPTH(IDATA_DEPTH)) u_replay (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(invalidate),
        .cancel_i(prediction_redirect || (transfer && candidate_fault)),
        .start_i(replay_start), .start_count_i(idata_count), .start_data_i(idata),
        .consume_i(transfer), .active_o(replay_active), .instr_o(replay_instr)
    );

    assign valid_o = active && permit_i && selected_valid;
    assign pc_o = pc_q;
    assign instr_o = valid_o && !candidate_fault ? normalized_instr : 32'd0;
    assign original_instr_o = valid_o ? selected_instr : 32'd0;
    assign compressed_o = valid_o && selected_compressed;
    assign next_pc_o = valid_o && !candidate_fault ? selected_next_pc : pc_q;
    assign predicted_next_pc_o = valid_o && !candidate_fault ? predicted_pc : pc_q;
    assign exception_valid_o = valid_o && candidate_fault;
    assign exception_cause_o = !exception_valid_o ? 5'd0 : access_fault ? access_cause : CAUSE_ILLEGAL;
    assign exception_tval_o = !exception_valid_o ? 32'd0 : access_fault ? access_tval : selected_instr;

    // This query is independent of allow. The engine samples the decision at
    // native acceptance, before any bus request, and retains it through waits.
    assign pmp_valid_o = fetch_fire;
    assign pmp_addr_o = pmp_valid_o ? fetch_addr_q : 32'd0;
    assign pmp_size_o = pmp_valid_o ? 2'd2 : 2'd0;
    assign pmp_priv_m_o = pmp_valid_o && priv_m_i;

    uqu_ifetch u_ifetch (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(invalidate || prediction_redirect),
        .req_valid_i(fetch_valid), .req_ready_o(fetch_ready), .req_addr_i(fetch_addr_q),
        .req_access_fault_i(!pmp_allow_i), .request_permit_i(start_permit),
        .busy_o(fetch_busy_o), .res_valid_o(result_valid), .res_ready_i(push_ready),
        .res_addr_o(result_addr), .res_data_o(result_data), .res_error_o(result_error),
        .imem_req_o(imem_req_o), .imem_addr_o(imem_addr_o), .imem_gnt_i(imem_gnt_i),
        .imem_rvalid_i(imem_rvalid_i), .imem_rdata_i(imem_rdata_i), .imem_err_i(imem_err_i)
    );
    uqu_if_buffer #(.MUA_IF_BUFFER_WORDS(MUA_IF_BUFFER_WORDS)) u_buffer (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(invalidate),
        .clear_i(prediction_redirect),
        .push_valid_i(result_valid), .push_ready_o(push_ready),
        .push_addr_i(result_addr), .push_data_i(result_data), .push_error_i(result_error),
        .pop_i(pop_word),
        .word0_valid_o(word0_valid), .word0_addr_o(), .word0_data_o(word0_data), .word0_error_o(word0_error),
        .word1_valid_o(word1_valid), .word1_addr_o(), .word1_data_o(word1_data), .word1_error_o(word1_error)
    );
    uqu_bpu #(
        .ISA_C(ISA_C), .MUA_BRANCH_PREDICTOR(MUA_BRANCH_PREDICTOR), .MUA_BP_ENTRIES(MUA_BP_ENTRIES),
        .MUA_BTB(MUA_BTB), .MUA_BTB_ENTRIES(MUA_BTB_ENTRIES), .MUA_BTB_IDATA_DEPTH(IDATA_DEPTH)
    ) u_bpu (
        .clk_i(clk_i), .rst_ni(rst_ni), .invalidate_i(predictor_invalidate_i),
        .lookup_valid_i(active && selected_valid && !candidate_fault), .lookup_pc_i(pc_q),
        .hit_o(), .taken_o(prediction_taken), .target_o(prediction_target),
        .update_valid_i(predictor_update_valid_i), .update_pc_i(predictor_update_pc_i),
        .update_control_flow_i(predictor_update_control_flow_i),
        .update_conditional_i(predictor_update_conditional_i),
        .update_taken_i(predictor_update_taken_i), .update_target_i(predictor_update_target_i),
        .stream_flush_i(invalidate), .capture_valid_i(transfer && !candidate_fault),
        .capture_pc_i(pc_q), .capture_instr_i(selected_instr),
        .idata_count_o(idata_count), .idata_next_pc_o(idata_next_pc), .idata_o(idata)
    );
    uqu_if_aligner #(.ISA_C(ISA_C)) u_aligner (
        .valid_i(active), .pc_i(pc_q),
        .word0_valid_i(word0_valid), .word0_data_i(word0_data), .word0_error_i(word0_error),
        .word1_valid_i(word1_valid), .word1_data_i(word1_data), .word1_error_i(word1_error),
        .valid_o(fetched_valid), .instr_o(fetched_instr), .compressed_o(fetched_compressed),
        .next_pc_o(fetched_next_pc), .drop_word_o(drop_word), .word1_needed_o(),
        .misaligned_o(misaligned_o), .exception_valid_o(fetched_fault),
        .exception_cause_o(fetched_cause), .exception_tval_o(fetched_tval)
    );
    generate
        if ((ISA_C == 1) && (MUA_C_IMPL == `UQU_C_IMPL_DECOMPRESS) &&
            (MUA_C_DECOMPRESS_STAGE == `UQU_C_DECOMPRESS_IF)) begin : gen_expand_if
            wire illegal;
            uqu_decompressor #(.ISA_C(1)) u_decompressor (
                .instr_i(selected_instr), .instr_o(normalized_instr), .original_instr_o(),
                .compressed_o(), .illegal_o(illegal), .hint_o()
            );
            assign expansion_fault = selected_valid && !access_fault && selected_compressed && illegal;
        end else begin : gen_raw_if
            assign normalized_instr = selected_instr;
            assign expansion_fault = 1'b0;
        end
        if (((ISA_C != 0) && (ISA_C != 1)) ||
            ((MUA_C_IMPL != `UQU_C_IMPL_DECOMPRESS) && (MUA_C_IMPL != `UQU_C_IMPL_DECODE_COMPRESSED)) ||
            ((MUA_C_DECOMPRESS_STAGE != `UQU_C_DECOMPRESS_IF) &&
             (MUA_C_DECOMPRESS_STAGE != `UQU_C_DECOMPRESS_DE)) ||
            ((MUA_BRANCH_PREDICTOR != `UQU_BP_NONE) &&
             (MUA_BRANCH_PREDICTOR != `UQU_BP_STATIC_NOT_TAKEN) &&
             (MUA_BRANCH_PREDICTOR != `UQU_BP_BIMODAL))) begin : gen_invalid
            uqu_stage_if_invalid_configuration invalid_configuration ();
        end
    endgenerate

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            pc_q <= boot_addr_i;
            fetch_addr_q <= {boot_addr_i[31:2],2'b00};
            running_q <= 1'b1;
            fault_hold_q <= 1'b0;
            prediction_held_q <= 1'b0;
        end else if (redirect_valid_i) begin
            pc_q <= redirect_addr_i;
            fetch_addr_q <= {redirect_addr_i[31:2],2'b00};
            running_q <= 1'b1;
            fault_hold_q <= 1'b0;
            prediction_held_q <= 1'b0;
        end else if (flush_i) begin
            running_q <= 1'b0;
            fault_hold_q <= 1'b0;
            prediction_held_q <= 1'b0;
        end else if (replay_recover) begin
            fetch_addr_q <= {pc_q[31:2],2'b00};
            fault_hold_q <= 1'b0;
            prediction_held_q <= 1'b0;
        end else begin
            if (prediction_redirect) begin
                fetch_addr_q <= replay_start ? {idata_next_pc[31:2],2'b00} : {predicted_pc[31:2],2'b00};
            end else if (fetch_fire) begin
                fetch_addr_q <= fetch_addr_q + 32'd4;
            end
            if (valid_o && !ready_i && !prediction_held_q &&
                ((MUA_BRANCH_PREDICTOR != `UQU_BP_NONE) && (MUA_BTB != `UQU_BTB_NONE))) begin
                prediction_held_q <= 1'b1;
                prediction_pc_q <= predicted_pc;
            end
            if (transfer) begin
                prediction_held_q <= 1'b0;
                if (candidate_fault) begin
                    fault_hold_q <= 1'b1;
                end else begin
                    pc_q <= predicted_pc;
                end
            end
        end
    end
endmodule

`default_nettype wire
