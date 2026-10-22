`default_nettype none
`include "uqu_config.vh"
`include "uqu_ctrl.vh"
`include "uqu_isa.vh"

// Native core region. All four pipeline boundaries, GPRs, shared hazards/PMP,
// privilege and architectural resume tracking live here. Memories are external.
module uqu_core #(
    parameter [31:0] HART_ID = 32'd0,
    parameter ISA_E = 0,
    parameter ISA_M = 0,
    parameter ISA_C = 0,
    parameter ISA_ZFINX = 0,
    parameter ISA_F = 0,
    parameter ISA_A = 0,
    parameter ISA_UMODE = 1,
    parameter ISA_ZIFENCEI = 0,
    parameter ISA_PMP = 0,
    parameter MUA_FORWARDING = 1,
    parameter MUA_FORWARD_EX_TO_DE = 1,
    parameter MUA_FORWARD_MEM_TO_DE = 1,
    parameter MUA_FORWARD_MEM_TO_EX = 1,
    parameter MUA_FORWARD_WB_TO_EX = 1,
    parameter MUA_DE_OPERAND_RETENTION = 0,
    parameter MUA_C_IMPL = `UQU_C_IMPL_DECOMPRESS,
    parameter MUA_C_DECOMPRESS_STAGE = `UQU_C_DECOMPRESS_IF,
    parameter MUA_BRANCH_PREDICTOR = `UQU_BP_NONE,
    parameter MUA_BP_ENTRIES = 16,
    parameter MUA_BTB = `UQU_BTB_NONE,
    parameter MUA_BTB_ENTRIES = 16,
    parameter MUA_BTB_IDATA_HWORDS = 0,
    parameter MUA_REGFILE_IMPL = `UQU_RF_FF,
    parameter MUA_IF_BUFFER_WORDS = 2,
    parameter MUA_HARDENED = 0,
    parameter MUA_MUL = `UQU_MUL_ITERATIVE,
    parameter MUA_DIV = `UQU_DIV_ITERATIVE,
    parameter MUA_MULDIV_ITERUNROLL = 8,
    parameter MUA_FPU_PIPE_REGS_FMA = 2,
    parameter MUA_FPU_PIPE_REGS_DIVSQRT = 0,
    parameter MUA_FPU_PIPE_REGS_NONCOMP = 0,
    parameter MUA_FPU_PIPE_REGS_CONV = 1,
    parameter MUA_FPU_PIPE_CONFIG = `UQU_FPU_PIPE_DISTRIBUTED,
    parameter MUA_FPU_DIVSQRT = `UQU_FPU_DIVSQRT_TH32,
    parameter XIF = 0,
    parameter XIF_NUM_RS = 3,
    parameter XIF_DUALWRITE = 0,
    parameter DEBUG = 0
) (
    input wire clk_i,
    input wire rst_ni,
    input wire [31:0] boot_addr_i,
    input wire irq_software_i,
    input wire irq_timer_i,
    input wire irq_external_i,
    output wire imem_req_o,
    output wire [31:0] imem_addr_o,
    input wire imem_gnt_i,
    input wire imem_rvalid_i,
    input wire [31:0] imem_rdata_i,
    input wire imem_err_i,
    output wire dmem_req_o,
    output wire dmem_we_o,
    output wire [31:0] dmem_addr_o,
    output wire [31:0] dmem_wdata_o,
    output wire [3:0] dmem_be_o,
    input wire dmem_gnt_i,
    input wire dmem_rvalid_i,
    input wire [31:0] dmem_rdata_i,
    input wire dmem_err_i,
    output wire fence_req_o,
    input wire fence_ack_i,
    output wire fencei_req_o,
    input wire fencei_ack_i,
    // Standard CV-X-IF issue/register/commit/result channels, inactive at XIF=0.
    output wire xif_issue_valid_o,
    input wire xif_issue_ready_i,
    output wire [31:0] xif_issue_instr_o,
    output wire [31:0] xif_issue_hartid_o,
    output wire [2:0] xif_issue_id_o,
    input wire xif_issue_accept_i,
    input wire [XIF_DUALWRITE:0] xif_issue_writeback_i,
    input wire [XIF_NUM_RS-1:0] xif_issue_register_read_i,
    output wire xif_register_valid_o,
    input wire xif_register_ready_i,
    output wire [31:0] xif_register_hartid_o,
    output wire [2:0] xif_register_id_o,
    output wire [32*XIF_NUM_RS-1:0] xif_register_rs_o,
    output wire [XIF_NUM_RS-1:0] xif_register_rs_valid_o,
    output wire xif_commit_valid_o,
    output wire [31:0] xif_commit_hartid_o,
    output wire [2:0] xif_commit_id_o,
    output wire xif_commit_kill_o,
    input wire xif_result_valid_i,
    output wire xif_result_ready_o,
    input wire [31:0] xif_result_hartid_i,
    input wire [2:0] xif_result_id_i,
    input wire [32*(1+XIF_DUALWRITE)-1:0] xif_result_data_i,
    input wire [4:0] xif_result_rd_i,
    input wire [XIF_DUALWRITE:0] xif_result_we_i
);
    localparam integer IDATA_HWORDS = ((MUA_BRANCH_PREDICTOR != `UQU_BP_NONE) &&
        (MUA_BTB != `UQU_BTB_NONE)) ? MUA_BTB_IDATA_HWORDS : 0;
    wire [31:0] replay_pmp_addr;
    wire replay_pmp_priv_m;
    wire [1:0] replay_pmp_allow;
    reg priv_m_q;
    reg [31:0] resume_pc_q;
    reg de_valid_q, ex_valid_q, mem_valid_q, wb_valid_q;
    reg [31:0] de_pc_q, de_instr_q, de_original_q, de_tval_q;
    reg [31:0] de_predicted_next_pc_q;
    reg de_compressed_q, de_priv_m_q, de_exception_q;
    reg [4:0] de_cause_q;

    reg [31:0] ex_pc_q, ex_original_q, ex_next_pc_q, ex_tval_q;
    reg ex_compressed_q, ex_priv_m_q, ex_exception_q, ex_serialize_q;
    reg [4:0] ex_cause_q, ex_rd_q;
    reg [4:0] ex_rd1_q, mem_rd1_q, wb_rd1_q;
    reg [2:0] ex_xif_id_q, mem_xif_id_q, wb_xif_id_q;
    reg ex_rd_we_q, ex_lsu_q, ex_mem_we_q, ex_csr_zero_q;
    reg [1:0] ex_pending_q, ex_fu_q, ex_a_sel_q, ex_b_sel_q;
    reg [4:0] ex_op_q;
    reg [2:0] ex_kind_q, ex_system_q, ex_mem_op_q, ex_csr_op_q, ex_rm_q;
    reg [31:0] ex_imm_q, ex_pass_q, ex_csr_src_q;
    reg [11:0] ex_csr_addr_q;
    reg [2:0] ex_used_q, ex_captured_q;
    reg [4:0] ex_rs_addr_q [0:2];
    reg [31:0] ex_rs_data_q [0:2];

    reg [31:0] mem_pc_q, mem_original_q, mem_next_pc_q, mem_tval_q;
    reg mem_compressed_q, mem_priv_m_q, mem_exception_q, mem_serialize_q;
    reg [4:0] mem_cause_q, mem_rd_q;
    reg mem_rd_we_q, mem_lsu_q, mem_we_q, mem_csr_zero_q, mem_fflags_valid_q;
    reg [1:0] mem_pending_q;
    reg [2:0] mem_kind_q, mem_system_q, mem_op_q, mem_csr_op_q;
    reg [31:0] mem_data_q, mem_store_data_q, mem_csr_src_q;
    reg [11:0] mem_csr_addr_q;
    reg [4:0] mem_fflags_q;

    reg [31:0] wb_pc_q, wb_original_q, wb_next_pc_q, wb_tval_q;
    reg wb_compressed_q, wb_priv_m_q, wb_exception_q, wb_serialize_q;
    reg [4:0] wb_cause_q, wb_rd_q;
    reg wb_rd_we_q, wb_csr_zero_q, wb_fflags_valid_q;
    reg [1:0] wb_pending_q;
    reg [2:0] wb_kind_q, wb_system_q, wb_csr_op_q;
    reg [31:0] wb_data_q, wb_csr_src_q;
    reg [11:0] wb_csr_addr_q;
    reg [4:0] wb_fflags_q;

    wire if_valid, if_permit, if_ready, fetch_enable, if_flush;
    wire [31:0] if_pc, if_instr, if_original, if_tval;
    wire [31:0] if_predicted_next_pc;
    wire if_compressed, if_exception;
    wire [4:0] if_cause;
    wire de_complete, ex_complete, mem_complete, wb_complete;
    wire de_permit, de_ready, ex_ready, mem_ready, wb_ready;
    wire if_fire, de_fire, ex_fire, mem_fire, wb_fire;
    wire de_enable, ex_enable, mem_enable, wb_enable;
    wire de_next_valid, ex_next_valid, mem_next_valid, wb_next_valid;
    wire de_flush, ex_flush, mem_flush, mem_request_permit;
    wire redirect_valid;
    wire [31:0] redirect_addr;
    wire trap_valid, trap_interrupt;
    wire [31:0] trap_pc, trap_tval;
    wire [4:0] trap_cause;
    wire [31:0] mstatus, mie, mip, mtvec, mepc;
    wire [127:0] pmpcfg;
    wire [511:0] pmpaddr;
    wire [2:0] frm;
    wire if_pmp_valid, if_pmp_priv_m, if_pmp_allow;
    wire [31:0] if_pmp_addr;
    wire [1:0] if_pmp_size;
    wire mem_pmp_valid, mem_pmp_priv_m, mem_pmp_allow;
    wire [31:0] mem_pmp_addr;
    wire [1:0] mem_pmp_size;
    wire [2:0] mem_pmp_access;
    wire mem_effective_priv_m = mem_priv_m_q && (!mstatus[17] || (mstatus[12:11] == 2'b11));

    wire [4:0] de_rs_addr [0:2];
    wire [31:0] gpr_data [0:2];
    wire [31:0] de_rs [0:2];
    wire [31:0] ex_rs [0:2];
    wire [2:0] de_used, de_need_now, de_ex_used, de_captured, de_rs_ready, de_guaranteed, ex_rs_ready;
    wire [1:0] de_fu, de_a_sel, de_b_sel, de_pending;
    wire [4:0] de_op, de_rd, de_rd1;
    wire [31:0] de_imm, de_pass, de_csr_src, de_next_pc, de_target;
    wire [11:0] de_csr_addr;
    wire [2:0] de_kind, de_system, de_mem_op, de_csr_op, de_rm;
    wire de_rd_we, de_lsu, de_mem_we, de_csr_zero, de_serialize, de_control_flow, de_branch_taken;
    wire de_exception;
    wire de_conditional = de_compressed_q ?
        ((de_original_q[15:13] == `UQU_C_Q1_BEQZ) || (de_original_q[15:13] == `UQU_C_Q1_BNEZ)) :
        (de_original_q[6:0] == `UQU_OPCODE_BRANCH);
    wire de_redirect = ((MUA_BRANCH_PREDICTOR != `UQU_BP_NONE) && (MUA_BTB != `UQU_BTB_NONE)) ?
                       (de_next_pc != de_predicted_next_pc_q) : de_branch_taken;
    wire [4:0] de_cause;
    wire [31:0] de_tval;
    wire ex_exception, ex_fflags_valid;
    wire [4:0] ex_cause, ex_fflags;
    wire [31:0] ex_tval, ex_result, ex_store_data;
    wire ex_operands_ready = ((ex_rs_ready & ex_used_q) == ex_used_q);
    wire [31:0] ex_a = (ex_a_sel_q == `UQU_A_PC) ? ex_pc_q :
                             (ex_a_sel_q == `UQU_A_RS1) ? ex_rs[0] : 32'd0;
    wire [31:0] ex_b = (ex_b_sel_q == `UQU_B_IMM) ? ex_imm_q :
                             (ex_b_sel_q == `UQU_B_RS2) ? ex_rs[1] : 32'd0;
    wire mem_exception, mem_fflags_valid, lsu_busy;
    wire [4:0] mem_cause, mem_fflags;
    wire [31:0] mem_tval, mem_result;
    wire wb_exception, wb_exception_fire, wb_retire, wb_mret;
    wire [4:0] wb_cause;
    wire [31:0] wb_tval, wb_result;
    wire wb_result_valid, wb_we0, wb_we1;
    wire predictor_invalidate = wb_retire && (wb_system_q == `UQU_SYS_FENCEI);
    wire xif_id_valid, xif_issued, xif_accepted, xif_cleanup_valid, xif_cleanup_ready;
    wire xif_de_cancel, xif_kill_valid, xif_kill_ready, xif_drain_ready, draining;
    wire [2:0] xif_de_id, xif_cleanup_id, xif_kill_id;
    wire [1:0] xif_allowed_writes = {wb_rd1_q != 5'd0, wb_rd_we_q};
    wire [1:0] xif_result_writes = {{(1-XIF_DUALWRITE){1'b0}}, xif_result_we_i};
    wire xif_result_allowed = ((xif_result_writes & ~xif_allowed_writes) == 2'd0);
    wire [4:0] wb_waddr0, wb_waddr1;
    wire [31:0] wb_wdata0, wb_wdata1;
    // Permission writes retire before any younger instruction uses cached bytes.
    // Preserve the BTB payload but refetch/recheck the architectural continuation.
    wire wb_csr_source_zero = wb_csr_op_q[2] ? (wb_csr_src_q[4:0] == 5'd0) : wb_csr_zero_q;
    wire wb_pmp_recover = (IDATA_HWORDS > 0) && (ISA_PMP == 1) && wb_retire &&
        (wb_kind_q == `UQU_WB_CSR) && ((wb_csr_op_q[1:0] == 2'b01) || !wb_csr_source_zero) &&
        (((wb_csr_addr_q >= 12'h3a0) && (wb_csr_addr_q <= 12'h3af)) ||
         ((wb_csr_addr_q >= 12'h3b0) && (wb_csr_addr_q <= 12'h3ef)));
    wire wb_redirect = wb_exception_fire || wb_mret || wb_pmp_recover;
    wire [31:0] wb_target = wb_exception_fire ? {mtvec[31:2],2'b00} : wb_mret ? mepc : wb_next_pc_q;
    wire ex_forwardable = ex_complete && !ex_exception && !ex_lsu_q && (ex_kind_q == `UQU_WB_RESULT);
    wire mem_forwardable = mem_complete && !mem_exception && (mem_kind_q == `UQU_WB_RESULT);

    uqu_pipeline_ctrl #(.ISA_ZIFENCEI(ISA_ZIFENCEI)) u_ctrl (
        .clk_i(clk_i), .rst_ni(rst_ni), .if_valid_i(if_valid),
        .de_valid_i(de_valid_q), .ex_valid_i(ex_valid_q), .mem_valid_i(mem_valid_q), .wb_valid_i(wb_valid_q),
        .de_complete_i(de_complete), .ex_complete_i(ex_complete), .mem_complete_i(mem_complete), .wb_complete_i(wb_complete),
        .de_exception_i(de_exception), .ex_exception_i(ex_exception), .mem_exception_i(mem_exception), .wb_exception_i(wb_exception),
        .ex_serialize_i(ex_serialize_q), .mem_serialize_i(mem_serialize_q), .wb_serialize_i(wb_serialize_q),
        .de_system_i(de_system), .ex_system_i(ex_system_q), .mem_system_i(mem_system_q), .wb_system_i(wb_system_q),
        .de_admit_i(1'b1), .commit_enable_i(1'b1), .wb_effect_safe_i(!wb_exception),
        .de_redirect_i(de_redirect), .de_redirect_addr_i(de_next_pc),
        .wb_redirect_valid_i(wb_redirect), .wb_redirect_addr_i(wb_target), .wb_next_pc_i(wb_next_pc_q),
        .de_pc_i(de_pc_q), .resume_pc_i(resume_pc_q), .priv_m_i(priv_m_q),
        .mstatus_i(mstatus), .mie_i(mie), .mip_i(mip), .mtvec_i(mtvec), .irq_mask_i(1'b0),
        .drain_req_i(1'b0), .drain_target_i(32'd0), .drain_ready_i(!lsu_busy && xif_drain_ready), .data_idle_i(!lsu_busy),
        .fence_ack_i(fence_ack_i), .fencei_ack_i(fencei_ack_i),
        .if_permit_o(if_permit), .fetch_enable_o(fetch_enable), .if_ready_o(if_ready),
        .de_permit_o(de_permit), .de_ready_o(de_ready), .ex_ready_o(ex_ready), .mem_ready_o(mem_ready), .wb_ready_o(wb_ready),
        .if_fire_o(if_fire), .de_fire_o(de_fire), .ex_fire_o(ex_fire), .mem_fire_o(mem_fire), .wb_fire_o(wb_fire),
        .de_enable_o(de_enable), .ex_enable_o(ex_enable), .mem_enable_o(mem_enable), .wb_enable_o(wb_enable),
        .de_valid_next_o(de_next_valid), .ex_valid_next_o(ex_next_valid), .mem_valid_next_o(mem_next_valid), .wb_valid_next_o(wb_next_valid),
        .if_flush_o(if_flush), .de_flush_o(de_flush), .ex_flush_o(ex_flush), .mem_flush_o(mem_flush),
        .mem_request_permit_o(mem_request_permit), .irq_eligible_o(), .draining_o(draining),
        .trap_valid_o(trap_valid), .trap_pc_o(trap_pc), .trap_interrupt_o(trap_interrupt), .trap_cause_o(trap_cause), .trap_tval_o(trap_tval),
        .drain_accept_o(), .drain_pc_o(), .redirect_valid_o(redirect_valid), .redirect_addr_o(redirect_addr),
        .fence_req_o(fence_req_o), .fencei_req_o(fencei_req_o)
    );
    uqu_xif_ctrl #(.XIF(XIF)) u_xif_ctrl (
        .clk_i(clk_i), .rst_ni(rst_ni), .draining_i(draining), .de_valid_i(de_valid_q),
        .de_fire_i(de_fire), .de_flush_i(de_flush), .de_issued_i(xif_issued), .issue_valid_i(xif_issue_valid_o),
        .de_cleanup_valid_i(xif_cleanup_valid), .de_cleanup_id_i(xif_cleanup_id), .de_cleanup_ready_o(xif_cleanup_ready),
        .de_id_valid_o(xif_id_valid), .de_id_o(xif_de_id), .de_cancel_o(xif_de_cancel),
        .ex_valid_i(ex_valid_q), .ex_xif_i(ex_kind_q == `UQU_WB_XIF), .ex_id_i(ex_xif_id_q), .ex_flush_i(ex_flush),
        .mem_valid_i(mem_valid_q), .mem_xif_i(mem_kind_q == `UQU_WB_XIF), .mem_id_i(mem_xif_id_q), .mem_flush_i(mem_flush),
        .wb_retire_i(wb_retire), .wb_xif_i(wb_kind_q == `UQU_WB_XIF), .wb_id_i(wb_xif_id_q),
        .commit_valid_i(xif_commit_valid_o), .commit_id_i(xif_commit_id_o), .commit_kill_i(xif_commit_kill_o),
        .kill_valid_o(xif_kill_valid), .kill_id_o(xif_kill_id), .kill_ready_i(xif_kill_ready), .drain_ready_o(xif_drain_ready)
    );
    uqu_stage_if #(
        .ISA_C(ISA_C), .MUA_C_IMPL(MUA_C_IMPL), .MUA_C_DECOMPRESS_STAGE(MUA_C_DECOMPRESS_STAGE),
        .MUA_BRANCH_PREDICTOR(MUA_BRANCH_PREDICTOR), .MUA_BP_ENTRIES(MUA_BP_ENTRIES),
        .MUA_BTB(MUA_BTB), .MUA_BTB_ENTRIES(MUA_BTB_ENTRIES), .MUA_BTB_IDATA_HWORDS(MUA_BTB_IDATA_HWORDS), .MUA_IF_BUFFER_WORDS(MUA_IF_BUFFER_WORDS)
    ) u_if (
        .clk_i(clk_i), .rst_ni(rst_ni), .boot_addr_i(boot_addr_i), .flush_i(if_flush),
        .redirect_valid_i(redirect_valid), .redirect_addr_i(redirect_addr), .fetch_enable_i(fetch_enable),
        .request_permit_i(1'b1), .branch_pending_i(de_control_flow), .permit_i(if_permit),
        .predictor_invalidate_i(predictor_invalidate),
        .predictor_update_valid_i(de_fire && !de_exception), .predictor_update_pc_i(de_pc_q),
        .predictor_update_control_flow_i(de_control_flow), .predictor_update_conditional_i(de_conditional),
        .predictor_update_taken_i(de_branch_taken), .predictor_update_target_i(de_target),
        .valid_o(if_valid), .ready_i(if_ready), .pc_o(if_pc), .instr_o(if_instr), .original_instr_o(if_original),
        .compressed_o(if_compressed), .next_pc_o(), .predicted_next_pc_o(if_predicted_next_pc),
        .exception_valid_o(if_exception), .exception_cause_o(if_cause),
        .exception_tval_o(if_tval), .misaligned_o(), .fetch_busy_o(), .priv_m_i(priv_m_q),
        .pmp_valid_o(if_pmp_valid), .pmp_addr_o(if_pmp_addr), .pmp_size_o(if_pmp_size), .pmp_priv_m_o(if_pmp_priv_m), .pmp_allow_i(if_pmp_allow),
        .replay_pmp_addr_o(replay_pmp_addr), .replay_pmp_priv_m_o(replay_pmp_priv_m), .replay_pmp_allow_i(replay_pmp_allow),
        .imem_req_o(imem_req_o), .imem_addr_o(imem_addr_o), .imem_gnt_i(imem_gnt_i),
        .imem_rvalid_i(imem_rvalid_i), .imem_rdata_i(imem_rdata_i), .imem_err_i(imem_err_i)
    );
    uqu_gpregfile #(
        .ISA_E(ISA_E), .ISA_ZFINX(ISA_ZFINX), .XIF(XIF), .XIF_NUM_RS(XIF_NUM_RS),
        .XIF_DUALWRITE(XIF_DUALWRITE), .MUA_REGFILE_IMPL(MUA_REGFILE_IMPL)
    ) u_gpr (
        .clk_i(clk_i), .rst_ni(rst_ni), .raddr0_i(de_rs_addr[0]), .raddr1_i(de_rs_addr[1]), .raddr2_i(de_rs_addr[2]),
        .rdata0_o(gpr_data[0]), .rdata1_o(gpr_data[1]), .rdata2_o(gpr_data[2]),
        .we0_i(wb_we0), .waddr0_i(wb_waddr0), .wdata0_i(wb_wdata0), .we1_i(wb_we1), .waddr1_i(wb_waddr1), .wdata1_i(wb_wdata1)
    );
    uqu_hazard #(
        .ISA_E(ISA_E), .ISA_ZFINX(ISA_ZFINX), .XIF(XIF), .XIF_NUM_RS(XIF_NUM_RS), .XIF_DUALWRITE(XIF_DUALWRITE),
        .MUA_FORWARDING(MUA_FORWARDING), .MUA_FORWARD_EX_TO_DE(MUA_FORWARD_EX_TO_DE),
        .MUA_FORWARD_MEM_TO_DE(MUA_FORWARD_MEM_TO_DE), .MUA_FORWARD_MEM_TO_EX(MUA_FORWARD_MEM_TO_EX),
        .MUA_FORWARD_WB_TO_EX(MUA_FORWARD_WB_TO_EX), .MUA_DE_OPERAND_RETENTION(MUA_DE_OPERAND_RETENTION)
    ) u_hazard (
        .clk_i(clk_i), .rst_ni(rst_ni), .de_valid_i(de_valid_q), .de_clear_i(de_flush || de_fire || xif_de_cancel),
        .de_rs0_addr_i(de_rs_addr[0]), .de_rs1_addr_i(de_rs_addr[1]), .de_rs2_addr_i(de_rs_addr[2]),
        .de_rs0_i(gpr_data[0]), .de_rs1_i(gpr_data[1]), .de_rs2_i(gpr_data[2]),
        .de_rs_used_i(de_used), .de_rs_need_now_i(de_need_now),
        .de_rs0_o(de_rs[0]), .de_rs1_o(de_rs[1]), .de_rs2_o(de_rs[2]), .de_rs_ready_o(de_rs_ready), .de_rs_ex_guaranteed_o(de_guaranteed),
        .ex_valid_i(ex_valid_q), .ex_rs0_addr_i(ex_rs_addr_q[0]), .ex_rs1_addr_i(ex_rs_addr_q[1]), .ex_rs2_addr_i(ex_rs_addr_q[2]),
        .ex_rs0_i(ex_rs_data_q[0]), .ex_rs1_i(ex_rs_data_q[1]), .ex_rs2_i(ex_rs_data_q[2]),
        .ex_rs_used_i(ex_used_q), .ex_rs_captured_i(ex_captured_q),
        .ex_rs0_o(ex_rs[0]), .ex_rs1_o(ex_rs[1]), .ex_rs2_o(ex_rs[2]), .ex_rs_ready_o(ex_rs_ready),
        .ex_pending_i(ex_pending_q), .ex_rd0_i(ex_rd_q), .ex_rd1_i(ex_rd1_q),
        .ex_result_available_i(ex_forwardable), .ex_result_forwardable_i(ex_forwardable), .ex_result_i(ex_result), .ex_advance_i(ex_fire),
        .mem_valid_i(mem_valid_q), .mem_pending_i(mem_pending_q), .mem_rd0_i(mem_rd_q), .mem_rd1_i(mem_rd1_q),
        .mem_result_available_i(mem_forwardable), .mem_result_forwardable_i(mem_forwardable), .mem_result_i(mem_result), .mem_advance_i(mem_fire),
        .wb_valid_i(wb_valid_q), .wb_pending_i(wb_pending_q), .wb_rd0_i(wb_rd_q), .wb_rd1_i(wb_rd1_q),
        .wb_result_available_i(wb_result_valid), .wb_result_forwardable_i(wb_result_valid), .wb_result_i(wb_result), .wb_advance_i(wb_fire)
    );
    uqu_stage_de #(
        .ISA_E(ISA_E), .ISA_M(ISA_M), .ISA_C(ISA_C), .ISA_ZFINX(ISA_ZFINX), .ISA_ZIFENCEI(ISA_ZIFENCEI),
        .ISA_F(ISA_F), .ISA_A(ISA_A), .ISA_UMODE(ISA_UMODE), .MUA_C_IMPL(MUA_C_IMPL), .MUA_C_DECOMPRESS_STAGE(MUA_C_DECOMPRESS_STAGE),
        .XIF(XIF), .XIF_NUM_RS(XIF_NUM_RS), .XIF_DUALWRITE(XIF_DUALWRITE), .DEBUG(DEBUG)
    ) u_de (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(de_flush || xif_de_cancel), .valid_i(de_valid_q), .ready_o(), .valid_o(de_complete), .ready_i(de_ready), .permit_i(de_permit),
        .pc_i(de_pc_q), .instr_i(de_instr_q), .original_instr_i(de_original_q), .compressed_i(de_compressed_q),
        .priv_m_i(de_priv_m_q), .debug_mode_i(1'b0), .tw_i(mstatus[21]), .frm_i(frm),
        .exception_valid_i(de_exception_q), .exception_cause_i(de_cause_q), .exception_tval_i(de_tval_q),
        .rs0_i(de_rs[0]), .rs1_i(de_rs[1]), .rs2_i(de_rs[2]), .rs_ready_i(de_rs_ready), .rs_ex_guaranteed_i(de_guaranteed),
        .rs0_addr_o(de_rs_addr[0]), .rs1_addr_o(de_rs_addr[1]), .rs2_addr_o(de_rs_addr[2]),
        .rs_used_o(de_used), .rs_need_now_o(de_need_now), .rs_ex_used_o(de_ex_used), .rs_captured_o(de_captured),
        .native_o(), .fu_o(de_fu), .op_o(de_op), .a_sel_o(de_a_sel), .b_sel_o(de_b_sel), .imm_o(de_imm),
        .a_o(), .b_o(), .c_o(), .rm_o(de_rm), .pass_data_o(de_pass), .store_data_o(),
        .rd_we_o(de_rd_we), .rd_o(de_rd), .rd1_o(de_rd1), .rd_pending_o(de_pending), .lsu_o(de_lsu), .mem_we_o(de_mem_we), .mem_op_o(de_mem_op),
        .wb_kind_o(de_kind), .system_o(de_system), .serialize_o(de_serialize), .csr_addr_o(de_csr_addr), .csr_op_o(de_csr_op),
        .csr_src_o(de_csr_src), .csr_src_zero_o(de_csr_zero), .control_flow_o(de_control_flow), .branch_resolve_o(),
        .branch_taken_o(de_branch_taken), .branch_target_o(de_target), .next_pc_o(de_next_pc),
        .exception_valid_o(de_exception), .exception_cause_o(de_cause), .exception_tval_o(de_tval),
        .xif_force_i(1'b0), .xif_id_valid_i(xif_id_valid), .xif_id_i(xif_de_id), .hart_id_i(HART_ID),
        .xif_issued_o(xif_issued), .xif_accepted_o(xif_accepted), .xif_cleanup_valid_o(xif_cleanup_valid), .xif_cleanup_id_o(xif_cleanup_id), .xif_cleanup_ready_i(xif_cleanup_ready),
        .xif_issue_valid_o(xif_issue_valid_o), .xif_issue_ready_i(xif_issue_ready_i), .xif_issue_instr_o(xif_issue_instr_o),
        .xif_issue_hartid_o(xif_issue_hartid_o), .xif_issue_id_o(xif_issue_id_o), .xif_issue_accept_i(xif_issue_accept_i),
        .xif_issue_writeback_i(xif_issue_writeback_i), .xif_issue_register_read_i(xif_issue_register_read_i),
        .xif_register_valid_o(xif_register_valid_o), .xif_register_ready_i(xif_register_ready_i), .xif_register_hartid_o(xif_register_hartid_o),
        .xif_register_id_o(xif_register_id_o), .xif_register_rs_o(xif_register_rs_o), .xif_register_rs_valid_o(xif_register_rs_valid_o)
    );
    uqu_stage_ex #(
        .MUA_FPU_PIPE_REGS_FMA(MUA_FPU_PIPE_REGS_FMA),
        .MUA_FPU_PIPE_REGS_DIVSQRT(MUA_FPU_PIPE_REGS_DIVSQRT),
        .MUA_FPU_PIPE_REGS_NONCOMP(MUA_FPU_PIPE_REGS_NONCOMP),
        .MUA_FPU_PIPE_REGS_CONV(MUA_FPU_PIPE_REGS_CONV),
        .MUA_FPU_PIPE_CONFIG(MUA_FPU_PIPE_CONFIG),
        .MUA_FPU_DIVSQRT(MUA_FPU_DIVSQRT),
        .ISA_M(ISA_M), .ISA_ZFINX(ISA_ZFINX), .MUA_MUL(MUA_MUL), .MUA_DIV(MUA_DIV), .MUA_MULDIV_ITERUNROLL(MUA_MULDIV_ITERUNROLL)
    ) u_ex (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(ex_flush), .valid_i(ex_valid_q), .ready_o(), .valid_o(ex_complete), .ready_i(ex_ready),
        .fu_i(ex_fu_q), .op_i(ex_op_q), .operands_ready_i(ex_operands_ready), .a_i(ex_a), .b_i(ex_b), .c_i(ex_rs[2]), .rm_i(ex_rm_q),
        .pass_data_i(ex_pass_q), .store_data_i(ex_rs[1]), .instr_i(ex_original_q),
        .exception_valid_i(ex_exception_q), .exception_cause_i(ex_cause_q), .exception_tval_i(ex_tval_q),
        .result_o(ex_result), .store_data_o(ex_store_data), .fflags_valid_o(ex_fflags_valid), .fflags_o(ex_fflags),
        .exception_valid_o(ex_exception), .exception_cause_o(ex_cause), .exception_tval_o(ex_tval)
    );
    uqu_stage_mem u_mem (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(mem_flush), .valid_i(mem_valid_q), .ready_o(), .valid_o(mem_complete), .ready_i(mem_ready),
        .lsu_i(mem_lsu_q), .we_i(mem_we_q), .op_i(mem_op_q), .result_i(mem_data_q), .store_data_i(mem_store_data_q),
        .instr_i(mem_original_q), .priv_m_i(mem_effective_priv_m), .fflags_valid_i(mem_fflags_valid_q), .fflags_i(mem_fflags_q),
        .exception_valid_i(mem_exception_q), .exception_cause_i(mem_cause_q), .exception_tval_i(mem_tval_q), .request_permit_i(mem_request_permit),
        .lsu_busy_o(lsu_busy), .pmp_valid_o(mem_pmp_valid), .pmp_addr_o(mem_pmp_addr), .pmp_size_o(mem_pmp_size),
        .pmp_access_o(mem_pmp_access), .pmp_priv_m_o(mem_pmp_priv_m), .pmp_allow_i(mem_pmp_allow),
        .result_o(mem_result), .load_result_valid_o(), .fflags_valid_o(mem_fflags_valid), .fflags_o(mem_fflags),
        .exception_valid_o(mem_exception), .exception_cause_o(mem_cause), .exception_tval_o(mem_tval),
        .dmem_req_o(dmem_req_o), .dmem_we_o(dmem_we_o), .dmem_addr_o(dmem_addr_o), .dmem_wdata_o(dmem_wdata_o), .dmem_be_o(dmem_be_o),
        .dmem_gnt_i(dmem_gnt_i), .dmem_rvalid_i(dmem_rvalid_i), .dmem_rdata_i(dmem_rdata_i), .dmem_err_i(dmem_err_i)
    );
    uqu_stage_wb #(
        .ISA_E(ISA_E), .ISA_M(ISA_M), .ISA_C(ISA_C), .ISA_ZFINX(ISA_ZFINX), .ISA_F(ISA_F), .ISA_A(ISA_A),
        .ISA_UMODE(ISA_UMODE), .ISA_PMP(ISA_PMP), .XIF(XIF), .XIF_DUALWRITE(XIF_DUALWRITE), .DEBUG(DEBUG)
    ) u_wb (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(1'b0), .valid_i(wb_valid_q), .ready_o(), .valid_o(wb_complete), .ready_i(wb_ready),
        .kind_i(wb_kind_q), .result_i(wb_data_q), .rd_we_i(wb_rd_we_q), .rd_i(wb_rd_q), .pc_i(wb_pc_q), .instr_i(wb_original_q),
        .csr_addr_i(wb_csr_addr_q), .csr_op_i(wb_csr_op_q), .csr_src_i(wb_csr_src_q), .csr_src_zero_i(wb_csr_zero_q),
        .fflags_valid_i(wb_fflags_valid_q), .fflags_i(wb_fflags_q), .exception_valid_i(wb_exception_q),
        .exception_cause_i(wb_cause_q), .exception_tval_i(wb_tval_q), .priv_m_i(wb_valid_q ? wb_priv_m_q : priv_m_q),
        .hart_id_i(HART_ID), .irq_software_i(irq_software_i), .irq_timer_i(irq_timer_i), .irq_external_i(irq_external_i),
        .trap_i(trap_valid), .trap_pc_i(trap_pc), .trap_interrupt_i(trap_interrupt), .trap_cause_i(trap_cause), .trap_tval_i(trap_tval),
        .xif_id_i(wb_xif_id_q), .xif_kill_valid_i(xif_kill_valid), .xif_kill_id_i(xif_kill_id), .xif_kill_ready_o(xif_kill_ready),
        .xif_commit_valid_o(xif_commit_valid_o), .xif_commit_hartid_o(xif_commit_hartid_o), .xif_commit_id_o(xif_commit_id_o), .xif_commit_kill_o(xif_commit_kill_o),
        .xif_result_valid_i(xif_result_valid_i && xif_result_allowed), .xif_result_ready_o(xif_result_ready_o), .xif_result_hartid_i(xif_result_hartid_i),
        .xif_result_id_i(xif_result_id_i), .xif_result_data_i(xif_result_data_i), .xif_result_rd_i(xif_result_rd_i), .xif_result_we_i(xif_result_we_i),
        .debug_mode_i(1'b0), .debug_enter_i(1'b0), .debug_pc_i(32'd0), .debug_cause_i(3'd0),
        .debug_enter_o(), .debug_exception_o(), .debug_ebreak_o(), .dret_o(), .dcsr_o(), .dpc_o(),
        .retire_o(wb_retire), .exception_fire_o(wb_exception_fire), .mret_o(wb_mret),
        .exception_valid_o(wb_exception), .exception_cause_o(wb_cause), .exception_tval_o(wb_tval), .exception_pc_o(),
        .result_valid_o(wb_result_valid), .result_o(wb_result),
        .we0_o(wb_we0), .waddr0_o(wb_waddr0), .wdata0_o(wb_wdata0), .we1_o(wb_we1), .waddr1_o(wb_waddr1), .wdata1_o(wb_wdata1),
        .mstatus_o(mstatus), .mie_o(mie), .mip_o(mip), .mtvec_o(mtvec), .mepc_o(mepc), .pmpcfg_o(pmpcfg), .pmpaddr_o(pmpaddr), .frm_o(frm), .fflags_o()
    );
    uqu_pmp #(.ISA_PMP(ISA_PMP), .ISA_C(ISA_C), .MUA_BTB_IDATA_HWORDS(IDATA_HWORDS)) u_pmp (
        .replay_addr_i(replay_pmp_addr), .replay_priv_m_i(replay_pmp_priv_m), .replay_allow_o(replay_pmp_allow),
        .pmpcfg_i(pmpcfg), .pmpaddr_i(pmpaddr), .if_addr_i(if_pmp_addr), .if_size_i(if_pmp_size), .if_priv_m_i(if_pmp_priv_m), .if_allow_o(if_pmp_allow),
        .mem_addr_i(mem_pmp_addr), .mem_size_i(mem_pmp_size), .mem_access_i(mem_pmp_access), .mem_priv_m_i(mem_pmp_priv_m), .mem_allow_o(mem_pmp_allow)
    );

    // Architectural control state alone resets. WB-owned recovery never
    // flushes its own unit; its accepted token clears through wb_enable.
    always @(posedge clk_i) begin
        if (!rst_ni) begin
            priv_m_q <= 1'b1;
            resume_pc_q <= boot_addr_i;
            de_valid_q <= 1'b0;
            ex_valid_q <= 1'b0;
            mem_valid_q <= 1'b0;
            wb_valid_q <= 1'b0;
            ex_captured_q <= 3'd0;
        end else begin
            if (trap_valid || wb_exception_fire) priv_m_q <= 1'b1;
            else if (wb_mret) priv_m_q <= (ISA_UMODE == 0) || (mstatus[12:11] == 2'b11);
            if (redirect_valid) resume_pc_q <= redirect_addr;
            else if (wb_retire) resume_pc_q <= wb_next_pc_q;
            if (de_enable) de_valid_q <= de_next_valid;
            if (ex_enable) begin
                ex_valid_q <= ex_next_valid;
                ex_captured_q <= ex_next_valid ? de_captured : 3'd0;
            end else if (ex_valid_q) begin
                ex_captured_q <= ex_captured_q | (ex_rs_ready & ex_used_q);
            end
            if (mem_enable) mem_valid_q <= mem_next_valid;
            if (wb_enable) wb_valid_q <= wb_next_valid;
        end
    end
    always @(posedge clk_i) begin
        if (rst_ni && de_enable && de_next_valid) begin
            de_pc_q <= if_pc;
            if ((MUA_BRANCH_PREDICTOR != `UQU_BP_NONE) && (MUA_BTB != `UQU_BTB_NONE))
                de_predicted_next_pc_q <= if_predicted_next_pc;
            de_instr_q <= if_instr;
            de_original_q <= if_original;
            de_compressed_q <= if_compressed;
            de_priv_m_q <= priv_m_q;
            de_exception_q <= if_exception;
            de_cause_q <= if_cause;
            de_tval_q <= if_tval;
        end
        if (rst_ni && ex_enable && ex_next_valid) begin
            ex_pc_q <= de_pc_q;
            ex_original_q <= de_original_q;
            ex_compressed_q <= de_compressed_q;
            ex_priv_m_q <= de_priv_m_q;
            ex_next_pc_q <= de_next_pc;
            ex_serialize_q <= de_serialize;
            ex_system_q <= de_system;
            ex_kind_q <= de_kind;
            ex_rd_q <= de_rd;
            ex_rd1_q <= de_rd1;
            ex_xif_id_q <= xif_de_id;
            ex_rd_we_q <= de_rd_we;
            ex_pending_q <= de_pending;
            ex_fu_q <= de_fu;
            ex_op_q <= de_op;
            ex_a_sel_q <= de_a_sel;
            ex_b_sel_q <= de_b_sel;
            ex_imm_q <= de_imm;
            ex_pass_q <= de_pass;
            ex_rm_q <= de_rm;
            ex_lsu_q <= de_lsu;
            ex_mem_we_q <= de_mem_we;
            ex_mem_op_q <= de_mem_op;
            ex_csr_addr_q <= de_csr_addr;
            ex_csr_op_q <= de_csr_op;
            ex_csr_src_q <= de_csr_src;
            ex_csr_zero_q <= de_csr_zero;
            ex_exception_q <= de_exception;
            ex_cause_q <= de_cause;
            ex_tval_q <= de_tval;
            ex_used_q <= de_ex_used;
        end
        if (rst_ni && mem_enable && mem_next_valid) begin
            mem_pc_q <= ex_pc_q;
            mem_original_q <= ex_original_q;
            mem_compressed_q <= ex_compressed_q;
            mem_priv_m_q <= ex_priv_m_q;
            mem_next_pc_q <= ex_next_pc_q;
            mem_serialize_q <= ex_serialize_q;
            mem_system_q <= ex_system_q;
            mem_kind_q <= ex_kind_q;
            mem_rd_q <= ex_rd_q;
            mem_rd1_q <= ex_rd1_q;
            mem_xif_id_q <= ex_xif_id_q;
            mem_rd_we_q <= ex_rd_we_q;
            mem_pending_q <= ex_pending_q;
            mem_data_q <= ex_result;
            mem_store_data_q <= ex_store_data;
            mem_lsu_q <= ex_lsu_q;
            mem_we_q <= ex_mem_we_q;
            mem_op_q <= ex_mem_op_q;
            mem_csr_addr_q <= ex_csr_addr_q;
            mem_csr_op_q <= ex_csr_op_q;
            mem_csr_src_q <= ex_csr_src_q;
            mem_csr_zero_q <= ex_csr_zero_q;
            mem_fflags_valid_q <= ex_fflags_valid;
            mem_fflags_q <= ex_fflags;
            mem_exception_q <= ex_exception;
            mem_cause_q <= ex_cause;
            mem_tval_q <= ex_tval;
        end
        if (rst_ni && wb_enable && wb_next_valid) begin
            wb_pc_q <= mem_pc_q;
            wb_original_q <= mem_original_q;
            wb_compressed_q <= mem_compressed_q;
            wb_priv_m_q <= mem_priv_m_q;
            wb_next_pc_q <= mem_next_pc_q;
            wb_serialize_q <= mem_serialize_q;
            wb_system_q <= mem_system_q;
            wb_kind_q <= mem_kind_q;
            wb_rd_q <= mem_rd_q;
            wb_rd1_q <= mem_rd1_q;
            wb_xif_id_q <= mem_xif_id_q;
            wb_rd_we_q <= mem_rd_we_q;
            wb_pending_q <= mem_pending_q;
            wb_data_q <= mem_result;
            wb_csr_addr_q <= mem_csr_addr_q;
            wb_csr_op_q <= mem_csr_op_q;
            wb_csr_src_q <= mem_csr_src_q;
            wb_csr_zero_q <= mem_csr_zero_q;
            wb_fflags_valid_q <= mem_fflags_valid;
            wb_fflags_q <= mem_fflags;
            wb_exception_q <= mem_exception;
            wb_cause_q <= mem_cause;
            wb_tval_q <= mem_tval;
        end
    end
    genvar source_idx;
    generate
        for (source_idx = 0; source_idx < 3; source_idx = source_idx + 1) begin : gen_ex_source
            always @(posedge clk_i) begin
                if (rst_ni && !ex_flush) begin
                    if (ex_enable && ex_next_valid) begin
                        ex_rs_addr_q[source_idx] <= de_rs_addr[source_idx];
                        ex_rs_data_q[source_idx] <= de_rs[source_idx];
                    end else if (ex_valid_q && !ex_fire && ex_used_q[source_idx] &&
                                 !ex_captured_q[source_idx] && ex_rs_ready[source_idx]) begin
                        ex_rs_data_q[source_idx] <= ex_rs[source_idx];
                    end
                end
            end
        end
        // Reserved features still require their backend or core integration.
        if ((ISA_F != 0) || (ISA_A != 0) ||
            (DEBUG != 0) || (MUA_HARDENED != 0)) begin : gen_unsupported
            uqu_core_unsupported_feature invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
