`default_nettype none
`include "uqu_config.vh"

// Frontend control/storage, not an IF/DE pipeline register. The core supplies
// accepted redirects, global permits and one shared PMP checker's IF result.
module uqu_stage_if #(
    parameter ISA_C = 0,
    parameter MUA_C_IMPL = `UQU_C_IMPL_DECOMPRESS,
    parameter MUA_C_DECOMPRESS_STAGE = `UQU_C_DECOMPRESS_IF,
    parameter MUA_BRANCH_PREDICTOR = `UQU_BP_NONE,
    parameter MUA_IF_BUFFER_WORDS = 2
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire [31:0] boot_addr_i,
    input  wire        flush_i,
    input  wire        redirect_valid_i,
    input  wire [31:0] redirect_addr_i,
    input  wire        fetch_enable_i,
    input  wire        request_permit_i,
    input  wire        branch_pending_i,
    input  wire        permit_i,
    output wire        valid_o,
    input  wire        ready_i,
    output wire [31:0] pc_o,
    output wire [31:0] instr_o,
    output wire [31:0] original_instr_o,
    output wire        compressed_o,
    output wire [31:0] next_pc_o,
    output wire        exception_valid_o,
    output wire [4:0]  exception_cause_o,
    output wire [31:0] exception_tval_o,
    output wire        misaligned_o,
    output wire        fetch_busy_o,
    input  wire        priv_m_i,
    output wire        pmp_valid_o,
    output wire [31:0] pmp_addr_o,
    output wire [1:0]  pmp_size_o,
    output wire        pmp_priv_m_o,
    input  wire        pmp_allow_i,
    output wire        imem_req_o,
    output wire [31:0] imem_addr_o,
    input  wire        imem_gnt_i,
    input  wire        imem_rvalid_i,
    input  wire [31:0] imem_rdata_i,
    input  wire        imem_err_i
);
    localparam [4:0] CAUSE_ILLEGAL = 5'd2;
    reg [31:0] pc_q;
    reg [31:0] fetch_addr_q;
    reg running_q;
    reg fault_hold_q;
    wire invalidate = flush_i || redirect_valid_i;
    wire active = rst_ni && !invalidate && running_q && !fault_hold_q;
    wire branch_hold = (MUA_BRANCH_PREDICTOR == `UQU_BP_NONE) && branch_pending_i;
    wire fetch_ready;
    wire push_ready;
    wire fetch_valid = active && fetch_enable_i && !branch_hold && !misaligned_o &&
                       !candidate_fault && push_ready;
    wire start_permit = fetch_enable_i && request_permit_i && !branch_hold &&
                        active && !candidate_fault && !misaligned_o;
    wire fetch_fire = fetch_valid && fetch_ready;
    wire result_valid;
    wire [31:0] result_addr, result_data;
    wire result_error;
    wire word0_valid, word1_valid;
    wire [31:0] word0_data, word1_data;
    wire word0_error, word1_error;
    wire selected_valid, selected_compressed, drop_word;
    wire [31:0] selected_instr, selected_next_pc;
    wire access_fault;
    wire [4:0] access_cause;
    wire [31:0] access_tval;
    wire [31:0] normalized_instr;
    wire expansion_fault;
    wire candidate_fault = access_fault || expansion_fault;
    wire transfer = valid_o && ready_i;
    wire pop_word = transfer && !candidate_fault && drop_word;

    assign valid_o = active && permit_i && selected_valid;
    assign pc_o = pc_q;
    assign instr_o = valid_o && !candidate_fault ? normalized_instr : 32'd0;
    assign original_instr_o = valid_o ? selected_instr : 32'd0;
    assign compressed_o = valid_o && selected_compressed;
    assign next_pc_o = valid_o && !candidate_fault ? selected_next_pc : pc_q;
    assign exception_valid_o = valid_o && candidate_fault;
    assign exception_cause_o = !exception_valid_o ? 5'd0 : access_fault ? access_cause : CAUSE_ILLEGAL;
    assign exception_tval_o = !exception_valid_o ? 32'd0 : access_fault ? access_tval : selected_instr;

    // This query is independent of allow. The engine samples the decision at
    // native acceptance, before any bus request, and retains it through waits.
    assign pmp_valid_o = fetch_fire;
    assign pmp_addr_o = pmp_valid_o ? fetch_addr_q : 32'd0;
    assign pmp_size_o = pmp_valid_o ? 2'd2 : 2'd0;
    assign pmp_priv_m_o = pmp_valid_o && priv_m_i;

    uqu_ifetch u_ifetch (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(invalidate),
        .req_valid_i(fetch_valid), .req_ready_o(fetch_ready), .req_addr_i(fetch_addr_q),
        .req_access_fault_i(!pmp_allow_i), .request_permit_i(start_permit),
        .busy_o(fetch_busy_o), .res_valid_o(result_valid), .res_ready_i(push_ready),
        .res_addr_o(result_addr), .res_data_o(result_data), .res_error_o(result_error),
        .imem_req_o(imem_req_o), .imem_addr_o(imem_addr_o), .imem_gnt_i(imem_gnt_i),
        .imem_rvalid_i(imem_rvalid_i), .imem_rdata_i(imem_rdata_i), .imem_err_i(imem_err_i)
    );
    uqu_if_buffer #(.MUA_IF_BUFFER_WORDS(MUA_IF_BUFFER_WORDS)) u_buffer (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(invalidate),
        .push_valid_i(result_valid), .push_ready_o(push_ready),
        .push_addr_i(result_addr), .push_data_i(result_data), .push_error_i(result_error),
        .pop_i(pop_word),
        .word0_valid_o(word0_valid), .word0_addr_o(), .word0_data_o(word0_data), .word0_error_o(word0_error),
        .word1_valid_o(word1_valid), .word1_addr_o(), .word1_data_o(word1_data), .word1_error_o(word1_error)
    );
    uqu_if_aligner #(.ISA_C(ISA_C)) u_aligner (
        .valid_i(active), .pc_i(pc_q),
        .word0_valid_i(word0_valid), .word0_data_i(word0_data), .word0_error_i(word0_error),
        .word1_valid_i(word1_valid), .word1_data_i(word1_data), .word1_error_i(word1_error),
        .valid_o(selected_valid), .instr_o(selected_instr), .compressed_o(selected_compressed),
        .next_pc_o(selected_next_pc), .drop_word_o(drop_word), .word1_needed_o(),
        .misaligned_o(misaligned_o), .exception_valid_o(access_fault),
        .exception_cause_o(access_cause), .exception_tval_o(access_tval)
    );
    generate
        if ((ISA_C == 1) && (MUA_C_IMPL == `UQU_C_IMPL_DECOMPRESS) &&
            (MUA_C_DECOMPRESS_STAGE == `UQU_C_DECOMPRESS_IF)) begin : gen_expand_if
            wire illegal;
            uqu_decompressor #(.ISA_C(1)) u_decompressor (
                .instr_i(selected_instr), .instr_o(normalized_instr), .original_instr_o(),
                .compressed_o(), .illegal_o(illegal), .hint_o()
            );
            assign expansion_fault = selected_valid && !access_fault && selected_compressed && illegal;
        end else begin : gen_raw_if
            assign normalized_instr = selected_instr;
            assign expansion_fault = 1'b0;
        end
        if (((ISA_C != 0) && (ISA_C != 1)) ||
            ((MUA_C_IMPL != `UQU_C_IMPL_DECOMPRESS) && (MUA_C_IMPL != `UQU_C_IMPL_DECODE_COMPRESSED)) ||
            ((MUA_C_DECOMPRESS_STAGE != `UQU_C_DECOMPRESS_IF) &&
             (MUA_C_DECOMPRESS_STAGE != `UQU_C_DECOMPRESS_DE)) ||
            ((MUA_BRANCH_PREDICTOR != `UQU_BP_NONE) &&
             (MUA_BRANCH_PREDICTOR != `UQU_BP_STATIC_NOT_TAKEN))) begin : gen_invalid
            uqu_stage_if_invalid_configuration invalid_configuration ();
        end
    endgenerate

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            pc_q <= boot_addr_i;
            fetch_addr_q <= {boot_addr_i[31:2],2'b00};
            running_q <= 1'b1;
            fault_hold_q <= 1'b0;
        end else if (redirect_valid_i) begin
            pc_q <= redirect_addr_i;
            fetch_addr_q <= {redirect_addr_i[31:2],2'b00};
            running_q <= 1'b1;
            fault_hold_q <= 1'b0;
        end else if (flush_i) begin
            running_q <= 1'b0;
            fault_hold_q <= 1'b0;
        end else begin
            if (fetch_fire) begin
                fetch_addr_q <= fetch_addr_q + 32'd4;
            end
            if (transfer) begin
                if (candidate_fault) begin
                    fault_hold_q <= 1'b1;
                end else begin
                    pc_q <= selected_next_pc;
                end
            end
        end
    end
endmodule

`default_nettype wire
