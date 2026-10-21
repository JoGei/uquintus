`default_nettype none
`include "uqu_ctrl.vh"

// Verification-only parent: actual boundary storage, controller, MEM/LSU and
// WB/CSR. IF/DE/EX computation is a normalized-token source/completion stub.
module uqu_pipeline_ctrl_tb #(
    parameter ISA_ZIFENCEI = 0
) (
    input wire clk_i,
    input wire rst_ni,
    input wire in_valid_i,
    output wire in_ready_o,
    input wire [31:0] in_pc_i,
    input wire [31:0] in_next_pc_i,
    input wire [31:0] in_instr_i,
    input wire [31:0] in_data_i,
    input wire [31:0] in_store_data_i,
    input wire [2:0] in_kind_i,
    input wire [2:0] in_system_i,
    input wire in_serialize_i,
    input wire in_branch_i,
    input wire in_fault_i,
    input wire [4:0] in_cause_i,
    input wire [31:0] in_tval_i,
    input wire in_lsu_i,
    input wire in_we_i,
    input wire [11:0] in_csr_addr_i,
    input wire [2:0] in_csr_op_i,
    input wire ex_done_i,
    input wire ex_fault_i,
    input wire commit_enable_i,
    input wire wb_effect_safe_i,
    input wire de_admit_i,
    input wire irq_software_i,
    input wire irq_timer_i,
    input wire irq_external_i,
    input wire irq_mask_i,
    input wire drain_req_i,
    input wire drain_ready_i,
    input wire fence_ack_i,
    input wire fencei_ack_i,
    output wire fence_req_o,
    output wire fencei_req_o,
    output wire [3:0] occupied_o,
    output wire [3:0] advance_o,
    output wire [2:0] clear_o,
    output wire in_fire_o,
    output wire [31:0] de_pc_o,
    output wire [31:0] ex_pc_o,
    output wire [31:0] mem_pc_o,
    output wire [31:0] wb_pc_o,
    output wire retire_o,
    output wire exception_fire_o,
    output wire [4:0] exception_cause_o,
    output wire [31:0] exception_tval_o,
    output wire write_o,
    output wire [31:0] write_data_o,
    output wire trap_valid_o,
    output wire [31:0] trap_pc_o,
    output wire [4:0] trap_cause_o,
    output wire drain_accept_o,
    output wire [31:0] drain_pc_o,
    output wire redirect_valid_o,
    output wire [31:0] redirect_addr_o,
    output wire [31:0] mstatus_o,
    output wire [31:0] mepc_o,
    output wire [31:0] mtvec_o,
    output wire [31:0] mie_o,
    output wire dmem_req_o,
    output wire dmem_we_o,
    output wire [31:0] dmem_addr_o,
    output wire [31:0] dmem_wdata_o,
    output wire [3:0] dmem_be_o,
    input wire dmem_gnt_i,
    input wire dmem_rvalid_i,
    input wire [31:0] dmem_rdata_i,
    input wire dmem_err_i
);
    reg [3:0] valid_q;
    reg [31:0] pc_q [0:3];
    reg [31:0] next_pc_q [0:3];
    reg [31:0] instr_q [0:3];
    reg [31:0] data_q [0:3];
    reg [31:0] store_data_q [0:3];
    reg [2:0] kind_q [0:3];
    reg [2:0] system_q [0:3];
    reg serial_q [0:3];
    reg branch_q [0:3];
    reg fault_q [0:3];
    reg [4:0] cause_q [0:3];
    reg [31:0] tval_q [0:3];
    reg lsu_q [0:3];
    reg we_q [0:3];
    reg [11:0] csr_addr_q [0:3];
    reg [2:0] csr_op_q [0:3];
    reg priv_m_q;
    reg [31:0] resume_pc_q;
    wire [3:0] enable;
    wire [3:0] next_valid;
    wire [2:0] flush;
    wire de_permit, de_ready, mem_ready, wb_ready;
    wire mem_complete, wb_complete, mem_fault, wb_fault;
    wire [4:0] mem_cause;
    wire [31:0] mem_tval, mem_result;
    wire lsu_busy, mem_request_permit, wb_mret;
    wire [31:0] mip;
    wire [31:0] wb_target = exception_fire_o ? {mtvec_o[31:2],2'b00} : mepc_o;
    integer k;

    assign occupied_o = valid_q;
    assign clear_o = flush;
    assign de_pc_o = pc_q[0];
    assign ex_pc_o = pc_q[1];
    assign mem_pc_o = pc_q[2];
    assign wb_pc_o = pc_q[3];

    uqu_pipeline_ctrl #(.ISA_ZIFENCEI(ISA_ZIFENCEI)) u_ctrl (
        .clk_i(clk_i), .rst_ni(rst_ni), .if_valid_i(in_valid_i),
        .de_valid_i(valid_q[0]), .ex_valid_i(valid_q[1]), .mem_valid_i(valid_q[2]), .wb_valid_i(valid_q[3]),
        .de_complete_i(valid_q[0] && de_permit),
        .ex_complete_i(valid_q[1] && (ex_done_i || fault_q[1] || ex_fault_i)),
        .mem_complete_i(mem_complete), .wb_complete_i(wb_complete),
        .de_exception_i(fault_q[0]), .ex_exception_i(fault_q[1] || ex_fault_i),
        .mem_exception_i(mem_fault), .wb_exception_i(wb_fault),
        .ex_serialize_i(serial_q[1]), .mem_serialize_i(serial_q[2]), .wb_serialize_i(serial_q[3]),
        .de_system_i(system_q[0]), .ex_system_i(system_q[1]), .mem_system_i(system_q[2]), .wb_system_i(system_q[3]),
        .de_admit_i(de_admit_i), .commit_enable_i(commit_enable_i), .wb_effect_safe_i(wb_effect_safe_i),
        .de_branch_taken_i(branch_q[0]), .de_branch_target_i(next_pc_q[0]),
        .wb_redirect_valid_i(exception_fire_o || wb_mret), .wb_redirect_addr_i(wb_target),
        .wb_next_pc_i(next_pc_q[3]), .de_pc_i(pc_q[0]), .resume_pc_i(resume_pc_q),
        .priv_m_i(priv_m_q), .mstatus_i(mstatus_o), .mie_i(mie_o), .mip_i(mip),
        .mtvec_i(mtvec_o), .irq_mask_i(irq_mask_i),
        .drain_req_i(drain_req_i), .drain_target_i(32'h00009000),
        .drain_ready_i(drain_ready_i && !lsu_busy), .data_idle_i(!lsu_busy),
        .fence_ack_i(fence_ack_i), .fencei_ack_i(fencei_ack_i),
        .if_permit_o(), .fetch_enable_o(), .if_ready_o(in_ready_o),
        .de_permit_o(de_permit), .de_ready_o(de_ready), .ex_ready_o(),
        .mem_ready_o(mem_ready), .wb_ready_o(wb_ready),
        .if_fire_o(in_fire_o), .de_fire_o(advance_o[0]), .ex_fire_o(advance_o[1]),
        .mem_fire_o(advance_o[2]), .wb_fire_o(advance_o[3]),
        .de_enable_o(enable[0]), .ex_enable_o(enable[1]), .mem_enable_o(enable[2]), .wb_enable_o(enable[3]),
        .de_valid_next_o(next_valid[0]), .ex_valid_next_o(next_valid[1]),
        .mem_valid_next_o(next_valid[2]), .wb_valid_next_o(next_valid[3]),
        .if_flush_o(), .de_flush_o(flush[0]), .ex_flush_o(flush[1]), .mem_flush_o(flush[2]),
        .mem_request_permit_o(mem_request_permit), .irq_eligible_o(), .draining_o(),
        .trap_valid_o(trap_valid_o), .trap_pc_o(trap_pc_o), .trap_interrupt_o(),
        .trap_cause_o(trap_cause_o), .trap_tval_o(), .drain_accept_o(drain_accept_o), .drain_pc_o(drain_pc_o),
        .redirect_valid_o(redirect_valid_o), .redirect_addr_o(redirect_addr_o),
        .fence_req_o(fence_req_o), .fencei_req_o(fencei_req_o)
    );
    uqu_stage_mem u_mem (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush[2]),
        .valid_i(valid_q[2]), .ready_o(), .valid_o(mem_complete), .ready_i(mem_ready),
        .lsu_i(lsu_q[2]), .we_i(we_q[2]), .op_i(3'b010), .result_i(data_q[2]),
        .store_data_i(store_data_q[2]), .instr_i(instr_q[2]), .priv_m_i(priv_m_q),
        .fflags_valid_i(1'b0), .fflags_i(5'd0), .exception_valid_i(fault_q[2]),
        .exception_cause_i(cause_q[2]), .exception_tval_i(tval_q[2]), .request_permit_i(mem_request_permit),
        .lsu_busy_o(lsu_busy), .pmp_valid_o(), .pmp_addr_o(), .pmp_size_o(), .pmp_access_o(),
        .pmp_priv_m_o(), .pmp_allow_i(1'b1), .result_o(mem_result), .load_result_valid_o(),
        .fflags_valid_o(), .fflags_o(), .exception_valid_o(mem_fault), .exception_cause_o(mem_cause),
        .exception_tval_o(mem_tval), .dmem_req_o(dmem_req_o), .dmem_we_o(dmem_we_o),
        .dmem_addr_o(dmem_addr_o), .dmem_wdata_o(dmem_wdata_o), .dmem_be_o(dmem_be_o),
        .dmem_gnt_i(dmem_gnt_i), .dmem_rvalid_i(dmem_rvalid_i), .dmem_rdata_i(dmem_rdata_i), .dmem_err_i(dmem_err_i)
    );
    uqu_stage_wb u_wb (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(1'b0),
        .valid_i(valid_q[3]), .ready_o(), .valid_o(wb_complete), .ready_i(wb_ready),
        .kind_i(kind_q[3]), .result_i(data_q[3]),
        .rd_we_i(!we_q[3] && (system_q[3] == `UQU_SYS_NONE)), .rd_i(5'd1),
        .pc_i(pc_q[3]), .instr_i(instr_q[3]), .csr_addr_i(csr_addr_q[3]), .csr_op_i(csr_op_q[3]),
        .csr_src_i(data_q[3]), .csr_src_zero_i(data_q[3] == 32'd0),
        .fflags_valid_i(1'b0), .fflags_i(5'd0), .exception_valid_i(fault_q[3]),
        .exception_cause_i(cause_q[3]), .exception_tval_i(tval_q[3]), .priv_m_i(priv_m_q),
        .hart_id_i(32'd0), .irq_software_i(irq_software_i), .irq_timer_i(irq_timer_i), .irq_external_i(irq_external_i),
        .trap_i(trap_valid_o), .trap_pc_i(trap_pc_o), .trap_interrupt_i(1'b1), .trap_cause_i(trap_cause_o), .trap_tval_i(32'd0),
        .xif_id_i(3'd0), .xif_kill_valid_i(1'b0), .xif_kill_id_i(3'd0), .xif_kill_ready_o(),
        .xif_commit_valid_o(), .xif_commit_hartid_o(), .xif_commit_id_o(), .xif_commit_kill_o(),
        .xif_result_valid_i(1'b0), .xif_result_ready_o(), .xif_result_hartid_i(32'd0), .xif_result_id_i(3'd0),
        .xif_result_data_i(32'd0), .xif_result_rd_i(5'd0), .xif_result_we_i(1'b0),
        .debug_mode_i(1'b0), .debug_enter_i(1'b0), .debug_pc_i(32'd0), .debug_cause_i(3'd0),
        .debug_enter_o(), .debug_exception_o(), .debug_ebreak_o(), .dret_o(), .dcsr_o(), .dpc_o(),
        .retire_o(retire_o), .exception_fire_o(exception_fire_o), .mret_o(wb_mret),
        .exception_valid_o(wb_fault), .exception_cause_o(exception_cause_o), .exception_tval_o(exception_tval_o),
        .exception_pc_o(), .result_valid_o(), .result_o(), .we0_o(write_o), .waddr0_o(), .wdata0_o(write_data_o),
        .we1_o(), .waddr1_o(), .wdata1_o(), .mstatus_o(mstatus_o), .mie_o(mie_o), .mip_o(mip),
        .mtvec_o(mtvec_o), .mepc_o(mepc_o), .pmpcfg_o(), .pmpaddr_o(), .frm_o(), .fflags_o()
    );

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            valid_q <= 4'd0;
            priv_m_q <= 1'b1;
            resume_pc_q <= 32'h00001000;
        end else begin
            if (trap_valid_o || exception_fire_o) priv_m_q <= 1'b1;
            else if (wb_mret) priv_m_q <= (mstatus_o[12:11] == 2'b11);
            if (redirect_valid_o) resume_pc_q <= redirect_addr_o;
            else if (retire_o) resume_pc_q <= next_pc_q[3];
            for (k = 0; k < 4; k = k + 1) begin
                if (enable[k]) begin
                    valid_q[k] <= next_valid[k];
                    if (next_valid[k]) begin
                        if (k == 0) begin
                            pc_q[k] <= in_pc_i;
                            next_pc_q[k] <= in_next_pc_i;
                            instr_q[k] <= in_instr_i;
                            data_q[k] <= in_data_i;
                            store_data_q[k] <= in_store_data_i;
                            kind_q[k] <= in_kind_i;
                            system_q[k] <= in_system_i;
                            serial_q[k] <= in_serialize_i;
                            branch_q[k] <= in_branch_i;
                            fault_q[k] <= in_fault_i;
                            cause_q[k] <= in_cause_i;
                            tval_q[k] <= in_tval_i;
                            lsu_q[k] <= in_lsu_i;
                            we_q[k] <= in_we_i;
                            csr_addr_q[k] <= in_csr_addr_i;
                            csr_op_q[k] <= in_csr_op_i;
                        end else begin
                            pc_q[k] <= pc_q[k-1];
                            next_pc_q[k] <= next_pc_q[k-1];
                            instr_q[k] <= instr_q[k-1];
                            data_q[k] <= (k == 3) ? mem_result : data_q[k-1];
                            store_data_q[k] <= store_data_q[k-1];
                            kind_q[k] <= kind_q[k-1];
                            system_q[k] <= system_q[k-1];
                            serial_q[k] <= serial_q[k-1];
                            branch_q[k] <= branch_q[k-1];
                            fault_q[k] <= (k == 3) ? mem_fault : fault_q[k-1] || ((k == 2) && ex_fault_i);
                            cause_q[k] <= (k == 3) ? mem_cause : ((k == 2) && ex_fault_i) ? 5'd2 : cause_q[k-1];
                            tval_q[k] <= (k == 3) ? mem_tval : ((k == 2) && ex_fault_i) ? instr_q[k-1] : tval_q[k-1];
                            lsu_q[k] <= lsu_q[k-1];
                            we_q[k] <= we_q[k-1];
                            csr_addr_q[k] <= csr_addr_q[k-1];
                            csr_op_q[k] <= csr_op_q[k-1];
                        end
                    end
                end
            end
        end
    end
endmodule

`default_nettype wire
