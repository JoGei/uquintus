`default_nettype none

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
    parameter DEBUG = 0
) (
    input  wire         clk_i,
    input  wire         rst_ni,
    input  wire         flush_i,
    input  wire         valid_i,
    output wire         ready_o,
    output wire         valid_o,
    input  wire         ready_i,
    input  wire [1:0]   kind_i,
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
    localparam [1:0] KIND_RESULT = 2'd0;
    localparam [1:0] KIND_CSR = 2'd1;
    localparam [1:0] KIND_MRET = 2'd2;
    localparam [1:0] KIND_XIF = 2'd3;
    localparam [4:0] CAUSE_ILLEGAL_INSTRUCTION = 5'd2;

    wire enabled = rst_ni && !flush_i;
    wire active = enabled && valid_i;
    wire destination_used = ((kind_i == KIND_RESULT) && rd_we_i) || (kind_i == KIND_CSR);
    wire illegal_control = (kind_i == KIND_XIF) ||
        ((kind_i == KIND_MRET) && !priv_m_i) ||
        ((ISA_E == 1) && destination_used && rd_i[4]) ||
        (fflags_valid_i && ((ISA_ZFINX == 0) || (kind_i != KIND_RESULT)));
    wire csr_query = active && (kind_i == KIND_CSR) && !exception_valid_i && !illegal_control;
    wire [31:0] csr_rdata;
    wire csr_exception;
    wire [4:0] csr_cause;
    wire [31:0] csr_tval;
    wire fault = exception_valid_i || illegal_control || csr_exception;
    wire wb_fire = valid_o && ready_i;
    wire destination_nonzero = destination_used && (rd_i != 5'd0);
    wire [31:0] selected_result = (kind_i == KIND_CSR) ? csr_rdata : result_i;
    wire accepted_trap = rst_ni && trap_i;
    wire csr_trap = accepted_trap || exception_fire_o;

    // ready_i accepts this token's retirement OR synchronous fault entry. The
    // parent must consume/clear MEM/WB on fire, never repeatedly acknowledge it.
    assign valid_o = active && !trap_i;
    assign ready_o = enabled && !trap_i && (!valid_i || ready_i);
    assign retire_o = wb_fire && !fault;
    assign exception_fire_o = wb_fire && fault;
    assign mret_o = retire_o && (kind_i == KIND_MRET);

    // Reports are independent of readiness/accepted external trap, so the
    // controller may inspect faults without a combinational arbitration loop.
    assign exception_valid_o = active && fault;
    assign exception_cause_o = !exception_valid_o ? 5'd0 :
        exception_valid_i ? exception_cause_i : illegal_control ? CAUSE_ILLEGAL_INSTRUCTION : csr_cause;
    assign exception_tval_o = !exception_valid_o ? 32'd0 :
        exception_valid_i ? exception_tval_i : illegal_control ? instr_i : csr_tval;
    assign exception_pc_o = exception_valid_o ? pc_i : 32'd0;

    // CSR reads reflect the actual commit edge (counters may keep changing
    // while held). Publish such results for forwarding only upon retirement.
    assign result_valid_o = valid_o && !fault && destination_nonzero &&
                            ((kind_i != KIND_CSR) || retire_o);
    assign result_o = result_valid_o ? selected_result : 32'd0;
    assign we0_o = retire_o && destination_nonzero;
    assign waddr0_o = we0_o ? rd_i : 5'd0;
    assign wdata0_o = we0_o ? selected_result : 32'd0;
    assign we1_o = 1'b0;
    assign waddr1_o = 5'd0;
    assign wdata1_o = 32'd0;

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
        .fp_flags_valid_i(retire_o && (kind_i == KIND_RESULT) && fflags_valid_i),
        .fp_flags_i(fflags_i), .csr_read_o(), .csr_write_o(), .csr_rdata_o(csr_rdata),
        .csr_exception_valid_o(csr_exception), .csr_exception_cause_o(csr_cause),
        .csr_exception_tval_o(csr_tval), .mstatus_o(mstatus_o), .mie_o(mie_o), .mip_o(mip_o),
        .mtvec_o(mtvec_o), .mepc_o(mepc_o), .pmpcfg_o(pmpcfg_o), .pmpaddr_o(pmpaddr_o),
        .frm_o(frm_o), .fflags_o(fflags_o)
    );

    generate
        if (XIF != 0) begin : GEN_NO_XIF_IMPLEMENTATION
            uqu_stage_wb_xif_not_implemented unsupported_xif ();
        end
    endgenerate
endmodule

`default_nettype wire
