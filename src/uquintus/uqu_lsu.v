`default_nettype none

// MEM owns request presentation; WB consumes the independent response channel.
// A stalled OBI request and an unconsumed response each retain their payload.
module uqu_lsu (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        flush_i,
    input  wire        res_flush_i,
    input  wire        req_valid_i,
    output wire        req_ready_o,
    input  wire        req_we_i,
    input  wire [2:0]  req_op_i,
    input  wire [31:0] req_addr_i,
    input  wire [31:0] req_wdata_i,
    input  wire [31:0] req_instr_i,
    input  wire        req_access_fault_i,
    input  wire        request_permit_i,
    output wire        req_exception_valid_o,
    output wire [4:0]  req_exception_cause_o,
    output wire [31:0] req_exception_tval_o,
    output wire        busy_o,
    output wire        res_registered_o,
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
    localparam [4:0] CAUSE_ILLEGAL_INSTRUCTION = 5'd2;
    localparam [4:0] CAUSE_LOAD_MISALIGNED = 5'd4;
    localparam [4:0] CAUSE_LOAD_ACCESS = 5'd5;
    localparam [4:0] CAUSE_STORE_MISALIGNED = 5'd6;
    localparam [4:0] CAUSE_STORE_ACCESS = 5'd7;

    reg held_q, held_killed_q;
    reg held_we_q;
    reg [2:0] held_op_q;
    reg [31:0] held_addr_q, held_wdata_q;
    reg [3:0] held_be_q;
    reg pending_q, killed_q;
    reg we_q;
    reg [2:0] op_q;
    reg [31:0] addr_q;
    reg response_buffer_valid_q;
    reg [31:0] result_q;
    reg error_q;

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

    wire response_present = pending_q &&
                            (response_buffer_valid_q || dmem_rvalid_i);
    wire response_error = response_buffer_valid_q ? error_q : dmem_err_i;
    wire res_fire = res_valid_o && res_ready_i;
    wire pending_done = response_present &&
                        (killed_q || res_flush_i || res_fire);
    // Successful completion may overlap the next grant. Faults contain all
    // younger effects even if the parent incorrectly leaves permission high.
    wire capacity = !pending_q || (pending_done && !response_error);
    wire start_request = req_valid_i && !flush_i && !local_fault &&
                         request_permit_i && capacity;
    wire grant_fire = dmem_req_o && dmem_gnt_i;
    wire request_killed = held_q && (held_killed_q || flush_i);

    assign req_exception_valid_o = rst_ni && !flush_i && req_valid_i &&
                                   !held_q && local_fault;
    assign req_exception_cause_o = req_exception_valid_o ? local_cause : 5'd0;
    assign req_exception_tval_o = req_exception_valid_o ? local_tval : 32'd0;
    assign req_ready_o = grant_fire && !request_killed;
    assign busy_o = rst_ni && (held_q || pending_q);
    assign res_valid_o = rst_ni && !res_flush_i && !killed_q && response_present;
    assign res_registered_o = res_valid_o && response_buffer_valid_q;
    assign res_data_o = !res_valid_o || response_error || we_q ? 32'd0 :
                        response_buffer_valid_q ? result_q : load_result;
    assign res_exception_valid_o = res_valid_o && response_error;
    assign res_exception_cause_o = !res_exception_valid_o ? 5'd0 :
                                  we_q ? CAUSE_STORE_ACCESS : CAUSE_LOAD_ACCESS;
    assign res_exception_tval_o = res_exception_valid_o ? addr_q : 32'd0;

    // The initial request is combinational; capture only when grant is delayed.
    // Once presented, request and payload persist through cancellation.
    assign dmem_req_o = rst_ni && (held_q || start_request);
    assign dmem_we_o = held_q ? held_we_q : req_we_i;
    assign dmem_addr_o = held_q ? {held_addr_q[31:2], 2'b00} :
                                           {req_addr_i[31:2], 2'b00};
    assign dmem_wdata_o = held_q ? held_wdata_q :
                         req_we_i ? (req_wdata_i << request_shift) : 32'd0;
    assign dmem_be_o = held_q ? held_be_q : request_be;

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
            held_q <= 1'b0;
            held_killed_q <= 1'b0;
            pending_q <= 1'b0;
            killed_q <= 1'b0;
            response_buffer_valid_q <= 1'b0;
        end else begin
            if (dmem_req_o && !dmem_gnt_i && !held_q) begin
                held_q <= 1'b1;
                held_killed_q <= 1'b0;
                held_we_q <= req_we_i;
                held_op_q <= req_op_i;
                held_addr_q <= req_addr_i;
                held_wdata_q <= dmem_wdata_o;
                held_be_q <= request_be;
            end
            if (held_q && flush_i) held_killed_q <= 1'b1;
            if (pending_q && res_flush_i) killed_q <= 1'b1;
            if (pending_q && !response_buffer_valid_q && dmem_rvalid_i &&
                !pending_done) begin
                response_buffer_valid_q <= 1'b1;
                result_q <= load_result;
                error_q <= dmem_err_i;
            end
            if (pending_done) begin
                pending_q <= 1'b0;
                response_buffer_valid_q <= 1'b0;
                killed_q <= 1'b0;
            end
            if (grant_fire) begin
                held_q <= 1'b0;
                held_killed_q <= 1'b0;
                pending_q <= 1'b1;
                killed_q <= request_killed;
                response_buffer_valid_q <= 1'b0;
                we_q <= held_q ? held_we_q : req_we_i;
                op_q <= held_q ? held_op_q : req_op_i;
                addr_q <= held_q ? held_addr_q : req_addr_i;
            end
        end
    end
endmodule

`default_nettype wire
