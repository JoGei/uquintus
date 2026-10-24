`default_nettype none
`include "uqu_config.vh"

// Integer storage only: WB qualification, paired-result legality, and operand
// forwarding belong to the pipeline. No architectural register is reset.
module uqu_gpregfile #(
    parameter ISA_E = 0,
    parameter ISA_M = 0,
    parameter MUA_MUL = `UQU_MUL_DADDA_MAC,
    parameter ISA_ZFINX = 0,
    parameter XIF = 0,
    parameter XIF_NUM_RS = 3,
    parameter XIF_DUALWRITE = 0,
    parameter MUA_REGFILE_IMPL = `UQU_RF_FF
) (
    input  wire        clk_i,
    input  wire        rst_ni,

    input  wire [4:0]  raddr0_i,
    input  wire [4:0]  raddr1_i,
    input  wire [4:0]  raddr2_i,
    output wire [31:0] rdata0_o,
    output wire [31:0] rdata1_o,
    output wire [31:0] rdata2_o,

    input  wire        we0_i,
    input  wire [4:0]  waddr0_i,
    input  wire [31:0] wdata0_i,
    input  wire        we1_i,
    input  wire [4:0]  waddr1_i,
    input  wire [31:0] wdata1_i
);
    localparam NUM_REGS = (ISA_E == 1) ? 16 : 32;
    localparam REG_ADDR_WIDTH = (ISA_E == 1) ? 4 : 5;
    localparam READ_THIRD = ((ISA_M == 1) && (MUA_MUL == `UQU_MUL_DADDA_MAC)) || (ISA_ZFINX == 1) || ((XIF == 1) && (XIF_NUM_RS == 3));
    localparam WRITE_SECOND = (XIF == 1) && (XIF_DUALWRITE == 1);

    // x0 has no storage. Keep architectural addresses five bits wide in E
    // configurations: an unavailable register must never alias x0..x15.
    wire [31:0] regs [0:NUM_REGS-1];
    assign regs[0] = 32'd0;

    assign rdata0_o = ((raddr0_i != 5'd0) && ((ISA_E == 0) || !raddr0_i[4]))
                      ? regs[raddr0_i[REG_ADDR_WIDTH-1:0]] : 32'd0;
    assign rdata1_o = ((raddr1_i != 5'd0) && ((ISA_E == 0) || !raddr1_i[4]))
                      ? regs[raddr1_i[REG_ADDR_WIDTH-1:0]] : 32'd0;

    generate
        if (READ_THIRD) begin : gen_read_third
            assign rdata2_o = ((raddr2_i != 5'd0) &&
                              ((ISA_E == 0) || !raddr2_i[4]))
                              ? regs[raddr2_i[REG_ADDR_WIDTH-1:0]] : 32'd0;
        end else begin : gen_no_read_third
            assign rdata2_o = 32'd0;
        end

        if (MUA_REGFILE_IMPL == `UQU_RF_FF) begin : gen_ff
            genvar reg_idx;
            for (reg_idx = 1; reg_idx < NUM_REGS; reg_idx = reg_idx + 1) begin : gen_word
                localparam [4:0] REG_ADDR = reg_idx;
                reg [31:0] value_q;
                assign regs[reg_idx] = value_q;
                always @(posedge clk_i) begin
                    if (rst_ni) begin
                        if (we0_i && (waddr0_i == REG_ADDR)) begin
                            value_q <= wdata0_i;
                        end else if (WRITE_SECOND && we1_i &&
                                     (waddr1_i == REG_ADDR)) begin
                            value_q <= wdata1_i;
                        end
                    end
                end
            end
        end else if (MUA_REGFILE_IMPL == `UQU_RF_LATCH) begin : gen_latch
            // Capture data on the rising edge; capture per-word enables while
            // the clock is low. Enables are thus stable throughout the high
            // phase, and a previously selected word stays closed when the next
            // write's data changes. All clock control is local to this backend.
            reg [31:0] wdata0_q;
            wire [31:0] wdata1;

            always @(posedge clk_i) begin
                if (rst_ni && we0_i) begin
                    wdata0_q <= wdata0_i;
                end
            end

            if (WRITE_SECOND) begin : gen_write_second
                reg [31:0] wdata1_q;
                assign wdata1 = wdata1_q;
                always @(posedge clk_i) begin
                    if (rst_ni && we1_i) begin
                        wdata1_q <= wdata1_i;
                    end
                end
            end else begin : gen_no_write_second
                assign wdata1 = 32'd0;
            end

            genvar reg_idx;
            for (reg_idx = 1; reg_idx < NUM_REGS; reg_idx = reg_idx + 1) begin : gen_word
                localparam [4:0] REG_ADDR = reg_idx;
                reg [31:0] value_q;
                reg write0_q;
                wire write1;
                assign regs[reg_idx] = value_q;

                // Intentional low-phase enable latch: never gate an open data
                // latch directly with live write address/control inputs.
                /* verilator lint_off LATCH */
                always @* begin
                    if (!clk_i) begin
                        write0_q = rst_ni && we0_i && (waddr0_i == REG_ADDR);
                    end
                end
                /* verilator lint_on LATCH */

                if (WRITE_SECOND) begin : gen_write_second
                    reg write1_q;
                    assign write1 = write1_q;
                    /* verilator lint_off LATCH */
                    always @* begin
                        if (!clk_i) begin
                            write1_q = rst_ni && we1_i &&
                                       (waddr1_i == REG_ADDR) &&
                                       !(we0_i && (waddr0_i == REG_ADDR));
                        end
                    end
                    /* verilator lint_on LATCH */
                end else begin : gen_no_write_second
                    assign write1 = 1'b0;
                end

                // Intentional high-level storage latch (style-guide exception).
                // Port 0 wins a collision, matching the flip-flop backend.
                /* verilator lint_off LATCH */
                always @* begin
                    if (clk_i && write0_q) begin
                        value_q = wdata0_q;
                    end else if (clk_i && write1) begin
                        value_q = wdata1;
                    end
                end
                /* verilator lint_on LATCH */
            end
        end else begin : gen_invalid_impl
            // An unresolved cell deliberately rejects an unsupported selector
            // during elaboration/synthesis, including tools without $fatal.
            uqu_gpregfile_invalid_implementation u_invalid_implementation ();
        end

        if (((ISA_E != 0) && (ISA_E != 1)) ||
            ((ISA_ZFINX != 0) && (ISA_ZFINX != 1)) ||
            ((XIF != 0) && (XIF != 1)) ||
            ((XIF_DUALWRITE != 0) && (XIF_DUALWRITE != 1)) ||
            ((XIF_NUM_RS != 2) && (XIF_NUM_RS != 3))) begin : gen_invalid_parameters
            uqu_gpregfile_invalid_parameters u_invalid_parameters ();
        end
    endgenerate
endmodule

`default_nettype wire
