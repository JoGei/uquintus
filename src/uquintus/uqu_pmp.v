`default_nettype none

// Decode CSR-owned regions once for independent IF, MEM and optional replay
// word checks. Packed entry zero occupies the low configuration bits.
module uqu_pmp #(
    parameter ISA_PMP = 0,
    parameter ISA_C = 0,
    parameter MUA_BTB_IDATA_DEPTH = 0
) (
    input  wire [127:0] pmpcfg_i,
    input  wire [511:0] pmpaddr_i,
    input  wire [31:0]  if_addr_i,
    input  wire [1:0]   if_size_i,
    input  wire         if_priv_m_i,
    output wire         if_allow_o,
    input  wire [31:0]  mem_addr_i,
    input  wire [1:0]   mem_size_i,
    input  wire [2:0]   mem_access_i,
    input  wire         mem_priv_m_i,
    output wire         mem_allow_o,
    input  wire [31:0]  replay_addr_i,
    input  wire         replay_priv_m_i,
    output wire [1:0]   replay_allow_o
);
    // Size is log2(bytes): 0=byte, 1=halfword, 2=word; 3 is invalid.
    // MEM access is an R/W/X requirement mask in pmpcfg bit order. IF always
    // requires X. Callers derive each port's effective privilege separately.
    localparam integer PORTS = 2 + ((MUA_BTB_IDATA_DEPTH > 0) ? ((ISA_C == 1) ? 2 : 1) : 0);
    generate
        if (ISA_PMP == 0) begin : GEN_DISABLED
            assign if_allow_o = 1'b1;
            assign mem_allow_o = 1'b1;
            assign replay_allow_o = 2'b11;
        end else if (ISA_PMP == 1) begin : GEN_ENABLED
            wire [559:0] region_lower;
            wire [559:0] region_upper;
            wire [32*PORTS-1:0] check_addr;
            wire [2*PORTS-1:0] check_size;
            wire [3*PORTS-1:0] check_access;
            wire [PORTS-1:0] check_priv_m;
            wire [PORTS-1:0] check_allow;

            assign check_addr[63:0] = {mem_addr_i, if_addr_i};
            assign check_size[3:0] = {mem_size_i, if_size_i};
            assign check_access[5:0] = {mem_access_i, 3'b100};
            assign check_priv_m[1:0] = {mem_priv_m_i, if_priv_m_i};
            assign if_allow_o = check_allow[0];
            assign mem_allow_o = check_allow[1];

            if (PORTS > 2) begin : GEN_REPLAY_FIRST
                assign check_addr[95:64] = replay_addr_i;
                assign check_size[5:4] = 2'd2;
                assign check_access[8:6] = 3'b100;
                assign check_priv_m[2] = replay_priv_m_i;
                assign replay_allow_o[0] = check_allow[2];
            end else begin : GEN_NO_REPLAY_FIRST
                assign replay_allow_o[0] = 1'b1;
            end
            if (PORTS > 3) begin : GEN_REPLAY_SECOND
                assign check_addr[127:96] = replay_addr_i + 32'd4;
                assign check_size[7:6] = 2'd2;
                assign check_access[11:9] = 3'b100;
                assign check_priv_m[3] = replay_priv_m_i;
                assign replay_allow_o[1] = check_allow[3];
            end else begin : GEN_NO_REPLAY_SECOND
                assign replay_allow_o[1] = 1'b1;
            end

            // This is the only region decoder bank. Neither requester affects
            // these bounds; both comparison banks consume the same wires.
            genvar region_index;
            for (region_index = 0; region_index < 16;
                 region_index = region_index + 1) begin : GEN_REGIONS
                wire [7:0] cfg;
                wire [31:0] encoded_addr;
                wire [33:0] previous_bound;
                reg [33:0] mask;
                reg [34:0] lower_bound;
                reg [34:0] upper_bound;
                integer bit_index;

                assign cfg = pmpcfg_i[region_index * 8 +: 8];
                assign encoded_addr = pmpaddr_i[region_index * 32 +: 32];
                assign region_lower[region_index * 35 +: 35] = lower_bound;
                assign region_upper[region_index * 35 +: 35] = upper_bound;
                if (region_index == 0) begin : GEN_ZERO_BOUND
                    assign previous_bound = 34'd0;
                end else begin : GEN_PREVIOUS_BOUND
                    // TOR uses the raw predecessor address even if it is OFF.
                    assign previous_bound = {pmpaddr_i[(region_index - 1) * 32 +: 32], 2'b00};
                end

                always @* begin
                    lower_bound = 35'd0;
                    upper_bound = 35'd0;
                    mask = 34'd3;
                    bit_index = 0;
                    case (cfg[4:3])
                        2'b01: begin
                            lower_bound = {1'b0, previous_bound};
                            upper_bound = {1'b0, encoded_addr, 2'b00};
                        end
                        2'b10: begin
                            lower_bound = {1'b0, encoded_addr, 2'b00};
                            upper_bound = lower_bound + 35'd4;
                        end
                        2'b11: begin
                            // Three low byte-address bits plus one more per
                            // trailing encoded one are ignored. Saturation at
                            // 34 bits covers every address on this core's bus.
                            mask[2] = 1'b1;
                            for (bit_index = 3; bit_index < 34;
                                 bit_index = bit_index + 1) begin
                                mask[bit_index] = mask[bit_index - 1] &&
                                                 encoded_addr[bit_index - 3];
                            end
                            lower_bound = {1'b0, ({encoded_addr, 2'b00} & ~mask)};
                            upper_bound = {1'b0, (lower_bound[33:0] | mask)} + 35'd1;
                        end
                        default: begin
                            lower_bound = 35'd0;
                            upper_bound = 35'd0;
                        end
                    endcase
                end
            end

            // Independent any-byte priority/permission checks: both requests
            // are evaluated concurrently without arbitration or shared state.
            genvar port_index;
            for (port_index = 0; port_index < PORTS;
                 port_index = port_index + 1) begin : GEN_CHECKS
                wire [1:0] size;
                wire [2:0] access;
                wire priv_m;
                wire [33:0] access_first;
                wire [33:0] access_last;
                wire [33:0] access_bytes;
                reg allow;
                reg found;
                reg [7:0] cfg;
                reg [34:0] lower_bound;
                reg [34:0] upper_bound;
                integer entry;

                assign size = check_size[port_index * 2 +: 2];
                assign access = check_access[port_index * 3 +: 3];
                assign priv_m = check_priv_m[port_index];
                assign access_first = {2'b00, check_addr[port_index * 32 +: 32]};
                assign access_bytes = 34'd1 << size;
                assign access_last = access_first + access_bytes - 34'd1;
                assign check_allow[port_index] = allow;

                always @* begin
                    // Sixteen implemented but OFF entries still deny U-mode.
                    allow = priv_m;
                    found = 1'b0;
                    cfg = 8'd0;
                    lower_bound = 35'd0;
                    upper_bound = 35'd0;
                    for (entry = 0; entry < 16; entry = entry + 1) begin
                        cfg = pmpcfg_i[entry * 8 +: 8];
                        lower_bound = region_lower[entry * 35 +: 35];
                        upper_bound = region_upper[entry * 35 +: 35];
                        if (!found && (lower_bound < upper_bound) &&
                            ({1'b0, access_first} < upper_bound) &&
                            ({1'b0, access_last} >= lower_bound)) begin
                            found = 1'b1;
                            // Partial coverage fails even for unlocked M-mode.
                            allow = ({1'b0, access_first} >= lower_bound) &&
                                    ({1'b0, access_last} < upper_bound) &&
                                    ((priv_m && !cfg[7]) ||
                                     ((cfg[2:0] & access) == access));
                        end
                    end
                    // Alignment exceptions remain the owning stage's concern.
                    if ((size == 2'd3) || (access == 3'b000) ||
                        (access_last[33:32] != 2'b00)) begin
                        allow = 1'b0;
                    end
                end
            end
        end else begin : GEN_INVALID
            uqu_pmp_invalid_isa_pmp invalid_parameter ();
        end
    endgenerate
endmodule

`default_nettype wire
