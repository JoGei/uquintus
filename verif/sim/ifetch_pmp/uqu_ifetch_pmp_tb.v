`default_nettype none

// Verification-only core region: one shared PMP supplies both real requesters.
module uqu_ifetch_pmp_tb #(
    parameter ISA_PMP = 0
) (
    input wire clk_i,
    input wire rst_ni,
    input wire [127:0] pmpcfg_i,
    input wire [511:0] pmpaddr_i,
    input wire if_valid_i,
    output wire if_ready_o,
    input wire [31:0] if_addr_i,
    input wire if_priv_m_i,
    input wire if_flush_i,
    input wire if_permit_i,
    output wire if_allow_o,
    output wire if_busy_o,
    output wire if_result_valid_o,
    input wire if_result_ready_i,
    output wire [31:0] if_result_addr_o,
    output wire [31:0] if_result_data_o,
    output wire if_result_error_o,
    input wire mem_valid_i,
    output wire mem_ready_o,
    input wire [31:0] mem_addr_i,
    input wire mem_priv_m_i,
    input wire mem_we_i,
    input wire [2:0] mem_op_i,
    input wire [31:0] mem_wdata_i,
    input wire mem_flush_i,
    input wire mem_permit_i,
    output wire mem_allow_o,
    output wire mem_busy_o,
    output wire mem_result_valid_o,
    input wire mem_result_ready_i,
    output wire [31:0] mem_result_data_o,
    output wire mem_exception_valid_o,
    output wire [4:0] mem_exception_cause_o,
    output wire [31:0] mem_exception_tval_o,
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
    input wire dmem_err_i
);
    uqu_pmp #(.ISA_PMP(ISA_PMP)) u_pmp (
        .replay_addr_i(32'd0), .replay_priv_m_i(1'b0), .replay_allow_o(),
        .pmpcfg_i(pmpcfg_i), .pmpaddr_i(pmpaddr_i),
        .if_addr_i({if_addr_i[31:2], 2'b00}), .if_size_i(2'd2),
        .if_priv_m_i(if_priv_m_i), .if_allow_o(if_allow_o),
        .mem_addr_i(mem_addr_i), .mem_size_i(mem_op_i[1:0]),
        .mem_access_i(mem_we_i ? 3'b010 : 3'b001),
        .mem_priv_m_i(mem_priv_m_i), .mem_allow_o(mem_allow_o)
    );
    uqu_ifetch u_ifetch (
        .clear_i(1'b0), .replace_i(1'b0),
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(if_flush_i),
        .req_valid_i(if_valid_i), .req_ready_o(if_ready_o), .req_addr_i(if_addr_i),
        .req_access_fault_i(!if_allow_o), .request_permit_i(if_permit_i),
        .busy_o(if_busy_o), .res_valid_o(if_result_valid_o), .res_ready_i(if_result_ready_i),
        .res_addr_o(if_result_addr_o), .res_data_o(if_result_data_o), .res_error_o(if_result_error_o),
        .imem_req_o(imem_req_o), .imem_addr_o(imem_addr_o), .imem_gnt_i(imem_gnt_i),
        .imem_rvalid_i(imem_rvalid_i), .imem_rdata_i(imem_rdata_i), .imem_err_i(imem_err_i)
    );
    wire req_ready, req_fault, res_valid, res_fault;
    wire [4:0] req_cause, res_cause;
    wire [31:0] req_tval, res_tval;
    assign mem_ready_o = req_ready || (req_fault && mem_result_ready_i);
    assign mem_result_valid_o = req_fault || res_valid;
    assign mem_exception_valid_o = req_fault || res_fault;
    assign mem_exception_cause_o = req_fault ? req_cause : res_cause;
    assign mem_exception_tval_o = req_fault ? req_tval : res_tval;
    uqu_lsu u_lsu (
        .res_flush_i(mem_flush_i), .res_registered_o(),
        .req_exception_valid_o(req_fault), .req_exception_cause_o(req_cause), .req_exception_tval_o(req_tval),
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(mem_flush_i),
        .req_valid_i(mem_valid_i), .req_ready_o(req_ready),
        .req_addr_i(mem_addr_i), .req_we_i(mem_we_i), .req_op_i(mem_op_i),
        .req_wdata_i(mem_wdata_i), .req_instr_i(32'd0),
        .req_access_fault_i(!mem_allow_o), .request_permit_i(mem_permit_i),
        .busy_o(mem_busy_o), .res_valid_o(res_valid), .res_ready_i(mem_result_ready_i),
        .res_data_o(mem_result_data_o), .res_exception_valid_o(res_fault),
        .res_exception_cause_o(res_cause), .res_exception_tval_o(res_tval),
        .dmem_req_o(dmem_req_o), .dmem_we_o(dmem_we_o), .dmem_addr_o(dmem_addr_o),
        .dmem_wdata_o(dmem_wdata_o), .dmem_be_o(dmem_be_o), .dmem_gnt_i(dmem_gnt_i),
        .dmem_rvalid_i(dmem_rvalid_i), .dmem_rdata_i(dmem_rdata_i), .dmem_err_i(dmem_err_i)
    );
endmodule

`default_nettype wire
