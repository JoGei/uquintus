`default_nettype none
`include "uqu_ctrl.vh"

// Core-owned arbitration and movement. The parent owns all boundary validity,
// payloads, privilege and resume PC. Completion reports may depend on local
// permits, but WB commitment permission never depends on result validity.
module uqu_pipeline_ctrl #(
    parameter ISA_ZIFENCEI = 0
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        if_valid_i,
    input  wire        de_valid_i,
    input  wire        ex_valid_i,
    input  wire        mem_valid_i,
    input  wire        wb_valid_i,
    input  wire        de_complete_i,
    input  wire        ex_complete_i,
    input  wire        mem_complete_i,
    input  wire        wb_complete_i,
    input  wire        de_exception_i,
    input  wire        ex_exception_i,
    input  wire        mem_exception_i,
    input  wire        wb_exception_i,
    input  wire        ex_serialize_i,
    input  wire        mem_serialize_i,
    input  wire        wb_serialize_i,
    input  wire [2:0]  de_system_i,
    input  wire [2:0]  ex_system_i,
    input  wire [2:0]  mem_system_i,
    input  wire [2:0]  wb_system_i,
    input  wire        de_admit_i,
    input  wire        commit_enable_i,
    input  wire        wb_effect_safe_i,
    input  wire        de_branch_taken_i,
    input  wire [31:0] de_branch_target_i,
    // Already accepted event from the instruction at WB, e.g. exception/MRET.
    // Never feed its resulting younger flushes back to that same WB unit.
    input  wire        wb_redirect_valid_i,
    input  wire [31:0] wb_redirect_addr_i,
    input  wire [31:0] wb_next_pc_i,
    input  wire [31:0] de_pc_i,
    input  wire [31:0] resume_pc_i,
    input  wire        priv_m_i,
    input  wire [31:0] mstatus_i,
    input  wire [31:0] mie_i,
    input  wire [31:0] mip_i,
    input  wire [31:0] mtvec_i,
    input  wire        irq_mask_i,
    // Optional core-internal drain endpoint (e.g. qualified debug entry).
    // Its requester owns cause/eligibility/latching; this block owns priority.
    input  wire        drain_req_i,
    input  wire [31:0] drain_target_i,
    input  wire        drain_ready_i,
    input  wire        data_idle_i,
    input  wire        fence_ack_i,
    input  wire        fencei_ack_i,
    output wire        if_permit_o,
    output wire        fetch_enable_o,
    output wire        if_ready_o,
    output wire        de_permit_o,
    output wire        de_ready_o,
    output wire        ex_ready_o,
    output wire        mem_ready_o,
    output wire        wb_ready_o,
    output wire        if_fire_o,
    output wire        de_fire_o,
    output wire        ex_fire_o,
    output wire        mem_fire_o,
    output wire        wb_fire_o,
    output wire        de_enable_o,
    output wire        ex_enable_o,
    output wire        mem_enable_o,
    output wire        wb_enable_o,
    output wire        de_valid_next_o,
    output wire        ex_valid_next_o,
    output wire        mem_valid_next_o,
    output wire        wb_valid_next_o,
    output wire        if_flush_o,
    output wire        de_flush_o,
    output wire        ex_flush_o,
    output wire        mem_flush_o,
    output wire        mem_request_permit_o,
    output wire        irq_eligible_o,
    output wire        draining_o,
    output wire        trap_valid_o,
    output wire [31:0] trap_pc_o,
    output wire        trap_interrupt_o,
    output wire [4:0]  trap_cause_o,
    output wire [31:0] trap_tval_o,
    output wire        drain_accept_o,
    output wire [31:0] drain_pc_o,
    output wire        redirect_valid_o,
    output wire [31:0] redirect_addr_o,
    output wire        fence_req_o,
    output wire        fencei_req_o
);
    // Fence request/acknowledgement tracking only. Occupancy, serialization,
    // faults and interrupt eligibility live in parent metadata/CSR state.
    reg fence_requested_q;
    reg fence_done_q;
    wire de_fault = de_valid_i && de_exception_i;
    wire ex_fault = ex_valid_i && ex_exception_i;
    wire mem_fault = mem_valid_i && mem_exception_i;
    wire wb_fault = wb_valid_i && wb_exception_i;
    wire older_fault = ex_fault || mem_fault || wb_fault;
    wire any_fault = de_fault || older_fault;
    wire older_serial = (ex_valid_i && ex_serialize_i) ||
                        (mem_valid_i && mem_serialize_i) || (wb_valid_i && wb_serialize_i);
    wire fencei_pending = (ISA_ZIFENCEI == 1) &&
        ((de_valid_i && (de_system_i == `UQU_SYS_FENCEI)) ||
         (ex_valid_i && (ex_system_i == `UQU_SYS_FENCEI)) ||
         (mem_valid_i && (mem_system_i == `UQU_SYS_FENCEI)) ||
         (wb_valid_i && (wb_system_i == `UQU_SYS_FENCEI)));
    wire wb_fence = wb_valid_i && (wb_system_i == `UQU_SYS_FENCE);
    wire wb_fencei = (ISA_ZIFENCEI == 1) && wb_valid_i && (wb_system_i == `UQU_SYS_FENCEI);
    wire fence_ack = (fence_req_o && fence_ack_i) || (fencei_req_o && fencei_ack_i);
    wire fence_complete = fence_done_q || fence_ack;
    wire irq_external = mie_i[11] && mip_i[11];
    wire irq_software = mie_i[3] && mip_i[3];
    wire irq_timer = mie_i[7] && mip_i[7];
    wire irq_enabled = !irq_mask_i && (!priv_m_i || mstatus_i[3]);
    wire [4:0] irq_cause = irq_external ? 5'd11 : irq_software ? 5'd3 : 5'd7;
    wire boundary_empty = !ex_valid_i && !mem_valid_i && !wb_valid_i;
    wire [31:0] boundary_pc = de_valid_i ? de_pc_i : resume_pc_i;
    wire wb_redirect = rst_ni && wb_redirect_valid_i && wb_fire_o;
    wire fencei_redirect = wb_fire_o && wb_fencei && !wb_fault;
    wire wb_recovery = wb_redirect || fencei_redirect;
    // Empty occupancy already excludes WB recovery. Do not depend on WB
    // completion here: trap_valid feeds WB's external-event suppression.
    wire async_entry = rst_ni && boundary_empty && drain_ready_i;
    wire branch_redirect = de_fire_o && de_branch_taken_i && !de_fault;

    assign irq_eligible_o = rst_ni && irq_enabled && (irq_external || irq_software || irq_timer);
    assign draining_o = rst_ni && (drain_req_i || irq_eligible_o);
    assign drain_accept_o = async_entry && drain_req_i;
    assign drain_pc_o = drain_accept_o ? boundary_pc : 32'd0;
    assign trap_valid_o = async_entry && !drain_req_i && irq_eligible_o;
    assign trap_pc_o = trap_valid_o ? boundary_pc : 32'd0;
    assign trap_interrupt_o = trap_valid_o;
    assign trap_cause_o = trap_valid_o ? irq_cause : 5'd0;
    assign trap_tval_o = 32'd0;

    // Requests precede/ignore acknowledgement and retain a completed handshake
    // across commitment stalls, so one fence causes exactly one sync request.
    assign fence_req_o = rst_ni && wb_fence && !wb_fault && !fence_done_q &&
                        (fence_requested_q || data_idle_i);
    assign fencei_req_o = rst_ni && wb_fencei && !wb_fault && !fence_done_q &&
                         (fence_requested_q || data_idle_i);
    // In particular, there is no wb_complete/result-valid -> wb_ready path.
    assign wb_ready_o = rst_ni && commit_enable_i &&
                        (wb_fault || !(wb_fence || wb_fencei) || fence_complete);
    assign wb_fire_o = wb_valid_i && wb_complete_i && wb_ready_o;

    assign mem_flush_o = rst_ni && (wb_fault || wb_recovery);
    assign ex_flush_o = rst_ni && (mem_fault || wb_fault || wb_recovery);
    assign de_flush_o = rst_ni && (older_fault || wb_recovery || trap_valid_o || drain_accept_o);
    assign mem_ready_o = rst_ni && (!wb_valid_i || wb_fire_o) && !mem_flush_o;
    assign mem_fire_o = mem_valid_i && mem_complete_i && mem_ready_o;
    assign ex_ready_o = rst_ni && (!mem_valid_i || mem_fire_o) && !ex_flush_o;
    assign ex_fire_o = ex_valid_i && ex_complete_i && ex_ready_o;
    assign de_permit_o = rst_ni && de_admit_i && !draining_o && !older_fault && !older_serial && !wb_recovery;
    assign de_ready_o = de_permit_o && (!ex_valid_i || ex_fire_o);
    assign de_fire_o = de_valid_i && de_complete_i && de_ready_o;
    assign if_permit_o = rst_ni && !any_fault && !draining_o && !wb_recovery && !branch_redirect;
    assign if_ready_o = if_permit_o && (!de_valid_i || de_fire_o);
    assign if_fire_o = if_valid_i && if_ready_o;
    assign fetch_enable_o = if_permit_o && !fencei_pending;
    assign if_flush_o = rst_ni && (any_fault || redirect_valid_o);

    assign de_enable_o = rst_ni && (de_flush_o || !de_valid_i || de_fire_o);
    assign ex_enable_o = rst_ni && (ex_flush_o || !ex_valid_i || ex_fire_o);
    assign mem_enable_o = rst_ni && (mem_flush_o || !mem_valid_i || mem_fire_o);
    assign wb_enable_o = rst_ni && (!wb_valid_i || wb_fire_o);
    assign de_valid_next_o = !de_flush_o && if_fire_o;
    assign ex_valid_next_o = !ex_flush_o && de_fire_o;
    assign mem_valid_next_o = !mem_flush_o && ex_fire_o;
    assign wb_valid_next_o = mem_fire_o;

    // Older reads and writes both remain live while a younger fault drains.
    // A proof of older WB safety can release the request before retirement.
    assign mem_request_permit_o = rst_ni && mem_valid_i && !mem_fault && !wb_fault && !wb_recovery &&
                                  (!wb_valid_i || wb_effect_safe_i);
    assign redirect_valid_o = rst_ni && (wb_recovery || drain_accept_o || trap_valid_o || branch_redirect);
    assign redirect_addr_o = !redirect_valid_o ? 32'd0 : wb_redirect ? wb_redirect_addr_i :
        fencei_redirect ? wb_next_pc_i : drain_accept_o ? drain_target_i : trap_valid_o ?
        ({mtvec_i[31:2],2'b00} + ((mtvec_i[1:0] == 2'b01) ? {25'd0,irq_cause,2'b00} : 32'd0)) :
        de_branch_target_i;

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            fence_requested_q <= 1'b0;
            fence_done_q <= 1'b0;
        end else if (!wb_valid_i || wb_fire_o || wb_fault) begin
            fence_requested_q <= 1'b0;
            fence_done_q <= 1'b0;
        end else begin
            if (fence_req_o || fencei_req_o) begin
                fence_requested_q <= 1'b1;
            end
            if (fence_ack) begin
                fence_done_q <= 1'b1;
            end
        end
    end
    generate
        if ((ISA_ZIFENCEI != 0) && (ISA_ZIFENCEI != 1)) begin : gen_invalid
            uqu_pipeline_ctrl_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
