`default_nettype none

// Fetched-word FIFO. The IF parent reserves space before starting a fetch,
// owns PC/redirects, and qualifies pop_i with actual instruction consumption.
module uqu_if_buffer #(
    parameter MUA_IF_BUFFER_WORDS = 2
) (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire        flush_i,
    // Synchronous discard after accepting the current head (e.g. prediction).
    // Unlike flush_i, this must not mask the head used to decide that transfer.
    input  wire        clear_i,
    input  wire        push_valid_i,
    output wire        push_ready_o,
    input  wire [31:0] push_addr_i,
    input  wire [31:0] push_data_i,
    input  wire        push_error_i,
    input  wire        pop_i,
    output wire        word0_valid_o,
    output wire [31:0] word0_addr_o,
    output wire [31:0] word0_data_o,
    output wire        word0_error_o,
    output wire        word1_valid_o,
    output wire [31:0] word1_addr_o,
    output wire [31:0] word1_data_o,
    output wire        word1_error_o
);
    localparam integer PTR_WIDTH = (MUA_IF_BUFFER_WORDS > 2) ? $clog2(MUA_IF_BUFFER_WORDS) : 1;
    localparam integer COUNT_WIDTH = $clog2(MUA_IF_BUFFER_WORDS + 1);
    localparam integer LAST_SLOT_INT = MUA_IF_BUFFER_WORDS - 1;
    localparam [PTR_WIDTH-1:0] LAST_SLOT = LAST_SLOT_INT[PTR_WIDTH-1:0];
    localparam [COUNT_WIDTH-1:0] CAPACITY = MUA_IF_BUFFER_WORDS[COUNT_WIDTH-1:0];

    reg [29:0] addr_q [0:MUA_IF_BUFFER_WORDS-1];
    reg [31:0] data_q [0:MUA_IF_BUFFER_WORDS-1];
    reg error_q [0:MUA_IF_BUFFER_WORDS-1];
    reg [PTR_WIDTH-1:0] head_q;
    reg [PTR_WIDTH-1:0] tail_q;
    reg [COUNT_WIDTH-1:0] count_q;
    wire active = rst_ni && !flush_i;
    wire pop_fire = pop_i && word0_valid_o;
    wire push_fire = push_valid_i && push_ready_o;
    wire [PTR_WIDTH-1:0] second = (head_q == LAST_SLOT) ? {PTR_WIDTH{1'b0}} : head_q + 1'b1;

    // No empty bypass. A full FIFO can replace its head on the same edge.
    assign push_ready_o = active && ((count_q < CAPACITY) || pop_fire);
    assign word0_valid_o = active && (count_q != 0);
    assign word1_valid_o = active && (count_q > 1);
    assign word0_addr_o = word0_valid_o ? {addr_q[head_q], 2'b00} : 32'd0;
    assign word1_addr_o = word1_valid_o ? {addr_q[second], 2'b00} : 32'd0;
    assign word0_error_o = word0_valid_o && error_q[head_q];
    assign word1_error_o = word1_valid_o && error_q[second];
    // Validity qualifies consumption, not the bytes used for lookahead.
    // Error payloads are already zeroed at insertion. Invalid bytes are idle
    // payload, keeping late flush/pop control out of length/decoder datapaths.
    assign word0_data_o = data_q[head_q];
    assign word1_data_o = data_q[second];

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            head_q <= {PTR_WIDTH{1'b0}};
            tail_q <= {PTR_WIDTH{1'b0}};
            count_q <= {COUNT_WIDTH{1'b0}};
        end else if (flush_i || clear_i) begin
            head_q <= {PTR_WIDTH{1'b0}};
            tail_q <= {PTR_WIDTH{1'b0}};
            count_q <= {COUNT_WIDTH{1'b0}};
        end else begin
            if (push_fire) begin
                addr_q[tail_q] <= push_addr_i[31:2];
                data_q[tail_q] <= push_error_i ? 32'd0 : push_data_i;
                error_q[tail_q] <= push_error_i;
                tail_q <= (tail_q == LAST_SLOT) ? {PTR_WIDTH{1'b0}} : tail_q + 1'b1;
            end
            if (pop_fire) begin
                head_q <= second;
            end
            case ({push_fire, pop_fire})
                2'b10: count_q <= count_q + 1'b1;
                2'b01: count_q <= count_q - 1'b1;
                default: ;
            endcase
        end
    end

    generate
        if (MUA_IF_BUFFER_WORDS < 2) begin : gen_invalid
            uqu_if_buffer_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
