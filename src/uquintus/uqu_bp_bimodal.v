`default_nettype none

// Tagged direction counters with independent capacity, no target addresses.
module uqu_bp_bimodal #(
    parameter ISA_C = 0,
    parameter MUA_BP_ENTRIES = 16
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        invalidate_i,
    input  wire        lookup_valid_i,
    input  wire [31:0] lookup_pc_i,
    output wire        hit_o,
    output wire        taken_o,
    input  wire        update_valid_i,
    input  wire [31:0] update_pc_i,
    input  wire        update_control_flow_i,
    input  wire        update_conditional_i,
    input  wire        update_taken_i
);
    localparam integer INDEX_WIDTH = $clog2(MUA_BP_ENTRIES);
    localparam integer OFFSET_WIDTH = (ISA_C == 1) ? 1 : 2;
    localparam integer TAG_LOW = OFFSET_WIDTH + INDEX_WIDTH;
    reg [MUA_BP_ENTRIES-1:0] valid_q;
    reg [31:TAG_LOW] tag_q [0:MUA_BP_ENTRIES-1];
    reg [1:0] counter_q [0:MUA_BP_ENTRIES-1];
    wire [INDEX_WIDTH-1:0] lookup_index = lookup_pc_i[TAG_LOW-1:OFFSET_WIDTH];
    wire [INDEX_WIDTH-1:0] update_index = update_pc_i[TAG_LOW-1:OFFSET_WIDTH];
    wire lookup_aligned = (ISA_C == 1) ? !lookup_pc_i[0] : !(|lookup_pc_i[1:0]);
    wire update_aligned = (ISA_C == 1) ? !update_pc_i[0] : !(|update_pc_i[1:0]);
    wire update_hit = valid_q[update_index] && (tag_q[update_index] == update_pc_i[31:TAG_LOW]);

    assign hit_o = rst_ni && !invalidate_i && lookup_valid_i && lookup_aligned &&
                   valid_q[lookup_index] && (tag_q[lookup_index] == lookup_pc_i[31:TAG_LOW]);
    assign taken_o = hit_o && counter_q[lookup_index][1];
    always @(posedge clk_i) begin
        if (!rst_ni || invalidate_i) begin
            valid_q <= {MUA_BP_ENTRIES{1'b0}};
        end else if (update_valid_i && update_aligned) begin
            if (update_control_flow_i && update_conditional_i) begin
                valid_q[update_index] <= 1'b1;
                tag_q[update_index] <= update_pc_i[31:TAG_LOW];
                if (!update_hit) begin
                    counter_q[update_index] <= update_taken_i ? 2'b10 : 2'b01;
                end else if (update_taken_i) begin
                    counter_q[update_index] <= (counter_q[update_index] == 2'b11) ?
                                               2'b11 : counter_q[update_index] + 1'b1;
                end else begin
                    counter_q[update_index] <= (counter_q[update_index] == 2'b00) ?
                                               2'b00 : counter_q[update_index] - 1'b1;
                end
            end else if (update_control_flow_i || update_hit) begin
                // An unconditional transfer replaces this direction-table slot
                // without allocating a counter. Ordinary code clears only a tag hit.
                valid_q[update_index] <= 1'b0;
            end
        end
    end
    generate
        if (((ISA_C != 0) && (ISA_C != 1)) ||
            (MUA_BP_ENTRIES < 2) || (MUA_BP_ENTRIES > 1024) ||
            ((MUA_BP_ENTRIES & (MUA_BP_ENTRIES - 1)) != 0)) begin : gen_invalid
            uqu_bp_bimodal_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
