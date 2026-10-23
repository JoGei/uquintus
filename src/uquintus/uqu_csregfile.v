`default_nettype none

// Architectural CSR state only. The parent serializes instructions, supplies
// one-shot commit/events, owns current privilege, and performs trap redirects.
module uqu_csregfile #(
    parameter ISA_E = 0,
    parameter ISA_M = 0,
    parameter ISA_C = 0,
    parameter ISA_ZFINX = 0,
    parameter ISA_F = 0,
    parameter ISA_A = 0,
    parameter ISA_UMODE = 1,
    parameter ISA_PMP = 0,
    parameter DEBUG = 0
) (
    input  wire         clk_i,
    input  wire         rst_ni,
    input  wire         flush_i,
    input  wire         csr_valid_i,
    input  wire         csr_commit_i,
    input  wire [11:0]  csr_addr_i,
    input  wire [2:0]   csr_op_i,
    input  wire [31:0]  csr_src_i,
    input  wire         csr_src_zero_i,
    input  wire         csr_rd_zero_i,
    input  wire [31:0]  csr_instr_i,
    input  wire         priv_m_i,
    input  wire         event_priv_m_i,
    input  wire [31:0]  hart_id_i,
    input  wire         irq_software_i,
    input  wire         irq_timer_i,
    input  wire         irq_external_i,
    input  wire         retire_i,
    input  wire         trap_i,
    input  wire [31:0]  trap_pc_i,
    input  wire         trap_interrupt_i,
    input  wire [4:0]   trap_cause_i,
    input  wire [31:0]  trap_tval_i,
    input  wire         mret_i,
    input  wire         debug_mode_i,
    input  wire         debug_enter_i,
    input  wire [31:0]  debug_pc_i,
    input  wire [2:0]   debug_cause_i,
    input  wire         debug_ebreak_i,
    input  wire         dret_i,
    output wire [31:0]  dcsr_o,
    output wire [31:0]  dpc_o,
    input  wire         fp_flags_valid_i,
    input  wire [4:0]   fp_flags_i,
    output wire         csr_read_o,
    output wire         csr_write_o,
    output wire [31:0]  csr_rdata_o,
    output wire         csr_exception_valid_o,
    output wire [4:0]   csr_exception_cause_o,
    output wire [31:0]  csr_exception_tval_o,
    output wire [31:0]  mstatus_o,
    output wire [31:0]  mie_o,
    output wire [31:0]  mip_o,
    output wire [31:0]  mtvec_o,
    output wire [31:0]  mepc_o,
    output wire [127:0] pmpcfg_o,
    output wire [511:0] pmpaddr_o,
    output wire [2:0]   frm_o,
    output wire [4:0]   fflags_o
);
    localparam EPC_LSB = (ISA_C == 1) ? 1 : 2;
    localparam [31:0] MISA = 32'h40000000 |
                           ((ISA_E == 1) ? 32'h00000010 : 32'h00000100) |
                           ((ISA_M == 1) ? 32'h00001000 : 32'd0) |
                           ((ISA_C == 1) ? 32'h00000004 : 32'd0) |
                           ((ISA_UMODE == 1) ? 32'h00100000 : 32'd0);

    reg mstatus_mie_q;
    reg mstatus_mpie_q;
    wire mstatus_mpp_m;
    wire mstatus_mprv;
    wire mstatus_tw;
    reg [2:0] mie_q;
    reg [30:0] mtvec_q;
    reg [31:EPC_LSB] mepc_q;
    reg [31:0] mscratch_q;
    reg [4:0] mcause_q;
    reg [31:0] mtval_q;
    reg [63:0] mcycle_q;
    reg [63:0] mcycle_d;
    reg [63:0] minstret_q;
    reg [63:0] minstret_d;
    reg [1:0] inhibit_q;
    wire [1:0] counteren;
    wire [31:0] mcountinhibit;
    wire [31:0] mcounteren;
    wire [31:0] mcause;
    wire [31:0] fcsr;
    wire [31:0] dscratch;
    reg [31:0] read_value;
    reg [31:0] write_value;
    reg mapped;
    reg counter_allowed;
    integer index;

    wire op_valid = (csr_op_i[1:0] != 2'b00);
    wire source_zero = csr_op_i[2] ? (csr_src_i[4:0] == 5'd0) : csr_src_zero_i;
    wire [31:0] source_value = csr_op_i[2] ? {27'd0, csr_src_i[4:0]} : csr_src_i;
    wire read_requested = (csr_op_i[1:0] != 2'b01) || !csr_rd_zero_i;
    wire write_requested = (csr_op_i[1:0] == 2'b01) || !source_zero;
    wire debug_mode = (DEBUG == 1) && debug_mode_i;
    wire debug_enter = (DEBUG == 1) && debug_enter_i && !debug_mode;
    wire debug_csr = (csr_addr_i[11:4] == 8'h7b);
    wire privilege_allowed = debug_csr ? debug_mode :
        (debug_mode || priv_m_i || ((ISA_UMODE == 1) && (csr_addr_i[9:8] == 2'b00)));
    wire illegal = !op_valid || !mapped || !privilege_allowed || !counter_allowed ||
                   (write_requested && (csr_addr_i[11:10] == 2'b11));
    wire active = rst_ni && csr_valid_i && !flush_i;
    wire csr_we = active && csr_commit_i && !illegal && write_requested &&
                  !trap_i && !mret_i && !debug_enter && !((DEBUG == 1) && dret_i);
    wire mret_fire = mret_i && priv_m_i && !debug_mode && !debug_enter;
    wire trap_fire = trap_i && !debug_mode && !debug_enter;
    wire count_enabled = !debug_mode && !((DEBUG == 1) && debug_ebreak_i);

    assign csr_read_o = active && !illegal && read_requested;
    assign csr_write_o = active && !illegal && write_requested;
    assign csr_rdata_o = csr_read_o ? read_value : 32'd0;
    assign csr_exception_valid_o = active && illegal;
    assign csr_exception_cause_o = csr_exception_valid_o ? 5'd2 : 5'd0;
    assign csr_exception_tval_o = csr_exception_valid_o ? csr_instr_i : 32'd0;

    assign mstatus_o = {10'd0, mstatus_tw, 3'd0, mstatus_mprv, 4'd0,
                        {2{mstatus_mpp_m}}, 3'd0, mstatus_mpie_q, 3'd0,
                        mstatus_mie_q, 3'd0};
    assign mie_o = {20'd0, mie_q[2], 3'd0, mie_q[1], 3'd0, mie_q[0], 3'd0};
    assign mip_o = {20'd0, irq_external_i, 3'd0, irq_timer_i, 3'd0, irq_software_i, 3'd0};
    assign mtvec_o = {mtvec_q[30:1], 1'b0, mtvec_q[0]};
    assign mepc_o = {mepc_q, {EPC_LSB{1'b0}}};
    assign mcause = {mcause_q[4], 27'd0, mcause_q[3:0]};
    assign mcountinhibit = {29'd0, inhibit_q[1], 1'b0, inhibit_q[0]};
    assign mcounteren = {29'd0, counteren[1], 1'b0, counteren[0]};
    assign fcsr = {24'd0, frm_o, fflags_o};

    // Decode only mapped CSRs; no payload array indexed by CSR address.
    always @* begin
        read_value = 32'd0;
        index = 0;
        mapped = 1'b1;
        counter_allowed = 1'b1;
        case (csr_addr_i)
            12'h001: begin read_value = {27'd0, fflags_o}; mapped = (ISA_ZFINX == 1); end
            12'h002: begin read_value = {29'd0, frm_o}; mapped = (ISA_ZFINX == 1); end
            12'h003: begin read_value = fcsr; mapped = (ISA_ZFINX == 1); end
            12'h300: read_value = mstatus_o;
            12'h301: read_value = MISA;
            12'h304: read_value = mie_o;
            12'h305: read_value = mtvec_o;
            12'h306: begin read_value = mcounteren; mapped = (ISA_UMODE == 1); end
            12'h30a, 12'h31a: mapped = (ISA_UMODE == 1);
            12'h310: read_value = 32'd0;
            12'h320: read_value = mcountinhibit;
            12'h340: read_value = mscratch_q;
            12'h341: read_value = mepc_o;
            12'h342: read_value = mcause;
            12'h343: read_value = mtval_q;
            12'h344: read_value = mip_o;
            12'h7b0: begin read_value = dcsr_o; mapped = (DEBUG == 1); end
            12'h7b1: begin read_value = dpc_o; mapped = (DEBUG == 1); end
            12'h7b2: begin read_value = dscratch; mapped = (DEBUG == 1); end
            12'hb00: read_value = mcycle_q[31:0];
            12'hb80: read_value = mcycle_q[63:32];
            12'hb02: read_value = minstret_q[31:0];
            12'hb82: read_value = minstret_q[63:32];
            12'hc00, 12'hc80: begin
                read_value = csr_addr_i[7] ? mcycle_q[63:32] : mcycle_q[31:0];
                counter_allowed = debug_mode || priv_m_i || counteren[0];
            end
            12'hc02, 12'hc82: begin
                read_value = csr_addr_i[7] ? minstret_q[63:32] : minstret_q[31:0];
                counter_allowed = debug_mode || priv_m_i || counteren[1];
            end
            12'hf11, 12'hf12, 12'hf13, 12'hf15: read_value = 32'd0;
            12'hf14: read_value = hart_id_i;
            default: begin
                mapped = 1'b0;
                // Unimplemented HPM counters/events are mapped zero, not RAM.
                if (((csr_addr_i >= 12'hb03) && (csr_addr_i <= 12'hb1f)) ||
                    ((csr_addr_i >= 12'hb83) && (csr_addr_i <= 12'hb9f)) ||
                    ((csr_addr_i >= 12'h323) && (csr_addr_i <= 12'h33f))) begin
                    mapped = 1'b1;
                end
                if (((csr_addr_i >= 12'hc03) && (csr_addr_i <= 12'hc1f)) ||
                    ((csr_addr_i >= 12'hc83) && (csr_addr_i <= 12'hc9f))) begin
                    mapped = 1'b1;
                    counter_allowed = debug_mode || priv_m_i;
                end
                for (index = 0; index < 4; index = index + 1) begin
                    if (csr_addr_i == (12'h3a0 + index[11:0])) begin
                        mapped = 1'b1;
                        read_value = pmpcfg_o[index * 32 +: 32];
                    end
                end
                for (index = 0; index < 16; index = index + 1) begin
                    if (csr_addr_i == (12'h3b0 + index[11:0])) begin
                        mapped = 1'b1;
                        read_value = pmpaddr_o[index * 32 +: 32];
                    end
                end
            end
        endcase
        case (csr_op_i[1:0])
            2'b01: write_value = source_value;
            2'b10: write_value = read_value | source_value;
            2'b11: write_value = read_value & ~source_value;
            default: write_value = read_value;
        endcase
    end

    always @* begin
        mcycle_d = mcycle_q;
        minstret_d = minstret_q;
        if (count_enabled && !inhibit_q[0]) mcycle_d = mcycle_q + 64'd1;
        if (count_enabled && !inhibit_q[1] && retire_i) minstret_d = minstret_q + 64'd1;
        // A half write overrides the entire counter's implicit increment.
        if (csr_we && (csr_addr_i == 12'hb00)) mcycle_d = {mcycle_q[63:32], write_value};
        if (csr_we && (csr_addr_i == 12'hb80)) mcycle_d = {write_value, mcycle_q[31:0]};
        if (csr_we && (csr_addr_i == 12'hb02)) minstret_d = {minstret_q[63:32], write_value};
        if (csr_we && (csr_addr_i == 12'hb82)) minstret_d = {write_value, minstret_q[31:0]};
    end

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            mstatus_mie_q <= 1'b0;
            mstatus_mpie_q <= 1'b0;
            mie_q <= 3'd0;
            mtvec_q <= 31'd0;
            mepc_q <= {32-EPC_LSB{1'b0}};
            mscratch_q <= 32'd0;
            mcause_q <= 5'd0;
            mtval_q <= 32'd0;
            mcycle_q <= 64'd0;
            minstret_q <= 64'd0;
            inhibit_q <= 2'd0;
        end else begin
            mcycle_q <= mcycle_d;
            minstret_q <= minstret_d;
            if (trap_fire) begin
                mstatus_mpie_q <= mstatus_mie_q;
                mstatus_mie_q <= 1'b0;
                mepc_q <= trap_pc_i[31:EPC_LSB];
                mcause_q <= {trap_interrupt_i, trap_cause_i[3:0]};
                mtval_q <= trap_tval_i;
            end else if (mret_fire) begin
                mstatus_mie_q <= mstatus_mpie_q;
                mstatus_mpie_q <= 1'b1;
            end else if (csr_we && (csr_addr_i == 12'h300)) begin
                mstatus_mie_q <= write_value[3];
                mstatus_mpie_q <= write_value[7];
            end
            if (csr_we) begin
                case (csr_addr_i)
                    12'h304: mie_q <= {write_value[11], write_value[7], write_value[3]};
                    12'h305: mtvec_q <= {write_value[31:2], (write_value[1:0] == 2'b01)};
                    12'h320: inhibit_q <= {write_value[2], write_value[0]};
                    12'h340: mscratch_q <= write_value;
                    12'h341: mepc_q <= write_value[31:EPC_LSB];
                    12'h342: mcause_q <= {write_value[31], write_value[3:0]};
                    12'h343: mtval_q <= write_value;
                    default: begin end
                endcase
            end
        end
    end

    generate
        if (DEBUG == 1) begin : GEN_DEBUG
            reg ebreakm_q;
            reg step_q;
            reg [2:0] cause_q;
            reg [31:EPC_LSB] dpc_q;
            reg [31:0] dscratch_q;
            wire ebreaku;
            wire prv_m;
            // debugver=4, stopcount=1, mprven=1; stepie/stoptime=0.
            assign dcsr_o = 32'h40000410 | ({31'd0, ebreakm_q} << 15) |
                            ({31'd0, ebreaku} << 12) | ({29'd0, cause_q} << 6) |
                            ({31'd0, step_q} << 2) | (prv_m ? 32'd3 : 32'd0);
            assign dpc_o = {dpc_q, {EPC_LSB{1'b0}}};
            assign dscratch = dscratch_q;
            always @(posedge clk_i) begin
                if (!rst_ni) begin
                    ebreakm_q <= 1'b0;
                    step_q <= 1'b0;
                    cause_q <= 3'd0;
                    dpc_q <= {32-EPC_LSB{1'b0}};
                    dscratch_q <= 32'd0;
                end else if (debug_enter) begin
                    cause_q <= debug_cause_i;
                    dpc_q <= debug_pc_i[31:EPC_LSB];
                end else if (csr_we) begin
                    case (csr_addr_i)
                        12'h7b0: begin ebreakm_q <= write_value[15]; step_q <= write_value[2]; end
                        12'h7b1: dpc_q <= write_value[31:EPC_LSB];
                        12'h7b2: dscratch_q <= write_value;
                        default: begin end
                    endcase
                end
            end
            if (ISA_UMODE == 1) begin : GEN_USER_DEBUG
                reg ebreaku_q;
                reg prv_m_q;
                assign ebreaku = ebreaku_q;
                assign prv_m = prv_m_q;
                always @(posedge clk_i) begin
                    if (!rst_ni) begin
                        ebreaku_q <= 1'b0;
                        prv_m_q <= 1'b1;
                    end else if (debug_enter) begin
                        prv_m_q <= event_priv_m_i;
                    end else if (csr_we && (csr_addr_i == 12'h7b0)) begin
                        ebreaku_q <= write_value[12];
                        prv_m_q <= (write_value[1:0] != 2'b00);
                    end
                end
            end else begin : GEN_MACHINE_DEBUG
                assign ebreaku = 1'b0;
                assign prv_m = 1'b1;
            end
        end else begin : GEN_NO_DEBUG
            assign dcsr_o = 32'd0;
            assign dpc_o = 32'd0;
            assign dscratch = 32'd0;
        end
        if (ISA_UMODE == 1) begin : GEN_UMODE
            reg mpp_m_q;
            reg mprv_q;
            reg tw_q;
            reg [1:0] counteren_q;
            assign mstatus_mpp_m = mpp_m_q;
            assign mstatus_mprv = mprv_q;
            assign mstatus_tw = tw_q;
            assign counteren = counteren_q;
            always @(posedge clk_i) begin
                if (!rst_ni) begin
                    mpp_m_q <= 1'b1;
                    mprv_q <= 1'b0;
                    tw_q <= 1'b0;
                    counteren_q <= 2'd0;
                end else begin
                    if (trap_fire) begin
                        mpp_m_q <= event_priv_m_i;
                    end else if (mret_fire) begin
                        mpp_m_q <= 1'b0;
                        if (!mpp_m_q) mprv_q <= 1'b0;
                    end else if ((DEBUG == 1) && dret_i && debug_mode && (dcsr_o[1:0] != 2'b11)) begin
                        mprv_q <= 1'b0;
                    end else if (csr_we && (csr_addr_i == 12'h300)) begin
                        mpp_m_q <= (write_value[12:11] != 2'b00);
                        mprv_q <= write_value[17];
                        tw_q <= write_value[21];
                    end
                    if (csr_we && (csr_addr_i == 12'h306))
                        counteren_q <= {write_value[2], write_value[0]};
                end
            end
        end else begin : GEN_NO_UMODE
            assign mstatus_mpp_m = 1'b1;
            assign mstatus_mprv = 1'b0;
            assign mstatus_tw = 1'b0;
            assign counteren = 2'd0;
        end

        if (ISA_ZFINX == 1) begin : GEN_ZFINX
            reg [2:0] frm_q;
            reg [4:0] fflags_q;
            assign frm_o = frm_q;
            assign fflags_o = fflags_q;
            always @(posedge clk_i) begin
                if (!rst_ni) begin
                    frm_q <= 3'd0;
                    fflags_q <= 5'd0;
                end else begin
                    if (fp_flags_valid_i) fflags_q <= fflags_q | fp_flags_i;
                    if (csr_we) begin
                        case (csr_addr_i)
                            12'h001: fflags_q <= write_value[4:0];
                            12'h002: frm_q <= write_value[2:0];
                            12'h003: begin
                                frm_q <= write_value[7:5];
                                fflags_q <= write_value[4:0];
                            end
                            default: begin end
                        endcase
                    end
                end
            end
        end else begin : GEN_NO_ZFINX
            assign frm_o = 3'd0;
            assign fflags_o = 5'd0;
        end

        if (ISA_PMP == 1) begin : GEN_PMP
            genvar region_index;
            for (region_index = 0; region_index < 16;
                 region_index = region_index + 1) begin : GEN_ENTRIES
                localparam [11:0] CFG_ADDR = 12'h3a0 + (region_index / 4);
                localparam [11:0] ADDR_ADDR = 12'h3b0 + region_index;
                localparam CFG_SHIFT = (region_index % 4) * 8;
                reg [5:0] cfg_q;
                reg [31:0] addr_q;
                wire next_tor_locked;
                assign pmpcfg_o[region_index * 8 +: 8] = {cfg_q[5], 2'b00, cfg_q[4:0]};
                assign pmpaddr_o[region_index * 32 +: 32] = addr_q;
                if (region_index == 15) begin : GEN_LAST
                    assign next_tor_locked = 1'b0;
                end else begin : GEN_NEXT
                    assign next_tor_locked = pmpcfg_o[(region_index + 1) * 8 + 7] &&
                        (pmpcfg_o[(region_index + 1) * 8 + 3 +: 2] == 2'b01);
                end
                always @(posedge clk_i) begin
                    if (!rst_ni) begin
                        cfg_q <= 6'd0;
                    end else if (csr_we && (csr_addr_i == CFG_ADDR) && !cfg_q[5]) begin
                        // Legalize reserved R=0/W=1 to R=0/W=0; bits 6:5 zero.
                        cfg_q <= {write_value[CFG_SHIFT + 7], write_value[CFG_SHIFT + 3 +: 2],
                                  write_value[CFG_SHIFT + 2],
                                  (write_value[CFG_SHIFT + 1] && write_value[CFG_SHIFT]),
                                  write_value[CFG_SHIFT]};
                    end
                    // Address payload is deliberately unreset. Reset cfg OFF
                    // prevents uninitialized bounds from granting permissions.
                    if (rst_ni && csr_we && (csr_addr_i == ADDR_ADDR) &&
                        !cfg_q[5] && !next_tor_locked) addr_q <= write_value;
                end
            end
        end else begin : GEN_NO_PMP
            assign pmpcfg_o = 128'd0;
            assign pmpaddr_o = 512'd0;
        end

        if (((ISA_E != 0) && (ISA_E != 1)) || ((ISA_M != 0) && (ISA_M != 1)) ||
            ((ISA_C != 0) && (ISA_C != 1)) || ((ISA_UMODE != 0) && (ISA_UMODE != 1)) ||
            ((ISA_PMP != 0) && (ISA_PMP != 1)) || ((ISA_ZFINX != 0) && (ISA_ZFINX != 1)) ||
            (ISA_F != 0) || (ISA_A != 0) || ((DEBUG != 0) && (DEBUG != 1))) begin : GEN_UNSUPPORTED
            uqu_csregfile_unsupported_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
