/* Locked NA4 regions deny M-mode data and instruction accesses. */
.section .text,"ax",@progbits
.option norvc
.balign 4
.global main,uqu_bench_start,uqu_bench_stop
main:
    mv s0, ra
    li s1, 0
    la t0, handler
    csrw mtvec, t0
    la t0, guard
    srli t1, t0, 2
    csrw pmpaddr0, t1
    addi t1, t0, 4
    srli t1, t1, 2
    csrw pmpaddr1, t1
    la t1, forbidden_fetch
    srli t1, t1, 2
    csrw pmpaddr2, t1
    li t1, 0x909190
    csrw pmpcfg0, t1
uqu_bench_start:
    csrr t2, mcycle
.global denied_load
denied_load:
    lw a0, 0(t0)
.global denied_store
denied_store:
    sw zero, 4(t0)
    la t1, forbidden_fetch
    jr t1
.global fetch_resume
fetch_resume:
    lw t1, 4(t0)
    li t2, 0x76543210
    bne t1, t2, fail
    li t1, 3
    bne s1, t1, fail
    li a0, 0
    j done
fail:
    li a0, 1
done:
uqu_bench_stop:
    csrr t2, mcycle
    jr s0
.balign 4
.global forbidden_fetch
forbidden_fetch:
    addi a0, zero, 1
    j fail
handler:
    addi s1, s1, 1
    csrr t1, mcause
    li t2, 1
    beq t1, t2, 1f
    csrr t1, mepc
    addi t1, t1, 4
    j 2f
1:  la t1, fetch_resume
2:  csrw mepc, t1
    mret
.section .data,"aw",@progbits
.balign 4
guard:.word 0xfeed1234,0x76543210
.section .uqu.traps,"a",@progbits
.balign 4
.global uqu_expected_traps,uqu_expected_traps_end
uqu_expected_traps:
    .word denied_load,5,guard
    .word denied_store,7,guard+4
    .word forbidden_fetch,1,forbidden_fetch
uqu_expected_traps_end:
