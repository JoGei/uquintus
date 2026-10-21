// Canonical native CSR channel catalog. X(name,width,index,lo,hi,ulo,uhi).
// High/user aliases share the canonical 64-bit machine counter channel.
`ifndef UQU_RVFI_CSRS_VH
`define UQU_RVFI_CSRS_VH
`define UQU_RVFI_CSR_COUNT 99


// Leading commas allow use after the ordinary RVFI port list.
`define UQU_RVFI_CSR_OUTPUT(NAME, WIDTH, INDEX, LO, HI, ULO, UHI) \
    , output wire [WIDTH-1:0] rvfi_csr_``NAME``_rmask \
    , output wire [WIDTH-1:0] rvfi_csr_``NAME``_wmask \
    , output wire [WIDTH-1:0] rvfi_csr_``NAME``_rdata \
    , output wire [WIDTH-1:0] rvfi_csr_``NAME``_wdata
`define UQU_RVFI_CSR_INPUT(NAME, WIDTH, INDEX, LO, HI, ULO, UHI) \
    , input wire [WIDTH-1:0] rvfi_csr_``NAME``_rmask \
    , input wire [WIDTH-1:0] rvfi_csr_``NAME``_wmask \
    , input wire [WIDTH-1:0] rvfi_csr_``NAME``_rdata \
    , input wire [WIDTH-1:0] rvfi_csr_``NAME``_wdata
`define UQU_RVFI_CSR_CONNECT(NAME, WIDTH, INDEX, LO, HI, ULO, UHI) \
    , .rvfi_csr_``NAME``_rmask(rvfi_csr_``NAME``_rmask) \
    , .rvfi_csr_``NAME``_wmask(rvfi_csr_``NAME``_wmask) \
    , .rvfi_csr_``NAME``_rdata(rvfi_csr_``NAME``_rdata) \
    , .rvfi_csr_``NAME``_wdata(rvfi_csr_``NAME``_wdata)
`endif
