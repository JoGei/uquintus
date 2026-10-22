`default_nettype none
`include "uqu_config.vh"

// IF-owned target storage; no conditional-direction prediction lives here.
module uqu_btb #(
    parameter ISA_C = 0,
    parameter MUA_BTB = `UQU_BTB_NONE,
    parameter MUA_BTB_ENTRIES = 16
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
    input  wire [31:0] update_target_i
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
            assign hit_o = 1'b0;
            assign conditional_o = 1'b0;
            assign target_o = 32'd0;
        end
        if (((ISA_C != 0) && (ISA_C != 1)) ||
            ((MUA_BTB != `UQU_BTB_NONE) && (MUA_BTB != `UQU_BTB_DIRECT_MAPPED)) ||
            (MUA_BTB_ENTRIES < 2) || (MUA_BTB_ENTRIES > 1024) ||
            ((MUA_BTB_ENTRIES & (MUA_BTB_ENTRIES - 1)) != 0)) begin : gen_invalid
            uqu_btb_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
