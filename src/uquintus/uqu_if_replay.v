`default_nettype none

// One active, immutable replay window. BTB entries remain retained independently
// of downstream stalls and replacement while this snapshot is being consumed.
module uqu_if_replay #(
    parameter ISA_C = 0,
    parameter MUA_BTB_IDATA_HWORDS = 0
) (
    input wire clk_i,
    input wire rst_ni,
    input wire flush_i,
    input wire cancel_i,
    input wire start_i,
    input wire [31:0] start_hwords_i,
    input wire [16*((MUA_BTB_IDATA_HWORDS > 0) ? MUA_BTB_IDATA_HWORDS : 1)-1:0] start_data_i,
    input wire consume_i,
    output wire active_o,
    output wire [31:0] instr_o
);
    generate
        if ((MUA_BTB_IDATA_HWORDS > 0) &&
            ((ISA_C == 1) || ((MUA_BTB_IDATA_HWORDS % 2) == 0))) begin : gen_enabled
            localparam integer CAPACITY = (ISA_C == 1) ? MUA_BTB_IDATA_HWORDS : MUA_BTB_IDATA_HWORDS/2;
            localparam integer INDEX_WIDTH = (CAPACITY > 1) ? $clog2(CAPACITY) : 1;
            localparam integer COUNT_WIDTH = $clog2(CAPACITY+1);
            reg active_q;
            reg [INDEX_WIDTH-1:0] index_q;
            reg [COUNT_WIDTH-1:0] count_q;
            reg [16*MUA_BTB_IDATA_HWORDS-1:0] data_q;
            wire [31:0] instr;
            wire short_instr = (ISA_C == 1) && (instr[1:0] != 2'b11);
            wire [31:0] step = ((ISA_C == 0) || short_instr) ? 32'd1 : 32'd2;
            wire [31:0] next_index = {{(32-INDEX_WIDTH){1'b0}},index_q} + step;
            if (ISA_C == 1) begin : gen_packed
                wire [15:0] first = data_q[16*index_q +: 16];
                wire [15:0] second;
                if (CAPACITY > 1) begin : gen_second
                    assign second = ({{(32-INDEX_WIDTH){1'b0}},index_q}+32'd1 < CAPACITY) ?
                        data_q[16*({{(32-INDEX_WIDTH){1'b0}},index_q}+32'd1) +: 16] : 16'd0;
                end else begin : gen_single
                    assign second = 16'd0;
                end
                assign instr = (first[1:0] != 2'b11) ? {16'd0,first} : {second,first};
            end else begin : gen_words
                assign instr = data_q[32*index_q +: 32];
            end
            assign active_o = rst_ni && !flush_i && active_q;
            assign instr_o = active_o ? instr : 32'd0;
            always @(posedge clk_i) begin
                if (!rst_ni || flush_i) active_q <= 1'b0;
                else if (start_i) begin
                    active_q <= start_hwords_i != 0;
                    index_q <= {INDEX_WIDTH{1'b0}};
                    count_q <= (ISA_C == 1) ? start_hwords_i[COUNT_WIDTH-1:0] : start_hwords_i[COUNT_WIDTH:1];
                    data_q <= start_data_i;
                end else if (cancel_i) active_q <= 1'b0;
                else if (active_q && consume_i) begin
                    if (next_index >=
                        {{(32-COUNT_WIDTH){1'b0}},count_q}) active_q <= 1'b0;
                    else index_q <= next_index[INDEX_WIDTH-1:0];
                end
            end
        end else begin : gen_disabled
            assign active_o = 1'b0;
            assign instr_o = 32'd0;
        end
        if (((ISA_C != 0) && (ISA_C != 1)) ||
            (MUA_BTB_IDATA_HWORDS < 0) || (MUA_BTB_IDATA_HWORDS > 2048) ||
            ((ISA_C == 0) && ((MUA_BTB_IDATA_HWORDS % 2) != 0))) begin : gen_invalid
            uqu_if_replay_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
