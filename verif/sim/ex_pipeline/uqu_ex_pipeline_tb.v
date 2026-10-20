`default_nettype none
`include "uqu_config.vh"

// Parent-owned DE/EX and EX/MEM registers. The DUT contains neither boundary.
// flush_i discards EX only: an older instruction in EX/MEM may still drain.
module uqu_ex_pipeline_tb #(
    parameter ISA_M = 0,
    parameter ISA_ZFINX = 0,
    parameter MUA_MUL = `UQU_MUL_ITERATIVE,
    parameter MUA_DIV = `UQU_DIV_ITERATIVE,
    parameter MUA_MULDIV_ITERUNROLL = 8
) (
    input wire          clk_i,
    input wire          rst_ni,
    input wire          flush_i,
    input wire          operands_ready_i,
    input wire          in_valid_i,
    output wire         in_ready_o,
    input wire  [1:0]   in_fu_i,
    input wire  [4:0]   in_op_i,
    input wire  [31:0]  in_a_i,
    input wire  [31:0]  in_b_i,
    input wire  [31:0]  in_c_i,
    input wire  [2:0]   in_rm_i,
    input wire  [31:0]  in_pass_data_i,
    input wire  [31:0]  in_store_data_i,
    input wire  [31:0]  in_instr_i,
    input wire          in_exception_valid_i,
    input wire  [4:0]   in_exception_cause_i,
    input wire  [31:0]  in_exception_tval_i,
    input wire  [31:0]  in_pc_i,
    input wire  [4:0]   in_rd_i,
    output wire         out_valid_o,
    input wire          out_ready_i,
    output wire [31:0]  out_result_o,
    output wire [31:0]  out_store_data_o,
    output wire         out_fflags_valid_o,
    output wire [4:0]   out_fflags_o,
    output wire         out_exception_valid_o,
    output wire [4:0]   out_exception_cause_o,
    output wire [31:0]  out_exception_tval_o,
    output wire [31:0]  out_pc_o,
    output wire [31:0]  out_instr_o,
    output wire [4:0]   out_rd_o,
    output wire         ex_valid_o,
    output wire [31:0]  ex_pc_o,
    output wire         ex_fire_o
);
    reg                 deex_valid_q;
    reg                 exmem_valid_q;
    reg         [1:0]   deex_fu_q;
    reg         [4:0]   deex_op_q;
    reg         [31:0]  deex_a_q;
    reg         [31:0]  deex_b_q;
    reg         [31:0]  deex_c_q;
    reg         [2:0]   deex_rm_q;
    reg         [31:0]  deex_pass_data_q;
    reg         [31:0]  deex_store_data_q;
    reg         [31:0]  deex_instr_q;
    reg                 deex_exception_valid_q;
    reg         [4:0]   deex_exception_cause_q;
    reg         [31:0]  deex_exception_tval_q;
    reg         [31:0]  deex_pc_q;
    reg         [4:0]   deex_rd_q;
    reg         [31:0]  exmem_result_q;
    reg         [31:0]  exmem_store_data_q;
    reg                 exmem_fflags_valid_q;
    reg         [4:0]   exmem_fflags_q;
    reg                 exmem_exception_valid_q;
    reg         [4:0]   exmem_exception_cause_q;
    reg         [31:0]  exmem_exception_tval_q;
    reg         [31:0]  exmem_pc_q;
    reg         [31:0]  exmem_instr_q;
    reg         [4:0]   exmem_rd_q;
    wire ex_ready;
    wire ex_valid;
    wire exmem_ready = !exmem_valid_q || out_ready_i;
    wire        [31:0]  ex_result;
    wire        [31:0]  ex_store_data;
    wire                ex_fflags_valid;
    wire        [4:0]   ex_fflags;
    wire                ex_exception_valid;
    wire        [4:0]   ex_exception_cause;
    wire        [31:0]  ex_exception_tval;

    assign in_ready_o = rst_ni && !flush_i && ex_ready;
    assign out_valid_o = rst_ni && exmem_valid_q;
    assign ex_valid_o = rst_ni && deex_valid_q;
    assign ex_pc_o = deex_pc_q;
    assign ex_fire_o = ex_valid && exmem_ready;
    assign out_result_o = exmem_result_q;
    assign out_store_data_o = exmem_store_data_q;
    assign out_fflags_valid_o = exmem_fflags_valid_q;
    assign out_fflags_o = exmem_fflags_q;
    assign out_exception_valid_o = exmem_exception_valid_q;
    assign out_exception_cause_o = exmem_exception_cause_q;
    assign out_exception_tval_o = exmem_exception_tval_q;
    assign out_pc_o = exmem_pc_q;
    assign out_instr_o = exmem_instr_q;
    assign out_rd_o = exmem_rd_q;

    always @(posedge clk_i) begin
        if (!rst_ni || flush_i) begin
            deex_valid_q <= 1'b0;
        end else if (ex_ready) begin
            deex_valid_q <= in_valid_i;
            if (in_valid_i) begin
                deex_fu_q <= in_fu_i;
                deex_op_q <= in_op_i;
                deex_a_q <= in_a_i;
                deex_b_q <= in_b_i;
                deex_c_q <= in_c_i;
                deex_rm_q <= in_rm_i;
                deex_pass_data_q <= in_pass_data_i;
                deex_store_data_q <= in_store_data_i;
                deex_instr_q <= in_instr_i;
                deex_exception_valid_q <= in_exception_valid_i;
                deex_exception_cause_q <= in_exception_cause_i;
                deex_exception_tval_q <= in_exception_tval_i;
                deex_pc_q <= in_pc_i;
                deex_rd_q <= in_rd_i;
            end
        end
        if (!rst_ni) begin
            exmem_valid_q <= 1'b0;
        end else if (exmem_ready) begin
            exmem_valid_q <= ex_valid;
            if (ex_valid) begin
                exmem_result_q <= ex_result;
                exmem_store_data_q <= ex_store_data;
                exmem_fflags_valid_q <= ex_fflags_valid;
                exmem_fflags_q <= ex_fflags;
                exmem_exception_valid_q <= ex_exception_valid;
                exmem_exception_cause_q <= ex_exception_cause;
                exmem_exception_tval_q <= ex_exception_tval;
                exmem_pc_q <= deex_pc_q;
                exmem_instr_q <= deex_instr_q;
                exmem_rd_q <= deex_rd_q;
            end
        end
    end

    uqu_ex #(
        .ISA_M(ISA_M), .ISA_ZFINX(ISA_ZFINX), .MUA_MUL(MUA_MUL), .MUA_DIV(MUA_DIV),
        .MUA_MULDIV_ITERUNROLL(MUA_MULDIV_ITERUNROLL)
    ) u_ex (
        .clk_i(clk_i), .rst_ni(rst_ni), .flush_i(flush_i),
        .valid_i(deex_valid_q), .ready_o(ex_ready), .valid_o(ex_valid), .ready_i(exmem_ready),
        .operands_ready_i(operands_ready_i),
        .fu_i(deex_fu_q),
        .op_i(deex_op_q),
        .a_i(deex_a_q),
        .b_i(deex_b_q),
        .c_i(deex_c_q),
        .rm_i(deex_rm_q),
        .pass_data_i(deex_pass_data_q),
        .store_data_i(deex_store_data_q),
        .instr_i(deex_instr_q),
        .exception_valid_i(deex_exception_valid_q),
        .exception_cause_i(deex_exception_cause_q),
        .exception_tval_i(deex_exception_tval_q),
        .result_o(ex_result),
        .store_data_o(ex_store_data),
        .fflags_valid_o(ex_fflags_valid),
        .fflags_o(ex_fflags),
        .exception_valid_o(ex_exception_valid),
        .exception_cause_o(ex_exception_cause),
        .exception_tval_o(ex_exception_tval)
    );
endmodule

`default_nettype wire
