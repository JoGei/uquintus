`default_nettype none

// Simulation-only third-operand/effective-rounding companion to standard RVFI.
// Observe actual EX consumption and follow the core-owned boundaries to WB.
module uqu_fp_trace (
    input wire clk_i, rst_ni,
    input wire ex_fire_i, ex_fp_i,
    input wire [4:0] ex_rs3_addr_i,
    input wire [31:0] ex_rs3_data_i,
    input wire [2:0] ex_rm_i,
    input wire mem_fire_i,
    input wire retire_i, wb_fp_i,
    input wire [63:0] order_i,
    input wire [31:0] pc_i, insn_i
);
    reg mem_fp_q, wb_fp_q;
    reg [4:0] mem_rs3_q, wb_rs3_q;
    reg [31:0] mem_data_q, wb_data_q;
    reg [2:0] mem_rm_q, wb_rm_q;
    integer file_handle;
    integer epoch = -1;
    bit reset_seen = 0;
    initial begin
        file_handle = $fopen("fpu.jsonl", "w");
        if (file_handle == 0) $fatal(1, "cannot open FP companion trace");
    end
    always @(posedge clk_i) begin
        if (!rst_ni) begin
            mem_fp_q <= 0;
            wb_fp_q <= 0;
            if (!reset_seen) epoch = epoch + 1;
            reset_seen = 1;
        end else begin
            reset_seen = 0;
            if (retire_i && wb_fp_i) begin
                if (!wb_fp_q) $fatal(1, "FP retirement has no consumed EX metadata");
                $fwrite(file_handle, "{\"epoch\":%0d,\"order\":%0d,\"pc\":%0d,\"insn\":%0d,\"rs3_addr\":%0d,\"rs3_rdata\":%0d,\"rm\":%0d}\n",
                    epoch, order_i, pc_i, insn_i, wb_rs3_q, wb_data_q, wb_rm_q);
                $fflush(file_handle);
            end
            if (ex_fire_i) begin
                mem_fp_q <= ex_fp_i;
                mem_rs3_q <= ex_rs3_addr_i;
                mem_data_q <= ex_rs3_addr_i == 0 ? 32'd0 : ex_rs3_data_i;
                mem_rm_q <= ex_rm_i;
            end
            if (mem_fire_i) begin
                wb_fp_q <= mem_fp_q;
                wb_rs3_q <= mem_rs3_q;
                wb_data_q <= mem_data_q;
                wb_rm_q <= mem_rm_q;
            end
        end
    end
    final $fclose(file_handle);
endmodule

`default_nettype wire
