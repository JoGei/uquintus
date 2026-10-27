`default_nettype none
`include "uqu_config.vh"

// IF-owned target storage; no conditional-direction prediction lives here.
module uqu_btb #(
    parameter ISA_C = 0,
    parameter MUA_BTB = `UQU_BTB_NONE,
    parameter MUA_BTB_ENTRIES = 16,
    parameter MUA_BTB_IDATA_HWORDS = 0
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        invalidate_i,
    input  wire        lookup_valid_i,
    input  wire [31:0] lookup_pc_i,
    output wire        hit_o,
    output wire        conditional_o,
    output wire [31:0] target_o,
    input  wire        update_valid_i,
    input  wire [31:0] update_pc_i,
    input  wire        update_control_flow_i,
    input  wire        update_conditional_i,
    input  wire [31:0] update_target_i,
    input  wire        update_taken_i,
    input  wire        stream_flush_i,
    input  wire        capture_valid_i,
    input  wire [31:0] capture_pc_i,
    input  wire [31:0] capture_instr_i,
    output wire [31:0] idata_hwords_o,
    output wire [31:0] idata_next_pc_o,
    output wire [16*((MUA_BTB_IDATA_HWORDS > 0) ? MUA_BTB_IDATA_HWORDS : 1)-1:0] idata_o
);
    localparam integer INDEX_WIDTH = $clog2(MUA_BTB_ENTRIES);
    localparam integer OFFSET_WIDTH = (ISA_C == 1) ? 1 : 2;
    localparam integer TAG_LOW = OFFSET_WIDTH + INDEX_WIDTH;
    generate
        if (MUA_BTB == `UQU_BTB_DIRECT_MAPPED) begin : gen_direct_mapped
            reg [MUA_BTB_ENTRIES-1:0] valid_q;
            reg [31:TAG_LOW] tag_q [0:MUA_BTB_ENTRIES-1];
            reg [31:OFFSET_WIDTH] target_q [0:MUA_BTB_ENTRIES-1];
            reg conditional_q [0:MUA_BTB_ENTRIES-1];
            wire [INDEX_WIDTH-1:0] lookup_index = lookup_pc_i[TAG_LOW-1:OFFSET_WIDTH];
            wire [INDEX_WIDTH-1:0] update_index = update_pc_i[TAG_LOW-1:OFFSET_WIDTH];
            wire lookup_aligned = (ISA_C == 1) ? !lookup_pc_i[0] : !(|lookup_pc_i[1:0]);
            wire update_aligned = (ISA_C == 1) ? !update_pc_i[0] : !(|update_pc_i[1:0]);
            wire target_aligned = (ISA_C == 1) ? !update_target_i[0] : !(|update_target_i[1:0]);
            wire update_hit = valid_q[update_index] && (tag_q[update_index] == update_pc_i[31:TAG_LOW]);

            assign hit_o = rst_ni && !invalidate_i && lookup_valid_i && lookup_aligned &&
                           valid_q[lookup_index] && (tag_q[lookup_index] == lookup_pc_i[31:TAG_LOW]);
            assign conditional_o = hit_o && conditional_q[lookup_index];
            assign target_o = hit_o ? {target_q[lookup_index], {OFFSET_WIDTH{1'b0}}} : 32'd0;

            if ((MUA_BTB_IDATA_HWORDS > 0) &&
                ((ISA_C == 1) || ((MUA_BTB_IDATA_HWORDS % 2) == 0))) begin : gen_idata
                // C stores packed halfwords; non-C elaborates ordinary words.
                // Counts and fill offsets use these internal storage units.
                localparam integer CELL_BITS = (ISA_C == 1) ? 16 : 32;
                localparam integer CAPACITY = (ISA_C == 1) ? MUA_BTB_IDATA_HWORDS : MUA_BTB_IDATA_HWORDS/2;
                localparam integer COUNT_WIDTH = $clog2(CAPACITY+1);
                reg [MUA_BTB_ENTRIES-1:0] prefix_valid_q;
                reg [COUNT_WIDTH-1:0] count_q [0:MUA_BTB_ENTRIES-1];
                wire [CELL_BITS*CAPACITY-1:0] bank_data [0:MUA_BTB_ENTRIES-1];
                wire [31:0] bank_stored_instr [0:MUA_BTB_ENTRIES-1];
                reg fill_valid_q;
                reg [INDEX_WIDTH-1:0] fill_index_q;
                reg [31:0] fill_owner_q, fill_target_q, fill_pc_q;
                reg [COUNT_WIDTH-1:0] fill_offset_q;
                wire changed = update_valid_i && update_aligned &&
                    ((update_control_flow_i && target_aligned) ?
                     (!update_hit || ({target_q[update_index],{OFFSET_WIDTH{1'b0}}} != update_target_i)) :
                     update_hit);
                wire start = update_valid_i && update_aligned && target_aligned &&
                             update_control_flow_i && update_taken_i;
                wire [INDEX_WIDTH-1:0] owner = start ? update_index : fill_index_q;
                wire [31:0] expected_pc = start ? update_target_i : fill_pc_q;
                wire [COUNT_WIDTH-1:0] offset = start ? {COUNT_WIDTH{1'b0}} : fill_offset_q;
                wire owner_live = valid_q[fill_index_q] &&
                    (tag_q[fill_index_q] == fill_owner_q[31:TAG_LOW]) &&
                    ({target_q[fill_index_q],{OFFSET_WIDTH{1'b0}}} == fill_target_q) &&
                    !(changed && (update_index == fill_index_q));
                wire retained = prefix_valid_q[owner] && !(start && changed);
                wire [COUNT_WIDTH-1:0] count = retained ? count_q[owner] : {COUNT_WIDTH{1'b0}};
                wire short_instr = (ISA_C == 1) && (capture_instr_i[1:0] != 2'b11);
                wire [31:0] length = short_instr ? 32'd2 : 32'd4;
                wire [31:0] step = ((ISA_C == 0) || short_instr) ? 32'd1 : 32'd2;
                wire [31:0] next_offset = {{(32-COUNT_WIDTH){1'b0}},offset} + step;
                wire fits = next_offset <= CAPACITY;
                wire [31:0] capture_instr = short_instr ? {16'd0,capture_instr_i[15:0]} : capture_instr_i;
                wire [31:0] stored_instr;
                wire same_prefix = (offset >= count) || (stored_instr == capture_instr);
                wire collect = capture_valid_i && (capture_pc_i == expected_pc) && same_prefix &&
                    fits &&
                    (start || (fill_valid_q && !stream_flush_i && owner_live));
                wire append = collect && (offset == count);
                assign idata_hwords_o = hit_o && prefix_valid_q[lookup_index] ?
                    ({{(32-COUNT_WIDTH){1'b0}},count_q[lookup_index]} << ((ISA_C == 1) ? 0 : 1)) : 32'd0;
                assign idata_next_pc_o = target_o + (idata_hwords_o << 1);
                // Entry selection gates each bank locally. Only the small
                // within-entry offset addresses its data; a late owner never
                // passes through owner*CAPACITY+offset address arithmetic.
                wire [COUNT_WIDTH:0] following_offset = {1'b0,offset} + 1'b1;
                assign stored_instr = bank_stored_instr[owner];
                genvar bank, unit_index;
                for (bank = 0; bank < MUA_BTB_ENTRIES; bank = bank+1) begin : gen_bank
                    reg [CELL_BITS-1:0] data_q [0:CAPACITY-1];
                    wire write_bank = rst_ni && !invalidate_i && append && (owner == bank);
                    if (ISA_C == 1) begin : gen_packed
                        wire [15:0] first = data_q[offset];
                        wire [15:0] second = ({{(31-COUNT_WIDTH){1'b0}},following_offset} < CAPACITY) ?
                            data_q[following_offset[COUNT_WIDTH-1:0]] : 16'd0;
                        assign bank_stored_instr[bank] =
                            (first[1:0] != 2'b11) ? {16'd0,first} : {second,first};
                    end else begin : gen_words
                        assign bank_stored_instr[bank] = data_q[offset];
                    end
                    for (unit_index = 0; unit_index < CAPACITY; unit_index = unit_index+1) begin : gen_cell
                        localparam [COUNT_WIDTH-1:0] UNIT_OFFSET = unit_index[COUNT_WIDTH-1:0];
                        assign bank_data[bank][CELL_BITS*unit_index +: CELL_BITS] = data_q[unit_index];
                        // Constant destinations prevent memory write-port
                        // widening from padding a non-power-of-two bank.
                        if (ISA_C == 1) begin : gen_packed
                            always @(posedge clk_i) begin
                                if (write_bank) begin
                                    if (offset == UNIT_OFFSET)
                                        data_q[unit_index] <= capture_instr_i[15:0];
                                    else if (!short_instr && (following_offset == {1'b0,UNIT_OFFSET}))
                                        data_q[unit_index] <= capture_instr_i[31:16];
                                end
                            end
                        end else begin : gen_words
                            always @(posedge clk_i) begin
                                if (write_bank && (offset == UNIT_OFFSET))
                                    data_q[unit_index] <= capture_instr_i;
                            end
                        end
                    end
                end
                genvar slot;
                for (slot = 0; slot < CAPACITY; slot = slot+1) begin : gen_slot
                    assign idata_o[CELL_BITS*slot +: CELL_BITS] =
                        hit_o && prefix_valid_q[lookup_index] && (count_q[lookup_index] > slot) ?
                        bank_data[lookup_index][CELL_BITS*slot +: CELL_BITS] : {CELL_BITS{1'b0}};
                end
                always @(posedge clk_i) begin
                    if (!rst_ni || invalidate_i) begin
                        prefix_valid_q <= {MUA_BTB_ENTRIES{1'b0}};
                        fill_valid_q <= 1'b0;
                    end else begin
                        if (changed) prefix_valid_q[update_index] <= 1'b0;
                        if (stream_flush_i || !owner_live) fill_valid_q <= 1'b0;
                        if (start) begin
                            fill_valid_q <= {{(32-COUNT_WIDTH){1'b0}},count} < CAPACITY;
                            fill_index_q <= update_index;
                            fill_owner_q <= update_pc_i;
                            fill_target_q <= update_target_i;
                            fill_pc_q <= update_target_i;
                            fill_offset_q <= {COUNT_WIDTH{1'b0}};
                        end else if (fill_valid_q && capture_valid_i && !stream_flush_i &&
                                     ((capture_pc_i != expected_pc) || !same_prefix || !fits)) fill_valid_q <= 1'b0;
                        if (start && capture_valid_i && (capture_pc_i == expected_pc) && (!same_prefix || !fits))
                            fill_valid_q <= 1'b0;
                        if (collect) begin
                            fill_pc_q <= capture_pc_i + length;
                            fill_offset_q <= next_offset[COUNT_WIDTH-1:0];
                            if (next_offset == CAPACITY) fill_valid_q <= 1'b0;
                        end
                        if (append) begin
                            count_q[owner] <= next_offset[COUNT_WIDTH-1:0];
                            prefix_valid_q[owner] <= 1'b1;
                        end
                    end
                end
            end else begin : gen_no_idata
                assign idata_hwords_o = 32'd0;
                assign idata_next_pc_o = 32'd0;
                assign idata_o = 16'd0;
            end

            always @(posedge clk_i) begin
                if (!rst_ni || invalidate_i) begin
                    valid_q <= {MUA_BTB_ENTRIES{1'b0}};
                end else if (update_valid_i && update_aligned) begin
                    if (update_control_flow_i && target_aligned) begin
                        valid_q[update_index] <= 1'b1;
                        tag_q[update_index] <= update_pc_i[31:TAG_LOW];
                        target_q[update_index] <= update_target_i[31:OFFSET_WIDTH];
                        conditional_q[update_index] <= update_conditional_i;
                    end else if (update_hit) begin
                        valid_q[update_index] <= 1'b0;
                    end
                end
            end
        end else begin : gen_none
            assign idata_hwords_o = 32'd0;
            assign idata_next_pc_o = 32'd0;
            assign idata_o = {16*((MUA_BTB_IDATA_HWORDS > 0) ? MUA_BTB_IDATA_HWORDS : 1){1'b0}};
            assign hit_o = 1'b0;
            assign conditional_o = 1'b0;
            assign target_o = 32'd0;
        end
        if (((ISA_C != 0) && (ISA_C != 1)) ||
            (MUA_BTB_IDATA_HWORDS < 0) || (MUA_BTB_IDATA_HWORDS > 2048) ||
            ((ISA_C == 0) && ((MUA_BTB_IDATA_HWORDS % 2) != 0)) ||
            ((MUA_BTB != `UQU_BTB_NONE) && (MUA_BTB != `UQU_BTB_DIRECT_MAPPED)) ||
            (MUA_BTB_ENTRIES < 2) || (MUA_BTB_ENTRIES > 1024) ||
            ((MUA_BTB_ENTRIES & (MUA_BTB_ENTRIES - 1)) != 0)) begin : gen_invalid
            uqu_btb_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
