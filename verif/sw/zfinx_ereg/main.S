/* Native-only negative checks: the qualified Spike lacks these E checks. */
#if !defined(__riscv_32e) || !UQU_ISA_ZFINX
#error zfinx_ereg requires RV32E with Zfinx
#endif
.option norvc
.section .uqu.traps, "a", @progbits
.balign 4
.global uqu_expected_traps, uqu_expected_traps_end
uqu_expected_traps:
.section .text, "ax", @progbits
.macro BAD name, encoding
\name:
    .word \encoding
    sw zero, 0(gp)
    .pushsection .uqu.traps, "a", @progbits
    .word \name, 2, \encoding
    .popsection
.endm
.global main
main:
    la t0, handler
    csrw mtvec, t0
    la gp, guard
    li s0, 0
    li t1, 0x3f800000
    li t2, 0x40000000
    li a0, 0x12345678
    BAD bad_e_rs1, 0x00780553
    BAD bad_e_rs2, 0x01030553
    BAD bad_e_rd, 0x00730853
    BAD bad_e_rs3, 0x80730543
    li t0, 4
    bne s0, t0, fail
    li t0, 0x12345678
    bne a0, t0, fail
    lw t1, 0(gp)
    li t0, 0xdeadbeef
    bne t1, t0, fail
    csrr t1, fflags
    bnez t1, fail
    li a0, 0
    ret
fail:
    li a0, 1
    ret
.balign 4
handler:
    addi s0, s0, 1
    csrr t0, mepc
    addi t0, t0, 8
    csrw mepc, t0
    mret
.section .data, "aw", @progbits
.balign 4
guard: .word 0xdeadbeef
.section .uqu.traps, "a", @progbits
uqu_expected_traps_end:
