`default_nettype none

// Verification-only prefetch controller. No DE/IF-DE, decoder, prediction,
// privileged state, or PMP instance: the core's denial is supplied externally.
module uqu_if_prefetch_tb #(
    parameter ISA_C = 0,
    parameter MUA_IF_BUFFER_WORDS = 2
) (
    input wire clk_i,
    input wire rst_ni,
    input wire flush_i,
    input wire [31:0] boot_addr_i,
    input wire [31:0] redirect_addr_i,
    input wire fetch_enable_i,
    input wire request_permit_i,
    input wire req_access_fault_i,
    input wire instr_ready_i,
    output wire instr_valid_o,
    output wire [31:0] instr_o,
    output wire [31:0] pc_o,
    output wire compressed_o,
    output wire [31:0] next_pc_o,
    output wire exception_valid_o,
    output wire [4:0] exception_cause_o,
    output wire [31:0] exception_tval_o,
    output wire fetch_accepted_o,
    output wire [31:0] fetch_addr_o,
    output wire fetch_busy_o,
    output wire push_fire_o,
    output wire pop_fire_o,
    output wire word0_valid_o,
    output wire [31:0] word0_addr_o,
    output wire word1_valid_o,
    output wire [31:0] word1_addr_o,
    output wire association_error_o,
    output wire imem_req_o,
    output wire [31:0] imem_addr_o,
    input wire imem_gnt_i,
    input wire imem_rvalid_i,
    input wire [31:0] imem_rdata_i,
    input wire imem_err_i
);
    reg [31:0] pc_q;
    reg [31:0] fetch_addr_q;
    reg fault_hold_q;
    wire fetch_ready;
    wire fetch_valid = fetch_enable_i && !fault_hold_q && push_ready;
    wire result_valid;
    wire [31:0] result_addr;
    wire [31:0] result_data;
    wire result_error;
    wire push_ready;
    wire [31:0] word0_data;
    wire word0_error;
    wire [31:0] word1_data;
    wire word1_error;
    wire drop_word;

    assign pc_o = pc_q;
    assign fetch_addr_o = fetch_addr_q;
    assign fetch_accepted_o = fetch_valid && fetch_ready;
    assign push_fire_o = result_valid && push_ready;
    assign pop_fire_o = instr_valid_o && instr_ready_i && drop_word;
    assign association_error_o =
        (word0_valid_o && (word0_addr_o != {pc_q[31:2],2'b00})) ||
        (word1_valid_o && (word1_addr_o != word0_addr_o + 32'd4));

    // With one outstanding transaction and no other writer, available space
    // at native acceptance remains reserved until that result is inserted.
    uqu_ifetch u_ifetch (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i),
        .req_valid_i(fetch_valid), .req_ready_o(fetch_ready),
        .req_addr_i(fetch_addr_q), .req_access_fault_i(req_access_fault_i),
        .request_permit_i(request_permit_i), .busy_o(fetch_busy_o),
        .res_valid_o(result_valid), .res_ready_i(push_ready),
        .res_addr_o(result_addr), .res_data_o(result_data), .res_error_o(result_error),
        .imem_req_o(imem_req_o), .imem_addr_o(imem_addr_o), .imem_gnt_i(imem_gnt_i),
        .imem_rvalid_i(imem_rvalid_i), .imem_rdata_i(imem_rdata_i), .imem_err_i(imem_err_i)
    );
    uqu_if_buffer #(.MUA_IF_BUFFER_WORDS(MUA_IF_BUFFER_WORDS)) u_buffer (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i),
        .push_valid_i(result_valid), .push_ready_o(push_ready),
        .push_addr_i(result_addr), .push_data_i(result_data), .push_error_i(result_error),
        .pop_i(pop_fire_o),
        .word0_valid_o(word0_valid_o), .word0_addr_o(word0_addr_o),
        .word0_data_o(word0_data), .word0_error_o(word0_error),
        .word1_valid_o(word1_valid_o), .word1_addr_o(word1_addr_o),
        .word1_data_o(word1_data), .word1_error_o(word1_error)
    );
    uqu_if_aligner #(.ISA_C(ISA_C)) u_aligner (
        .valid_i(rst_ni && !flush_i && !fault_hold_q), .pc_i(pc_q),
        .word0_valid_i(word0_valid_o), .word0_data_i(word0_data), .word0_error_i(word0_error),
        .word1_valid_i(word1_valid_o), .word1_data_i(word1_data), .word1_error_i(word1_error),
        .valid_o(instr_valid_o), .instr_o(instr_o), .compressed_o(compressed_o),
        .next_pc_o(next_pc_o), .drop_word_o(drop_word), .word1_needed_o(), .misaligned_o(),
        .exception_valid_o(exception_valid_o), .exception_cause_o(exception_cause_o),
        .exception_tval_o(exception_tval_o)
    );

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            pc_q <= boot_addr_i;
            fetch_addr_q <= {boot_addr_i[31:2],2'b00};
            fault_hold_q <= 1'b0;
        end else if (flush_i) begin
            pc_q <= redirect_addr_i;
            fetch_addr_q <= {redirect_addr_i[31:2],2'b00};
            fault_hold_q <= 1'b0;
        end else begin
            if (fetch_accepted_o) begin
                fetch_addr_q <= fetch_addr_q + 32'd4;
            end
            if (instr_valid_o && instr_ready_i) begin
                if (exception_valid_o) begin
                    fault_hold_q <= 1'b1;
                end else begin
                    pc_q <= next_pc_o;
                end
            end
        end
    end
endmodule

`default_nettype wire
