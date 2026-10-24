`default_nettype none
`include "uqu_ctrl.vh"
`include "uqu_config.vh"

// DE execution/control only. The parent owns IF/DE and DE/EX registers,
// instruction identity, GPRs, hazards, global events and XIF ID allocation.
module uqu_stage_de #(
    parameter ISA_E = 0,
    parameter ISA_M = 0,
    parameter MUA_MUL = `UQU_MUL_DADDA_MAC,
    parameter ISA_C = 0,
    parameter MUA_C_IMPL = `UQU_C_IMPL_DECOMPRESS,
    parameter MUA_C_DECOMPRESS_STAGE = `UQU_C_DECOMPRESS_IF,
    parameter ISA_ZFINX = 0,
    parameter ISA_ZIFENCEI = 0,
    parameter ISA_F = 0,
    parameter ISA_A = 0,
    parameter ISA_UMODE = 1,
    parameter XIF = 0,
    parameter XIF_NUM_RS = 3,
    parameter XIF_DUALWRITE = 0,
    parameter DEBUG = 0
) (
    input  wire                           clk_i,
    input  wire                           rst_ni,
    input  wire                           flush_i,
    input  wire                           valid_i,
    output wire                           ready_o,
    output wire                           valid_o,
    input  wire                           ready_i,
    input  wire                           permit_i,
    input  wire [31:0]                    pc_i,
    input  wire [31:0]                    instr_i,
    input  wire [31:0]                    original_instr_i,
    input  wire                           compressed_i,
    input  wire                           priv_m_i,
    input  wire                           debug_mode_i,
    input  wire                           tw_i,
    input  wire [2:0]                     frm_i,
    input  wire                           exception_valid_i,
    input  wire [4:0]                     exception_cause_i,
    input  wire [31:0]                    exception_tval_i,
    input  wire [31:0]                    rs0_i,
    input  wire [31:0]                    rs1_i,
    input  wire [31:0]                    rs2_i,
    input  wire [2:0]                     rs_ready_i,
    input  wire [2:0]                     rs_ex_guaranteed_i,
    output wire [4:0]                     rs0_addr_o,
    output wire [4:0]                     rs1_addr_o,
    output wire [4:0]                     rs2_addr_o,
    output wire [2:0]                     rs_used_o,
    output wire [2:0]                     rs_need_now_o,
    output wire [2:0]                     rs_ex_used_o,
    output wire [2:0]                     rs_captured_o,
    output wire                           native_o,
    output wire                           late_c_o,
    output wire [1:0]                     fu_o,
    output wire [4:0]                     op_o,
    output wire [1:0]                     a_sel_o,
    output wire [1:0]                     b_sel_o,
    output wire [31:0]                    imm_o,
    output wire [31:0]                    a_o,
    output wire [31:0]                    b_o,
    output wire [31:0]                    c_o,
    output wire [2:0]                     rm_o,
    output wire [31:0]                    pass_data_o,
    output wire [31:0]                    store_data_o,
    output wire                           rd_we_o,
    output wire [4:0]                     rd_o,
    output wire [4:0]                     rd1_o,
    output wire [1:0]                     rd_pending_o,
    output wire                           lsu_o,
    output wire                           mem_we_o,
    output wire [2:0]                     mem_op_o,
    output wire [2:0]                     wb_kind_o,
    output wire [2:0]                     system_o,
    output wire                           serialize_o,
    output wire [11:0]                    csr_addr_o,
    output wire [2:0]                     csr_op_o,
    output wire [31:0]                    csr_src_o,
    output wire                           csr_src_zero_o,
    output wire                           control_flow_o,
    output wire                           branch_resolve_o,
    output wire                           branch_taken_o,
    output wire [31:0]                    branch_target_o,
    output wire [31:0]                    next_pc_o,
    output wire                           exception_valid_o,
    output wire [4:0]                     exception_cause_o,
    output wire [31:0]                    exception_tval_o,
    input  wire                           xif_force_i,
    input  wire                           xif_id_valid_i,
    input  wire [2:0]                     xif_id_i,
    input  wire [31:0]                    hart_id_i,
    output wire                           xif_issued_o,
    output wire                           xif_accepted_o,
    output wire                           xif_cleanup_valid_o,
    output wire [2:0]                     xif_cleanup_id_o,
    input  wire                           xif_cleanup_ready_i,
    output wire                           xif_issue_valid_o,
    input  wire                           xif_issue_ready_i,
    output wire [31:0]                    xif_issue_instr_o,
    output wire [31:0]                    xif_issue_hartid_o,
    output wire [2:0]                     xif_issue_id_o,
    input  wire                           xif_issue_accept_i,
    input  wire [XIF_DUALWRITE:0]         xif_issue_writeback_i,
    input  wire [XIF_NUM_RS-1:0]          xif_issue_register_read_i,
    output wire                           xif_register_valid_o,
    input  wire                           xif_register_ready_i,
    output wire [31:0]                    xif_register_hartid_o,
    output wire [2:0]                     xif_register_id_o,
    output wire [32*XIF_NUM_RS-1:0]       xif_register_rs_o,
    output wire [XIF_NUM_RS-1:0]          xif_register_rs_valid_o
);

    localparam [4:0] CAUSE_MISALIGNED = 5'd0;
    localparam [4:0] CAUSE_ILLEGAL = 5'd2;
    localparam [4:0] CAUSE_ECALL_U = 5'd8;
    localparam [4:0] CAUSE_ECALL_M = 5'd11;
    wire enabled = rst_ni && !flush_i;
    wire active = enabled && valid_i;
    wire debug_mode = (DEBUG == 1) && debug_mode_i;
    wire machine = (ISA_UMODE == 0) || priv_m_i || debug_mode;
    wire dec_native, dec_illegal, dec_illegal_c, unused_dec_illegal_reg;
    // IF marks an extension-expanded compressed instruction for mandatory
    // re-offload, even if the expansion resembles a native 32-bit instruction.
    wire core_native = dec_native && !((XIF == 1) && xif_force_i);
    wire [2:0] dec_rs_used;
    wire [4:0] dec_rs0, dec_rs1, dec_rs2, dec_rd;
    wire dec_rd_we;
    wire [31:0] dec_imm;
    wire [1:0] dec_fu, dec_a_sel, dec_b_sel, dec_branch;
    wire [4:0] dec_op;
    wire dec_pass_link, dec_lsu, dec_mem_we, dec_serialize, dec_csr_imm;
    wire [2:0] dec_branch_op, dec_mem_op, dec_wb_kind, dec_system, dec_csr_op, dec_rm;
    wire [11:0] dec_csr_addr;
    wire [2:0] effective_rm = (dec_rm == `UQU_RM_DYN) ? frm_i : dec_rm;
    wire rounding_illegal = (dec_fu == `UQU_FU_FPU) && (dec_rm == `UQU_RM_DYN) &&
                            (frm_i > `UQU_RM_RMM);
    wire privilege_illegal = ((dec_system == `UQU_SYS_MRET) && (!machine || debug_mode)) ||
        ((dec_system == `UQU_SYS_DRET) && !debug_mode) ||
        ((dec_system == `UQU_SYS_WFI) && !machine && tw_i);
    wire length_illegal = (ISA_C == 0) && compressed_i;
    wire native_illegal = core_native && (dec_illegal || privilege_illegal || rounding_illegal);
    wire force_illegal = (XIF == 1) && xif_force_i && ((ISA_C == 0) || !compressed_i);
    wire pre_fault = exception_valid_i || length_illegal || native_illegal || force_illegal || dec_illegal_c;
    wire xif_candidate = (XIF == 1) && !core_native && !pre_fault;
    wire xif_done, xif_accept, xif_bad, xif_clean;
    wire [1:0] xif_writeback;
    wire native_live = active && core_native && !pre_fault;
    // Candidate source intent/addressing is independent of slot/control
    // qualification. The parent hazard unit owns slot validity; DE transfer,
    // redirects, faults and XIF handshakes remain qualified below.
    wire native_sources = core_native && !pre_fault;
    wire xif_sources = xif_candidate && !xif_done;
    wire [2:0] native_need_now = ((dec_branch != `UQU_BR_NONE) ||
                                (dec_wb_kind == `UQU_WB_CSR)) ? dec_rs_used : 3'd0;
    wire now_ready = ((rs_ready_i & rs_need_now_o) == rs_need_now_o);
    wire ex_ready = (((rs_ready_i | rs_ex_guaranteed_i) & rs_ex_used_o) == rs_ex_used_o);
    wire branch_taken, unused_branch_illegal, branch_misaligned;
    wire [31:0] branch_target, branch_next_pc, branch_link;
    wire branch_fault = native_live && (dec_branch != `UQU_BR_NONE) && now_ready && branch_misaligned;
    wire ecall_fault = native_live && (dec_system == `UQU_SYS_ECALL);
    wire unknown_fault = !core_native && ((XIF == 0) || (xif_done && (!xif_accept || xif_bad)));
    wire fault = pre_fault || branch_fault || ecall_fault || unknown_fault;
    wire [31:0] illegal_tval = compressed_i ? {16'd0, original_instr_i[15:0]} : original_instr_i;
    wire offload_ready = xif_done && ((xif_accept && !xif_bad) || xif_clean);
    wire completed = fault ? (!xif_done || xif_clean) :
                     xif_candidate ? offload_ready : now_ready && ex_ready;
    wire de_fire = valid_o && ready_i;
    wire payload = active && !fault;
    wire native_payload = payload && core_native;
    wire xif_payload = payload && xif_done && xif_accept;
    wire [1:0] destination_write = native_payload ? {1'b0, dec_rd_we} :
                                  xif_payload ? xif_writeback : 2'd0;
    wire destination_pair = destination_write[1];
    wire [4:0] destination = native_payload ? dec_rd :
                            xif_payload && (|xif_writeback) ? instr_i[11:7] : 5'd0;
    wire ignored_pair = destination_pair && (destination == 5'd0);

    assign native_o = active && core_native;
    // Source intent never depends on the comparison result or live XIF response:
    // parent hazard/readiness feedback and XIF requests must remain acyclic.
    assign rs_used_o = native_sources ? dec_rs_used : xif_sources ?
                       ((XIF_NUM_RS == 3) ? 3'b111 : 3'b011) : 3'd0;
    assign rs_need_now_o = native_sources ? native_need_now : xif_sources ? rs_used_o : 3'd0;
    assign rs_ex_used_o = native_sources && (dec_fu != `UQU_FU_PASS) ? dec_rs_used : 3'd0;
    assign rs0_addr_o = native_sources ? dec_rs0 : xif_sources ? instr_i[19:15] : 5'd0;
    assign rs1_addr_o = native_sources ? dec_rs1 : xif_sources ? instr_i[24:20] : 5'd0;
    assign rs2_addr_o = native_sources ? dec_rs2 : xif_sources && (XIF_NUM_RS == 3) ? instr_i[11:7] : 5'd0;
    assign rs_captured_o = rs_used_o & rs_ready_i;
    assign valid_o = active && permit_i && completed;
    assign ready_o = enabled && (!valid_i || de_fire);
    assign exception_valid_o = active && fault;
    assign exception_cause_o = !exception_valid_o ? 5'd0 : exception_valid_i ? exception_cause_i :
                              pre_fault || unknown_fault ? CAUSE_ILLEGAL :
                              branch_fault ? CAUSE_MISALIGNED : machine ? CAUSE_ECALL_M : CAUSE_ECALL_U;
    assign exception_tval_o = !exception_valid_o ? 32'd0 : exception_valid_i ? exception_tval_i :
                             pre_fault || unknown_fault ? illegal_tval : branch_fault ? branch_target : 32'd0;
    assign serialize_o = active && (fault || (core_native && dec_serialize));
    assign control_flow_o = native_live && (dec_branch != `UQU_BR_NONE);
    assign branch_resolve_o = de_fire && !fault && control_flow_o;
    assign branch_taken_o = branch_resolve_o && branch_taken;
    assign branch_target_o = control_flow_o ? branch_target : 32'd0;
    // Misaligned/illegal branch candidates already select pc_i in u_branch.
    // Other instruction faults retain the old PC fallback without introducing
    // live flush, validity or source-readiness control into this data word.
    assign next_pc_o = pre_fault || unknown_fault ||
                       (core_native && (dec_system == `UQU_SYS_ECALL)) ? pc_i : branch_next_pc;
    // Operand-consumption metadata must not depend on operand readiness/faults.
    assign late_c_o = (MUA_MUL == `UQU_MUL_DADDA_MAC) && native_sources &&
        (dec_fu == `UQU_FU_MULDIV) && (dec_op == `UQU_MDU_MAC);
    assign fu_o = native_payload ? dec_fu : `UQU_FU_PASS;
    assign op_o = native_payload ? dec_op : 5'd0;
    assign a_sel_o = native_payload ? dec_a_sel : `UQU_A_ZERO;
    assign b_sel_o = native_payload ? dec_b_sel : `UQU_B_ZERO;
    assign imm_o = native_payload ? dec_imm : 32'd0;
    assign a_o = !native_payload ? 32'd0 : dec_a_sel == `UQU_A_PC ? pc_i :
                 dec_a_sel == `UQU_A_RS1 && rs_ready_i[0] ? rs0_i : 32'd0;
    assign b_o = !native_payload ? 32'd0 : dec_b_sel == `UQU_B_IMM ? dec_imm :
                 dec_b_sel == `UQU_B_RS2 && rs_ready_i[1] ? rs1_i : 32'd0;
    assign c_o = native_payload && dec_rs_used[2] && rs_ready_i[2] ? rs2_i : 32'd0;
    assign rm_o = native_payload ? effective_rm : 3'd0;
    assign pass_data_o = native_payload && dec_pass_link ? branch_link : 32'd0;
    assign store_data_o = native_payload && dec_mem_we && rs_ready_i[1] ? rs1_i : 32'd0;
    assign rd_we_o = destination_write[0];
    assign rd_o = destination;
    assign rd1_o = destination_pair ? destination + 5'd1 : 5'd0;
    assign rd_pending_o = ignored_pair ? 2'd0 :
                          {destination_write[1], destination_write[0] && (destination != 5'd0)};
    assign lsu_o = native_payload && dec_lsu;
    assign mem_we_o = native_payload && dec_mem_we;
    assign mem_op_o = native_payload ? dec_mem_op : 3'd0;
    assign wb_kind_o = native_payload ? dec_wb_kind : xif_payload ? `UQU_WB_XIF : `UQU_WB_RESULT;
    assign system_o = native_payload ? dec_system : `UQU_SYS_NONE;
    assign csr_addr_o = native_payload ? dec_csr_addr : 12'd0;
    assign csr_op_o = native_payload ? dec_csr_op : 3'd0;
    assign csr_src_o = native_payload && (dec_wb_kind == `UQU_WB_CSR) ?
                      (dec_csr_imm ? dec_imm : rs_ready_i[0] ? rs0_i : 32'd0) : 32'd0;
    assign csr_src_zero_o = native_payload && (dec_wb_kind == `UQU_WB_CSR) &&
                           (instr_i[19:15] == 5'd0);

    uqu_decoder_select #(
        .ISA_C(ISA_C), .MUA_C_IMPL(MUA_C_IMPL), .MUA_C_DECOMPRESS_STAGE(MUA_C_DECOMPRESS_STAGE),
        .ISA_E(ISA_E), .ISA_M(ISA_M), .ISA_ZFINX(ISA_ZFINX),
        .ISA_ZIFENCEI(ISA_ZIFENCEI), .ISA_F(ISA_F), .ISA_A(ISA_A), .DEBUG(DEBUG)
    ) u_decoder_select (
        .instr_i(instr_i), .original_instr_i(original_instr_i), .compressed_i(compressed_i),
        .xif_force_i((XIF == 1) && xif_force_i), .illegal_c_o(dec_illegal_c),
        .native_o(dec_native), .illegal_o(dec_illegal),
        .illegal_reg_o(unused_dec_illegal_reg), .rs_used_o(dec_rs_used),
        .rs1_o(dec_rs0), .rs2_o(dec_rs1), .rs3_o(dec_rs2), .rd_we_o(dec_rd_we),
        .rd_o(dec_rd), .imm_o(dec_imm), .fu_o(dec_fu), .op_o(dec_op),
        .a_sel_o(dec_a_sel), .b_sel_o(dec_b_sel), .pass_link_o(dec_pass_link),
        .branch_o(dec_branch), .branch_op_o(dec_branch_op), .lsu_o(dec_lsu),
        .mem_we_o(dec_mem_we), .mem_op_o(dec_mem_op), .wb_kind_o(dec_wb_kind),
        .system_o(dec_system), .serialize_o(dec_serialize), .csr_addr_o(dec_csr_addr),
        .csr_op_o(dec_csr_op), .csr_imm_o(dec_csr_imm), .rm_o(dec_rm)
    );
    uqu_branch #(.ISA_C(ISA_C)) u_branch (
        .branch_i(core_native ? dec_branch : `UQU_BR_NONE), .branch_op_i(dec_branch_op), .pc_i(pc_i),
        .imm_i(dec_imm), .rs1_i(rs0_i), .rs2_i(rs1_i), .compressed_i(compressed_i),
        .taken_o(branch_taken), .target_o(branch_target), .next_pc_o(branch_next_pc),
        .link_o(branch_link), .illegal_o(unused_branch_illegal), .misaligned_o(branch_misaligned)
    );

    generate
        if (XIF == 1) begin : gen_xif
            reg done_q, accept_q, bad_q, clean_q;
            reg [XIF_DUALWRITE:0] writeback_q;
            wire request_valid = active && permit_i && xif_candidate && !done_q && xif_id_valid_i;
            wire issue_fire = request_valid && xif_issue_ready_i;
            wire cleanup_fire = xif_cleanup_valid_o && xif_cleanup_ready_i;
            wire [XIF_NUM_RS-1:0] source_range_bad;
            wire requested_unavailable = |(xif_issue_register_read_i & ~xif_register_rs_valid_o);
            wire read_range_bad = |(xif_issue_register_read_i & source_range_bad);
            wire destination_range_bad = (ISA_E == 1) && (|xif_issue_writeback_i) && instr_i[11];
            wire pair_bad;
            assign xif_done = done_q;
            assign xif_accept = accept_q;
            assign xif_bad = bad_q;
            assign xif_clean = clean_q || cleanup_fire;
            assign xif_writeback = {{(1-XIF_DUALWRITE){1'b0}}, writeback_q};
            assign xif_issued_o = rst_ni && valid_i && done_q;
            assign xif_accepted_o = xif_issued_o && accept_q;
            assign xif_issue_valid_o = request_valid;
            // Allow parallel extension recognition before issue qualification.
            // These fields carry no transaction while issue_valid is low.
            assign xif_issue_instr_o = active ? instr_i : 32'd0;
            assign xif_issue_hartid_o = active ? hart_id_i : 32'd0;
            assign xif_issue_id_o = request_valid ? xif_id_i : 3'd0;
            assign xif_register_valid_o = request_valid;
            assign xif_register_hartid_o = request_valid ? hart_id_i : 32'd0;
            assign xif_register_id_o = request_valid ? xif_id_i : 3'd0;
            assign xif_cleanup_valid_o = active && done_q && (!accept_q || bad_q) && !clean_q;
            assign xif_cleanup_id_o = xif_cleanup_valid_o ? xif_id_i : 3'd0;
            if (XIF_DUALWRITE == 1) begin : gen_pair
                assign pair_bad = xif_issue_writeback_i[1] && instr_i[7];
            end else begin : gen_single
                assign pair_bad = 1'b0;
            end
            genvar slot;
            for (slot = 0; slot < XIF_NUM_RS; slot = slot + 1) begin : gen_source
                reg valid_q;
                reg [31:0] data_q;
                wire [31:0] current_data;
                wire current_ready = rs_ready_i[slot];
                wire [4:0] address;
                if (slot == 0) begin : gen_rs1
                    assign current_data = rs0_i;
                    assign address = instr_i[19:15];
                end else if (slot == 1) begin : gen_rs2
                    assign current_data = rs1_i;
                    assign address = instr_i[24:20];
                end else begin : gen_rs3
                    assign current_data = rs2_i;
                    assign address = instr_i[11:7];
                end
                assign source_range_bad[slot] = (ISA_E == 1) && address[4];
                assign xif_register_rs_valid_o[slot] = request_valid && (valid_q || current_ready);
                assign xif_register_rs_o[32*slot +: 32] = !xif_register_rs_valid_o[slot] ? 32'd0 :
                    valid_q ? data_q : address == 5'd0 ? 32'd0 : current_data;
                always @(posedge clk_i) begin
                    if (!rst_ni || flush_i || !valid_i || de_fire) valid_q <= 1'b0;
                    else if (request_valid && !valid_q && current_ready) valid_q <= 1'b1;
                    if (rst_ni && !flush_i && valid_i && !de_fire &&
                        request_valid && !valid_q && current_ready)
                        data_q <= (address == 5'd0) ? 32'd0 : current_data;
                end
            end
            always @(posedge clk_i) begin
                if (!rst_ni || flush_i || !valid_i || de_fire) begin
                    done_q <= 1'b0;
                    accept_q <= 1'b0;
                    bad_q <= 1'b0;
                    clean_q <= 1'b0;
                end else begin
                    if (issue_fire) begin
                        done_q <= 1'b1;
                        accept_q <= xif_issue_accept_i;
                        bad_q <= xif_issue_accept_i && (requested_unavailable || read_range_bad ||
                                                       destination_range_bad || pair_bad);
                    end
                    if (cleanup_fire) clean_q <= 1'b1;
                end
                if (rst_ni && !flush_i && issue_fire) writeback_q <= xif_issue_writeback_i;
            end
            // Integration supplies matching coupled readies, so issue_ready
            // identifies both handshakes without response-to-request gating.
            wire unused_register_ready = xif_register_ready_i;
        end else begin : gen_no_xif
            assign xif_done = 1'b0;
            assign xif_accept = 1'b0;
            assign xif_bad = 1'b0;
            assign xif_clean = 1'b0;
            assign xif_writeback = 2'd0;
            assign xif_issued_o = 1'b0;
            assign xif_accepted_o = 1'b0;
            assign xif_cleanup_valid_o = 1'b0;
            assign xif_cleanup_id_o = 3'd0;
            assign xif_issue_valid_o = 1'b0;
            assign xif_issue_instr_o = 32'd0;
            assign xif_issue_hartid_o = 32'd0;
            assign xif_issue_id_o = 3'd0;
            assign xif_register_valid_o = 1'b0;
            assign xif_register_hartid_o = 32'd0;
            assign xif_register_id_o = 3'd0;
            assign xif_register_rs_o = {32*XIF_NUM_RS{1'b0}};
            assign xif_register_rs_valid_o = {XIF_NUM_RS{1'b0}};
        end
        if (((ISA_C != 0) && (ISA_C != 1)) || ((ISA_UMODE != 0) && (ISA_UMODE != 1)) ||
            ((XIF != 0) && (XIF != 1)) || ((XIF_NUM_RS != 2) && (XIF_NUM_RS != 3)) ||
            ((XIF_DUALWRITE != 0) && (XIF_DUALWRITE != 1))) begin : gen_invalid
            uqu_stage_de_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
