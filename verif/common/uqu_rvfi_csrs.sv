`default_nettype none
`include "uqu_rvfi_csrs.vh"

// Capture the pre-state at acceptance. The following observation cycle reads
// the real committed post-state, including WARL legalization and lock behavior.
// No predicted CSR file, simulator delays or processor outputs are introduced.
module uqu_rvfi_csrs (
    input wire clk_i,
    input wire rst_ni,
    input wire event_i,
    input wire [11:0] csr_addr_i,
    input wire csr_read_i,
    input wire csr_write_i,
    input wire trap_i,
    input wire mret_i,
    input wire fp_flags_valid_i, fp_rm_read_i,
    input wire [64*`UQU_RVFI_CSR_COUNT-1:0] values_i
    `define UQU_RVFI_CSR(NAME, WIDTH, INDEX, LO, HI, ULO, UHI) `UQU_RVFI_CSR_OUTPUT(NAME, WIDTH, INDEX, LO, HI, ULO, UHI)
    `include "uqu_rvfi_csr_list.vh"
    `undef UQU_RVFI_CSR
);
`define UQU_RVFI_CSR_OBSERVE(NAME, W, INDEX, L, H, UL, UH) \
    uqu_rvfi_csr #(.WIDTH(W), .LO(L), .HI(H), .ULO(UL), .UHI(UH)) u_``NAME ( \
        .clk_i(clk_i), .rst_ni(rst_ni), .event_i(event_i), .csr_addr_i(csr_addr_i), \
        .csr_read_i(csr_read_i), .csr_write_i(csr_write_i), .trap_i(trap_i), .mret_i(mret_i), \
        .fp_flags_valid_i(fp_flags_valid_i), .fp_rm_read_i(fp_rm_read_i), \
        .value_i(values_i[INDEX*64 +: W]), .rmask(rvfi_csr_``NAME``_rmask), \
        .wmask(rvfi_csr_``NAME``_wmask), .rdata(rvfi_csr_``NAME``_rdata), .wdata(rvfi_csr_``NAME``_wdata));
    `define UQU_RVFI_CSR(NAME, WIDTH, INDEX, LO, HI, ULO, UHI) `UQU_RVFI_CSR_OBSERVE(NAME, WIDTH, INDEX, LO, HI, ULO, UHI)
    `include "uqu_rvfi_csr_list.vh"
    `undef UQU_RVFI_CSR
`undef UQU_RVFI_CSR_OBSERVE
endmodule

module uqu_rvfi_csr #(
    parameter WIDTH = 32,
    parameter [11:0] LO = 12'hfff,
    parameter [11:0] HI = 12'hfff,
    parameter [11:0] ULO = 12'hfff,
    parameter [11:0] UHI = 12'hfff
) (
    input wire clk_i, rst_ni, event_i,
    input wire [11:0] csr_addr_i,
    input wire csr_read_i, csr_write_i, trap_i, mret_i,
    input wire fp_flags_valid_i, fp_rm_read_i,
    input wire [WIDTH-1:0] value_i,
    output wire [WIDTH-1:0] rmask, wmask, rdata, wdata
);
    reg [WIDTH-1:0] csr_before_q;
    reg [WIDTH-1:0] csr_rmask_q, csr_wmask_q;
    wire selected = (csr_addr_i == LO) ||
        ((HI != 12'hfff) && (csr_addr_i == HI)) ||
        ((ULO != 12'hfff) && (csr_addr_i == ULO)) ||
        ((UHI != 12'hfff) && (csr_addr_i == UHI));
    wire [63:0] csr_mask = ((WIDTH == 64) &&
        ((csr_addr_i == HI) || (csr_addr_i == UHI))) ?
        64'hffffffff00000000 : 64'h00000000ffffffff;
    wire csr_implicit_read =
        (trap_i && ((LO == 12'h300) || (LO == 12'h305))) ||
        (mret_i && ((LO == 12'h300) || (LO == 12'h341)));
    wire csr_implicit_write =
        (trap_i && ((LO == 12'h300) || (LO == 12'h341) ||
                    (LO == 12'h342) || (LO == 12'h343))) ||
        (mret_i && (LO == 12'h300));
    // Observe accrued exceptions and writes through another FCSR alias.
    // Register fields outside the selected view remain unmodified.
    wire [31:0] fp_read_mask =
        ((fp_flags_valid_i && ((LO == 12'h001) || (LO == 12'h003))) ? 32'h1f : 32'd0) |
        (fp_rm_read_i ? ((LO == 12'h002) ? 32'h7 : (LO == 12'h003) ? 32'he0 : 32'd0) : 32'd0);
    wire [31:0] fp_write_mask =
        ((LO == 12'h001) && (fp_flags_valid_i || (csr_write_i && csr_addr_i == 12'h003))) ? 32'h1f :
        ((LO == 12'h002) && csr_write_i && csr_addr_i == 12'h003) ? 32'h7 :
        (LO == 12'h003) ?
            (((fp_flags_valid_i || (csr_write_i && csr_addr_i == 12'h001)) ? 32'h1f : 32'd0) |
             ((csr_write_i && csr_addr_i == 12'h002) ? 32'he0 : 32'd0)) : 32'd0;
    wire [63:0] fp_read_mask_wide = {32'd0, fp_read_mask};
    wire [63:0] fp_write_mask_wide = {32'd0, fp_write_mask};
    assign rmask = rst_ni ? csr_rmask_q : {WIDTH{1'b0}};
    assign wmask = rst_ni ? csr_wmask_q : {WIDTH{1'b0}};
    assign rdata = (|csr_rmask_q) ? csr_before_q : {WIDTH{1'b0}};
    assign wdata = (|csr_wmask_q) ? value_i :
        (|csr_rmask_q) ? csr_before_q : {WIDTH{1'b0}};
    always @(posedge clk_i) begin
        if (!rst_ni || !event_i) begin
            csr_rmask_q <= {WIDTH{1'b0}};
            csr_wmask_q <= {WIDTH{1'b0}};
        end else begin
            csr_before_q <= value_i;
            csr_rmask_q <= csr_implicit_read ? {WIDTH{1'b1}} :
                (csr_read_i && selected) ? csr_mask[WIDTH-1:0] : fp_read_mask_wide[WIDTH-1:0];
            csr_wmask_q <= csr_implicit_write ? {WIDTH{1'b1}} :
                (csr_write_i && selected) ? csr_mask[WIDTH-1:0] : fp_write_mask_wide[WIDTH-1:0];
        end
    end
endmodule

`default_nettype wire
