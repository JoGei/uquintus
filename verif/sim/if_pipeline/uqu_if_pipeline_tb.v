`default_nettype none
`include "uqu_config.vh"
`include "uqu_isa.vh"

// Verification-only core parent. IF/DE lives here, outside both real stages.
// DE sources are ready zeros; EX, GPRs, PMP and the global trap controller are
// outside this fixture. Accepted taken DE branches redirect IF without echoing
// a flush into that same DE transaction.
module uqu_if_pipeline_tb #(
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
    input wire clk_i,
    input wire rst_ni,
    input wire [31:0] boot_addr_i,
    input wire flush_i,
    input wire redirect_valid_i,
    input wire [31:0] redirect_addr_i,
    input wire fetch_enable_i,
    input wire if_permit_i,
    input wire de_permit_i,
    input wire ready_i,
    input wire pmp_allow_i,
    output wire pmp_valid_o,
    output wire [31:0] pmp_addr_o,
    output wire if_transfer_o,
    output wire [31:0] if_pc_o,
    output wire [31:0] if_instr_o,
    output wire [31:0] if_original_o,
    output wire if_compressed_o,
    output wire if_exception_o,
    output wire slot_valid_o,
    output wire [31:0] slot_instr_o,
    output wire [31:0] slot_original_o,
    output wire slot_compressed_o,
    output wire valid_o,
    output wire [31:0] pc_o,
    output wire [31:0] original_instr_o,
    output wire compressed_o,
    output wire [31:0] link_o,
    output wire branch_resolve_o,
    output wire branch_taken_o,
    output wire [31:0] branch_target_o,
    output wire correction_o,
    output wire exception_valid_o,
    output wire [4:0] exception_cause_o,
    output wire [31:0] exception_tval_o,
    output wire imem_req_o,
    output wire [31:0] imem_addr_o,
    input wire imem_gnt_i,
    input wire imem_rvalid_i,
    input wire [31:0] imem_rdata_i,
    input wire imem_err_i
);
    reg slot_valid_q;
    reg [31:0] pc_q, instr_q, original_q, tval_q;
    reg [31:0] predicted_next_pc_q;
    reg compressed_q, exception_q;
    reg [4:0] cause_q;
    wire if_valid, if_ready;
    wire if_exception;
    wire [4:0] if_cause;
    wire [31:0] if_tval;
    wire [31:0] if_predicted_next_pc, de_next_pc;
    wire control_flow;
    wire external_flush = flush_i || redirect_valid_i;
    wire correction = valid_o && ready_i && !exception_valid_o &&
        (((MUA_BRANCH_PREDICTOR != `UQU_BP_NONE) && (MUA_BTB != `UQU_BTB_NONE)) ?
         (de_next_pc != predicted_next_pc_q) : branch_taken_o);
    wire redirect = redirect_valid_i || correction;
    wire [31:0] target = redirect_valid_i ? redirect_addr_i : de_next_pc;
    wire conditional = compressed_q ?
        ((original_q[15:13] == `UQU_C_Q1_BEQZ) || (original_q[15:13] == `UQU_C_Q1_BNEZ)) :
        (original_q[6:0] == `UQU_OPCODE_BRANCH);
    assign correction_o = correction;

    assign if_transfer_o = if_valid && if_ready;
    assign if_exception_o = if_exception;
    assign slot_valid_o = slot_valid_q;
    assign slot_instr_o = instr_q;
    assign slot_original_o = original_q;
    assign slot_compressed_o = compressed_q;
    assign pc_o = pc_q;
    assign original_instr_o = original_q;
    assign compressed_o = compressed_q;

    uqu_stage_if #(
        .ISA_C(ISA_C), .MUA_C_IMPL(MUA_C_IMPL), .MUA_C_DECOMPRESS_STAGE(MUA_C_DECOMPRESS_STAGE),
        .MUA_BRANCH_PREDICTOR(MUA_BRANCH_PREDICTOR), .MUA_BP_ENTRIES(MUA_BP_ENTRIES),
        .MUA_BTB(MUA_BTB), .MUA_BTB_ENTRIES(MUA_BTB_ENTRIES), .MUA_BTB_IDATA_DEPTH(MUA_BTB_IDATA_DEPTH), .MUA_IF_BUFFER_WORDS(MUA_IF_BUFFER_WORDS)
    ) u_if (
        .clk_i(clk_i), .rst_ni(rst_ni), .boot_addr_i(boot_addr_i), .flush_i(flush_i),
        .redirect_valid_i(redirect), .redirect_addr_i(target), .fetch_enable_i(fetch_enable_i),
        .request_permit_i(1'b1), .branch_pending_i(control_flow), .permit_i(if_permit_i),
        .predictor_invalidate_i(1'b0), .predictor_update_valid_i(valid_o && ready_i && !exception_valid_o),
        .predictor_update_pc_i(pc_q), .predictor_update_control_flow_i(control_flow),
        .predictor_update_conditional_i(conditional), .predictor_update_taken_i(branch_taken_o),
        .predictor_update_target_i(branch_target_o),
        .valid_o(if_valid), .ready_i(if_ready), .pc_o(if_pc_o), .instr_o(if_instr_o),
        .original_instr_o(if_original_o), .compressed_o(if_compressed_o), .next_pc_o(),
        .predicted_next_pc_o(if_predicted_next_pc),
        .exception_valid_o(if_exception), .exception_cause_o(if_cause), .exception_tval_o(if_tval),
        .misaligned_o(), .fetch_busy_o(), .priv_m_i(1'b1), .pmp_valid_o(pmp_valid_o),
        .pmp_addr_o(pmp_addr_o), .pmp_size_o(), .pmp_priv_m_o(), .pmp_allow_i(pmp_allow_i),
        .replay_pmp_addr_o(), .replay_pmp_priv_m_o(), .replay_pmp_allow_i(2'b11),
        .imem_req_o(imem_req_o), .imem_addr_o(imem_addr_o), .imem_gnt_i(imem_gnt_i),
        .imem_rvalid_i(imem_rvalid_i), .imem_rdata_i(imem_rdata_i), .imem_err_i(imem_err_i)
    );
    uqu_stage_de #(
        .ISA_C(ISA_C), .MUA_C_IMPL(MUA_C_IMPL), .MUA_C_DECOMPRESS_STAGE(MUA_C_DECOMPRESS_STAGE)
    ) u_de (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(external_flush),
        .valid_i(slot_valid_q), .ready_o(if_ready), .valid_o(valid_o),
        .ready_i(ready_i), .permit_i(de_permit_i), .pc_i(pc_q), .instr_i(instr_q),
        .original_instr_i(original_q), .compressed_i(compressed_q),
        .priv_m_i(1'b1), .debug_mode_i(1'b0), .tw_i(1'b0), .frm_i(3'd0),
        .exception_valid_i(exception_q), .exception_cause_i(cause_q), .exception_tval_i(tval_q),
        .rs0_i(32'd0), .rs1_i(32'd0), .rs2_i(32'd0), .rs_ready_i(3'b111), .rs_ex_guaranteed_i(3'd0),
        .rs0_addr_o(), .rs1_addr_o(), .rs2_addr_o(), .rs_used_o(), .rs_need_now_o(),
        .rs_ex_used_o(), .rs_captured_o(), .native_o(), .fu_o(), .op_o(), .a_sel_o(), .b_sel_o(),
        .imm_o(), .a_o(), .b_o(), .c_o(), .rm_o(), .pass_data_o(link_o), .store_data_o(),
        .rd_we_o(), .rd_o(), .rd1_o(), .rd_pending_o(), .lsu_o(), .mem_we_o(), .mem_op_o(),
        .wb_kind_o(), .system_o(), .serialize_o(), .csr_addr_o(), .csr_op_o(), .csr_src_o(),
        .csr_src_zero_o(), .control_flow_o(control_flow), .branch_resolve_o(branch_resolve_o),
        .branch_taken_o(branch_taken_o), .branch_target_o(branch_target_o), .next_pc_o(de_next_pc),
        .exception_valid_o(exception_valid_o), .exception_cause_o(exception_cause_o),
        .exception_tval_o(exception_tval_o), .xif_force_i(1'b0), .xif_id_valid_i(1'b0),
        .xif_id_i(3'd0), .hart_id_i(32'd0), .xif_issued_o(), .xif_accepted_o(),
        .xif_cleanup_valid_o(), .xif_cleanup_id_o(), .xif_cleanup_ready_i(1'b0),
        .xif_issue_valid_o(), .xif_issue_ready_i(1'b0), .xif_issue_instr_o(), .xif_issue_hartid_o(),
        .xif_issue_id_o(), .xif_issue_accept_i(1'b0), .xif_issue_writeback_i(1'b0),
        .xif_issue_register_read_i(3'd0), .xif_register_valid_o(), .xif_register_ready_i(1'b0),
        .xif_register_hartid_o(), .xif_register_id_o(), .xif_register_rs_o(), .xif_register_rs_valid_o()
    );
    always @(posedge clk_i) begin
        if (!rst_ni || external_flush || correction) begin
            slot_valid_q <= 1'b0;
        end else if (if_ready) begin
            slot_valid_q <= if_valid;
            if (if_valid) begin
                pc_q <= if_pc_o;
                predicted_next_pc_q <= if_predicted_next_pc;
                instr_q <= if_instr_o;
                original_q <= if_original_o;
                compressed_q <= if_compressed_o;
                exception_q <= if_exception;
                cause_q <= if_cause;
                tval_q <= if_tval;
            end
        end
    end
endmodule

`default_nettype wire
