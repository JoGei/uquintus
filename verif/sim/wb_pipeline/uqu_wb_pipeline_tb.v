`default_nettype none
`include "uqu_config.vh"

// Verification parent owns MEM/WB, the GPR file, and a minimal privilege stub.
// This is not a pipeline-wide event arbiter or redirect implementation.
module uqu_wb_pipeline_tb #(
    parameter ISA_E = 0,
    parameter ISA_M = 0,
    parameter ISA_C = 0,
    parameter ISA_ZFINX = 0,
    parameter ISA_F = 0,
    parameter ISA_A = 0,
    parameter ISA_UMODE = 1,
    parameter ISA_PMP = 0,
    parameter XIF = 0,
    parameter DEBUG = 0,
    parameter XIF_NUM_RS = 3,
    parameter XIF_DUALWRITE = 0,
    parameter MUA_REGFILE_IMPL = `UQU_RF_FF
) (
    input wire clk_i,
    input wire rst_ni,
    input wire flush_i,
    input wire in_valid_i,
    input wire commit_ready_i,
    output wire in_ready_o,
    input wire [1:0] in_kind_i,
    input wire [31:0] in_result_i,
    input wire in_rd_we_i,
    input wire [4:0] in_rd_i,
    input wire [31:0] in_pc_i,
    input wire [31:0] in_instr_i,
    input wire [11:0] in_csr_addr_i,
    input wire [2:0] in_csr_op_i,
    input wire [31:0] in_csr_src_i,
    input wire in_csr_src_zero_i,
    input wire in_fflags_valid_i,
    input wire [4:0] in_fflags_i,
    input wire in_exception_valid_i,
    input wire [4:0] in_exception_cause_i,
    input wire [31:0] in_exception_tval_i,
    input wire [31:0] hart_id_i,
    input wire irq_software_i,
    input wire irq_timer_i,
    input wire irq_external_i,
    input wire trap_i,
    input wire [31:0] trap_pc_i,
    input wire trap_interrupt_i,
    input wire [4:0] trap_cause_i,
    input wire [31:0] trap_tval_i,
    output wire wb_valid_o,
    output wire wb_ready_o,
    output wire priv_m_o,
    output wire retire_o,
    output wire exception_fire_o,
    output wire mret_o,
    output wire exception_valid_o,
    output wire [4:0] exception_cause_o,
    output wire [31:0] exception_tval_o,
    output wire [31:0] exception_pc_o,
    output wire result_valid_o,
    output wire [31:0] result_o,
    output wire we0_o,
    output wire [4:0] waddr0_o,
    output wire [31:0] wdata0_o,
    output wire we1_o,
    output wire [4:0] waddr1_o,
    output wire [31:0] wdata1_o,
    output wire [31:0] mstatus_o,
    output wire [31:0] mie_o,
    output wire [31:0] mip_o,
    output wire [31:0] mtvec_o,
    output wire [31:0] mepc_o,
    output wire [127:0] pmpcfg_o,
    output wire [511:0] pmpaddr_o,
    output wire [2:0] frm_o,
    output wire [4:0] fflags_o,
    input wire [4:0] raddr0_i,
    input wire [4:0] raddr1_i,
    output wire [31:0] rdata0_o,
    output wire [31:0] rdata1_o
);
    reg memwb_valid_q;
    reg priv_m_q;
    reg [1:0] memwb_kind_q;
    reg [31:0] memwb_result_q;
    reg memwb_rd_we_q;
    reg [4:0] memwb_rd_q;
    reg [31:0] memwb_pc_q;
    reg [31:0] memwb_instr_q;
    reg [11:0] memwb_csr_addr_q;
    reg [2:0] memwb_csr_op_q;
    reg [31:0] memwb_csr_src_q;
    reg memwb_csr_src_zero_q;
    reg memwb_fflags_valid_q;
    reg [4:0] memwb_fflags_q;
    reg memwb_exception_valid_q;
    reg [4:0] memwb_exception_cause_q;
    reg [31:0] memwb_exception_tval_q;
    wire redirect = exception_fire_o || mret_o;
    assign priv_m_o = priv_m_q;
    assign in_ready_o = rst_ni && !flush_i && !trap_i && !redirect && wb_ready_o;

    always @(posedge clk_i) begin
        if (!rst_ni || flush_i || trap_i || redirect) begin
            memwb_valid_q <= 1'b0;
        end else if (wb_ready_o) begin
            memwb_valid_q <= in_valid_i;
            if (in_valid_i) begin
                memwb_kind_q <= in_kind_i;
                memwb_result_q <= in_result_i;
                memwb_rd_we_q <= in_rd_we_i;
                memwb_rd_q <= in_rd_i;
                memwb_pc_q <= in_pc_i;
                memwb_instr_q <= in_instr_i;
                memwb_csr_addr_q <= in_csr_addr_i;
                memwb_csr_op_q <= in_csr_op_i;
                memwb_csr_src_q <= in_csr_src_i;
                memwb_csr_src_zero_q <= in_csr_src_zero_i;
                memwb_fflags_valid_q <= in_fflags_valid_i;
                memwb_fflags_q <= in_fflags_i;
                memwb_exception_valid_q <= in_exception_valid_i;
                memwb_exception_cause_q <= in_exception_cause_i;
                memwb_exception_tval_q <= in_exception_tval_i;
            end
        end
        if (!rst_ni) begin
            priv_m_q <= 1'b1;
        end else if (trap_i || exception_fire_o) begin
            priv_m_q <= 1'b1;
        end else if (mret_o) begin
            priv_m_q <= (mstatus_o[12:11] == 2'b11);
        end
    end

    uqu_stage_wb #(
        .ISA_E(ISA_E),
        .ISA_M(ISA_M),
        .ISA_C(ISA_C),
        .ISA_ZFINX(ISA_ZFINX),
        .ISA_F(ISA_F),
        .ISA_A(ISA_A),
        .ISA_UMODE(ISA_UMODE),
        .ISA_PMP(ISA_PMP),
        .XIF(XIF),
        .DEBUG(DEBUG)
    ) u_wb (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i),
        .valid_i(memwb_valid_q), .ready_o(wb_ready_o), .valid_o(wb_valid_o), .ready_i(commit_ready_i),
        .priv_m_i(priv_m_q),
        .kind_i(memwb_kind_q),
        .result_i(memwb_result_q),
        .rd_we_i(memwb_rd_we_q),
        .rd_i(memwb_rd_q),
        .pc_i(memwb_pc_q),
        .instr_i(memwb_instr_q),
        .csr_addr_i(memwb_csr_addr_q),
        .csr_op_i(memwb_csr_op_q),
        .csr_src_i(memwb_csr_src_q),
        .csr_src_zero_i(memwb_csr_src_zero_q),
        .fflags_valid_i(memwb_fflags_valid_q),
        .fflags_i(memwb_fflags_q),
        .exception_valid_i(memwb_exception_valid_q),
        .exception_cause_i(memwb_exception_cause_q),
        .exception_tval_i(memwb_exception_tval_q),
        .hart_id_i(hart_id_i),
        .irq_software_i(irq_software_i),
        .irq_timer_i(irq_timer_i),
        .irq_external_i(irq_external_i),
        .trap_i(trap_i),
        .trap_pc_i(trap_pc_i),
        .trap_interrupt_i(trap_interrupt_i),
        .trap_cause_i(trap_cause_i),
        .trap_tval_i(trap_tval_i),
        .retire_o(retire_o),
        .exception_fire_o(exception_fire_o),
        .mret_o(mret_o),
        .exception_valid_o(exception_valid_o),
        .exception_cause_o(exception_cause_o),
        .exception_tval_o(exception_tval_o),
        .exception_pc_o(exception_pc_o),
        .result_valid_o(result_valid_o),
        .result_o(result_o),
        .we0_o(we0_o),
        .waddr0_o(waddr0_o),
        .wdata0_o(wdata0_o),
        .we1_o(we1_o),
        .waddr1_o(waddr1_o),
        .wdata1_o(wdata1_o),
        .mstatus_o(mstatus_o),
        .mie_o(mie_o),
        .mip_o(mip_o),
        .mtvec_o(mtvec_o),
        .mepc_o(mepc_o),
        .pmpcfg_o(pmpcfg_o),
        .pmpaddr_o(pmpaddr_o),
        .frm_o(frm_o),
        .fflags_o(fflags_o)
    );

    uqu_gpregfile #(
        .ISA_E(ISA_E), .ISA_ZFINX(ISA_ZFINX), .XIF(XIF),
        .XIF_NUM_RS(XIF_NUM_RS), .XIF_DUALWRITE(XIF_DUALWRITE), .MUA_REGFILE_IMPL(MUA_REGFILE_IMPL)
    ) u_gpregfile (
        .clk_i(clk_i), .rst_ni(rst_ni), .raddr0_i(raddr0_i), .raddr1_i(raddr1_i),
        .raddr2_i(5'd0), .rdata0_o(rdata0_o), .rdata1_o(rdata1_o), .rdata2_o(),
        .we0_i(we0_o), .waddr0_i(waddr0_o), .wdata0_i(wdata0_o),
        .we1_i(we1_o), .waddr1_i(waddr1_o), .wdata1_i(wdata1_o)
    );
endmodule

`default_nettype wire
