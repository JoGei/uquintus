`default_nettype none

// Core-owned interface lifetime only. Instructions remain in DE/EX/MEM/WB;
// the bitmap retains IDs for pending notifications, never instruction payloads.
module uqu_xif_ctrl #(
    parameter XIF = 0
) (
    input  wire       clk_i,
    input  wire       rst_ni,
    input  wire       draining_i,
    input  wire       de_valid_i,
    input  wire       de_fire_i,
    input  wire       de_flush_i,
    input  wire       de_issued_i,
    input  wire       issue_valid_i,
    input  wire       de_cleanup_valid_i,
    input  wire [2:0] de_cleanup_id_i,
    output wire       de_cleanup_ready_o,
    output wire       de_id_valid_o,
    output wire [2:0] de_id_o,
    output wire       de_cancel_o,
    input  wire       ex_valid_i,
    input  wire       ex_xif_i,
    input  wire [2:0] ex_id_i,
    input  wire       ex_flush_i,
    input  wire       mem_valid_i,
    input  wire       mem_xif_i,
    input  wire [2:0] mem_id_i,
    input  wire       mem_flush_i,
    input  wire       wb_retire_i,
    input  wire       wb_xif_i,
    input  wire [2:0] wb_id_i,
    input  wire       commit_valid_i,
    input  wire [2:0] commit_id_i,
    input  wire       commit_kill_i,
    output wire       kill_valid_o,
    output wire [2:0] kill_id_o,
    input  wire       kill_ready_i,
    output wire       drain_ready_o
);
    generate
        if (XIF == 1) begin : gen_enabled
            reg [7:0] live_q, live_d;
            reg [7:0] kill_q, kill_d;
            reg [2:0] next_q;
            reg reserved_q;
            reg [2:0] de_id_q;
            reg [7:0] kill_needed;
            reg [2:0] selected;
            reg found;
            integer idx;
            wire de_clear = de_flush_i || de_cancel_o || !de_valid_i;
            wire reserve = issue_valid_i && !reserved_q;
            wire retract = reserved_q && !de_issued_i && !issue_valid_i;

            assign de_cancel_o = rst_ni && draining_i && de_valid_i;
            // Sequential allocation cannot lap the oldest live ID: its bitmap
            // bit stops next_q even if younger rejected/killed IDs left holes.
            assign de_id_valid_o = rst_ni &&
                                   (reserved_q || (!(|kill_q) && !live_q[next_q]));
            assign de_id_o = !de_id_valid_o ? 3'd0 : reserved_q ? de_id_q : next_q;
            assign drain_ready_o = !(|live_q);
            assign kill_valid_o = rst_ni && found;
            assign kill_id_o = kill_valid_o ? selected : 3'd0;
            assign de_cleanup_ready_o = kill_valid_o && kill_ready_i &&
                                        (selected == de_cleanup_id_i);

            always @* begin
                kill_needed = kill_q;
                if (de_cleanup_valid_i) kill_needed[de_cleanup_id_i] = 1'b1;
                if (reserved_q && de_issued_i && de_clear) kill_needed[de_id_q] = 1'b1;
                if (ex_valid_i && ex_xif_i && ex_flush_i) kill_needed[ex_id_i] = 1'b1;
                if (mem_valid_i && mem_xif_i && mem_flush_i) kill_needed[mem_id_i] = 1'b1;
                kill_needed = kill_needed & live_q;
                selected = 3'd0;
                found = 1'b0;
                for (idx = 0; idx < 8; idx = idx + 1) begin
                    if (kill_needed[idx] && !found) begin
                        selected = idx[2:0];
                        found = 1'b1;
                    end
                end
            end
            always @* begin
                live_d = live_q;
                kill_d = kill_needed;
                if (reserve) live_d[next_q] = 1'b1;
                if (retract) live_d[de_id_q] = 1'b0;
                if (wb_retire_i && wb_xif_i) live_d[wb_id_i] = 1'b0;
                if (commit_valid_i && commit_kill_i) begin
                    live_d[commit_id_i] = 1'b0;
                    kill_d[commit_id_i] = 1'b0;
                end
            end
            always @(posedge clk_i) begin
                if (!rst_ni) begin
                    live_q <= 8'd0;
                    kill_q <= 8'd0;
                    next_q <= 3'd0;
                    reserved_q <= 1'b0;
                end else begin
                    live_q <= live_d;
                    kill_q <= kill_d;
                    if (reserve) begin
                        de_id_q <= next_q;
                        next_q <= next_q + 3'd1;
                    end
                    if (de_clear || de_fire_i || retract) reserved_q <= 1'b0;
                    else if (reserve) reserved_q <= 1'b1;
                end
            end
        end else begin : gen_disabled
            assign de_id_valid_o = 1'b0;
            assign de_id_o = 3'd0;
            assign de_cancel_o = 1'b0;
            assign de_cleanup_ready_o = 1'b0;
            assign kill_valid_o = 1'b0;
            assign kill_id_o = 3'd0;
            assign drain_ready_o = 1'b1;
        end
        if ((XIF != 0) && (XIF != 1)) begin : gen_invalid
            uqu_xif_ctrl_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
