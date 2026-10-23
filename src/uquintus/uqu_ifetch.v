`default_nettype none
`include "uqu_config.vh"

// Request bypass, one granted transaction and two optionally fall-through results.
// A response may retire on the same edge as the following request is granted.
// The core supplies the completed PMP denial decision at native acceptance.
module uqu_ifetch #(
    parameter MUA_REDIRECT_BYPASS = `UQU_REDIRECT_BYPASS_NONE
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        flush_i,
    // Local accepted prediction: discard at the edge without masking the
    // current registered result used to compute that prediction.
    input  wire        clear_i,
    // req_* belongs to the new stream while flush/clear cancels the old one.
    input  wire        replace_i,
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

    wire invalidate = flush_i || clear_i;
    wire res_fire = res_valid_o && res_ready_i;
    wire stored_pop = res_fire && (result_count_q != 0);
    // Do not mask the live head with local clear: this very instruction may
    // generate that clear through prediction. Global flush still masks it.
    wire live_response = ((MUA_REDIRECT_BYPASS & `UQU_REDIRECT_BYPASS_IFETCH_RESULT) != 0) &&
                         rst_ni && !flush_i && (result_count_q == 0) &&
                         pending_q && !pending_killed_q && imem_rvalid_i;
    wire consume_live = live_response && res_ready_i;
    wire response = pending_q && imem_rvalid_i;
    wire response_push = response && !pending_killed_q && !invalidate && !consume_live;
    // Reserve room for the next non-backpressurable response before presenting
    // its request. A presented request retains that reservation through grant.
    wire [2:0] count_after_response = {1'b0,result_count_q} - {2'b00,stored_pop} +
                                    {2'b00,response_push};
    wire response_room = invalidate || (count_after_response < 3'd2);
    wire use_queued = request_valid_q && (!invalidate || request_presented_q);
    wire may_present = (request_armed_q || request_permit_i) && !invalidate && response_room && (!pending_q || response);
    wire queued_request = rst_ni && request_valid_q && !request_fault_q &&
                          (request_presented_q || may_present);
    // An empty request slot bypasses directly to OBI. Native readiness stays
    // independent of the live protection decision and bus grant on this path.
    wire direct_request = rst_ni && (!invalidate || replace_i) && !use_queued && req_valid_i &&
                          !req_access_fault_i && request_permit_i && response_room &&
                          (!pending_q || response);
    wire queued_grant = queued_request && imem_gnt_i;
    wire direct_grant = direct_request && imem_gnt_i;
    wire grant_fire = queued_grant || direct_grant;
    wire denied_done = request_valid_q && request_fault_q && !pending_q &&
                       !invalidate && response_room;
    wire request_done = queued_grant || denied_done;
    wire req_fire = req_valid_i && req_ready_o;
    // Preserve the original next-cycle completion for an idle denied request.
    // Otherwise it queues behind earlier work, preserving response order.
    wire denied_direct = !invalidate && req_fire && req_access_fault_i && !request_valid_q &&
                         !pending_q && response_room;
    wire push = response_push || denied_done || denied_direct;
    wire [31:0] push_addr = response_push ? pending_addr_q :
                           denied_done ? request_addr_q : {req_addr_i[31:2],2'b00};
    wire push_error = !response_push || imem_err_i;
    wire [2:0] count_after_push = {1'b0,result_count_q} - {2'b00,stored_pop} + {2'b00,push};
    wire pending_after = grant_fire || (pending_q && !response);

    assign req_ready_o = rst_ni && (!invalidate || replace_i) && (!use_queued || request_done);
    assign busy_o = rst_ni && (request_valid_q || pending_q || (result_count_q != 0));
    assign res_valid_o = rst_ni && !flush_i && ((result_count_q != 0) || live_response);
    assign res_addr_o = !res_valid_o ? 32'd0 : live_response ? pending_addr_q : result_addr_q[result_head_q];
    assign res_error_o = res_valid_o && (live_response ? imem_err_i : result_error_q[result_head_q]);
    assign res_data_o = !res_valid_o || res_error_o ? 32'd0 :
                        live_response ? imem_rdata_i : result_data_q[result_head_q];
    // A consumed live response is not enqueued. A stalled live response is
    // captured with its address/error and becomes a stable registered head.
    // Flush may cancel private work, but never withdraw a presented request.
    assign imem_req_o = queued_request || direct_request;
    // Payload is irrelevant while idle; avoid a request-control mux at the
    // address endpoint. Presented requests use their retained address.
    assign imem_addr_o = use_queued ? request_addr_q : {req_addr_i[31:2],2'b00};

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
            if (invalidate && pending_q) pending_killed_q <= 1'b1;
            if (grant_fire) begin
                pending_q <= 1'b1;
                pending_addr_q <= queued_grant ? request_addr_q : {req_addr_i[31:2],2'b00};
                pending_killed_q <= queued_grant && (request_killed_q || invalidate);
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
            if (invalidate) begin
                if (request_valid_q && request_presented_q && !grant_fire)
                    request_killed_q <= 1'b1;
                else begin
                    request_valid_q <= 1'b0;
                    request_presented_q <= 1'b0;
                end
            end
            // Replacement wins over cancellation only for the newly accepted
            // stream. A presented old request still owns the bus through grant.
            if (req_fire) begin
                request_valid_q <= !denied_direct && !direct_grant;
                request_addr_q <= {req_addr_i[31:2],2'b00};
                request_fault_q <= req_access_fault_i;
                request_armed_q <= request_permit_i;
                request_killed_q <= 1'b0;
                // A bypassed ungranted request becomes retained immediately.
                // Permission/capacity release also preserves presentation through flush.
                request_presented_q <= !req_access_fault_i && request_permit_i &&
                                       !pending_after && (invalidate || (count_after_push < 3'd2));
            end

            if (invalidate) begin
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
                if (stored_pop) result_head_q <= !result_head_q;
                result_count_q <= count_after_push[1:0];
            end
        end
    end
    generate
        if ((MUA_REDIRECT_BYPASS < `UQU_REDIRECT_BYPASS_NONE) ||
            (MUA_REDIRECT_BYPASS > `UQU_REDIRECT_BYPASS_IF_BUFFER_REDIRECT_REQUEST_IFETCH_RESULT)) begin : gen_invalid
            uqu_ifetch_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
