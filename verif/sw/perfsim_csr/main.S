/* Deterministic CSR values; live cycle counters never control execution. */
.section .text,"ax",@progbits
.option norvc
.balign 4
.global main,uqu_bench_start,uqu_bench_stop
main:
    mv s0, ra
    csrwi mcountinhibit, 5
    li t0, 0x12345678
    csrw mcycle, t0
    csrr t1, mcycle
    bne t0, t1, fail
    li t0, 99
    csrw minstret, t0
    csrwi mcountinhibit, 1
    nop
    csrr t1, minstret
    li t0, 100
    bne t0, t1, fail
    li t0, 19
    csrw minstret, t0
    csrr t1, minstret
    bne t0, t1, fail
    csrwi mcountinhibit, 0
uqu_bench_start:
    csrr t2, mcycle
    li t0, 0x100
    csrrw t1, mscratch, t0
    csrrsi t1, mscratch, 3
    li t0, 0x100
    bne t0, t1, fail
    csrrci t1, mscratch, 1
    li t0, 0x103
    bne t0, t1, fail
    li t0, 2
    csrrc t1, mscratch, t0
    li t0, 0x102
    bne t0, t1, fail
    csrrwi t1, mscratch, 17
    li t0, 0x100
    bne t0, t1, fail
    csrrs t1, mscratch, zero
    li t0, 17
    bne t0, t1, fail
    li a0, 0
    j done
fail:
    li a0, 1
done:
uqu_bench_stop:
    csrr t2, mcycle
    jr s0
