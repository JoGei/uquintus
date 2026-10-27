`default_nettype none

// Stateless instruction selection. The parent supplies the word containing PC
// and its consecutive successor, and qualifies any PC/pop update with transfer.
module uqu_if_aligner #(
    parameter ISA_C = 0
) (
    input  wire        valid_i,
    input  wire [31:0] pc_i,
    input  wire        word0_valid_i,
    input  wire [31:0] word0_data_i,
    input  wire        word0_error_i,
    input  wire        word1_valid_i,
    input  wire [31:0] word1_data_i,
    input  wire        word1_error_i,
    output wire        valid_o,
    output wire [31:0] instr_o,
    output wire        compressed_o,
    output wire [31:0] next_pc_o,
    output wire        drop_word_o,
    output wire        word1_needed_o,
    output wire        misaligned_o,
    output wire        exception_valid_o,
    output wire [4:0]  exception_cause_o,
    output wire [31:0] exception_tval_o
);
    localparam [4:0] CAUSE_INSTRUCTION_ACCESS = 5'd1;
    wire [15:0] first_half = pc_i[1] ? word0_data_i[31:16] : word0_data_i[15:0];
    wire short_instruction = (ISA_C == 1) && (first_half[1:0] != 2'b11);
    wire crossing = (ISA_C == 1) && pc_i[1] && !short_instruction;
    reg valid;
    reg compressed;
    reg word1_needed;
    reg exception;
    reg [31:0] tval;

    assign misaligned_o = valid_i && (pc_i[0] || ((ISA_C == 0) && pc_i[1]));
    assign valid_o = valid;
    // Compute lookahead from bytes independently of validity and faults.
    // Only valid, nonfaulting selections may consume these payloads.
    assign instr_o = short_instruction ? {16'd0,first_half} :
                     crossing ? {word1_data_i[15:0],first_half} : word0_data_i;
    assign compressed_o = compressed;
    assign word1_needed_o = word1_needed;
    assign exception_valid_o = exception;
    assign exception_cause_o = exception ? CAUSE_INSTRUCTION_ACCESS : 5'd0;
    assign exception_tval_o = tval;
    assign next_pc_o = pc_i + (short_instruction ? 32'd2 : 32'd4);
    assign drop_word_o = valid && !exception && (!compressed || pc_i[1]);

    always @* begin
        valid = 1'b0;
        compressed = 1'b0;
        word1_needed = 1'b0;
        exception = 1'b0;
        tval = 32'd0;
        if (valid_i && !misaligned_o && word0_valid_i) begin
            if (word0_error_i) begin
                // No data from a failed first word can identify instruction length.
                valid = 1'b1;
                exception = 1'b1;
                tval = pc_i;
            end else if (short_instruction) begin
                valid = 1'b1;
                compressed = 1'b1;
            end else if (crossing) begin
                word1_needed = 1'b1;
                if (word1_valid_i) begin
                    valid = 1'b1;
                    if (word1_error_i) begin
                        exception = 1'b1;
                        tval = pc_i + 32'd2;
                    end
                end
            end else begin
                valid = 1'b1;
            end
        end
    end

    generate
        if ((ISA_C != 0) && (ISA_C != 1)) begin : gen_invalid
            uqu_if_aligner_invalid_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
