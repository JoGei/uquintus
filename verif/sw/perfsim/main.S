/* One deterministic instruction stream for RTL/ISS/model comparisons.
 * Counter values only delimit the window; they never control this program.
 */
.section .text
.balign 4
.global main
main:
    la t0, scratch
    li t1, 7
    li t2, -3
.global uqu_bench_start
uqu_bench_start:
    csrr a3, mcycle
    add t3, t1, t2
    sub t4, t3, t2
    sw t4, 0(t0)
    lw t5, 0(t0)
    bne t5, t1, fail
    addi t5, t5, 1
    li t6, 8
    bne t5, t6, fail
    li t4, 6
1:  addi t3, t3, 1
    addi t4, t4, -1
    bnez t4, 1b
    li t6, 10
    bne t3, t6, fail
#ifdef __riscv_muldiv
    mul t3, t1, t2
    li t6, -21
    bne t3, t6, fail
    mulh t3, t1, t2
    li t6, -1
    bne t3, t6, fail
    div t3, t1, t2
    li t6, -2
    bne t3, t6, fail
    rem t3, t1, t2
    li t6, 1
    bne t3, t6, fail
    divu t3, t1, zero
    li t6, -1
    bne t3, t6, fail
    mul zero, t1, t2
#endif
    la t6, 2f
    jalr zero, t6, 0
    j fail
2:  fence
.global uqu_bench_stop
uqu_bench_stop:
    csrr a4, mcycle
    li a0, 0
    ret
fail:
    li a0, 1
    ret
.section .bss
.balign 4
scratch:
    .zero 4
