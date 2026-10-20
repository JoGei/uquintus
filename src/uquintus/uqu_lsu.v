`default_nettype none

// Blocking native load/store unit owned by MEM. Private transaction and
// completion state do not replace the parent's EX/MEM or MEM/WB registers.
module uqu_lsu (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        flush_i,
    input  wire        req_valid_i,
    output wire        req_ready_o,
    input  wire        req_we_i,
    input  wire [2:0]  req_op_i,
    input  wire [31:0] req_addr_i,
    input  wire [31:0] req_wdata_i,
    input  wire [31:0] req_instr_i,
    input  wire        req_access_fault_i,
    input  wire        request_permit_i,
    output wire        busy_o,
    output wire        res_valid_o,
    input  wire        res_ready_i,
    output wire [31:0] res_data_o,
    output wire        res_exception_valid_o,
    output wire [4:0]  res_exception_cause_o,
    output wire [31:0] res_exception_tval_o,

    output wire        dmem_req_o,
    output wire        dmem_we_o,
    output wire [31:0] dmem_addr_o,
    output wire [31:0] dmem_wdata_o,
    output wire [3:0]  dmem_be_o,
    input  wire        dmem_gnt_i,
    input  wire        dmem_rvalid_i,
    input  wire [31:0] dmem_rdata_i,
    input  wire        dmem_err_i
);
    localparam [2:0] ST_IDLE = 3'd0;
    localparam [2:0] ST_PERMISSION = 3'd1;
    localparam [2:0] ST_REQUEST = 3'd2;
    localparam [2:0] ST_RESPONSE = 3'd3;
    localparam [2:0] ST_RESULT = 3'd4;
    localparam [4:0] CAUSE_ILLEGAL_INSTRUCTION = 5'd2;
    localparam [4:0] CAUSE_LOAD_MISALIGNED = 5'd4;
    localparam [4:0] CAUSE_LOAD_ACCESS = 5'd5;
    localparam [4:0] CAUSE_STORE_MISALIGNED = 5'd6;
    localparam [4:0] CAUSE_STORE_ACCESS = 5'd7;

    reg [2:0] state_q;
    reg killed_q;
    reg we_q;
    reg [2:0] op_q;
    reg [31:0] addr_q;
    reg [31:0] wdata_q;
    reg [3:0] be_q;
    reg [31:0] result_q;
    reg exception_q;
    reg [4:0] cause_q;
    reg [31:0] tval_q;

    wire req_fire = req_valid_i && req_ready_o;
    wire res_fire = res_valid_o && res_ready_i;
    wire grant_fire = dmem_req_o && dmem_gnt_i;
    // Operation bits are the instruction's funct3, qualified by load/store.
    wire op_valid = (req_op_i == 3'b000) || (req_op_i == 3'b001) ||
        (req_op_i == 3'b010) || (!req_we_i &&
        ((req_op_i == 3'b100) || (req_op_i == 3'b101)));
    wire misaligned = ((req_op_i[1:0] == 2'd1) && req_addr_i[0]) ||
                      ((req_op_i[1:0] == 2'd2) && (req_addr_i[1:0] != 2'b00));
    wire local_fault = !op_valid || misaligned || req_access_fault_i;
    wire [4:0] local_cause = !op_valid ? CAUSE_ILLEGAL_INSTRUCTION :
        misaligned ? (req_we_i ? CAUSE_STORE_MISALIGNED : CAUSE_LOAD_MISALIGNED) :
                     (req_we_i ? CAUSE_STORE_ACCESS : CAUSE_LOAD_ACCESS);
    wire [31:0] local_tval = !op_valid ? req_instr_i : req_addr_i;
    wire [3:0] request_be = (req_op_i[1:0] == 2'd0) ? (4'b0001 << req_addr_i[1:0]) :
                            (req_op_i[1:0] == 2'd1) ? (4'b0011 << req_addr_i[1:0]) :
                                                                    4'b1111;
    wire [4:0] request_shift = {req_addr_i[1:0], 3'b000};
    wire [4:0] response_shift = {addr_q[1:0], 3'b000};
    wire [31:0] selected_data = dmem_rdata_i >> response_shift;
    reg [31:0] load_result;

    assign req_ready_o = rst_ni && !flush_i && (state_q == ST_IDLE);
    assign busy_o = rst_ni && (state_q != ST_IDLE);
    assign res_valid_o = rst_ni && !flush_i && (state_q == ST_RESULT);
    assign res_data_o = res_valid_o ? result_q : 32'd0;
    assign res_exception_valid_o = res_valid_o && exception_q;
    assign res_exception_cause_o = res_exception_valid_o ? cause_q : 5'd0;
    assign res_exception_tval_o = res_exception_valid_o ? tval_q : 32'd0;

    // Once presented, OBI request and payload persist even through flush.
    // Only reset may abandon transaction tracking under system integration rules.
    assign dmem_req_o = rst_ni && (state_q == ST_REQUEST);
    assign dmem_we_o = dmem_req_o && we_q;
    assign dmem_addr_o = dmem_req_o ? {addr_q[31:2], 2'b00} : 32'd0;
    assign dmem_wdata_o = dmem_req_o ? wdata_q : 32'd0;
    assign dmem_be_o = dmem_req_o ? be_q : 4'd0;

    always @* begin
        load_result = 32'd0;
        case (op_q)
            3'b000: load_result = {{24{selected_data[7]}}, selected_data[7:0]};
            3'b001: load_result = {{16{selected_data[15]}}, selected_data[15:0]};
            3'b010: load_result = selected_data;
            3'b100: load_result = {24'd0, selected_data[7:0]};
            3'b101: load_result = {16'd0, selected_data[15:0]};
            default: load_result = 32'd0;
        endcase
    end

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
                        killed_q <= 1'b0;
                        we_q <= req_we_i;
                        op_q <= req_op_i;
                        addr_q <= req_addr_i;
                        wdata_q <= req_we_i ? (req_wdata_i << request_shift) : 32'd0;
                        be_q <= request_be;
                        if (local_fault) begin
                            result_q <= 32'd0;
                            exception_q <= 1'b1;
                            cause_q <= local_cause;
                            tval_q <= local_tval;
                            state_q <= ST_RESULT;
                        end else begin
                            state_q <= request_permit_i ? ST_REQUEST : ST_PERMISSION;
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
                    if (dmem_rvalid_i) begin
                        if (killed_q || flush_i) begin
                            state_q <= ST_IDLE;
                        end else begin
                            // Capture before exposing data/status to MEM or any
                            // forwarding consumer; no combinational OBI bypass.
                            result_q <= we_q || dmem_err_i ? 32'd0 : load_result;
                            exception_q <= dmem_err_i;
                            cause_q <= we_q ? CAUSE_STORE_ACCESS : CAUSE_LOAD_ACCESS;
                            tval_q <= addr_q;
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
