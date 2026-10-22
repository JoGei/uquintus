`default_nettype none

// Combinational request bypass, one granted transaction, two registered results.
// A response may retire on the same edge as the following request is granted.
// The core supplies the completed PMP denial decision at native acceptance.
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
    reg request_valid_q;
    reg request_presented_q;
    reg request_armed_q;
    reg request_killed_q;
    reg [31:0] request_addr_q;
    reg request_fault_q;
    reg pending_q;
    reg pending_killed_q;
    reg [31:0] pending_addr_q;
    reg [31:0] result_addr_q [0:1];
    reg [31:0] result_data_q [0:1];
    reg result_error_q [0:1];
    reg result_head_q;
    reg result_tail_q;
    reg [1:0] result_count_q;

    wire res_fire = res_valid_o && res_ready_i;
    wire response = pending_q && imem_rvalid_i;
    wire response_push = response && !pending_killed_q && !flush_i;
    // Reserve room for the next non-backpressurable response before presenting
    // its request. A presented request retains that reservation through grant.
    wire [2:0] count_after_response = {1'b0,result_count_q} - {2'b00,res_fire} +
                                    {2'b00,response_push};
    wire response_room = count_after_response < 3'd2;
    wire may_present = (request_armed_q || request_permit_i) && !flush_i && response_room && (!pending_q || response);
    wire queued_request = rst_ni && request_valid_q && !request_fault_q &&
                          (request_presented_q || may_present);
    // An empty request slot bypasses directly to OBI. Native readiness stays
    // independent of the live protection decision and bus grant on this path.
    wire direct_request = rst_ni && !flush_i && !request_valid_q && req_valid_i &&
                          !req_access_fault_i && request_permit_i && response_room &&
                          (!pending_q || response);
    wire queued_grant = queued_request && imem_gnt_i;
    wire direct_grant = direct_request && imem_gnt_i;
    wire grant_fire = queued_grant || direct_grant;
    wire denied_done = request_valid_q && request_fault_q && !pending_q &&
                       !flush_i && response_room;
    wire request_done = queued_grant || denied_done;
    wire req_fire = req_valid_i && req_ready_o;
    // Preserve the original next-cycle completion for an idle denied request.
    // Otherwise it queues behind earlier work, preserving response order.
    wire denied_direct = req_fire && req_access_fault_i && !request_valid_q &&
                         !pending_q && response_room;
    wire push = response_push || denied_done || denied_direct;
    wire [31:0] push_addr = response_push ? pending_addr_q :
                           denied_done ? request_addr_q : {req_addr_i[31:2],2'b00};
    wire push_error = !response_push || imem_err_i;
    wire [2:0] count_after_push = {1'b0,result_count_q} - {2'b00,res_fire} + {2'b00,push};
    wire pending_after = grant_fire || (pending_q && !response);

    assign req_ready_o = rst_ni && !flush_i && (!request_valid_q || request_done);
    assign busy_o = rst_ni && (request_valid_q || pending_q || (result_count_q != 0));
    assign res_valid_o = rst_ni && !flush_i && (result_count_q != 0);
    assign res_addr_o = res_valid_o ? result_addr_q[result_head_q] : 32'd0;
    assign res_error_o = res_valid_o && result_error_q[result_head_q];
    assign res_data_o = res_valid_o && !res_error_o ? result_data_q[result_head_q] : 32'd0;
    // No response-data bypass. Only response validity participates in turnover.
    // Flush may cancel private work, but never withdraw a presented request.
    assign imem_req_o = queued_request || direct_request;
    // Payload is irrelevant while idle; avoid a request-control mux at the
    // address endpoint. Presented requests use their retained address.
    assign imem_addr_o = request_valid_q ? request_addr_q : {req_addr_i[31:2],2'b00};

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            request_valid_q <= 1'b0;
            request_presented_q <= 1'b0;
            request_armed_q <= 1'b0;
            request_killed_q <= 1'b0;
            pending_q <= 1'b0;
            pending_killed_q <= 1'b0;
            result_head_q <= 1'b0;
            result_tail_q <= 1'b0;
            result_count_q <= 2'd0;
        end else begin
            if (response) pending_q <= 1'b0;
            if (flush_i && pending_q) pending_killed_q <= 1'b1;
            if (grant_fire) begin
                pending_q <= 1'b1;
                pending_addr_q <= request_valid_q ? request_addr_q : {req_addr_i[31:2],2'b00};
                pending_killed_q <= (request_valid_q && request_killed_q) || flush_i;
            end

            if (request_valid_q && !request_armed_q && request_permit_i)
                request_armed_q <= 1'b1;
            if (imem_req_o) request_presented_q <= 1'b1;
            if (request_done) begin
                request_valid_q <= 1'b0;
                request_presented_q <= 1'b0;
            end
            // If this edge opens permission/capacity, the request becomes
            // visible immediately afterwards. Preserve it even if the next
            // cycle introduces a flush before another sampling edge.
            if (request_valid_q && !request_done && !request_fault_q &&
                (request_armed_q || request_permit_i) && !pending_after &&
                (count_after_push < 3'd2)) request_presented_q <= 1'b1;
            if (flush_i) begin
                if (request_valid_q && request_presented_q && !grant_fire)
                    request_killed_q <= 1'b1;
                else begin
                    request_valid_q <= 1'b0;
                    request_presented_q <= 1'b0;
                end
            end else if (req_fire) begin
                request_valid_q <= !denied_direct && !direct_grant;
                request_addr_q <= {req_addr_i[31:2],2'b00};
                request_fault_q <= req_access_fault_i;
                request_armed_q <= request_permit_i;
                request_killed_q <= 1'b0;
                // A bypassed ungranted request becomes retained immediately.
                // Permission/capacity release also preserves presentation through flush.
                request_presented_q <= !req_access_fault_i && request_permit_i &&
                                       !pending_after && (count_after_push < 3'd2);
            end

            if (flush_i) begin
                result_head_q <= 1'b0;
                result_tail_q <= 1'b0;
                result_count_q <= 2'd0;
            end else begin
                if (push) begin
                    result_addr_q[result_tail_q] <= push_addr;
                    result_data_q[result_tail_q] <= push_error ? 32'd0 : imem_rdata_i;
                    result_error_q[result_tail_q] <= push_error;
                    result_tail_q <= !result_tail_q;
                end
                if (res_fire) result_head_q <= !result_head_q;
                result_count_q <= count_after_push[1:0];
            end
        end
    end
endmodule

`default_nettype wire
