`default_nettype none

// Simulation-only custom-instruction observation. Standard RVFI carries the
// first two sources and primary destination; this companion records all three
// source slots and both actual GPR updates without inventing extra retirement.
module uqu_xif_trace #(
    parameter XIF = 0,
    parameter XIF_NUM_RS = 3
) (
    input wire clk_i,
    input wire rst_ni,
    input wire issue_valid_i,
    input wire issue_ready_i,
    input wire issue_accept_i,
    input wire [2:0] issue_id_i,
    input wire [31:0] issue_pc_i,
    input wire [31:0] issue_instr_i,
    input wire [XIF_NUM_RS-1:0] register_read_i,
    input wire [32*XIF_NUM_RS-1:0] register_rs_i,
    input wire [2:0] de_id_i,
    output wire [1:0] de_used_o,
    output wire [4:0] de_rs1_addr_o,
    output wire [4:0] de_rs2_addr_o,
    output wire [31:0] de_rs1_data_o,
    output wire [31:0] de_rs2_data_o,
    input wire retire_i,
    input wire [2:0] wb_id_i,
    input wire [63:0] order_i,
    input wire we0_i,
    input wire [4:0] rd0_i,
    input wire [31:0] data0_i,
    input wire we1_i,
    input wire [4:0] rd1_i,
    input wire [31:0] data1_i
);
    generate
        if (XIF == 1) begin : gen_enabled
            reg [2:0] used [0:7];
            reg [31:0] pc [0:7], instr [0:7];
            reg [31:0] operands [0:7][0:2];
            integer file_handle, slot;
            integer epoch = -1;
            bit reset_seen = 0;
            assign de_used_o = used[de_id_i][1:0];
            assign de_rs1_addr_o = instr[de_id_i][19:15];
            assign de_rs2_addr_o = instr[de_id_i][24:20];
            assign de_rs1_data_o = operands[de_id_i][0];
            assign de_rs2_data_o = operands[de_id_i][1];
            initial begin
                file_handle = $fopen("xif.jsonl", "w");
                if (file_handle == 0) $fatal(1, "cannot open xif.jsonl");
            end
            always @(posedge clk_i) begin
                if (!rst_ni) begin
                    if (!reset_seen) epoch = epoch + 1;
                    reset_seen = 1;
                end else reset_seen = 0;
                if (rst_ni && issue_valid_i && issue_ready_i && issue_accept_i) begin
                    pc[issue_id_i] <= issue_pc_i;
                    instr[issue_id_i] <= issue_instr_i;
                    used[issue_id_i] <= {{(3-XIF_NUM_RS){1'b0}},register_read_i};
                    for (slot=0; slot<3; slot=slot+1) begin
                        if (slot<XIF_NUM_RS)
                            operands[issue_id_i][slot] <= register_rs_i[32*slot +: 32];
                        else operands[issue_id_i][slot] <= 32'd0;
                    end
                end
                if (rst_ni && retire_i) begin
                    $fwrite(file_handle, "{\"epoch\":%0d,\"order\":%0d,\"pc\":%0d,\"id\":%0d,\"instr\":%0d,\"used\":%0d,\"rs\":[%0d,%0d,%0d],\"rd\":[%0d,%0d],\"data\":[%0d,%0d]}\n",
                        epoch,order_i,pc[wb_id_i],wb_id_i,instr[wb_id_i],used[wb_id_i],
                        used[wb_id_i][0] ? operands[wb_id_i][0] : 32'd0,
                        used[wb_id_i][1] ? operands[wb_id_i][1] : 32'd0,
                        used[wb_id_i][2] ? operands[wb_id_i][2] : 32'd0,
                        we0_i ? rd0_i : 5'd0, we1_i ? rd1_i : 5'd0,
                        we0_i ? data0_i : 32'd0, we1_i ? data1_i : 32'd0);
                    $fflush(file_handle);
                end
            end
        end else begin : gen_disabled
            assign de_used_o = 2'd0;
            assign de_rs1_addr_o = 5'd0;
            assign de_rs2_addr_o = 5'd0;
            assign de_rs1_data_o = 32'd0;
            assign de_rs2_data_o = 32'd0;
        end
    endgenerate
endmodule

`default_nettype wire
