`default_nettype none

// Verification-only parent with real EX/MEM and MEM/WB registers. An owning
// MEM flush discards EX/MEM, while the older MEM/WB slot remains drainable.
module uqu_mem_pipeline_tb #(
    parameter ISA_PMP = 0
) (
    input wire             clk_i,
    input wire             rst_ni,
    input wire             flush_i,
    input wire             in_valid_i,
    output wire            in_ready_o,
    input wire             in_lsu_i,
    input wire             in_we_i,
    input wire   [2:0]     in_op_i,
    input wire   [31:0]    in_result_i,
    input wire   [31:0]    in_store_data_i,
    input wire   [31:0]    in_instr_i,
    input wire             in_priv_m_i,
    input wire             in_fflags_valid_i,
    input wire   [4:0]     in_fflags_i,
    input wire             in_exception_valid_i,
    input wire   [4:0]     in_exception_cause_i,
    input wire   [31:0]    in_exception_tval_i,
    input wire   [31:0]    in_pc_i,
    input wire   [4:0]     in_rd_i,
    output wire            out_valid_o,
    input wire             out_ready_i,
    output wire  [31:0]    out_result_o,
    output wire            out_fflags_valid_o,
    output wire  [4:0]     out_fflags_o,
    output wire            out_exception_valid_o,
    output wire  [4:0]     out_exception_cause_o,
    output wire  [31:0]    out_exception_tval_o,
    output wire            out_load_result_valid_o,
    output wire  [31:0]    out_pc_o,
    output wire  [31:0]    out_instr_o,
    output wire  [4:0]     out_rd_o,
    input wire             request_permit_i,
    input wire   [127:0]   pmpcfg_i,
    input wire   [511:0]   pmpaddr_i,
    output wire            lsu_busy_o,
    output wire            mem_valid_o,
    output wire  [31:0]    mem_pc_o,
    output wire            mem_fire_o,
    output wire            dmem_req_o,
    output wire            dmem_we_o,
    output wire  [31:0]    dmem_addr_o,
    output wire  [31:0]    dmem_wdata_o,
    output wire  [3:0]     dmem_be_o,
    input wire             dmem_gnt_i,
    input wire             dmem_rvalid_i,
    input wire   [31:0]    dmem_rdata_i,
    input wire             dmem_err_i
);
    reg exmem_valid_q;
    reg memwb_valid_q;
    reg memwb_lsu_q, memwb_we_q;
    wire res_valid, res_error;
    wire [31:0] res_data, res_tval;
    wire [4:0] res_cause;
    reg                    exmem_lsu_q;
    reg                    exmem_we_q;
    reg          [2:0]     exmem_op_q;
    reg          [31:0]    exmem_result_q;
    reg          [31:0]    exmem_store_data_q;
    reg          [31:0]    exmem_instr_q;
    reg                    exmem_priv_m_q;
    reg                    exmem_fflags_valid_q;
    reg          [4:0]     exmem_fflags_q;
    reg                    exmem_exception_valid_q;
    reg          [4:0]     exmem_exception_cause_q;
    reg          [31:0]    exmem_exception_tval_q;
    reg          [31:0]    exmem_pc_q;
    reg          [4:0]     exmem_rd_q;
    reg          [31:0]    memwb_result_q;
    reg                    memwb_fflags_valid_q;
    reg          [4:0]     memwb_fflags_q;
    reg                    memwb_exception_valid_q;
    reg          [4:0]     memwb_exception_cause_q;
    reg          [31:0]    memwb_exception_tval_q;
    reg                    memwb_load_result_valid_q;
    reg          [31:0]    memwb_pc_q;
    reg          [31:0]    memwb_instr_q;
    reg          [4:0]     memwb_rd_q;
    wire mem_ready;
    wire mem_valid;
    wire memwb_ready = !memwb_valid_q || (out_valid_o && out_ready_i);
    wire         [31:0]    mem_result;
    wire                   mem_fflags_valid;
    wire         [4:0]     mem_fflags;
    wire                   mem_exception_valid;
    wire         [4:0]     mem_exception_cause;
    wire         [31:0]    mem_exception_tval;
    wire                   mem_load_result_valid;
    wire pmp_valid;
    wire [31:0] pmp_addr;
    wire [1:0] pmp_size;
    wire [2:0] pmp_access;
    wire pmp_priv_m;
    wire pmp_allow;

    assign in_ready_o = rst_ni && !flush_i && mem_ready;
    assign out_valid_o = rst_ni && memwb_valid_q && (!memwb_lsu_q || res_valid);
    assign mem_valid_o = rst_ni && exmem_valid_q;
    assign mem_pc_o = exmem_pc_q;
    assign mem_fire_o = mem_valid && memwb_ready;
    assign out_result_o = out_exception_valid_o ? 32'd0 : memwb_lsu_q ? res_data : memwb_result_q;
    assign out_fflags_valid_o = memwb_fflags_valid_q;
    assign out_fflags_o = memwb_fflags_q;
    assign out_exception_valid_o = memwb_exception_valid_q || (memwb_lsu_q && res_valid && res_error);
    assign out_exception_cause_o = memwb_exception_valid_q ? memwb_exception_cause_q :
                                   (memwb_lsu_q && res_error) ? res_cause : 5'd0;
    assign out_exception_tval_o = memwb_exception_valid_q ? memwb_exception_tval_q :
                                  (memwb_lsu_q && res_error) ? res_tval : 32'd0;
    assign out_load_result_valid_o = out_valid_o && memwb_lsu_q && !memwb_we_q && !out_exception_valid_o;
    assign out_pc_o = memwb_pc_q;
    assign out_instr_o = memwb_instr_q;
    assign out_rd_o = memwb_rd_q;

    always @(posedge clk_i) begin
        if (!rst_ni || flush_i) begin
            exmem_valid_q <= 1'b0;
        end else if (mem_ready) begin
            exmem_valid_q <= in_valid_i;
            if (in_valid_i) begin
                exmem_lsu_q <= in_lsu_i;
                exmem_we_q <= in_we_i;
                exmem_op_q <= in_op_i;
                exmem_result_q <= in_result_i;
                exmem_store_data_q <= in_store_data_i;
                exmem_instr_q <= in_instr_i;
                exmem_priv_m_q <= in_priv_m_i;
                exmem_fflags_valid_q <= in_fflags_valid_i;
                exmem_fflags_q <= in_fflags_i;
                exmem_exception_valid_q <= in_exception_valid_i;
                exmem_exception_cause_q <= in_exception_cause_i;
                exmem_exception_tval_q <= in_exception_tval_i;
                exmem_pc_q <= in_pc_i;
                exmem_rd_q <= in_rd_i;
            end
        end
        if (!rst_ni) begin
            memwb_valid_q <= 1'b0;
        end else if (memwb_ready) begin
            memwb_valid_q <= mem_valid;
            if (mem_valid) begin
                memwb_result_q <= mem_result;
                memwb_lsu_q <= exmem_lsu_q && !mem_exception_valid;
                memwb_we_q <= exmem_we_q;
                memwb_fflags_valid_q <= mem_fflags_valid;
                memwb_fflags_q <= mem_fflags;
                memwb_exception_valid_q <= mem_exception_valid;
                memwb_exception_cause_q <= mem_exception_cause;
                memwb_exception_tval_q <= mem_exception_tval;
                memwb_load_result_valid_q <= mem_load_result_valid;
                memwb_pc_q <= exmem_pc_q;
                memwb_instr_q <= exmem_instr_q;
                memwb_rd_q <= exmem_rd_q;
            end
        end
    end

    uqu_stage_mem u_mem (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i),
        .valid_i(exmem_valid_q), .ready_o(mem_ready), .valid_o(mem_valid), .ready_i(memwb_ready),
        .lsu_i(exmem_lsu_q),
        .we_i(exmem_we_q),
        .op_i(exmem_op_q),
        .result_i(exmem_result_q),
        .store_data_i(exmem_store_data_q),
        .instr_i(exmem_instr_q),
        .priv_m_i(exmem_priv_m_q),
        .fflags_valid_i(exmem_fflags_valid_q),
        .fflags_i(exmem_fflags_q),
        .exception_valid_i(exmem_exception_valid_q),
        .exception_cause_i(exmem_exception_cause_q),
        .exception_tval_i(exmem_exception_tval_q),
        .lsu_res_flush_i(1'b0), .lsu_res_ready_i(memwb_valid_q && memwb_lsu_q && out_ready_i),
        .lsu_res_valid_o(res_valid), .lsu_res_registered_o(), .lsu_res_data_o(res_data),
        .lsu_res_forward_data_o(),
        .lsu_res_exception_valid_o(res_error), .lsu_res_exception_cause_o(res_cause), .lsu_res_exception_tval_o(res_tval),
        .request_permit_i(request_permit_i && (!memwb_valid_q || (out_valid_o && !out_exception_valid_o))), .lsu_busy_o(lsu_busy_o),
        .pmp_valid_o(pmp_valid), .pmp_addr_o(pmp_addr), .pmp_size_o(pmp_size),
        .pmp_access_o(pmp_access), .pmp_priv_m_o(pmp_priv_m), .pmp_allow_i(pmp_allow),
        .result_o(mem_result),
        .fflags_valid_o(mem_fflags_valid),
        .fflags_o(mem_fflags),
        .exception_valid_o(mem_exception_valid),
        .exception_cause_o(mem_exception_cause),
        .exception_tval_o(mem_exception_tval),
        .load_result_valid_o(mem_load_result_valid),
        .dmem_req_o(dmem_req_o), .dmem_we_o(dmem_we_o), .dmem_addr_o(dmem_addr_o),
        .dmem_wdata_o(dmem_wdata_o), .dmem_be_o(dmem_be_o), .dmem_gnt_i(dmem_gnt_i),
        .dmem_rvalid_i(dmem_rvalid_i), .dmem_rdata_i(dmem_rdata_i), .dmem_err_i(dmem_err_i)
    );

    // One parent-owned block; IF is unused in this MEM-only fixture. The
    // query-valid qualifier is not a handshake and does not gate the checker.
    uqu_pmp #(.ISA_PMP(ISA_PMP)) u_pmp (
        .replay_addr_i(32'd0), .replay_priv_m_i(1'b0), .replay_allow_o(),
        .pmpcfg_i(pmpcfg_i), .pmpaddr_i(pmpaddr_i),
        .if_addr_i(32'd0), .if_size_i(2'd2), .if_priv_m_i(1'b1), .if_allow_o(),
        .mem_addr_i(pmp_addr), .mem_size_i(pmp_size), .mem_access_i(pmp_access),
        .mem_priv_m_i(pmp_priv_m), .mem_allow_o(pmp_allow)
    );
endmodule

`default_nettype wire
