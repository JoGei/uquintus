/* Every fault is followed by a poison store. The handler skips both; any
 * younger store reaching the bus corrupts guard and fails the RAM oracle. */
.option push
.option norvc
.section .text, "ax", @progbits
.balign 4
.global main
main:
    mv s0, ra
    li s1, 0
    li s2, 0x2468ace0
    la t4, guard
    la t0, trap_handler
    ori t0, t0, 1            /* Synchronous exceptions use BASE in vectored mode. */
    csrw mtvec, t0
    li t0, 0x1888            /* Establish matching MSTATUS; no IRQ inputs. */
    csrw mstatus, t0
    li t2, 0x123
.global trap_ecall
trap_ecall:
    ecall
    sw zero, 0(t4)
.global trap_illegal
trap_illegal:
    .word 0x02001013         /* Reserved RV32 SLLI encoding, unambiguously 32-bit. */
    sw zero, 0(t4)
.global trap_break
trap_break:
    ebreak
    sw zero, 0(t4)
.global trap_lh
trap_lh:
    lh s2, 1(t4)
    sw zero, 0(t4)
.global trap_lw
trap_lw:
    lw s2, 2(t4)
    sw zero, 0(t4)
.global trap_sh
trap_sh:
    sh t2, 1(t4)
    sw zero, 0(t4)
.global trap_sw
trap_sw:
    sw t2, 2(t4)
    sw zero, 0(t4)
#ifndef __riscv_compressed
.global trap_jal
trap_jal:
    jal s2, .+2
    sw zero, 0(t4)
    la t3, trap_jalr
    addi t3, t3, 2
.global trap_jalr
trap_jalr:
    jalr s2, 0(t3)
    sw zero, 0(t4)
#else
.global trap_illegal_c
trap_illegal_c:
    .2byte 0
    sw zero, 0(t4)
.global trap_break_c
trap_break_c:
    .2byte 0x9002
    sw zero, 0(t4)
#endif
#if UQU_ISA_UMODE
    li t0, 0x80             /* MPP=U, MPIE=1. */
    csrw mstatus, t0
    la t0, user_entry
    csrw mepc, t0
    mret
    sw zero, 0(t4)          /* Flushed sequential path of MRET. */
    j fail
user_entry:
.global trap_user_ecall
trap_user_ecall:
    ecall
    sw zero, 0(t4)
.global trap_user_mret
trap_user_mret:
    mret
    sw zero, 0(t4)
.global trap_user_csr
trap_user_csr:
    csrr t0, mstatus
    sw zero, 0(t4)
.global trap_user_exit
trap_user_exit:
    ecall
    sw zero, 0(t4)
#endif
    li t0, 0x2468ace0
    bne s2, t0, fail
    lw t0, 0(t4)
    li t1, 0xdeadbeef
    bne t0, t1, fail
    li t0, 9 + 4*UQU_ISA_UMODE
    bne s1, t0, fail
    li a0, 0
    jr s0
fail:
    li a0, 1
    jr s0
.balign 4
trap_handler:
    addi sp, sp, -16
    sw t0, 0(sp)
    sw t1, 4(sp)
    sw t2, 8(sp)
    addi s1, s1, 1
    csrr t0, mepc
#if UQU_ISA_UMODE
    la t1, trap_user_exit
    bne t0, t1, 1f
    li t1, 0x1800
    csrs mstatus, t1         /* Final U ECALL returns to M. */
1:
#endif
#ifdef __riscv_compressed
    lhu t1, 0(t0)
    andi t1, t1, 3
    li t2, 3
    beq t1, t2, 2f
    addi t0, t0, 6          /* 16-bit fault plus skipped poison store. */
    j 3f
2:
#endif
    addi t0, t0, 8
3:
    csrw mepc, t0
    lw t2, 8(sp)
    lw t1, 4(sp)
    lw t0, 0(sp)
    addi sp, sp, 16
    mret
.section .data, "aw", @progbits
.balign 4
.global guard
guard: .word 0xdeadbeef
.section .uqu.traps, "a", @progbits
.balign 4
.global uqu_expected_traps, uqu_expected_traps_end
uqu_expected_traps:
    .word trap_ecall, 11, 0
    .word trap_illegal, 2, 0x02001013
    .word trap_break, 3, 0
    .word trap_lh, 4, guard+1
    .word trap_lw, 4, guard+2
    .word trap_sh, 6, guard+1
    .word trap_sw, 6, guard+2
#ifndef __riscv_compressed
    .word trap_jal, 0, trap_jal+2
    .word trap_jalr, 0, trap_jalr+2
#else
    .word trap_illegal_c, 2, 0
    .word trap_break_c, 3, 0
#endif
#if UQU_ISA_UMODE
    .word trap_user_ecall, 8, 0
    .word trap_user_mret, 2, 0x30200073
    .word trap_user_csr, 2, 0x300022f3
    .word trap_user_exit, 8, 0
#endif
uqu_expected_traps_end:
.option pop
