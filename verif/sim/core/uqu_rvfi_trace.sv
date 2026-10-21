`default_nettype none
`include "uqu_rvfi_csrs.vh"

// Simulation-only JSONL sink. Deliberately separate from formal-capable RVFI.
module uqu_rvfi_trace (
    input wire clk_i,
    input wire rst_ni,
    input wire irq_valid_i,
    input wire [31:0] irq_pc_i,
    input wire [4:0] irq_cause_i,
    input wire [31:0] irq_target_i,
    input wire [4:0] exception_cause_i,
    input wire [31:0] exception_tval_i,
    input wire rvfi_valid,
    input wire [63:0] rvfi_order,
    input wire [31:0] rvfi_insn,
    input wire rvfi_trap,
    input wire rvfi_halt,
    input wire rvfi_intr,
    input wire [1:0] rvfi_mode,
    input wire [1:0] rvfi_ixl,
    input wire [4:0] rvfi_rs1_addr,
    input wire [4:0] rvfi_rs2_addr,
    input wire [31:0] rvfi_rs1_rdata,
    input wire [31:0] rvfi_rs2_rdata,
    input wire [4:0] rvfi_rd_addr,
    input wire [31:0] rvfi_rd_wdata,
    input wire [31:0] rvfi_pc_rdata,
    input wire [31:0] rvfi_pc_wdata,
    input wire [31:0] rvfi_mem_addr,
    input wire [3:0] rvfi_mem_rmask,
    input wire [3:0] rvfi_mem_wmask,
    input wire [31:0] rvfi_mem_rdata,
    input wire [31:0] rvfi_mem_wdata,
    input wire rvfi_mem_fault,
    input wire [3:0] rvfi_mem_fault_rmask,
    input wire [3:0] rvfi_mem_fault_wmask
    `define UQU_RVFI_CSR(NAME, WIDTH, INDEX, LO, HI, ULO, UHI) `UQU_RVFI_CSR_INPUT(NAME, WIDTH, INDEX, LO, HI, ULO, UHI)
    `include "uqu_rvfi_csr_list.vh"
    `undef UQU_RVFI_CSR
);
    integer file_handle;
    integer epoch = -1;
    bit reset_seen = 0;
    string trace_path;
    bit csr_first;
    task automatic write_csrs;
        csr_first = 1;
`define UQU_RVFI_CSR_LOG(NAME, WIDTH, INDEX, LO, HI, ULO, UHI) \
        if ((|rvfi_csr_``NAME``_rmask) || (|rvfi_csr_``NAME``_wmask)) begin \
            if (!csr_first) $fwrite(file_handle, ","); \
            csr_first = 0; \
            $fwrite(file_handle, "\"%s\":{\"rmask\":%0d,\"wmask\":%0d,\"rdata\":%0d,\"wdata\":%0d}", \
                    `"NAME`", rvfi_csr_``NAME``_rmask, rvfi_csr_``NAME``_wmask, \
                    rvfi_csr_``NAME``_rdata, rvfi_csr_``NAME``_wdata); \
        end
        `define UQU_RVFI_CSR(NAME, WIDTH, INDEX, LO, HI, ULO, UHI) `UQU_RVFI_CSR_LOG(NAME, WIDTH, INDEX, LO, HI, ULO, UHI)
        `include "uqu_rvfi_csr_list.vh"
        `undef UQU_RVFI_CSR
`undef UQU_RVFI_CSR_LOG
        $fwrite(file_handle, "}}\n");
    endtask
    initial begin
        if (!$value$plusargs("rvfi_trace_file=%s", trace_path)) trace_path = "rvfi.jsonl";
        file_handle = $fopen(trace_path, "w");
        if (file_handle == 0) $fatal(1, "cannot open RVFI trace: %s", trace_path);
    end
    always @(negedge clk_i) begin
        if (!rst_ni) begin
            if (!reset_seen) begin
                epoch = epoch + 1;
                $fwrite(file_handle, "{\"type\":\"reset\",\"epoch\":%0d}\n", epoch);
            end
            reset_seen = 1;
        end else begin
            reset_seen = 0;
            if (irq_valid_i) begin
                $fwrite(file_handle, "{\"type\":\"interrupt\",\"epoch\":%0d,\"pc\":%0d,\"cause\":%0d,\"target\":%0d,\"csrs\":{",
                        epoch, irq_pc_i, irq_cause_i, irq_target_i);
                write_csrs();
            end
            if (rvfi_valid) begin
                $fwrite(file_handle, "{\"type\":\"instruction\",\"epoch\":%0d,\"cause\":%0d,\"tval\":%0d,\"rvfi_order\":%0d,\"rvfi_insn\":%0d,\"rvfi_trap\":%0d,\"rvfi_halt\":%0d,\"rvfi_intr\":%0d,\"rvfi_mode\":%0d,\"rvfi_ixl\":%0d,\"rvfi_rs1_addr\":%0d,\"rvfi_rs2_addr\":%0d,\"rvfi_rs1_rdata\":%0d,\"rvfi_rs2_rdata\":%0d,\"rvfi_rd_addr\":%0d,\"rvfi_rd_wdata\":%0d,\"rvfi_pc_rdata\":%0d,\"rvfi_pc_wdata\":%0d,\"rvfi_mem_addr\":%0d,\"rvfi_mem_rmask\":%0d,\"rvfi_mem_wmask\":%0d,\"rvfi_mem_rdata\":%0d,\"rvfi_mem_wdata\":%0d,\"rvfi_mem_fault\":%0d,\"rvfi_mem_fault_rmask\":%0d,\"rvfi_mem_fault_wmask\":%0d,\"csrs\":{",
                        epoch, rvfi_trap ? exception_cause_i : 5'd0,
                        rvfi_trap ? exception_tval_i : 32'd0, rvfi_order, rvfi_insn, rvfi_trap, rvfi_halt, rvfi_intr, rvfi_mode, rvfi_ixl, rvfi_rs1_addr, rvfi_rs2_addr, rvfi_rs1_rdata, rvfi_rs2_rdata, rvfi_rd_addr, rvfi_rd_wdata, rvfi_pc_rdata, rvfi_pc_wdata, rvfi_mem_addr, rvfi_mem_rmask, rvfi_mem_wmask, rvfi_mem_rdata, rvfi_mem_wdata, rvfi_mem_fault, rvfi_mem_fault_rmask, rvfi_mem_fault_wmask);
                write_csrs();
            end
            $fflush(file_handle);
        end
    end
    final $fclose(file_handle);
endmodule

`default_nettype wire
