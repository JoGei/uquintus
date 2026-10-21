`default_nettype none

// One word transaction for IF. The core owns PMP; the requester supplies its
// completed denial decision for the aligned containing word at acceptance.
module uqu_ifetch (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        flush_i,
    input  wire        req_valid_i,
    output wire        req_ready_o,
    input  wire [31:0] req_addr_i,
    input  wire        req_access_fault_i,
    input  wire        request_permit_i,
    output wire        busy_o,
    output wire        res_valid_o,
    input  wire        res_ready_i,
    output wire [31:0] res_addr_o,
    output wire [31:0] res_data_o,
    output wire        res_error_o,
    output wire        imem_req_o,
    output wire [31:0] imem_addr_o,
    input  wire        imem_gnt_i,
    input  wire        imem_rvalid_i,
    input  wire [31:0] imem_rdata_i,
    input  wire        imem_err_i
);
    localparam [2:0] ST_IDLE = 3'd0;
    localparam [2:0] ST_PERMISSION = 3'd1;
    localparam [2:0] ST_REQUEST = 3'd2;
    localparam [2:0] ST_RESPONSE = 3'd3;
    localparam [2:0] ST_RESULT = 3'd4;

    reg [2:0] state_q;
    reg killed_q;
    reg [31:0] addr_q;
    reg [31:0] data_q;
    reg error_q;
    wire req_fire = req_valid_i && req_ready_o;
    wire grant_fire = imem_req_o && imem_gnt_i;
    wire res_fire = res_valid_o && res_ready_i;

    assign req_ready_o = rst_ni && !flush_i && (state_q == ST_IDLE);
    assign busy_o = rst_ni && (state_q != ST_IDLE);
    assign res_valid_o = rst_ni && !flush_i && (state_q == ST_RESULT);
    assign res_addr_o = res_valid_o ? addr_q : 32'd0;
    assign res_data_o = res_valid_o && !error_q ? data_q : 32'd0;
    assign res_error_o = res_valid_o && error_q;

    // Ordinary flush and permission changes cannot retract an OBI request.
    // Reset alone may abandon it under the coordinated system-reset contract.
    assign imem_req_o = rst_ni && (state_q == ST_REQUEST);
    assign imem_addr_o = imem_req_o ? addr_q : 32'd0;

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            state_q <= ST_IDLE;
            killed_q <= 1'b0;
        end else begin
            if (flush_i && (state_q != ST_IDLE)) begin
                killed_q <= 1'b1;
            end
            case (state_q)
                ST_IDLE: begin
                    if (req_fire) begin
                        addr_q <= {req_addr_i[31:2], 2'b00};
                        killed_q <= 1'b0;
                        if (req_access_fault_i) begin
                            data_q <= 32'd0;
                            error_q <= 1'b1;
                            state_q <= ST_RESULT;
                        end else if (request_permit_i) begin
                            state_q <= ST_REQUEST;
                        end else begin
                            state_q <= ST_PERMISSION;
                        end
                    end
                end
                ST_PERMISSION: begin
                    if (flush_i) begin
                        state_q <= ST_IDLE;
                    end else if (request_permit_i) begin
                        state_q <= ST_REQUEST;
                    end
                end
                ST_REQUEST: begin
                    if (grant_fire) begin
                        state_q <= ST_RESPONSE;
                    end
                end
                ST_RESPONSE: begin
                    if (imem_rvalid_i) begin
                        if (killed_q || flush_i) begin
                            state_q <= ST_IDLE;
                        end else begin
                            data_q <= imem_err_i ? 32'd0 : imem_rdata_i;
                            error_q <= imem_err_i;
                            state_q <= ST_RESULT;
                        end
                    end
                end
                ST_RESULT: begin
                    if (flush_i || res_fire) begin
                        state_q <= ST_IDLE;
                    end
                end
                default: state_q <= ST_IDLE;
            endcase
        end
    end
endmodule

`default_nettype wire
