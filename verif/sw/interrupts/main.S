/* IRQ levels come from the ELF-bound testbench plan. Each accepted source is
 * acknowledged by the harness; other pending sources remain asserted. */
.option push
.option norvc
.section .text,"ax",@progbits
.balign 4
.global main
main:
    mv s0,ra
    li s1,0
    la s2,irq_log
    la s3,guard
    la t0,vector_table
    csrw mtvec,t0
    li t0,0x1800
    csrw mstatus,t0
    li t0,0x888
    csrw mie,t0
.global irq_global_masked
irq_global_masked:
    addi zero,zero,0
    csrr t0,mip
    li t1,8
    bne t0,t1,fail
    csrw mip,zero          /* Hardware-owned sources cannot be cleared by CSR. */
    csrr t0,mip
    bne t0,t1,fail
    li t1,12
1:  addi t1,t1,-1
    bnez t1,1b
    li t0,0x1808
    csrw mstatus,t0
    li t0,1
    bne s1,t0,wait_global
    j global_done
wait_global:
    li t0,1
    bne s1,t0,wait_global
global_done:
    li t0,8
    csrw mie,t0
.global irq_source_masked
irq_source_masked:
    addi zero,zero,0
    csrr t0,mip
    li t1,128
    bne t0,t1,fail
    csrrc t0,mip,t1
    li t1,128
    bne t0,t1,fail
    csrr t0,mip
    bne t0,t1,fail
    li t1,12
2:  addi t1,t1,-1
    bnez t1,2b
    li t0,0x888
    csrw mie,t0
wait_source:
    li t0,2
    bne s1,t0,wait_source
    la t0,vector_table
    ori t0,t0,1
    csrw mtvec,t0
.global irq_memory
irq_memory:
    lw s4,0(s3)
    addi s4,s4,1
    sw s4,4(s3)
wait_memory:
    li t0,3
    bne s1,t0,wait_memory
#ifdef __riscv_muldiv
    li t1,-29
    li t2,7
.global irq_division
irq_division:
    div s5,t1,t2
    li t0,-4
    bne s5,t0,fail
wait_division:
    li t0,4
    bne s1,t0,wait_division
#endif
.global irq_priority
irq_priority:
    addi zero,zero,0
wait_priority:
    li t0,6
#ifdef __riscv_muldiv
    li t0,7
#endif
    bne s1,t0,wait_priority
#if UQU_ISA_UMODE
    li t0,0                /* MRET enters U with MIE=0. */
    csrw mstatus,t0
    la t0,user_entry
    csrw mepc,t0
    mret
    sw zero,0(s3)           /* Flushed sequential path of MRET. */
    j fail
user_entry:
.global irq_user
irq_user:
    addi zero,zero,0        /* M-mode IRQ eligible in U even with MIE=0. */
wait_user:
    li t0,7
#ifdef __riscv_muldiv
    li t0,8
#endif
    bne s1,t0,wait_user
#endif
    lw t0,0(s3)
    li t1,0x13579bdf
    bne t0,t1,fail
    lw t0,4(s3)
    li t1,0x13579be0
    bne t0,t1,fail
    li a0,0
    jr s0
fail:
    li a0,1
    jr s0
.balign 64
vector_table:
    /* Fixed 4-byte slots even when C is enabled. BASE also serves direct mode. */
    .rept 12
    j handler
    .endr
handler:
    addi sp,sp,-16
    sw t0,0(sp)
    sw t1,4(sp)
    sw t2,8(sp)
    csrr t0,mcause
    slli t1,s1,2
    add t1,s2,t1
    sw t0,0(t1)
    addi s1,s1,1
    li t2,0x1800
    csrs mstatus,t2         /* Return to M, including the U-mode scenario. */
    lw t2,8(sp)
    lw t1,4(sp)
    lw t0,0(sp)
    addi sp,sp,16
    mret
.section .data,"aw",@progbits
.balign 4
guard: .word 0x13579bdf,0
irq_log: .zero 32
.section .uqu.irqs,"a",@progbits
.balign 4
.global uqu_interrupts,uqu_interrupts_end
uqu_interrupts:
    .word 1,irq_global_masked,8,0
    .word 1,irq_source_masked,128,0
    .word 2,irq_memory,2048,0
#ifdef __riscv_muldiv
    .word 3,irq_division,8,0
#endif
    .word 1,irq_priority,0x888,0
#if UQU_ISA_UMODE
    .word 1,irq_user,2048,0
#endif
uqu_interrupts_end:
.option pop
