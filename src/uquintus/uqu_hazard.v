`default_nettype none

// Core-owned operand resolution. Pipeline identity, movement and instruction-
// specific result qualification are supplied by the parent, not decoded here.
module uqu_hazard #(
    parameter ISA_E = 0,
    parameter ISA_ZFINX = 0,
    parameter XIF = 0,
    parameter XIF_NUM_RS = 3,
    parameter XIF_DUALWRITE = 0,
    parameter MUA_FORWARDING = 1,
    parameter MUA_FORWARD_EX_TO_DE = 1,
    parameter MUA_FORWARD_MEM_TO_DE = 1,
    parameter MUA_FORWARD_MEM_TO_EX = 1,
    parameter MUA_FORWARD_WB_TO_EX = 1,
    parameter MUA_DE_OPERAND_RETENTION = 0
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        de_valid_i,
    input  wire        de_clear_i,
    input  wire [4:0]  de_rs0_addr_i,
    input  wire [4:0]  de_rs1_addr_i,
    input  wire [4:0]  de_rs2_addr_i,
    input  wire [31:0] de_rs0_i,
    input  wire [31:0] de_rs1_i,
    input  wire [31:0] de_rs2_i,
    input  wire [2:0]  de_rs_used_i,
    input  wire [2:0]  de_rs_need_now_i,
    output wire [31:0] de_rs0_o,
    output wire [31:0] de_rs1_o,
    output wire [31:0] de_rs2_o,
    output wire [2:0]  de_rs_ready_o,
    output wire [2:0]  de_rs_ex_guaranteed_o,
    input  wire        ex_valid_i,
    input  wire [4:0]  ex_rs0_addr_i,
    input  wire [4:0]  ex_rs1_addr_i,
    input  wire [4:0]  ex_rs2_addr_i,
    input  wire [31:0] ex_rs0_i,
    input  wire [31:0] ex_rs1_i,
    input  wire [31:0] ex_rs2_i,
    input  wire [2:0]  ex_rs_used_i,
    input  wire [2:0]  ex_rs_captured_i,
    output wire [31:0] ex_rs0_o,
    output wire [31:0] ex_rs1_o,
    output wire [31:0] ex_rs2_o,
    output wire [2:0]  ex_rs_ready_o,
    // EX slot validity is ex_valid_i for both producer and consumer roles.
    input  wire [1:0]  ex_pending_i,
    input  wire [4:0]  ex_rd0_i,
    input  wire [4:0]  ex_rd1_i,
    input  wire        ex_result_available_i,
    input  wire        ex_result_forwardable_i,
    input  wire [31:0] ex_result_i,
    input  wire        ex_advance_i,
    input  wire        mem_valid_i,
    input  wire [1:0]  mem_pending_i,
    input  wire [4:0]  mem_rd0_i,
    input  wire [4:0]  mem_rd1_i,
    input  wire        mem_result_available_i,
    input  wire        mem_result_forwardable_i,
    input  wire [31:0] mem_result_i,
    input  wire        mem_advance_i,
    input  wire        wb_valid_i,
    input  wire [1:0]  wb_pending_i,
    input  wire [4:0]  wb_rd0_i,
    input  wire [4:0]  wb_rd1_i,
    input  wire        wb_result_available_i,
    input  wire        wb_result_forwardable_i,
    input  wire [31:0] wb_result_i,
    input  wire        wb_advance_i
);
    localparam THIRD_SOURCE = (ISA_ZFINX == 1) || ((XIF == 1) && (XIF_NUM_RS == 3));
    localparam SECOND_DESTINATION = (XIF == 1) && (XIF_DUALWRITE == 1);

    wire [4:0] de_addr [0:2];
    wire [4:0] ex_addr [0:2];
    wire [31:0] de_data [0:2];
    wire [31:0] ex_data [0:2];
    wire [31:0] de_resolved [0:2];
    wire [31:0] ex_resolved [0:2];
    assign de_addr[0] = de_rs0_addr_i;
    assign de_addr[1] = de_rs1_addr_i;
    assign de_addr[2] = de_rs2_addr_i;
    assign ex_addr[0] = ex_rs0_addr_i;
    assign ex_addr[1] = ex_rs1_addr_i;
    assign ex_addr[2] = ex_rs2_addr_i;
    assign de_data[0] = de_rs0_i;
    assign de_data[1] = de_rs1_i;
    assign de_data[2] = de_rs2_i;
    assign ex_data[0] = ex_rs0_i;
    assign ex_data[1] = ex_rs1_i;
    assign ex_data[2] = ex_rs2_i;
    assign de_rs0_o = de_resolved[0];
    assign de_rs1_o = de_resolved[1];
    assign de_rs2_o = de_resolved[2];
    assign ex_rs0_o = ex_resolved[0];
    assign ex_rs1_o = ex_resolved[1];
    assign ex_rs2_o = ex_resolved[2];

    wire ex_result_usable = ex_result_available_i && ex_result_forwardable_i;
    wire mem_result_usable = mem_result_available_i && mem_result_forwardable_i;
    wire wb_result_usable = wb_result_available_i && wb_result_forwardable_i;
    // WB movement is part of the uniform producer descriptor. No future-WB
    // bypass guarantee is needed: enabled WB-to-DE already supplies its value.
    wire unused_wb_advance = wb_advance_i;

    function [1:0] match_destination;
        input valid;
        input [1:0] pending;
        input [4:0] rd0;
        input [4:0] rd1;
        input [4:0] source;
        begin
            match_destination[0] = valid && pending[0] && (rd0 != 5'd0) && (rd0 == source);
            match_destination[1] = valid && SECOND_DESTINATION && pending[1] &&
                                   (rd1 != 5'd0) && (rd1 == source);
        end
    endfunction

    genvar source_idx;
    generate
        for (source_idx = 0; source_idx < 3; source_idx = source_idx + 1) begin : gen_source
            if ((source_idx < 2) || THIRD_SOURCE) begin : gen_enabled
                wire [1:0] de_ex_match = match_destination(ex_valid_i, ex_pending_i,
                    ex_rd0_i, ex_rd1_i, de_addr[source_idx]);
                wire [1:0] de_mem_match = match_destination(mem_valid_i, mem_pending_i,
                    mem_rd0_i, mem_rd1_i, de_addr[source_idx]);
                wire [1:0] de_wb_match = match_destination(wb_valid_i, wb_pending_i,
                    wb_rd0_i, wb_rd1_i, de_addr[source_idx]);
                wire [1:0] ex_mem_match = match_destination(mem_valid_i, mem_pending_i,
                    mem_rd0_i, mem_rd1_i, ex_addr[source_idx]);
                wire [1:0] ex_wb_match = match_destination(wb_valid_i, wb_pending_i,
                    wb_rd0_i, wb_rd1_i, ex_addr[source_idx]);
                wire de_live = rst_ni && de_valid_i && de_rs_used_i[source_idx] &&
                               ((ISA_E == 0) || !de_addr[source_idx][4]);
                wire ex_live = rst_ni && ex_valid_i && ex_rs_used_i[source_idx] &&
                               ((ISA_E == 0) || !ex_addr[source_idx][4]);
                wire retained_valid;
                wire [31:0] retained_data;
                reg [31:0] de_value;
                reg de_ready;
                reg de_guaranteed;
                reg [31:0] ex_value;
                reg ex_ready;

                always @* begin
                    de_value = 32'd0;
                    de_ready = 1'b0;
                    de_guaranteed = 1'b0;
                    if (de_live) begin
                        if (de_addr[source_idx] == 5'd0) begin
                            de_ready = 1'b1;
                        end else if (retained_valid) begin
                            de_value = retained_data;
                            de_ready = 1'b1;
                        end else if (|de_ex_match) begin
                            // Select candidate data by producer identity and
                            // configured route, independently of availability.
                            if (de_ex_match[0] && (MUA_FORWARDING == 1) &&
                                (MUA_FORWARD_EX_TO_DE == 1)) de_value = ex_result_i;
                            if (de_ex_match[0] && ex_result_usable && (MUA_FORWARDING == 1)) begin
                                if (MUA_FORWARD_EX_TO_DE == 1) begin
                                    de_ready = 1'b1;
                                end else if (!de_rs_need_now_i[source_idx] && ex_advance_i &&
                                             (MUA_FORWARD_MEM_TO_EX == 1)) begin
                                    de_guaranteed = 1'b1;
                                end
                            end
                        end else if (|de_mem_match) begin
                            if (de_mem_match[0] && (MUA_FORWARDING == 1) &&
                                (MUA_FORWARD_MEM_TO_DE == 1)) de_value = mem_result_i;
                            if (de_mem_match[0] && mem_result_usable && (MUA_FORWARDING == 1)) begin
                                if (MUA_FORWARD_MEM_TO_DE == 1) begin
                                    de_ready = 1'b1;
                                end else if (!de_rs_need_now_i[source_idx]) begin
                                    // The producer can stay in MEM or advance to WB
                                    // while an empty EX slot accepts the consumer.
                                    de_guaranteed = mem_advance_i ? (MUA_FORWARD_WB_TO_EX == 1) :
                                                                 (MUA_FORWARD_MEM_TO_EX == 1);
                                end
                            end
                        end else if (|de_wb_match) begin
                            if (de_wb_match[0] && (MUA_FORWARDING == 1)) de_value = wb_result_i;
                            if (de_wb_match[0] && wb_result_usable && (MUA_FORWARDING == 1)) begin
                                de_ready = 1'b1;
                            end
                        end else begin
                            de_value = de_data[source_idx];
                            de_ready = 1'b1;
                        end
                    end
                end

                always @* begin
                    ex_value = 32'd0;
                    ex_ready = 1'b0;
                    if (ex_live) begin
                        if (ex_addr[source_idx] == 5'd0) begin
                            ex_ready = 1'b1;
                        end else if (ex_rs_captured_i[source_idx]) begin
                            ex_value = ex_data[source_idx];
                            ex_ready = 1'b1;
                        end else if (|ex_mem_match) begin
                            if (ex_mem_match[0] && (MUA_FORWARDING == 1) &&
                                (MUA_FORWARD_MEM_TO_EX == 1)) ex_value = mem_result_i;
                            if (ex_mem_match[0] && mem_result_usable && (MUA_FORWARDING == 1) &&
                                (MUA_FORWARD_MEM_TO_EX == 1)) begin
                                ex_ready = 1'b1;
                            end
                        end else if (|ex_wb_match) begin
                            if (ex_wb_match[0] && (MUA_FORWARDING == 1) &&
                                (MUA_FORWARD_WB_TO_EX == 1)) ex_value = wb_result_i;
                            if (ex_wb_match[0] && wb_result_usable && (MUA_FORWARDING == 1) &&
                                (MUA_FORWARD_WB_TO_EX == 1)) begin
                                ex_ready = 1'b1;
                            end
                        end
                    end
                end

                assign de_resolved[source_idx] = de_value;
                assign de_rs_ready_o[source_idx] = de_ready;
                assign de_rs_ex_guaranteed_o[source_idx] = de_guaranteed;
                assign ex_resolved[source_idx] = ex_value;
                assign ex_rs_ready_o[source_idx] = ex_ready;

                if (MUA_DE_OPERAND_RETENTION == 1) begin : gen_retention
                    reg valid_q;
                    reg [31:0] data_q;
                    assign retained_valid = valid_q;
                    assign retained_data = data_q;
                    always @(posedge clk_i) begin
                        if (!rst_ni || de_clear_i || !de_valid_i) begin
                            valid_q <= 1'b0;
                        end else if (!valid_q && de_ready && (de_addr[source_idx] != 5'd0)) begin
                            valid_q <= 1'b1;
                        end
                        if (rst_ni && !de_clear_i && de_valid_i && !valid_q &&
                            de_ready && (de_addr[source_idx] != 5'd0)) begin
                            data_q <= de_value;
                        end
                    end
                end else begin : gen_continuous
                    assign retained_valid = 1'b0;
                    assign retained_data = 32'd0;
                end
            end else begin : gen_disabled
                assign de_resolved[source_idx] = 32'd0;
                assign ex_resolved[source_idx] = 32'd0;
                assign de_rs_ready_o[source_idx] = 1'b0;
                assign de_rs_ex_guaranteed_o[source_idx] = 1'b0;
                assign ex_rs_ready_o[source_idx] = 1'b0;
            end
        end

        if (((ISA_E != 0) && (ISA_E != 1)) ||
            ((ISA_ZFINX != 0) && (ISA_ZFINX != 1)) ||
            ((XIF != 0) && (XIF != 1)) ||
            ((XIF_NUM_RS != 2) && (XIF_NUM_RS != 3)) ||
            ((XIF_DUALWRITE != 0) && (XIF_DUALWRITE != 1)) ||
            ((MUA_FORWARDING != 0) && (MUA_FORWARDING != 1)) ||
            ((MUA_FORWARD_EX_TO_DE != 0) && (MUA_FORWARD_EX_TO_DE != 1)) ||
            ((MUA_FORWARD_MEM_TO_DE != 0) && (MUA_FORWARD_MEM_TO_DE != 1)) ||
            ((MUA_FORWARD_MEM_TO_EX != 0) && (MUA_FORWARD_MEM_TO_EX != 1)) ||
            ((MUA_FORWARD_WB_TO_EX != 0) && (MUA_FORWARD_WB_TO_EX != 1)) ||
            ((MUA_DE_OPERAND_RETENTION != 0) && (MUA_DE_OPERAND_RETENTION != 1))) begin : gen_invalid
            uqu_hazard_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
