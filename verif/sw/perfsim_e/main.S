/* ilp32e: all live operands are x0..x15; x16 encoding must trap. */
.section .text,"ax",@progbits
.option norvc
.balign 4
.global main,uqu_bench_start,uqu_bench_stop
main:
    mv s0, ra
    la t0, handler
    csrw mtvec, t0
    li a2, 0
uqu_bench_start:
    csrr t0, mcycle
    csrrwi t0, mscratch, 31
    csrr t1, mscratch
    li t0, 31
    bne t0, t1, fail
    li a0, 0
    li a1, 20
1:  add a0, a0, a1
    addi a1, a1, -1
    bnez a1, 1b
    li t0, 210
    bne a0, t0, fail
    csrr t0, misa
    andi t0, t0, 0x110
    li t1, 0x10
    bne t0, t1, fail
.global forbidden_x16
forbidden_x16:
    .word 0x00100813
.global forbidden_rs16,forbidden_rs17
forbidden_rs16:
    .word 0x00180293
forbidden_rs17:
    .word 0x011002b3
    li t0, 3
    bne a2, t0, fail
    li a0, 0
    j done
fail:
    li a0, 1
done:
uqu_bench_stop:
    csrr t0, mcycle
    jr s0
handler:
    csrr t0, mepc
    addi t0, t0, 4
    csrw mepc, t0
    addi a2, a2, 1
    mret
.section .uqu.traps,"a",@progbits
.balign 4
.global uqu_expected_traps,uqu_expected_traps_end
uqu_expected_traps:
    .word forbidden_x16,2,0x00100813
    .word forbidden_rs16,2,0x00180293
    .word forbidden_rs17,2,0x011002b3
uqu_expected_traps_end:
