`default_nettype none
`include "uqu_config.vh"
// Verification-only core parent: real IF/DE and DE/EX storage, GPRs and hazard
// unit. EX computation and MEM/WB producers are externally controlled stubs.
module uqu_de_pipeline_tb #(
    parameter ISA_E = 0,
    parameter ISA_M = 0,
    parameter ISA_C = 0,
    parameter MUA_C_IMPL = `UQU_C_IMPL_DECOMPRESS,
    parameter MUA_C_DECOMPRESS_STAGE = `UQU_C_DECOMPRESS_IF,
    parameter ISA_ZFINX = 0,
    parameter ISA_ZIFENCEI = 0,
    parameter ISA_UMODE = 1,
    parameter DEBUG = 0,
    parameter MUA_FORWARDING = 1,
    parameter MUA_FORWARD_EX_TO_DE = 1,
    parameter MUA_FORWARD_MEM_TO_DE = 1,
    parameter MUA_FORWARD_MEM_TO_EX = 1,
    parameter MUA_FORWARD_WB_TO_EX = 1,
    parameter MUA_DE_OPERAND_RETENTION = 0,
    parameter MUA_REGFILE_IMPL = 0
) (
    input wire  clk_i,
    input wire  rst_ni,
    input wire  flush_i,
    input wire  permit_i,
    input wire  fetch_valid_i,
    output wire  fetch_ready_o,
    input wire [31:0] fetch_instr_i,
    input wire [31:0] fetch_original_i,
    input wire [31:0] fetch_pc_i,
    input wire  fetch_compressed_i,
    input wire  fetch_fault_i,
    input wire [4:0] fetch_cause_i,
    input wire [31:0] fetch_tval_i,
    input wire  out_ready_i,
    input wire  ex_result_available_i,
    input wire  ex_result_forwardable_i,
    input wire [31:0] ex_result_i,
    input wire  mem_valid_i,
    input wire [1:0] mem_pending_i,
    input wire [4:0] mem_rd0_i,
    input wire [4:0] mem_rd1_i,
    input wire  mem_result_available_i,
    input wire  mem_result_forwardable_i,
    input wire [31:0] mem_result_i,
    input wire  mem_advance_i,
    input wire  wb_valid_i,
    input wire [1:0] wb_pending_i,
    input wire [4:0] wb_rd0_i,
    input wire [4:0] wb_rd1_i,
    input wire  wb_result_available_i,
    input wire  wb_result_forwardable_i,
    input wire [31:0] wb_result_i,
    input wire  wb_advance_i,
    output wire  de_slot_valid_o,
    output wire [31:0] de_instr_o,
    output wire [31:0] de_original_o,
    output wire  de_compressed_o,
    output wire  de_fault_o,
    output wire [4:0] de_cause_o,
    output wire [31:0] de_tval_o,
    output wire  de_transfer_o,
    output wire  branch_resolve_o,
    output wire  branch_taken_o,
    output wire [31:0] next_pc_o,
    output wire  ex_valid_o,
    output wire  ex_fault_o,
    output wire [4:0] ex_cause_o,
    output wire [4:0] ex_rd_o,
    output wire [31:0] ex_instr_o,
    output wire [31:0] ex_original_o,
    output wire  ex_compressed_o,
    output wire [31:0] ex_link_o,
    output wire [31:0] ex_pc_o,
    output wire [31:0] ex_tval_o,
    output wire [31:0] ex_a_o,
    output wire [31:0] ex_b_o,
    output wire [31:0] ex_store_data_o,
    output wire [2:0] ex_captured_o,
    output wire [2:0] ex_source_ready_o
);

    reg de_valid_q, de_compressed_q, de_fault_q;
    reg [31:0] de_instr_q, de_original_q, de_pc_q, de_tval_q;
    reg [4:0] de_cause_q;
    reg ex_valid_q, ex_fault_q, ex_mem_we_q, ex_compressed_q;
    reg [31:0] ex_original_q, ex_link_q;
    reg [31:0] ex_instr_q, ex_pc_q, ex_tval_q, ex_imm_q;
    reg [4:0] ex_cause_q, ex_rd_q;
    reg [1:0] ex_pending_q, ex_a_sel_q, ex_b_sel_q;
    reg [2:0] ex_used_q, ex_captured_q;
    reg [4:0] ex_addr_q [0:2];
    reg [31:0] ex_data_q [0:2];
    wire [4:0] de_addr [0:2];
    wire [31:0] gpr [0:2];
    wire [31:0] de_source [0:2];
    wire [31:0] ex_source [0:2];
    wire [2:0] de_used, de_now, de_ex_used, de_captured, de_ready, de_guaranteed, ex_ready;
    wire stage_valid, stage_ready, de_fire, ex_advance;
    wire fault;
    wire [4:0] cause, rd;
    wire [31:0] tval, immediate, link;
    wire [31:0] selected_instr, selected_tval;
    wire selected_fault;
    wire [4:0] selected_cause;
    wire [1:0] pending, a_sel, b_sel;
    wire mem_we;
    wire ex_operands_ready = ((ex_ready & ex_used_q) == ex_used_q);
    assign ex_advance = rst_ni && !flush_i && ex_valid_q && out_ready_i && (ex_operands_ready || ex_fault_q);
    assign de_fire = stage_valid && (!ex_valid_q || ex_advance);
    assign fetch_ready_o = stage_ready;
    assign de_slot_valid_o = de_valid_q;
    assign de_instr_o = de_instr_q;
    assign de_original_o = de_original_q;
    assign de_compressed_o = de_compressed_q;
    assign de_fault_o = de_valid_q && de_fault_q;
    assign de_cause_o = de_cause_q;
    assign de_tval_o = de_tval_q;
    assign de_transfer_o = de_fire;
    assign ex_valid_o = ex_valid_q;
    assign ex_instr_o = ex_instr_q;
    assign ex_original_o = ex_original_q;
    assign ex_compressed_o = ex_compressed_q;
    assign ex_link_o = ex_link_q;
    assign ex_pc_o = ex_pc_q;
    assign ex_fault_o = ex_valid_q && ex_fault_q;
    assign ex_cause_o = ex_cause_q;
    assign ex_tval_o = ex_tval_q;
    assign ex_rd_o = ex_rd_q;
    assign ex_captured_o = ex_captured_q;
    assign ex_source_ready_o = ex_ready;
    assign ex_a_o = ex_a_sel_q == 2'd1 ? ex_pc_q : ex_a_sel_q == 2'd0 ? ex_source[0] : 32'd0;
    assign ex_b_o = ex_b_sel_q == 2'd1 ? ex_imm_q : ex_b_sel_q == 2'd0 ? ex_source[1] : 32'd0;
    assign ex_store_data_o = ex_mem_we_q ? ex_source[1] : 32'd0;
    // Exercise the real IF placement across the parent-owned IF/DE register.
    // DE placement instead instantiates its expander inside uqu_stage_de.
    generate
        if ((ISA_C == 1) && (MUA_C_IMPL == `UQU_C_IMPL_DECOMPRESS) &&
            (MUA_C_DECOMPRESS_STAGE == `UQU_C_DECOMPRESS_IF)) begin : gen_expand_if
            wire [31:0] expanded;
            wire is_compressed, is_illegal;
            wire expansion_fault = fetch_compressed_i && (!is_compressed || is_illegal);
            uqu_decompressor #(.ISA_C(1)) u_decompressor (
                .instr_i(fetch_instr_i), .instr_o(expanded), .original_instr_o(),
                .compressed_o(is_compressed), .illegal_o(is_illegal), .hint_o()
            );
            assign selected_instr = fetch_compressed_i ? (is_compressed ? expanded : 32'd0) : fetch_instr_i;
            assign selected_fault = fetch_fault_i || expansion_fault;
            assign selected_cause = fetch_fault_i ? fetch_cause_i : expansion_fault ? 5'd2 : 5'd0;
            assign selected_tval = fetch_fault_i ? fetch_tval_i :
                                   expansion_fault ? {16'd0, fetch_original_i[15:0]} : 32'd0;
        end else begin : gen_raw_if
            assign selected_instr = fetch_instr_i;
            assign selected_fault = fetch_fault_i;
            assign selected_cause = fetch_cause_i;
            assign selected_tval = fetch_tval_i;
        end
    endgenerate
    always @(posedge clk_i) begin
        if (!rst_ni || flush_i) begin
            de_valid_q <= 1'b0;
            ex_valid_q <= 1'b0;
            ex_captured_q <= 3'd0;
        end else begin
            if (stage_ready) begin
                de_valid_q <= fetch_valid_i;
                if (fetch_valid_i) begin
                    de_instr_q <= selected_instr;
                    de_original_q <= fetch_compressed_i ? {16'd0, fetch_original_i[15:0]} : fetch_original_i;
                    de_pc_q <= fetch_pc_i;
                    de_compressed_q <= fetch_compressed_i;
                    de_fault_q <= selected_fault;
                    de_cause_q <= selected_cause;
                    de_tval_q <= selected_tval;
                end
            end
            if (!ex_valid_q || ex_advance) begin
                ex_valid_q <= stage_valid;
                if (stage_valid) begin
                    ex_instr_q <= de_instr_q;
                    ex_original_q <= de_original_q;
                    ex_compressed_q <= de_compressed_q;
                    ex_link_q <= link;
                    ex_pc_q <= de_pc_q;
                    ex_fault_q <= fault;
                    ex_cause_q <= cause;
                    ex_tval_q <= tval;
                    ex_imm_q <= immediate;
                    ex_rd_q <= rd;
                    ex_pending_q <= pending;
                    ex_a_sel_q <= a_sel;
                    ex_b_sel_q <= b_sel;
                    ex_mem_we_q <= mem_we;
                    ex_used_q <= de_ex_used;
                    ex_captured_q <= de_captured;
                end
            end else if (ex_valid_q) begin
                ex_captured_q <= ex_captured_q | (ex_ready & ex_used_q);
            end
        end
    end
    always @(posedge clk_i) begin
        if (rst_ni && !flush_i) begin
            if ((!ex_valid_q || ex_advance) && stage_valid) begin
                ex_addr_q[0] <= de_addr[0];
                ex_data_q[0] <= de_source[0];
            end else if (ex_valid_q && !ex_advance && ex_used_q[0] && !ex_captured_q[0] && ex_ready[0]) begin
                ex_data_q[0] <= ex_source[0];
            end
        end
    end
    always @(posedge clk_i) begin
        if (rst_ni && !flush_i) begin
            if ((!ex_valid_q || ex_advance) && stage_valid) begin
                ex_addr_q[1] <= de_addr[1];
                ex_data_q[1] <= de_source[1];
            end else if (ex_valid_q && !ex_advance && ex_used_q[1] && !ex_captured_q[1] && ex_ready[1]) begin
                ex_data_q[1] <= ex_source[1];
            end
        end
    end
    always @(posedge clk_i) begin
        if (rst_ni && !flush_i) begin
            if ((!ex_valid_q || ex_advance) && stage_valid) begin
                ex_addr_q[2] <= de_addr[2];
                ex_data_q[2] <= de_source[2];
            end else if (ex_valid_q && !ex_advance && ex_used_q[2] && !ex_captured_q[2] && ex_ready[2]) begin
                ex_data_q[2] <= ex_source[2];
            end
        end
    end
    uqu_gpregfile #(.ISA_E(ISA_E), .ISA_ZFINX(ISA_ZFINX), .MUA_REGFILE_IMPL(MUA_REGFILE_IMPL)) u_gpr (
        .clk_i(clk_i), .rst_ni(rst_ni), .raddr0_i(de_addr[0]), .raddr1_i(de_addr[1]), .raddr2_i(de_addr[2]),
        .rdata0_o(gpr[0]), .rdata1_o(gpr[1]), .rdata2_o(gpr[2]),
        .we0_i(wb_valid_i && wb_advance_i && wb_pending_i[0]), .waddr0_i(wb_rd0_i), .wdata0_i(wb_result_i),
        .we1_i(1'b0), .waddr1_i(5'd0), .wdata1_i(32'd0)
    );
    uqu_hazard #(
        .MUA_FORWARDING(MUA_FORWARDING),
        .MUA_FORWARD_EX_TO_DE(MUA_FORWARD_EX_TO_DE),
        .MUA_FORWARD_MEM_TO_DE(MUA_FORWARD_MEM_TO_DE),
        .MUA_FORWARD_MEM_TO_EX(MUA_FORWARD_MEM_TO_EX),
        .MUA_FORWARD_WB_TO_EX(MUA_FORWARD_WB_TO_EX),
        .MUA_DE_OPERAND_RETENTION(MUA_DE_OPERAND_RETENTION),
        .ISA_E(ISA_E),
        .ISA_ZFINX(ISA_ZFINX)
    ) u_hazard (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .de_valid_i(de_valid_q),
        .de_clear_i(flush_i || de_fire),
        .de_rs0_addr_i(de_addr[0]),
        .de_rs1_addr_i(de_addr[1]),
        .de_rs2_addr_i(de_addr[2]),
        .de_rs0_i(gpr[0]),
        .de_rs1_i(gpr[1]),
        .de_rs2_i(gpr[2]),
        .de_rs_used_i(de_used),
        .de_rs_need_now_i(de_now),
        .de_rs0_o(de_source[0]),
        .de_rs1_o(de_source[1]),
        .de_rs2_o(de_source[2]),
        .de_rs_ready_o(de_ready),
        .de_rs_ex_guaranteed_o(de_guaranteed),
        .ex_valid_i(ex_valid_q),
        .ex_rs0_addr_i(ex_addr_q[0]),
        .ex_rs1_addr_i(ex_addr_q[1]),
        .ex_rs2_addr_i(ex_addr_q[2]),
        .ex_rs0_i(ex_data_q[0]),
        .ex_rs1_i(ex_data_q[1]),
        .ex_rs2_i(ex_data_q[2]),
        .ex_rs_used_i(ex_used_q),
        .ex_rs_captured_i(ex_captured_q),
        .ex_rs0_o(ex_source[0]),
        .ex_rs1_o(ex_source[1]),
        .ex_rs2_o(ex_source[2]),
        .ex_rs_ready_o(ex_ready),
        .ex_pending_i(ex_pending_q),
        .ex_rd0_i(ex_rd_q),
        .ex_rd1_i(5'd0),
        .ex_result_available_i(ex_result_available_i && ex_operands_ready && !ex_fault_q),
        .ex_result_forwardable_i(ex_result_forwardable_i),
        .ex_result_i(ex_result_i),
        .ex_advance_i(ex_advance),
        .mem_valid_i(mem_valid_i),
        .mem_pending_i(mem_pending_i),
        .mem_rd0_i(mem_rd0_i),
        .mem_rd1_i(mem_rd1_i),
        .mem_result_available_i(mem_result_available_i),
        .mem_result_forwardable_i(mem_result_forwardable_i),
        .mem_result_i(mem_result_i),
        .mem_advance_i(mem_advance_i),
        .wb_valid_i(wb_valid_i),
        .wb_pending_i(wb_pending_i),
        .wb_rd0_i(wb_rd0_i),
        .wb_rd1_i(wb_rd1_i),
        .wb_result_available_i(wb_result_available_i),
        .wb_result_forwardable_i(wb_result_forwardable_i),
        .wb_result_i(wb_result_i),
        .wb_advance_i(wb_advance_i)
    );
    uqu_stage_de #(
        .ISA_E(ISA_E),
        .ISA_M(ISA_M),
        .ISA_C(ISA_C),
        .MUA_C_IMPL(MUA_C_IMPL),
        .MUA_C_DECOMPRESS_STAGE(MUA_C_DECOMPRESS_STAGE),
        .ISA_ZFINX(ISA_ZFINX),
        .ISA_ZIFENCEI(ISA_ZIFENCEI),
        .ISA_UMODE(ISA_UMODE),
        .DEBUG(DEBUG)
    ) u_de (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .flush_i(flush_i),
        .valid_i(de_valid_q),
        .ready_o(stage_ready),
        .valid_o(stage_valid),
        .ready_i(!ex_valid_q || ex_advance),
        .permit_i(permit_i),
        .pc_i(de_pc_q),
        .instr_i(de_instr_q),
        .original_instr_i(de_original_q),
        .compressed_i(de_compressed_q),
        .priv_m_i(1'b1),
        .debug_mode_i(1'b0),
        .tw_i(1'b0),
        .frm_i(3'd0),
        .exception_valid_i(de_fault_q),
        .exception_cause_i(de_cause_q),
        .exception_tval_i(de_tval_q),
        .rs0_i(de_source[0]),
        .rs1_i(de_source[1]),
        .rs2_i(de_source[2]),
        .rs_ready_i(de_ready),
        .rs_ex_guaranteed_i(de_guaranteed),
        .rs0_addr_o(de_addr[0]),
        .rs1_addr_o(de_addr[1]),
        .rs2_addr_o(de_addr[2]),
        .rs_used_o(de_used),
        .rs_need_now_o(de_now),
        .rs_ex_used_o(de_ex_used),
        .rs_captured_o(de_captured),
        .native_o(),
        .fu_o(),
        .op_o(),
        .a_sel_o(a_sel),
        .b_sel_o(b_sel),
        .imm_o(immediate),
        .a_o(),
        .b_o(),
        .c_o(),
        .rm_o(),
        .pass_data_o(link),
        .store_data_o(),
        .rd_we_o(),
        .rd_o(rd),
        .rd1_o(),
        .rd_pending_o(pending),
        .lsu_o(),
        .mem_we_o(mem_we),
        .mem_op_o(),
        .wb_kind_o(),
        .system_o(),
        .serialize_o(),
        .csr_addr_o(),
        .csr_op_o(),
        .csr_src_o(),
        .csr_src_zero_o(),
        .control_flow_o(),
        .branch_resolve_o(branch_resolve_o),
        .branch_taken_o(branch_taken_o),
        .branch_target_o(),
        .next_pc_o(next_pc_o),
        .exception_valid_o(fault),
        .exception_cause_o(cause),
        .exception_tval_o(tval),
        .xif_force_i(1'd0),
        .xif_id_valid_i(1'd0),
        .xif_id_i(3'd0),
        .hart_id_i(32'd0),
        .xif_issued_o(),
        .xif_accepted_o(),
        .xif_cleanup_valid_o(),
        .xif_cleanup_id_o(),
        .xif_cleanup_ready_i(1'd0),
        .xif_issue_valid_o(),
        .xif_issue_ready_i(1'd0),
        .xif_issue_instr_o(),
        .xif_issue_hartid_o(),
        .xif_issue_id_o(),
        .xif_issue_accept_i(1'd0),
        .xif_issue_writeback_i(1'd0),
        .xif_issue_register_read_i(3'd0),
        .xif_register_valid_o(),
        .xif_register_ready_i(1'd0),
        .xif_register_hartid_o(),
        .xif_register_id_o(),
        .xif_register_rs_o(),
        .xif_register_rs_valid_o()
    );
endmodule
`default_nettype wire
