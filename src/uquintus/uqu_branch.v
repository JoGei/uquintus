`default_nettype none
`include "uqu_ctrl.vh"

// Stateless DE branch resolution. The parent supplies available operands and
// accepts resolution once with DE transfer; prediction and redirects are external.
module uqu_branch #(
    parameter ISA_C = 0
) (
    input  wire [1:0]  branch_i,
    input  wire [2:0]  branch_op_i,
    input  wire [31:0] pc_i,
    input  wire [31:0] imm_i,
    input  wire [31:0] rs1_i,
    input  wire [31:0] rs2_i,
    input  wire        compressed_i,
    output wire        taken_o,
    output wire [31:0] target_o,
    output wire [31:0] next_pc_o,
    output wire [31:0] link_o,
    output wire        illegal_o,
    output wire        misaligned_o
);
    wire conditional = (branch_i == `UQU_BR_COND);
    wire jal = (branch_i == `UQU_BR_JAL);
    wire jalr = (branch_i == `UQU_BR_JALR);
    wire control_transfer = conditional || jal || jalr;
    wire equal = (rs1_i == rs2_i);
    wire less_unsigned = (rs1_i < rs2_i);
    // One unsigned magnitude comparator also serves signed comparisons.
    wire less_signed = (rs1_i[31] != rs2_i[31]) ? rs1_i[31] : less_unsigned;
    wire [31:0] target_base = jalr ? rs1_i : pc_i;
    wire [31:0] target_sum = target_base + imm_i;
    wire [31:0] target = jalr ? {target_sum[31:1], 1'b0} : target_sum;
    wire [31:0] instruction_bytes = ((ISA_C == 1) && compressed_i) ? 32'd2 : 32'd4;
    wire [31:0] fallthrough = pc_i + instruction_bytes;
    wire target_bad_alignment = (ISA_C == 1) ? target[0] : (|target[1:0]);
    reg condition;
    reg condition_valid;

    always @* begin
        condition = 1'b0;
        condition_valid = 1'b1;
        case (branch_op_i)
            `UQU_FUNCT3_BEQ: condition = equal;
            `UQU_FUNCT3_BNE: condition = !equal;
            `UQU_FUNCT3_BLT: condition = less_signed;
            `UQU_FUNCT3_BGE: condition = !less_signed;
            `UQU_FUNCT3_BLTU: condition = less_unsigned;
            `UQU_FUNCT3_BGEU: condition = !less_unsigned;
            default: condition_valid = 1'b0;
        endcase
    end

    // Illegal normalized controls are defensive diagnostics for DE. They never
    // independently generate trap events or attempt an ordinary redirect.
    assign illegal_o = (conditional && !condition_valid) || ((ISA_C == 0) && compressed_i);
    // Taken expresses branch intent, including when its target is misaligned.
    assign taken_o = !illegal_o && (jal || jalr || (conditional && condition));
    assign target_o = !illegal_o && control_transfer ? target : 32'd0;
    assign misaligned_o = taken_o && target_bad_alignment;
    // Preserve the bad target for tval, but suppress successful link/next-PC
    // candidates on faults. DE supplies instruction PC/original bits to WB.
    assign next_pc_o = illegal_o || misaligned_o ? pc_i : taken_o ? target : fallthrough;
    assign link_o = !illegal_o && !misaligned_o && (jal || jalr) ? fallthrough : 32'd0;

    generate
        if ((ISA_C != 0) && (ISA_C != 1)) begin : GEN_UNSUPPORTED
            uqu_branch_unsupported_configuration invalid_configuration ();
        end
    endgenerate
endmodule

`default_nettype wire
