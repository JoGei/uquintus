`default_nettype none
`include "uqu_ctrl.vh"

// WB commit/control and CSR state. The parent owns MEM/WB, the GPR file,
// current privilege, serialization, event arbitration, and redirects.
module uqu_stage_wb #(
    parameter ISA_E = 0,
    parameter ISA_M = 0,
    parameter ISA_C = 0,
    parameter ISA_ZFINX = 0,
    parameter ISA_F = 0,
    parameter ISA_A = 0,
    parameter ISA_UMODE = 1,
    parameter ISA_PMP = 0,
    parameter XIF = 0,
    parameter XIF_DUALWRITE = 0,
    parameter DEBUG = 0
) (
    input  wire         clk_i,
    input  wire         rst_ni,
    input  wire         flush_i,
    input  wire         valid_i,
    output wire         ready_o,
    output wire         valid_o,
    input  wire         ready_i,
    input  wire         lsu_i,
    input  wire         lsu_res_valid_i,
    input  wire         lsu_res_registered_i,
    input  wire [31:0]  lsu_res_data_i,
    input  wire [31:0]  lsu_res_forward_data_i,
    input  wire         lsu_res_exception_valid_i,
    input  wire [4:0]   lsu_res_exception_cause_i,
    input  wire [31:0]  lsu_res_exception_tval_i,
    output wire         lsu_res_ready_o,
    input  wire [2:0]   kind_i,
    input  wire [31:0]  result_i,
    input  wire         rd_we_i,
    input  wire [4:0]   rd_i,
    input  wire [31:0]  pc_i,
    input  wire [31:0]  instr_i,
    input  wire [11:0]  csr_addr_i,
    input  wire [2:0]   csr_op_i,
    input  wire [31:0]  csr_src_i,
    input  wire         csr_src_zero_i,
    input  wire         fflags_valid_i,
    input  wire [4:0]   fflags_i,
    input  wire         exception_valid_i,
    input  wire [4:0]   exception_cause_i,
    input  wire [31:0]  exception_tval_i,
    input  wire         priv_m_i,
    input  wire [31:0]  hart_id_i,
    input  wire         irq_software_i,
    input  wire         irq_timer_i,
    input  wire         irq_external_i,
    input  wire         trap_i,
    input  wire [31:0]  trap_pc_i,
    input  wire         trap_interrupt_i,
    input  wire [4:0]   trap_cause_i,
    input  wire [31:0]  trap_tval_i,
    // Pipeline ID and younger kill arbitration are core-internal metadata.
    input  wire [2:0]   xif_id_i,
    input  wire         xif_kill_valid_i,
    input  wire [2:0]   xif_kill_id_i,
    output wire        xif_kill_ready_o,
    // Kill IDs cover that instruction and all newer offloads of this hart.
    // The parent blocks surviving issue on a kill edge and clears affected slots.
    // Flattened, unmodified CV-X-IF v1.0.0 commit/result packet fields.
    output wire        xif_commit_valid_o,
    output wire [31:0] xif_commit_hartid_o,
    output wire [2:0]  xif_commit_id_o,
    output wire        xif_commit_kill_o,
    input  wire        xif_result_valid_i,
    output wire        xif_result_ready_o,
    input  wire [31:0] xif_result_hartid_i,
    input  wire [2:0]  xif_result_id_i,
    input  wire [32*(1+XIF_DUALWRITE)-1:0] xif_result_data_i,
    input  wire [4:0]  xif_result_rd_i,
    input  wire [XIF_DUALWRITE:0] xif_result_we_i,
    // Already-arbitrated debug entry; parent owns Debug Mode and redirects.
    input  wire         debug_mode_i,
    input  wire         debug_enter_i,
    input  wire [31:0]  debug_pc_i,
    input  wire [2:0]   debug_cause_i,
    output wire         debug_enter_o,
    output wire         debug_exception_o,
    output wire         debug_ebreak_o,
    output wire         dret_o,
    output wire [31:0]  dcsr_o,
    output wire [31:0]  dpc_o,
    output wire         retire_o,
    output wire         exception_fire_o,
    output wire         mret_o,
    output wire         exception_valid_o,
    output wire [4:0]   exception_cause_o,
    output wire [31:0]  exception_tval_o,
    output wire [31:0]  exception_pc_o,
    output wire         result_valid_o,
    output wire [31:0]  result_o,
    output wire         we0_o,
    output wire [4:0]   waddr0_o,
    output wire [31:0]  wdata0_o,
    output wire         we1_o,
    output wire [4:0]   waddr1_o,
    output wire [31:0]  wdata1_o,
    output wire [31:0]  mstatus_o,
    output wire [31:0]  mie_o,
    output wire [31:0]  mip_o,
    output wire [31:0]  mtvec_o,
    output wire [31:0]  mepc_o,
    output wire [127:0] pmpcfg_o,
    output wire [511:0] pmpaddr_o,
    output wire [2:0]   frm_o,
    output wire [4:0]   fflags_o
);
    localparam [2:0] KIND_RESULT = `UQU_WB_RESULT;
    localparam [2:0] KIND_CSR = `UQU_WB_CSR;
    localparam [2:0] KIND_MRET = `UQU_WB_MRET;
    localparam [2:0] KIND_XIF = `UQU_WB_XIF;
    localparam [2:0] KIND_DRET = `UQU_WB_DRET;
    localparam [2:0] KIND_EBREAK = `UQU_WB_EBREAK;
    localparam [4:0] CAUSE_ILLEGAL_INSTRUCTION = 5'd2;

    wire debug_mode = (DEBUG == 1) && debug_mode_i;
    wire external_debug = rst_ni && (DEBUG == 1) && debug_enter_i && !debug_mode;
    wire enabled = rst_ni && !flush_i;
    wire active = enabled && valid_i;
    wire is_xif = (XIF == 1) && (kind_i == KIND_XIF);
    wire debug_break = (DEBUG == 1) && (kind_i == KIND_EBREAK) &&
                       (debug_mode || (priv_m_i ? dcsr_o[15] : dcsr_o[12]));
    wire destination_used = ((kind_i == KIND_RESULT) && rd_we_i) || (kind_i == KIND_CSR);
    wire illegal_control = ((kind_i == KIND_XIF) && (XIF == 0)) ||
        ((kind_i == KIND_MRET) && (!priv_m_i || debug_mode)) ||
        ((kind_i == KIND_DRET) && !debug_mode) || (kind_i > KIND_EBREAK) ||
        ((ISA_E == 1) && destination_used && rd_i[4]) ||
        (fflags_valid_i && ((ISA_ZFINX == 0) || (kind_i != KIND_RESULT)));
    wire csr_query = active && (kind_i == KIND_CSR) && !exception_valid_i && !illegal_control;
    wire [31:0] csr_rdata;
    wire csr_exception;
    wire [4:0] csr_cause;
    wire [31:0] csr_tval;
    wire memory_fault = lsu_i && lsu_res_valid_i && lsu_res_exception_valid_i;
    wire fault = memory_fault || exception_valid_i || illegal_control || csr_exception ||
                 ((kind_i == KIND_EBREAK) && !debug_break);
    wire accepted_trap = rst_ni && trap_i && !debug_mode && !external_debug;
    wire blocked_event = accepted_trap || external_debug;
    wire wb_fire = valid_o && ready_i;
    wire local_debug = wb_fire && debug_break && !fault;
    wire csr_trap = accepted_trap || exception_fire_o;
    wire xif_committed;
    wire xif_commit_sent;
    wire xif_pair;
    wire xif_result_match = xif_result_valid_i && (xif_result_id_i == xif_id_i) &&
                           (xif_result_hartid_i == hart_id_i);
    // Malformed result packets are protocol violations, never CPU exceptions.
    // Never retire them or silently update an unrelated register. Readiness
    // cannot depend on packet contents; invalid packets may handshake/discard.
    wire xif_packet_ok = (!xif_pair || xif_result_we_i[0]) && (!xif_result_we_i[0] ||
                        ((xif_result_rd_i == rd_i) &&
                         ((ISA_E == 0) || !xif_result_rd_i[4]) &&
                         (!xif_pair || !xif_result_rd_i[0])));
    wire completion = (!lsu_i || lsu_res_valid_i) &&
                      (!is_xif || fault ||
                       (xif_committed && xif_result_match && xif_packet_ok));
    wire destination_nonzero = is_xif ?
        (xif_result_we_i[0] && (xif_result_rd_i != 5'd0)) :
        (destination_used && (rd_i != 5'd0));
    wire [4:0] selected_rd = is_xif ? xif_result_rd_i : rd_i;
    wire [31:0] selected_result = is_xif ? xif_result_data_i[31:0] :
                                 (kind_i == KIND_CSR) ? csr_rdata : lsu_i ? lsu_res_data_i : result_i;
    wire wb_notify = (XIF == 1) && rst_ni && valid_i && is_xif && !xif_commit_sent &&
                     (flush_i || (!blocked_event && (!fault || ready_i)));
    wire wb_kill = flush_i || fault;

    // Commit has implicit ready. It must precede (or coincide with) results,
    // independently of controller retirement readiness and result validity.
    assign xif_commit_valid_o = (XIF == 1) && rst_ni &&
                               (wb_notify || xif_kill_valid_i);
    assign xif_commit_hartid_o = xif_commit_valid_o ? hart_id_i : 32'd0;
    assign xif_commit_id_o = !xif_commit_valid_o ? 3'd0 :
                            wb_notify ? xif_id_i : xif_kill_id_i;
    assign xif_commit_kill_o = xif_commit_valid_o && (wb_notify ? wb_kill : 1'b1);
    assign xif_kill_ready_o = (XIF == 1) && rst_ni && !wb_notify;
    // CV-X-IF forbids combinational result-input -> interface-output paths.
    // Advertise capacity before the coprocessor presents a valid packet. The
    // parent must likewise supply ready_i independently of incoming results.
    assign xif_result_ready_o = active && is_xif && !fault && !blocked_event &&
                                xif_committed && ready_i;

    assign lsu_res_ready_o = active && lsu_i && !blocked_event && ready_i;

    assign valid_o = active && !blocked_event && completion;
    assign ready_o = enabled && !blocked_event && (!valid_i || (valid_o && ready_i));
    assign retire_o = wb_fire && !fault && !debug_break;
    assign exception_fire_o = wb_fire && fault && !debug_mode;
    assign debug_exception_o = wb_fire && fault && debug_mode;
    assign debug_ebreak_o = local_debug && debug_mode;
    assign debug_enter_o = external_debug || (local_debug && !debug_mode);
    assign mret_o = retire_o && (kind_i == KIND_MRET);
    assign dret_o = retire_o && (kind_i == KIND_DRET);

    // Reports are independent of readiness/accepted external events.
    assign exception_valid_o = active && fault;
    assign exception_cause_o = !exception_valid_o ? 5'd0 :
        exception_valid_i ? exception_cause_i : illegal_control ? CAUSE_ILLEGAL_INSTRUCTION :
        memory_fault ? lsu_res_exception_cause_i :
        (kind_i == KIND_EBREAK) ? 5'd3 : csr_cause;
    assign exception_tval_o = !exception_valid_o ? 32'd0 :
        exception_valid_i ? exception_tval_i : illegal_control ? instr_i :
        memory_fault ? lsu_res_exception_tval_i :
        (kind_i == KIND_EBREAK) ? 32'd0 : csr_tval;
    assign exception_pc_o = exception_valid_o ? pc_i : 32'd0;
    assign result_valid_o = valid_o && !fault && destination_nonzero &&
                            ((kind_i != KIND_CSR) || retire_o) &&
                            (!lsu_i || lsu_res_registered_i);
    // Forwarding candidate is separate from the live response used to write
    // the GPR file at retirement. Availability/faults qualify result_valid_o.
    assign result_o = is_xif ? xif_result_data_i[31:0] :
        (kind_i == KIND_CSR) ? csr_rdata : lsu_i ? lsu_res_forward_data_i : result_i;
    assign we0_o = retire_o && destination_nonzero;
    assign waddr0_o = we0_o ? selected_rd : 5'd0;
    assign wdata0_o = we0_o ? selected_result : 32'd0;

    generate
        if (XIF == 1) begin : GEN_XIF
            reg committed_q;
            assign xif_commit_sent = committed_q;
            assign xif_committed = committed_q || (wb_notify && !wb_kill);
            always @(posedge clk_i) begin
                if (!rst_ni || flush_i || wb_fire) committed_q <= 1'b0;
                else if (wb_notify && !wb_kill) committed_q <= 1'b1;
            end
        end else begin : GEN_NO_XIF
            assign xif_committed = 1'b0;
            assign xif_commit_sent = 1'b0;
        end
        if ((XIF == 1) && (XIF_DUALWRITE == 1)) begin : GEN_DUALWRITE
            assign xif_pair = xif_result_we_i[1];
            assign we1_o = we0_o && is_xif && xif_pair;
            assign waddr1_o = we1_o ? (selected_rd + 5'd1) : 5'd0;
            assign wdata1_o = we1_o ? xif_result_data_i[63:32] : 32'd0;
        end else begin : GEN_NO_DUALWRITE
            assign xif_pair = 1'b0;
            assign we1_o = 1'b0;
            assign waddr1_o = 5'd0;
            assign wdata1_o = 32'd0;
        end
        if (((XIF != 0) && (XIF != 1)) ||
            ((XIF_DUALWRITE != 0) && (XIF_DUALWRITE != 1))) begin : GEN_UNSUPPORTED
            uqu_stage_wb_unsupported_configuration invalid_configuration ();
        end
    endgenerate

    uqu_csregfile #(
        .ISA_E(ISA_E), .ISA_M(ISA_M), .ISA_C(ISA_C), .ISA_ZFINX(ISA_ZFINX),
        .ISA_F(ISA_F), .ISA_A(ISA_A), .ISA_UMODE(ISA_UMODE), .ISA_PMP(ISA_PMP), .DEBUG(DEBUG)
    ) u_csregfile (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i),
        .csr_valid_i(csr_query), .csr_commit_i(retire_o && (kind_i == KIND_CSR)),
        .csr_addr_i(csr_addr_i), .csr_op_i(csr_op_i), .csr_src_i(csr_src_i),
        .csr_src_zero_i(csr_src_zero_i), .csr_rd_zero_i(rd_i == 5'd0), .csr_instr_i(instr_i),
        .priv_m_i(priv_m_i), .hart_id_i(hart_id_i), .irq_software_i(irq_software_i),
        .irq_timer_i(irq_timer_i), .irq_external_i(irq_external_i), .retire_i(retire_o),
        .trap_i(csr_trap), .trap_pc_i(accepted_trap ? trap_pc_i : pc_i),
        .trap_interrupt_i(accepted_trap && trap_interrupt_i),
        .trap_cause_i(accepted_trap ? trap_cause_i : exception_cause_o),
        .trap_tval_i(accepted_trap ? trap_tval_i : exception_tval_o), .mret_i(mret_o),
        .debug_mode_i(debug_mode), .debug_enter_i(debug_enter_o),
        .debug_pc_i(external_debug ? debug_pc_i : pc_i),
        .debug_cause_i(external_debug ? debug_cause_i : 3'd1),
        .debug_ebreak_i(local_debug && !debug_mode), .dret_i(dret_o),
        .dcsr_o(dcsr_o), .dpc_o(dpc_o),
        .fp_flags_valid_i(retire_o && (kind_i == KIND_RESULT) && fflags_valid_i),
        .fp_flags_i(fflags_i), .csr_read_o(), .csr_write_o(), .csr_rdata_o(csr_rdata),
        .csr_exception_valid_o(csr_exception), .csr_exception_cause_o(csr_cause),
        .csr_exception_tval_o(csr_tval), .mstatus_o(mstatus_o), .mie_o(mie_o), .mip_o(mip_o),
        .mtvec_o(mtvec_o), .mepc_o(mepc_o), .pmpcfg_o(pmpcfg_o), .pmpaddr_o(pmpaddr_o),
        .frm_o(frm_o), .fflags_o(fflags_o)
    );

endmodule

`default_nettype wire
