`default_nettype none

// MEM execution/control only. The parent owns EX/MEM and MEM/WB payloads,
// instruction identity, validity, and the core-wide PMP block.
module uqu_stage_mem (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        flush_i,
    input  wire        valid_i,
    output wire        ready_o,
    output wire        valid_o,
    input  wire        ready_i,
    input  wire        lsu_i,
    input  wire        we_i,
    input  wire [2:0]  op_i,
    input  wire [31:0] result_i,
    input  wire [31:0] store_data_i,
    input  wire [31:0] instr_i,
    input  wire        priv_m_i,
    input  wire        fflags_valid_i,
    input  wire [4:0]  fflags_i,
    input  wire        exception_valid_i,
    input  wire [4:0]  exception_cause_i,
    input  wire [31:0] exception_tval_i,
    input  wire        request_permit_i,
    output wire        lsu_busy_o,
    input  wire        lsu_res_ready_i,
    input  wire        lsu_res_flush_i,
    output wire        lsu_res_valid_o,
    output wire        lsu_res_registered_o,
    output wire [31:0] lsu_res_data_o,
    output wire        lsu_res_exception_valid_o,
    output wire [4:0]  lsu_res_exception_cause_o,
    output wire [31:0] lsu_res_exception_tval_o,
    output wire        pmp_valid_o,
    output wire [31:0] pmp_addr_o,
    output wire [1:0]  pmp_size_o,
    output wire [2:0]  pmp_access_o,
    output wire        pmp_priv_m_o,
    input  wire        pmp_allow_i,
    output wire [31:0] result_o,
    output wire        load_result_valid_o,
    output wire        fflags_valid_o,
    output wire [4:0]  fflags_o,
    output wire        exception_valid_o,
    output wire [4:0]  exception_cause_o,
    output wire [31:0] exception_tval_o,
    output wire        dmem_req_o,
    output wire        dmem_we_o,
    output wire [31:0] dmem_addr_o,
    output wire [31:0] dmem_wdata_o,
    output wire [3:0]  dmem_be_o,
    input  wire        dmem_gnt_i,
    input  wire        dmem_rvalid_i,
    input  wire [31:0] dmem_rdata_i,
    input  wire        dmem_err_i
);
    // One-shot LSU acceptance tracking, not a pipeline boundary-valid bit.
    reg issued_q;
    reg cancel_response_q;
    wire enabled = rst_ni && !flush_i;
    wire active = enabled && valid_i;
    wire lsu_req_valid = active && lsu_i && !exception_valid_i && !issued_q;
    wire lsu_req_ready;
    wire lsu_exception_valid;
    wire [4:0] lsu_exception_cause;
    wire [31:0] lsu_exception_tval;
    wire lsu_req_fire = lsu_req_valid && lsu_req_ready;
    wire mem_fire = valid_o && ready_i;

    // Grant transfers ownership into the parent's MEM/WB boundary. Local
    // faults transfer directly as exception metadata without a bus request.
    assign valid_o = active && (exception_valid_i || !lsu_i ||
                               lsu_exception_valid || issued_q || lsu_req_fire);
    assign ready_o = enabled && (!valid_i || mem_fire);
    assign exception_valid_o = active && (exception_valid_i ||
                                          lsu_exception_valid);
    assign exception_cause_o = !exception_valid_o ? 5'd0 :
        exception_valid_i ? exception_cause_i : lsu_exception_cause;
    assign exception_tval_o = !exception_valid_o ? 32'd0 :
        exception_valid_i ? exception_tval_i : lsu_exception_tval;
    assign result_o = !valid_o || exception_valid_o ? 32'd0 :
                     result_i;
    assign load_result_valid_o = 1'b0; // Load values become available in WB.
    assign fflags_valid_o = valid_o && !exception_valid_o && !lsu_i && fflags_valid_i;
    assign fflags_o = fflags_valid_o ? fflags_i : 5'd0;

    // Pure combinational query into the parent's two-port PMP block. The LSU
    // captures denial at native acceptance; later PMP inputs cannot change it.
    assign pmp_valid_o = lsu_req_valid;
    assign pmp_addr_o = pmp_valid_o ? result_i : 32'd0;
    assign pmp_size_o = pmp_valid_o ? op_i[1:0] : 2'd0;
    assign pmp_access_o = !pmp_valid_o ? 3'd0 : we_i ? 3'b010 : 3'b001;
    assign pmp_priv_m_o = pmp_valid_o && priv_m_i;

    always @(posedge clk_i) begin
        if (!rst_ni) cancel_response_q <= 1'b0;
        else cancel_response_q <= flush_i && issued_q;
        if (!rst_ni || flush_i) begin
            issued_q <= 1'b0;
        end else if (mem_fire) begin
            issued_q <= 1'b0;
        end else if (lsu_req_fire) begin
            issued_q <= 1'b1;
        end
    end

    uqu_lsu u_lsu (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i),
        .res_flush_i(lsu_res_flush_i || cancel_response_q),
        .req_valid_i(lsu_req_valid), .req_ready_o(lsu_req_ready),
        .req_we_i(we_i), .req_op_i(op_i), .req_addr_i(result_i),
        .req_wdata_i(store_data_i), .req_instr_i(instr_i),
        .req_access_fault_i(!pmp_allow_i), .request_permit_i(request_permit_i && ready_i),
        .req_exception_valid_o(lsu_exception_valid),
        .req_exception_cause_o(lsu_exception_cause),
        .req_exception_tval_o(lsu_exception_tval),
        .busy_o(lsu_busy_o), .res_valid_o(lsu_res_valid_o),
        .res_ready_i(lsu_res_ready_i), .res_registered_o(lsu_res_registered_o),
        .res_data_o(lsu_res_data_o),
        .res_exception_valid_o(lsu_res_exception_valid_o),
        .res_exception_cause_o(lsu_res_exception_cause_o),
        .res_exception_tval_o(lsu_res_exception_tval_o),
        .dmem_req_o(dmem_req_o), .dmem_we_o(dmem_we_o),
        .dmem_addr_o(dmem_addr_o), .dmem_wdata_o(dmem_wdata_o), .dmem_be_o(dmem_be_o),
        .dmem_gnt_i(dmem_gnt_i), .dmem_rvalid_i(dmem_rvalid_i),
        .dmem_rdata_i(dmem_rdata_i), .dmem_err_i(dmem_err_i)
    );
endmodule

`default_nettype wire
