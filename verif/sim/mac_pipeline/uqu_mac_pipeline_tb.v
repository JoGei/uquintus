`default_nettype none
`include "uqu_config.vh"
`include "uqu_ctrl.vh"

// Instruction-level fixture for the internal MAC operation. No ISA encoding is
// invented here. Real EX, MEM, hazard and GPR blocks share parent-owned slots.
module uqu_mac_pipeline_tb #(
    parameter MUA_MUL = `UQU_MUL_DADDA_MAC,
    parameter MUA_FORWARDING = 1,
    parameter MUA_FORWARD_EX_TO_DE = 1,
    parameter MUA_FORWARD_MEM_TO_DE = 1,
    parameter MUA_FORWARD_MEM_TO_EX = 1,
    parameter MUA_FORWARD_WB_TO_EX = 1,
    parameter MUA_DE_OPERAND_RETENTION = 0
) (
    input wire clk_i, rst_ni, flush_i,
    input wire seed_we_i,
    input wire [4:0] seed_addr_i,
    input wire [31:0] seed_data_i,
    input wire in_valid_i, in_mac_i,
    input wire [4:0] in_rs0_i, in_rs1_i, in_rs2_i, in_rd_i,
    output wire in_ready_o,
    input wire out_ready_i,
    output wire out_valid_o,
    output wire [4:0] out_rd_o,
    output wire [31:0] out_data_o,
    output wire ex_fire_o, mem_fire_o
);
    reg ex_valid_q, mem_valid_q, wb_valid_q;
    reg ex_mac_q, mem_mac_q;
    reg [4:0] ex_rd_q, mem_rd_q, wb_rd_q;
    reg [4:0] ex_addr_q [0:2];
    reg [31:0] ex_data_q [0:2];
    reg [2:0] ex_captured_q;
    wire [2:0] used = in_mac_i ? 3'b111 : 3'b011;
    wire [2:0] ex_used = ex_mac_q ? 3'b111 : 3'b011;
    wire late_ex = (MUA_MUL == `UQU_MUL_DADDA_MAC) && ex_mac_q;
    wire [31:0] rf [0:2];
    wire [31:0] de_data [0:2];
    wire [31:0] ex_resolved [0:2];
    wire [2:0] de_ready, de_guaranteed, ex_ready;
    wire de_complete = (((de_ready | de_guaranteed) & used) == used);
    wire ex_operands = ((ex_ready & ex_used & (late_ex ? 3'b011 : 3'b111)) ==
                        (ex_used & (late_ex ? 3'b011 : 3'b111)));
    wire ex_complete, ex_fault, ex_phase2, ex_high, ex_available;
    wire [31:0] ex_result, mem_result;
    wire [63:0] ex_row_a, ex_row_b;
    reg [63:0] mem_row_a_q, mem_row_b_q;
    reg [31:0] mem_c_q, wb_data_q;
    reg [4:0] mem_c_addr_q;
    reg mem_c_captured_q;
    wire [31:0] mem_c;
    wire mem_c_ready, mem_complete, mem_fault;
    wire wb_space = !wb_valid_q || out_ready_i;
    wire mem_space = !mem_valid_q || (mem_complete && wb_space);
    wire ex_space = !ex_valid_q || (ex_complete && mem_space);
    wire in_fire = in_valid_i && in_ready_o;
    assign ex_fire_o = ex_complete && mem_space;
    assign mem_fire_o = mem_complete && wb_space;
    assign in_ready_o = rst_ni && !flush_i && de_complete && ex_space;
    assign out_valid_o = rst_ni && wb_valid_q;
    assign out_rd_o = wb_rd_q;
    assign out_data_o = wb_data_q;

    uqu_gpregfile #(.ISA_M(1), .MUA_MUL(MUA_MUL)) u_gpr (
        .clk_i(clk_i), .rst_ni(rst_ni),
        .raddr0_i(in_rs0_i), .raddr1_i(in_rs1_i), .raddr2_i(in_rs2_i),
        .rdata0_o(rf[0]), .rdata1_o(rf[1]), .rdata2_o(rf[2]),
        .we0_i(seed_we_i || (out_valid_o && out_ready_i)),
        .waddr0_i(seed_we_i ? seed_addr_i : wb_rd_q),
        .wdata0_i(seed_we_i ? seed_data_i : wb_data_q),
        .we1_i(1'b0), .waddr1_i(5'd0), .wdata1_i(32'd0)
    );
    uqu_hazard #(.ISA_M(1), .MUA_MUL(MUA_MUL),
        .MUA_FORWARDING(MUA_FORWARDING), .MUA_FORWARD_EX_TO_DE(MUA_FORWARD_EX_TO_DE),
        .MUA_FORWARD_MEM_TO_DE(MUA_FORWARD_MEM_TO_DE), .MUA_FORWARD_MEM_TO_EX(MUA_FORWARD_MEM_TO_EX),
        .MUA_FORWARD_WB_TO_EX(MUA_FORWARD_WB_TO_EX), .MUA_DE_OPERAND_RETENTION(MUA_DE_OPERAND_RETENTION)
    ) u_hazard (
        .clk_i(clk_i), .rst_ni(rst_ni), .de_valid_i(in_valid_i), .de_clear_i(in_fire || flush_i),
        .de_rs0_addr_i(in_rs0_i), .de_rs1_addr_i(in_rs1_i), .de_rs2_addr_i(in_rs2_i),
        .de_rs0_i(rf[0]), .de_rs1_i(rf[1]), .de_rs2_i(rf[2]), .de_rs_used_i(used), .de_rs_need_now_i(3'd0),
        .de_late_c_i((MUA_MUL == `UQU_MUL_DADDA_MAC) && in_mac_i),
        .ex_late_c_i(late_ex), .ex_primary_registered_i(1'b1), .mem_primary_registered_i(1'b1),
        .de_rs0_o(de_data[0]), .de_rs1_o(de_data[1]), .de_rs2_o(de_data[2]),
        .de_rs_ready_o(de_ready), .de_rs_ex_guaranteed_o(de_guaranteed),
        .ex_valid_i(ex_valid_q), .ex_rs0_addr_i(ex_addr_q[0]), .ex_rs1_addr_i(ex_addr_q[1]), .ex_rs2_addr_i(ex_addr_q[2]),
        .ex_rs0_i(ex_data_q[0]), .ex_rs1_i(ex_data_q[1]), .ex_rs2_i(ex_data_q[2]),
        .ex_rs_used_i(ex_used), .ex_rs_captured_i(ex_captured_q),
        .ex_rs0_o(ex_resolved[0]), .ex_rs1_o(ex_resolved[1]), .ex_rs2_o(ex_resolved[2]), .ex_rs_ready_o(ex_ready),
        .ex_pending_i(2'b01), .ex_rd0_i(ex_rd_q), .ex_rd1_i(5'd0),
        .ex_result_available_i(ex_available), .ex_result_forwardable_i(ex_available), .ex_result_i(ex_result), .ex_advance_i(ex_fire_o),
        .mem_valid_i(mem_valid_q), .mem_pending_i(2'b01), .mem_rd0_i(mem_rd_q), .mem_rd1_i(5'd0),
        .mem_result_available_i(mem_complete), .mem_result_forwardable_i(!mem_fault), .mem_result_i(mem_result), .mem_advance_i(mem_fire_o),
        .mem_late_c_i(mem_mac_q), .mem_c_addr_i(mem_c_addr_q), .mem_c_i(mem_c_q), .mem_c_captured_i(mem_c_captured_q),
        .mem_c_o(mem_c), .mem_c_ready_o(mem_c_ready),
        .wb_valid_i(wb_valid_q), .wb_pending_i(2'b01), .wb_rd0_i(wb_rd_q), .wb_rd1_i(5'd0),
        .wb_result_available_i(1'b1), .wb_result_forwardable_i(1'b1), .wb_result_i(wb_data_q), .wb_advance_i(out_ready_i)
    );
    uqu_stage_ex #(.ISA_M(1), .MUA_MUL(MUA_MUL)) u_ex (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .flush_i(flush_i),
        .valid_i(ex_valid_q),
        .ready_o(),
        .valid_o(ex_complete),
        .ready_i(mem_space),
        .fu_i(`UQU_FU_MULDIV),
        .op_i(ex_mac_q ? `UQU_MDU_MAC : 5'd0),
        .operands_ready_i(ex_operands),
        .a_i(ex_resolved[0]),
        .b_i(ex_resolved[1]),
        .c_i(ex_resolved[2]),
        .muldiv_a_i(ex_resolved[0]),
        .muldiv_b_i(ex_resolved[1]),
        .rm_i(3'd0),
        .pass_data_i(32'd0),
        .store_data_i(32'd0),
        .instr_i(32'd0),
        .exception_valid_i(1'd0),
        .exception_cause_i(5'd0),
        .exception_tval_i(32'd0),
        .result_o(ex_result),
        .result_available_o(ex_available),
        .mul_phase2_o(ex_phase2),
        .mul_high_o(ex_high),
        .mul_row_a_o(ex_row_a),
        .mul_row_b_o(ex_row_b),
        .store_data_o(),
        .fflags_valid_o(),
        .fflags_o(),
        .exception_valid_o(ex_fault),
        .exception_cause_o(),
        .exception_tval_o()
    );
    uqu_stage_mem #(.ISA_M(1), .MUA_MUL(MUA_MUL)) u_mem (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .flush_i(flush_i),
        .valid_i(mem_valid_q),
        .ready_o(),
        .valid_o(mem_complete),
        .ready_i(wb_space),
        .lsu_i(1'd0),
        .we_i(1'd0),
        .op_i(3'd0),
        .result_i(mem_row_a_q[31:0]),
        .store_data_i(mem_row_a_q[63:32]),
        .mul_row_b_i(mem_row_b_q),
        .mul_phase2_i(1'b1),
        .mul_high_i(1'd0),
        .mul_accumulate_i(mem_mac_q),
        .mul_addend_i(mem_c),
        .mul_addend_ready_i(mem_c_ready),
        .instr_i(32'd0),
        .priv_m_i(1'd0),
        .fflags_valid_i(1'd0),
        .fflags_i(5'd0),
        .exception_valid_i(1'd0),
        .exception_cause_i(5'd0),
        .exception_tval_i(32'd0),
        .request_permit_i(1'd0),
        .lsu_busy_o(),
        .lsu_res_ready_i(1'd0),
        .lsu_res_flush_i(1'd0),
        .lsu_res_valid_o(),
        .lsu_res_registered_o(),
        .lsu_res_data_o(),
        .lsu_res_forward_data_o(),
        .lsu_res_exception_valid_o(),
        .lsu_res_exception_cause_o(),
        .lsu_res_exception_tval_o(),
        .pmp_valid_o(),
        .pmp_addr_o(),
        .pmp_size_o(),
        .pmp_access_o(),
        .pmp_priv_m_o(),
        .pmp_allow_i(1'd0),
        .result_o(mem_result),
        .load_result_valid_o(),
        .fflags_valid_o(),
        .fflags_o(),
        .exception_valid_o(mem_fault),
        .exception_cause_o(),
        .exception_tval_o(),
        .dmem_req_o(),
        .dmem_we_o(),
        .dmem_addr_o(),
        .dmem_wdata_o(),
        .dmem_be_o(),
        .dmem_gnt_i(1'd0),
        .dmem_rvalid_i(1'd0),
        .dmem_rdata_i(32'd0),
        .dmem_err_i(1'd0)
    );

    genvar n;
    generate for (n=0; n<3; n=n+1) begin : gen_operand
        always @(posedge clk_i) begin
            if (rst_ni && !flush_i) begin
                if (in_fire) begin
                    ex_addr_q[n] <= n == 0 ? in_rs0_i : n == 1 ? in_rs1_i : in_rs2_i;
                    ex_data_q[n] <= de_data[n];
                end else if (ex_valid_q && !ex_fire_o && !ex_captured_q[n] && ex_ready[n]) begin
                    ex_data_q[n] <= ex_resolved[n];
                end
            end
        end
    end endgenerate
    always @(posedge clk_i) begin
        if (!rst_ni || flush_i) begin
            ex_valid_q <= 1'b0;
            mem_valid_q <= 1'b0;
            wb_valid_q <= 1'b0;
            ex_captured_q <= 3'd0;
            mem_c_captured_q <= 1'b0;
        end else begin
            if (ex_space) begin
                ex_valid_q <= in_fire;
                ex_captured_q <= de_ready;
                if (in_fire) begin
                    ex_rd_q <= in_rd_i;
                    ex_mac_q <= in_mac_i;
                end
            end else begin
                ex_captured_q <= ex_captured_q | (ex_ready & ex_used);
            end
            if (mem_space) begin
                mem_valid_q <= ex_fire_o;
                if (ex_fire_o) begin
                    mem_row_a_q <= ex_row_a;
                    mem_row_b_q <= ex_row_b;
                    mem_rd_q <= ex_rd_q;
                    mem_mac_q <= ex_mac_q;
                    mem_c_q <= ex_resolved[2];
                    mem_c_addr_q <= ex_addr_q[2];
                    mem_c_captured_q <= ex_ready[2];
                end
            end else if (mem_valid_q && !mem_c_captured_q && mem_c_ready) begin
                mem_c_q <= mem_c;
                mem_c_captured_q <= 1'b1;
            end
            if (wb_space) begin
                wb_valid_q <= mem_fire_o;
                if (mem_fire_o) begin
                    wb_rd_q <= mem_rd_q;
                    wb_data_q <= mem_result;
                end
            end
        end
    end
endmodule
`default_nettype wire
