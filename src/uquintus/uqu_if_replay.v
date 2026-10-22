`default_nettype none

// One active, immutable replay window. BTB entries remain retained independently
// of downstream stalls and replacement while this snapshot is being consumed.
module uqu_if_replay #(
    parameter MUA_BTB_IDATA_DEPTH = 0
) (
    input wire clk_i,
    input wire rst_ni,
    input wire flush_i,
    input wire cancel_i,
    input wire start_i,
    input wire [31:0] start_count_i,
    input wire [32*((MUA_BTB_IDATA_DEPTH > 0) ? MUA_BTB_IDATA_DEPTH : 1)-1:0] start_data_i,
    input wire consume_i,
    output wire active_o,
    output wire [31:0] instr_o
);
    generate
        if (MUA_BTB_IDATA_DEPTH > 0) begin : gen_enabled
            localparam integer INDEX_WIDTH = (MUA_BTB_IDATA_DEPTH > 1) ? $clog2(MUA_BTB_IDATA_DEPTH) : 1;
            localparam integer COUNT_WIDTH = $clog2(MUA_BTB_IDATA_DEPTH+1);
            reg active_q;
            reg [INDEX_WIDTH-1:0] index_q;
            reg [COUNT_WIDTH-1:0] count_q;
            reg [32*MUA_BTB_IDATA_DEPTH-1:0] data_q;
            assign active_o = rst_ni && !flush_i && active_q;
            assign instr_o = active_o ? data_q[32*index_q +: 32] : 32'd0;
            always @(posedge clk_i) begin
                if (!rst_ni || flush_i) active_q <= 1'b0;
                else if (start_i) begin
                    active_q <= start_count_i != 0;
                    index_q <= {INDEX_WIDTH{1'b0}};
                    count_q <= start_count_i[COUNT_WIDTH-1:0];
                    data_q <= start_data_i;
                end else if (cancel_i) active_q <= 1'b0;
                else if (active_q && consume_i) begin
                    if ({{(32-INDEX_WIDTH){1'b0}},index_q} + 32'd1 ==
                        {{(32-COUNT_WIDTH){1'b0}},count_q}) active_q <= 1'b0;
                    else index_q <= index_q + 1'b1;
                end
            end
        end else begin : gen_disabled
            assign active_o = 1'b0;
            assign instr_o = 32'd0;
        end
    endgenerate
endmodule

`default_nettype wire
