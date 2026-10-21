`default_nettype none
`include "uqu_config.vh"
`include "uqu_rvfi_csrs.vh"

// Verification-only wrapper; hierarchical observation is confined here.
module uqu_core_tb #(
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
    parameter MUA_REGFILE_IMPL = `UQU_RF_FF,
    parameter MUA_IF_BUFFER_WORDS = 2,
    parameter MUA_HARDENED = 0,
    parameter MUA_MUL = `UQU_MUL_ITERATIVE,
    parameter MUA_DIV = `UQU_DIV_ITERATIVE,
    parameter MUA_MULDIV_ITERUNROLL = 8,
    parameter XIF = 0,
    parameter XIF_NUM_RS = 3,
    parameter XIF_DUALWRITE = 0,
    parameter DEBUG = 0
) (
    input wire clk_i,
    input wire rst_ni,
    input wire [31:0] boot_addr_i,
    input wire [31:0] hart_id_i,
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
    // Retained standard issue/register/commit/result declarations. Native
    // bring-up requires XIF=0; the stages provide deterministic inactive pins.
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
    input wire [XIF_DUALWRITE:0] xif_result_we_i,
    output reg rvfi_valid,
    output reg [63:0] rvfi_order,
    output reg [31:0] rvfi_insn,
    output reg rvfi_trap,
    output reg rvfi_halt,
    output reg rvfi_intr,
    output reg [1:0] rvfi_mode,
    output reg [1:0] rvfi_ixl,
    output reg [4:0] rvfi_rs1_addr,
    output reg [4:0] rvfi_rs2_addr,
    output reg [31:0] rvfi_rs1_rdata,
    output reg [31:0] rvfi_rs2_rdata,
    output reg [4:0] rvfi_rd_addr,
    output reg [31:0] rvfi_rd_wdata,
    output reg [31:0] rvfi_pc_rdata,
    output reg [31:0] rvfi_pc_wdata,
    output reg [31:0] rvfi_mem_addr,
    output reg [3:0] rvfi_mem_rmask,
    output reg [3:0] rvfi_mem_wmask,
    output reg [31:0] rvfi_mem_rdata,
    output reg [31:0] rvfi_mem_wdata,
    output reg rvfi_mem_fault,
    output reg [3:0] rvfi_mem_fault_rmask,
    output reg [3:0] rvfi_mem_fault_wmask
    `define UQU_RVFI_CSR(NAME, WIDTH, INDEX, LO, HI, ULO, UHI) `UQU_RVFI_CSR_OUTPUT(NAME, WIDTH, INDEX, LO, HI, ULO, UHI)
    `include "uqu_rvfi_csr_list.vh"
    `undef UQU_RVFI_CSR
);

    wire raw_rvfi_valid;
    wire [63:0] raw_rvfi_order;
    wire [31:0] raw_rvfi_insn;
    wire raw_rvfi_trap;
    wire raw_rvfi_halt;
    wire raw_rvfi_intr;
    wire [1:0] raw_rvfi_mode;
    wire [1:0] raw_rvfi_ixl;
    wire [4:0] raw_rvfi_rs1_addr;
    wire [4:0] raw_rvfi_rs2_addr;
    wire [31:0] raw_rvfi_rs1_rdata;
    wire [31:0] raw_rvfi_rs2_rdata;
    wire [4:0] raw_rvfi_rd_addr;
    wire [31:0] raw_rvfi_rd_wdata;
    wire [31:0] raw_rvfi_pc_rdata;
    wire [31:0] raw_rvfi_pc_wdata;
    wire [31:0] raw_rvfi_mem_addr;
    wire [3:0] raw_rvfi_mem_rmask;
    wire [3:0] raw_rvfi_mem_wmask;
    wire [31:0] raw_rvfi_mem_rdata;
    wire [31:0] raw_rvfi_mem_wdata;
    wire raw_rvfi_mem_fault;
    wire [3:0] raw_rvfi_mem_fault_rmask;
    wire [3:0] raw_rvfi_mem_fault_wmask;
    uqu_core #(
        .ISA_E(ISA_E),
        .ISA_M(ISA_M),
        .ISA_C(ISA_C),
        .ISA_ZFINX(ISA_ZFINX),
        .ISA_F(ISA_F),
        .ISA_A(ISA_A),
        .ISA_UMODE(ISA_UMODE),
        .ISA_ZIFENCEI(ISA_ZIFENCEI),
        .ISA_PMP(ISA_PMP),
        .MUA_FORWARDING(MUA_FORWARDING),
        .MUA_FORWARD_EX_TO_DE(MUA_FORWARD_EX_TO_DE),
        .MUA_FORWARD_MEM_TO_DE(MUA_FORWARD_MEM_TO_DE),
        .MUA_FORWARD_MEM_TO_EX(MUA_FORWARD_MEM_TO_EX),
        .MUA_FORWARD_WB_TO_EX(MUA_FORWARD_WB_TO_EX),
        .MUA_DE_OPERAND_RETENTION(MUA_DE_OPERAND_RETENTION),
        .MUA_C_IMPL(MUA_C_IMPL),
        .MUA_C_DECOMPRESS_STAGE(MUA_C_DECOMPRESS_STAGE),
        .MUA_BRANCH_PREDICTOR(MUA_BRANCH_PREDICTOR),
        .MUA_REGFILE_IMPL(MUA_REGFILE_IMPL),
        .MUA_IF_BUFFER_WORDS(MUA_IF_BUFFER_WORDS),
        .MUA_HARDENED(MUA_HARDENED),
        .MUA_MUL(MUA_MUL),
        .MUA_DIV(MUA_DIV),
        .MUA_MULDIV_ITERUNROLL(MUA_MULDIV_ITERUNROLL),
        .XIF(XIF),
        .XIF_NUM_RS(XIF_NUM_RS),
        .XIF_DUALWRITE(XIF_DUALWRITE),
        .DEBUG(DEBUG)
    ) u_core (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .boot_addr_i(boot_addr_i),
        .hart_id_i(hart_id_i),
        .irq_software_i(irq_software_i),
        .irq_timer_i(irq_timer_i),
        .irq_external_i(irq_external_i),
        .imem_req_o(imem_req_o),
        .imem_addr_o(imem_addr_o),
        .imem_gnt_i(imem_gnt_i),
        .imem_rvalid_i(imem_rvalid_i),
        .imem_rdata_i(imem_rdata_i),
        .imem_err_i(imem_err_i),
        .dmem_req_o(dmem_req_o),
        .dmem_we_o(dmem_we_o),
        .dmem_addr_o(dmem_addr_o),
        .dmem_wdata_o(dmem_wdata_o),
        .dmem_be_o(dmem_be_o),
        .dmem_gnt_i(dmem_gnt_i),
        .dmem_rvalid_i(dmem_rvalid_i),
        .dmem_rdata_i(dmem_rdata_i),
        .dmem_err_i(dmem_err_i),
        .fence_req_o(fence_req_o),
        .fence_ack_i(fence_ack_i),
        .fencei_req_o(fencei_req_o),
        .fencei_ack_i(fencei_ack_i),
        .xif_issue_valid_o(xif_issue_valid_o),
        .xif_issue_ready_i(xif_issue_ready_i),
        .xif_issue_instr_o(xif_issue_instr_o),
        .xif_issue_hartid_o(xif_issue_hartid_o),
        .xif_issue_id_o(xif_issue_id_o),
        .xif_issue_accept_i(xif_issue_accept_i),
        .xif_issue_writeback_i(xif_issue_writeback_i),
        .xif_issue_register_read_i(xif_issue_register_read_i),
        .xif_register_valid_o(xif_register_valid_o),
        .xif_register_ready_i(xif_register_ready_i),
        .xif_register_hartid_o(xif_register_hartid_o),
        .xif_register_id_o(xif_register_id_o),
        .xif_register_rs_o(xif_register_rs_o),
        .xif_register_rs_valid_o(xif_register_rs_valid_o),
        .xif_commit_valid_o(xif_commit_valid_o),
        .xif_commit_hartid_o(xif_commit_hartid_o),
        .xif_commit_id_o(xif_commit_id_o),
        .xif_commit_kill_o(xif_commit_kill_o),
        .xif_result_valid_i(xif_result_valid_i),
        .xif_result_ready_o(xif_result_ready_o),
        .xif_result_hartid_i(xif_result_hartid_i),
        .xif_result_id_i(xif_result_id_i),
        .xif_result_data_i(xif_result_data_i),
        .xif_result_rd_i(xif_result_rd_i),
        .xif_result_we_i(xif_result_we_i)
    );

    uqu_rvfi u_rvfi (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .de_fire_i(u_core.de_fire),
        .de_used_i(u_core.de_used[1:0]),
        .de_rs1_addr_i(u_core.de_rs_addr[0]),
        .de_rs2_addr_i(u_core.de_rs_addr[1]),
        .de_rs1_rdata_i(u_core.de_rs[0]),
        .de_rs2_rdata_i(u_core.de_rs[1]),
        .ex_fire_i(u_core.ex_fire),
        .ex_used_i(u_core.ex_used_q[1:0]),
        .ex_rs1_rdata_i(u_core.ex_rs[0]),
        .ex_rs2_rdata_i(u_core.ex_rs[1]),
        .mem_enable_i(u_core.mem_enable),
        .mem_response_i(dmem_rvalid_i && u_core.u_mem.issued_q && !u_core.mem_flush),
        .mem_response_data_i(dmem_rdata_i),
        .mem_fire_i(u_core.mem_fire),
        .mem_lsu_i(u_core.mem_lsu_q),
        .mem_we_i(u_core.mem_we_q),
        .mem_op_i(u_core.mem_op_q),
        .mem_addr_i(u_core.mem_data_q),
        .mem_wdata_i(u_core.mem_store_data_q),
        .wb_retire_i(u_core.wb_retire),
        .wb_exception_i(u_core.wb_exception_fire),
        .wb_cause_i(u_core.wb_cause),
        .wb_pc_i(u_core.wb_pc_q),
        .wb_insn_i(u_core.wb_original_q),
        .wb_next_pc_i(u_core.wb_next_pc_q),
        .wb_redirect_i(u_core.wb_redirect),
        .wb_target_i(u_core.wb_target),
        .wb_priv_m_i(u_core.wb_priv_m_q),
        .wb_we_i(u_core.wb_we0),
        .wb_rd_i(u_core.wb_waddr0),
        .wb_wdata_i(u_core.wb_wdata0),
        .irq_entry_i(u_core.trap_valid),
        .rvfi_valid(raw_rvfi_valid),
        .rvfi_order(raw_rvfi_order),
        .rvfi_insn(raw_rvfi_insn),
        .rvfi_trap(raw_rvfi_trap),
        .rvfi_halt(raw_rvfi_halt),
        .rvfi_intr(raw_rvfi_intr),
        .rvfi_mode(raw_rvfi_mode),
        .rvfi_ixl(raw_rvfi_ixl),
        .rvfi_rs1_addr(raw_rvfi_rs1_addr),
        .rvfi_rs2_addr(raw_rvfi_rs2_addr),
        .rvfi_rs1_rdata(raw_rvfi_rs1_rdata),
        .rvfi_rs2_rdata(raw_rvfi_rs2_rdata),
        .rvfi_rd_addr(raw_rvfi_rd_addr),
        .rvfi_rd_wdata(raw_rvfi_rd_wdata),
        .rvfi_pc_rdata(raw_rvfi_pc_rdata),
        .rvfi_pc_wdata(raw_rvfi_pc_wdata),
        .rvfi_mem_addr(raw_rvfi_mem_addr),
        .rvfi_mem_rmask(raw_rvfi_mem_rmask),
        .rvfi_mem_wmask(raw_rvfi_mem_wmask),
        .rvfi_mem_rdata(raw_rvfi_mem_rdata),
        .rvfi_mem_wdata(raw_rvfi_mem_wdata),
        .rvfi_mem_fault(raw_rvfi_mem_fault),
        .rvfi_mem_fault_rmask(raw_rvfi_mem_fault_rmask),
        .rvfi_mem_fault_wmask(raw_rvfi_mem_fault_wmask)
    );

    wire [64*`UQU_RVFI_CSR_COUNT-1:0] csr_values;
    assign csr_values[0*64 +: 64] = {32'd0, u_core.u_wb.u_csregfile.mstatus_o};
    assign csr_values[1*64 +: 64] = {32'd0, u_core.u_wb.u_csregfile.MISA};
    assign csr_values[2*64 +: 64] = {32'd0, u_core.u_wb.u_csregfile.mie_o};
    assign csr_values[3*64 +: 64] = {32'd0, u_core.u_wb.u_csregfile.mtvec_o};
    assign csr_values[4*64 +: 64] = {32'd0, u_core.u_wb.u_csregfile.mcounteren};
    assign csr_values[5*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[6*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[7*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[8*64 +: 64] = {32'd0, u_core.u_wb.u_csregfile.mcountinhibit};
    assign csr_values[9*64 +: 64] = {32'd0, u_core.u_wb.u_csregfile.mscratch_q};
    assign csr_values[10*64 +: 64] = {32'd0, u_core.u_wb.u_csregfile.mepc_o};
    assign csr_values[11*64 +: 64] = {32'd0, u_core.u_wb.u_csregfile.mcause};
    assign csr_values[12*64 +: 64] = {32'd0, u_core.u_wb.u_csregfile.mtval_q};
    assign csr_values[13*64 +: 64] = {32'd0, u_core.u_wb.u_csregfile.mip_o};
    assign csr_values[14*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[15*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[16*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[17*64 +: 64] = {32'd0, u_core.u_wb.u_csregfile.hart_id_i};
    assign csr_values[18*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[19*64 +: 64] = u_core.u_wb.u_csregfile.mcycle_q;
    assign csr_values[20*64 +: 64] = u_core.u_wb.u_csregfile.minstret_q;
    assign csr_values[21*64 +: 64] = {32'd0, u_core.pmpcfg[0 +: 32]};
    assign csr_values[22*64 +: 64] = {32'd0, u_core.pmpcfg[32 +: 32]};
    assign csr_values[23*64 +: 64] = {32'd0, u_core.pmpcfg[64 +: 32]};
    assign csr_values[24*64 +: 64] = {32'd0, u_core.pmpcfg[96 +: 32]};
    assign csr_values[25*64 +: 64] = {32'd0, u_core.pmpaddr[0 +: 32]};
    assign csr_values[26*64 +: 64] = {32'd0, u_core.pmpaddr[32 +: 32]};
    assign csr_values[27*64 +: 64] = {32'd0, u_core.pmpaddr[64 +: 32]};
    assign csr_values[28*64 +: 64] = {32'd0, u_core.pmpaddr[96 +: 32]};
    assign csr_values[29*64 +: 64] = {32'd0, u_core.pmpaddr[128 +: 32]};
    assign csr_values[30*64 +: 64] = {32'd0, u_core.pmpaddr[160 +: 32]};
    assign csr_values[31*64 +: 64] = {32'd0, u_core.pmpaddr[192 +: 32]};
    assign csr_values[32*64 +: 64] = {32'd0, u_core.pmpaddr[224 +: 32]};
    assign csr_values[33*64 +: 64] = {32'd0, u_core.pmpaddr[256 +: 32]};
    assign csr_values[34*64 +: 64] = {32'd0, u_core.pmpaddr[288 +: 32]};
    assign csr_values[35*64 +: 64] = {32'd0, u_core.pmpaddr[320 +: 32]};
    assign csr_values[36*64 +: 64] = {32'd0, u_core.pmpaddr[352 +: 32]};
    assign csr_values[37*64 +: 64] = {32'd0, u_core.pmpaddr[384 +: 32]};
    assign csr_values[38*64 +: 64] = {32'd0, u_core.pmpaddr[416 +: 32]};
    assign csr_values[39*64 +: 64] = {32'd0, u_core.pmpaddr[448 +: 32]};
    assign csr_values[40*64 +: 64] = {32'd0, u_core.pmpaddr[480 +: 32]};
    assign csr_values[41*64 +: 64] = 64'd0;
    assign csr_values[42*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[43*64 +: 64] = 64'd0;
    assign csr_values[44*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[45*64 +: 64] = 64'd0;
    assign csr_values[46*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[47*64 +: 64] = 64'd0;
    assign csr_values[48*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[49*64 +: 64] = 64'd0;
    assign csr_values[50*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[51*64 +: 64] = 64'd0;
    assign csr_values[52*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[53*64 +: 64] = 64'd0;
    assign csr_values[54*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[55*64 +: 64] = 64'd0;
    assign csr_values[56*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[57*64 +: 64] = 64'd0;
    assign csr_values[58*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[59*64 +: 64] = 64'd0;
    assign csr_values[60*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[61*64 +: 64] = 64'd0;
    assign csr_values[62*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[63*64 +: 64] = 64'd0;
    assign csr_values[64*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[65*64 +: 64] = 64'd0;
    assign csr_values[66*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[67*64 +: 64] = 64'd0;
    assign csr_values[68*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[69*64 +: 64] = 64'd0;
    assign csr_values[70*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[71*64 +: 64] = 64'd0;
    assign csr_values[72*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[73*64 +: 64] = 64'd0;
    assign csr_values[74*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[75*64 +: 64] = 64'd0;
    assign csr_values[76*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[77*64 +: 64] = 64'd0;
    assign csr_values[78*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[79*64 +: 64] = 64'd0;
    assign csr_values[80*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[81*64 +: 64] = 64'd0;
    assign csr_values[82*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[83*64 +: 64] = 64'd0;
    assign csr_values[84*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[85*64 +: 64] = 64'd0;
    assign csr_values[86*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[87*64 +: 64] = 64'd0;
    assign csr_values[88*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[89*64 +: 64] = 64'd0;
    assign csr_values[90*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[91*64 +: 64] = 64'd0;
    assign csr_values[92*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[93*64 +: 64] = 64'd0;
    assign csr_values[94*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[95*64 +: 64] = 64'd0;
    assign csr_values[96*64 +: 64] = {32'd0, 32'd0};
    assign csr_values[97*64 +: 64] = 64'd0;
    assign csr_values[98*64 +: 64] = {32'd0, 32'd0};

    // One observation register permits read-before/write-after CSR values
    // without predicting WARL or implicit updates in the monitor.
    reg trace_irq_valid;
    reg [31:0] trace_irq_pc, trace_irq_target, trace_tval;
    reg [4:0] trace_irq_cause, trace_cause;
    always @(posedge clk_i) begin
        if (!rst_ni) begin
            rvfi_valid <= 1'b0;
            trace_irq_valid <= 1'b0;
        end else begin
            rvfi_valid <= raw_rvfi_valid;
            rvfi_order <= raw_rvfi_order;
            rvfi_insn <= raw_rvfi_insn;
            rvfi_trap <= raw_rvfi_trap;
            rvfi_halt <= raw_rvfi_halt;
            rvfi_intr <= raw_rvfi_intr;
            rvfi_mode <= raw_rvfi_mode;
            rvfi_ixl <= raw_rvfi_ixl;
            rvfi_rs1_addr <= raw_rvfi_rs1_addr;
            rvfi_rs2_addr <= raw_rvfi_rs2_addr;
            rvfi_rs1_rdata <= raw_rvfi_rs1_rdata;
            rvfi_rs2_rdata <= raw_rvfi_rs2_rdata;
            rvfi_rd_addr <= raw_rvfi_rd_addr;
            rvfi_rd_wdata <= raw_rvfi_rd_wdata;
            rvfi_pc_rdata <= raw_rvfi_pc_rdata;
            rvfi_pc_wdata <= raw_rvfi_pc_wdata;
            rvfi_mem_addr <= raw_rvfi_mem_addr;
            rvfi_mem_rmask <= raw_rvfi_mem_rmask;
            rvfi_mem_wmask <= raw_rvfi_mem_wmask;
            rvfi_mem_rdata <= raw_rvfi_mem_rdata;
            rvfi_mem_wdata <= raw_rvfi_mem_wdata;
            rvfi_mem_fault <= raw_rvfi_mem_fault;
            rvfi_mem_fault_rmask <= raw_rvfi_mem_fault_rmask;
            rvfi_mem_fault_wmask <= raw_rvfi_mem_fault_wmask;
            trace_irq_valid <= u_core.trap_valid;
            trace_irq_pc <= u_core.trap_pc;
            trace_irq_target <= u_core.redirect_addr;
            trace_irq_cause <= u_core.trap_cause;
            trace_cause <= u_core.wb_cause;
            trace_tval <= u_core.wb_tval;
        end
    end
    uqu_rvfi_csrs u_csrs (
        .clk_i(clk_i), .rst_ni(rst_ni),
        .event_i(raw_rvfi_valid || u_core.trap_valid),
        .csr_addr_i(u_core.wb_csr_addr_q),
        .csr_read_i(raw_rvfi_valid && u_core.u_wb.u_csregfile.csr_read_o),
        .csr_write_i(raw_rvfi_valid && u_core.u_wb.u_csregfile.csr_we),
        .trap_i(u_core.trap_valid || u_core.wb_exception_fire),
        .mret_i(u_core.wb_mret), .values_i(csr_values)
        `define UQU_RVFI_CSR(NAME, WIDTH, INDEX, LO, HI, ULO, UHI) `UQU_RVFI_CSR_CONNECT(NAME, WIDTH, INDEX, LO, HI, ULO, UHI)
        `include "uqu_rvfi_csr_list.vh"
        `undef UQU_RVFI_CSR
    );

    uqu_rvfi_trace u_trace (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .irq_valid_i(trace_irq_valid),
        .irq_pc_i(trace_irq_pc),
        .irq_cause_i(trace_irq_cause),
        .irq_target_i(trace_irq_target),
        .exception_cause_i(trace_cause),
        .exception_tval_i(trace_tval),
        .rvfi_valid(rvfi_valid),
        .rvfi_order(rvfi_order),
        .rvfi_insn(rvfi_insn),
        .rvfi_trap(rvfi_trap),
        .rvfi_halt(rvfi_halt),
        .rvfi_intr(rvfi_intr),
        .rvfi_mode(rvfi_mode),
        .rvfi_ixl(rvfi_ixl),
        .rvfi_rs1_addr(rvfi_rs1_addr),
        .rvfi_rs2_addr(rvfi_rs2_addr),
        .rvfi_rs1_rdata(rvfi_rs1_rdata),
        .rvfi_rs2_rdata(rvfi_rs2_rdata),
        .rvfi_rd_addr(rvfi_rd_addr),
        .rvfi_rd_wdata(rvfi_rd_wdata),
        .rvfi_pc_rdata(rvfi_pc_rdata),
        .rvfi_pc_wdata(rvfi_pc_wdata),
        .rvfi_mem_addr(rvfi_mem_addr),
        .rvfi_mem_rmask(rvfi_mem_rmask),
        .rvfi_mem_wmask(rvfi_mem_wmask),
        .rvfi_mem_rdata(rvfi_mem_rdata),
        .rvfi_mem_wdata(rvfi_mem_wdata),
        .rvfi_mem_fault(rvfi_mem_fault),
        .rvfi_mem_fault_rmask(rvfi_mem_fault_rmask),
        .rvfi_mem_fault_wmask(rvfi_mem_fault_wmask)
        `define UQU_RVFI_CSR(NAME, WIDTH, INDEX, LO, HI, ULO, UHI) `UQU_RVFI_CSR_CONNECT(NAME, WIDTH, INDEX, LO, HI, ULO, UHI)
        `include "uqu_rvfi_csr_list.vh"
        `undef UQU_RVFI_CSR
    );
endmodule

`default_nettype wire
