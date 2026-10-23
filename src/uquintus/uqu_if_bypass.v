`default_nettype none
`include "uqu_config.vh"

// IF-owned delivery policy around the registered fetched-word FIFO. Its input
// is the ifetch completion, which may be live with ifetch_result enabled.
module uqu_if_bypass #(
    parameter MUA_IF_BUFFER_WORDS = 2,
    parameter MUA_REDIRECT_BYPASS = `UQU_REDIRECT_BYPASS_NONE
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        flush_i,
    input  wire        clear_i,
    input  wire        push_valid_i,
    output wire        push_ready_o,
    input  wire [31:0] push_addr_i,
    input  wire [31:0] push_data_i,
    input  wire        push_error_i,
    input  wire        pop_i,
    output wire        word0_valid_o,
    output wire [31:0] word0_addr_o,
    output wire [31:0] word0_data_o,
    output wire        word0_error_o,
    output wire        word1_valid_o,
    output wire [31:0] word1_addr_o,
    output wire [31:0] word1_data_o,
    output wire        word1_error_o
);
    wire stored0_valid, stored1_valid;
    wire [31:0] stored0_addr, stored1_addr;
    wire [31:0] stored0_data, stored1_data;
    wire stored0_error, stored1_error;
    wire active = rst_ni && !flush_i;
    wire bypass = ((MUA_REDIRECT_BYPASS & `UQU_REDIRECT_BYPASS_IF_BUFFER) != 0);
    wire live0 = active && bypass && !stored0_valid && push_valid_i;
    wire live1 = active && bypass && stored0_valid && !stored1_valid && push_valid_i;
    wire consume_live = live0 && pop_i;
    wire [31:0] live_data = push_error_i ? 32'd0 : push_data_i;

    // A consumed live head must not be inserted and delivered a second time.
    // A live second word is always stored: a crossing instruction consumes
    // only the old head, retaining the second word's remaining halfword.
    uqu_if_buffer #(.MUA_IF_BUFFER_WORDS(MUA_IF_BUFFER_WORDS)) u_buffer (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i), .clear_i(clear_i),
        .push_valid_i(push_valid_i && !consume_live), .push_ready_o(push_ready_o),
        .push_addr_i(push_addr_i), .push_data_i(push_data_i), .push_error_i(push_error_i),
        .pop_i(pop_i && stored0_valid),
        .word0_valid_o(stored0_valid), .word0_addr_o(stored0_addr),
        .word0_data_o(stored0_data), .word0_error_o(stored0_error),
        .word1_valid_o(stored1_valid), .word1_addr_o(stored1_addr),
        .word1_data_o(stored1_data), .word1_error_o(stored1_error)
    );

    assign word0_valid_o = stored0_valid || live0;
    assign word0_addr_o = live0 ? {push_addr_i[31:2],2'b00} : stored0_addr;
    assign word0_data_o = live0 ? live_data : stored0_data;
    assign word0_error_o = live0 ? push_error_i : stored0_error;
    assign word1_valid_o = stored1_valid || live1;
    assign word1_addr_o = live1 ? {push_addr_i[31:2],2'b00} : stored1_addr;
    assign word1_data_o = live1 ? live_data : stored1_data;
    assign word1_error_o = live1 ? push_error_i : stored1_error;

    generate
        if ((MUA_REDIRECT_BYPASS != `UQU_REDIRECT_BYPASS_NONE) &&
            (MUA_REDIRECT_BYPASS != `UQU_REDIRECT_BYPASS_IF_BUFFER) &&
            (MUA_REDIRECT_BYPASS != `UQU_REDIRECT_BYPASS_REDIRECT_REQUEST) &&
            (MUA_REDIRECT_BYPASS != `UQU_REDIRECT_BYPASS_IF_BUFFER_REDIRECT_REQUEST) &&
            (MUA_REDIRECT_BYPASS != `UQU_REDIRECT_BYPASS_IFETCH_RESULT) &&
            (MUA_REDIRECT_BYPASS != `UQU_REDIRECT_BYPASS_IF_BUFFER_IFETCH_RESULT) &&
            (MUA_REDIRECT_BYPASS != `UQU_REDIRECT_BYPASS_REDIRECT_REQUEST_IFETCH_RESULT) &&
            (MUA_REDIRECT_BYPASS != `UQU_REDIRECT_BYPASS_IF_BUFFER_REDIRECT_REQUEST_IFETCH_RESULT)) begin : gen_invalid
            uqu_if_bypass_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
