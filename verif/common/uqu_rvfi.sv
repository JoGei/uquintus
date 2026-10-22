`default_nettype none

// Passive NRET=1, XLEN=ILEN=32 observation. No core state is driven here.
// Inputs are accepted transfers and actual resolved operands, not a re-decoder
// or architectural shadow register file. Simulation file I/O is separate.
module uqu_rvfi (
    input wire clk_i,
    input wire rst_ni,
    input wire de_fire_i,
    input wire [1:0] de_used_i,
    input wire [4:0] de_rs1_addr_i,
    input wire [4:0] de_rs2_addr_i,
    input wire [31:0] de_rs1_rdata_i,
    input wire [31:0] de_rs2_rdata_i,
    input wire ex_fire_i,
    input wire [1:0] ex_used_i,
    input wire [31:0] ex_rs1_rdata_i,
    input wire [31:0] ex_rs2_rdata_i,
    input wire mem_enable_i,
    input wire wb_response_i,
    input wire [31:0] wb_response_data_i,
    input wire mem_fire_i,
    input wire mem_lsu_i,
    input wire mem_we_i,
    input wire [2:0] mem_op_i,
    input wire [31:0] mem_addr_i,
    input wire [31:0] mem_wdata_i,
    input wire wb_retire_i,
    input wire wb_exception_i,
    input wire [4:0] wb_cause_i,
    input wire [31:0] wb_pc_i,
    input wire [31:0] wb_insn_i,
    input wire [31:0] wb_next_pc_i,
    input wire wb_redirect_i,
    input wire [31:0] wb_target_i,
    input wire wb_priv_m_i,
    input wire wb_we_i,
    input wire [4:0] wb_rd_i,
    input wire [31:0] wb_wdata_i,
    input wire irq_entry_i,
    output wire rvfi_valid,
    output wire [63:0] rvfi_order,
    output wire [31:0] rvfi_insn,
    output wire rvfi_trap,
    output wire rvfi_halt,
    output wire rvfi_intr,
    output wire [1:0] rvfi_mode,
    output wire [1:0] rvfi_ixl,
    output wire [4:0] rvfi_rs1_addr,
    output wire [4:0] rvfi_rs2_addr,
    output wire [31:0] rvfi_rs1_rdata,
    output wire [31:0] rvfi_rs2_rdata,
    output wire [4:0] rvfi_rd_addr,
    output wire [31:0] rvfi_rd_wdata,
    output wire [31:0] rvfi_pc_rdata,
    output wire [31:0] rvfi_pc_wdata,
    output wire [31:0] rvfi_mem_addr,
    output wire [3:0] rvfi_mem_rmask,
    output wire [3:0] rvfi_mem_wmask,
    output wire [31:0] rvfi_mem_rdata,
    output wire [31:0] rvfi_mem_wdata,
    output wire rvfi_mem_fault,
    output wire [3:0] rvfi_mem_fault_rmask,
    output wire [3:0] rvfi_mem_fault_wmask
);
    reg [63:0] order_q;
    reg entry_pending_q;
    reg [4:0] ex_rs1_addr_q, ex_rs2_addr_q;
    reg [31:0] ex_rs1_data_q, ex_rs2_data_q;
    reg [4:0] mem_rs1_addr_q, mem_rs2_addr_q;
    reg [31:0] mem_rs1_data_q, mem_rs2_data_q;
    reg [4:0] wb_rs1_addr_q, wb_rs2_addr_q;
    reg [31:0] wb_rs1_data_q, wb_rs2_data_q;
    reg wb_lsu_q, wb_mem_we_q;
    reg [31:0] wb_mem_addr_q, wb_mem_read_q, wb_mem_write_q;
    reg [3:0] wb_mask_q;
    wire fetch_fault = wb_exception_i && (wb_cause_i == 5'd1);
    wire data_fault = wb_exception_i && wb_lsu_q &&
                      ((wb_cause_i == 5'd5) || (wb_cause_i == 5'd7));
    wire successful_memory = rvfi_valid && wb_lsu_q && !wb_exception_i;
    wire [3:0] mem_mask = (mem_op_i[1:0] == 2'd0) ? 4'b0001 :
                         (mem_op_i[1:0] == 2'd1) ? 4'b0011 : 4'b1111;
    wire [4:0] mem_shift = {mem_addr_i[1:0],3'b000};

    assign rvfi_valid = rst_ni && (wb_retire_i || wb_exception_i);
    assign rvfi_order = order_q;
    assign rvfi_insn = rvfi_valid && !fetch_fault ? wb_insn_i : 32'd0;
    assign rvfi_trap = rvfi_valid && wb_exception_i;
    assign rvfi_halt = 1'b0;
    assign rvfi_intr = rvfi_valid && entry_pending_q;
    assign rvfi_mode = !rvfi_valid ? 2'd0 : wb_priv_m_i ? 2'd3 : 2'd0;
    assign rvfi_ixl = 2'd1;
    assign rvfi_rs1_addr = rvfi_valid ? wb_rs1_addr_q : 5'd0;
    assign rvfi_rs2_addr = rvfi_valid ? wb_rs2_addr_q : 5'd0;
    assign rvfi_rs1_rdata = (rvfi_rs1_addr != 5'd0) ? wb_rs1_data_q : 32'd0;
    assign rvfi_rs2_rdata = (rvfi_rs2_addr != 5'd0) ? wb_rs2_data_q : 32'd0;
    assign rvfi_rd_addr = rvfi_valid && wb_we_i && !wb_exception_i ? wb_rd_i : 5'd0;
    assign rvfi_rd_wdata = (rvfi_rd_addr != 5'd0) ? wb_wdata_i : 32'd0;
    assign rvfi_pc_rdata = rvfi_valid ? wb_pc_i : 32'd0;
    assign rvfi_pc_wdata = !rvfi_valid ? 32'd0 : wb_redirect_i ? wb_target_i : wb_next_pc_i;
    // RISCV_FORMAL_ALIGNED_MEM: masks/data use bus byte lanes. Raw read data
    // is observed at the response, independently of load extension/writeback.
    assign rvfi_mem_addr = rvfi_valid && wb_lsu_q ? wb_mem_addr_q : 32'd0;
    assign rvfi_mem_rmask = successful_memory && !wb_mem_we_q ? wb_mask_q : 4'd0;
    assign rvfi_mem_wmask = successful_memory && wb_mem_we_q ? wb_mask_q : 4'd0;
    assign rvfi_mem_rdata = (|rvfi_mem_rmask) ? (wb_response_i ? wb_response_data_i : wb_mem_read_q) : 32'd0;
    assign rvfi_mem_wdata = (|rvfi_mem_wmask) ? wb_mem_write_q : 32'd0;
    assign rvfi_mem_fault = rvfi_valid && (fetch_fault || data_fault);
    assign rvfi_mem_fault_rmask = rvfi_valid && data_fault && !wb_mem_we_q ? wb_mask_q : 4'd0;
    assign rvfi_mem_fault_wmask = rvfi_valid && data_fault && wb_mem_we_q ? wb_mask_q : 4'd0;

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            order_q <= 64'd0;
            entry_pending_q <= 1'b0;
        end else begin
            if (rvfi_valid) order_q <= order_q + 64'd1;
            // IRQ entry has no invented instruction/order record. Synchronous
            // traps also mark the first following handler instruction.
            if (irq_entry_i || wb_exception_i) entry_pending_q <= 1'b1;
            else if (rvfi_valid) entry_pending_q <= 1'b0;
        end
        if (rst_ni && de_fire_i) begin
            ex_rs1_addr_q <= de_used_i[0] ? de_rs1_addr_i : 5'd0;
            ex_rs2_addr_q <= de_used_i[1] ? de_rs2_addr_i : 5'd0;
            ex_rs1_data_q <= de_rs1_rdata_i;
            ex_rs2_data_q <= de_rs2_rdata_i;
        end
        if (rst_ni && ex_fire_i) begin
            mem_rs1_addr_q <= ex_rs1_addr_q;
            mem_rs2_addr_q <= ex_rs2_addr_q;
            mem_rs1_data_q <= ex_used_i[0] ? ex_rs1_rdata_i : ex_rs1_data_q;
            mem_rs2_data_q <= ex_used_i[1] ? ex_rs2_rdata_i : ex_rs2_data_q;
        end
        if (!rst_ni || mem_fire_i) wb_mem_read_q <= 32'd0;
        else if (wb_response_i) wb_mem_read_q <= wb_response_data_i;
        if (rst_ni && mem_fire_i) begin
            wb_rs1_addr_q <= mem_rs1_addr_q;
            wb_rs2_addr_q <= mem_rs2_addr_q;
            wb_rs1_data_q <= mem_rs1_data_q;
            wb_rs2_data_q <= mem_rs2_data_q;
            wb_lsu_q <= mem_lsu_i;
            wb_mem_we_q <= mem_we_i;
            wb_mask_q <= mem_mask << mem_addr_i[1:0];
            wb_mem_addr_q <= {mem_addr_i[31:2],2'b00};
            wb_mem_write_q <= mem_wdata_i << mem_shift;
        end
    end
endmodule

`default_nettype wire
