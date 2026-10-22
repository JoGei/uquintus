/* Native clock edges determine cycle values; Spike checks the CSR instruction
 * semantics with independently verified pre-instruction counter inputs. */
.option push
.option norvc
.section .text,"ax",@progbits
.balign 4
.global main
main:
    mv s0,ra
    li s10,0
    la t0,handler
    csrw mtvec,t0
    li t0,0x1800
    csrw mstatus,t0
    csrwi mcountinhibit,5
    li t0,0x12345678
    csrw mcycle,t0
    li t0,7
    csrw mcycleh,t0
    csrw minstreth,t0
    li t0,99
    csrw minstret,t0
    csrr t1,cycle
    li t0,0x12345678
    bne t0,t1,fail
    csrr t1,cycleh
    li t0,7
    bne t0,t1,fail
    csrr t1,instret
    li t0,99
    bne t0,t1,fail
    csrr t1,instreth
    li t0,7
    bne t0,t1,fail
    /* All six CSR operation forms, including read/write suppression. */
    li t0,0x100
    csrrw t1,mcycle,t0
    li t2,0x12345678
    bne t1,t2,fail
    csrsi mcycle,3
    csrrci t1,mcycle,1
    li t2,0x103
    bne t1,t2,fail
    li t0,2
    csrrc t1,mcycle,t0
    csrrs t2,mcycle,t0
    li t0,0x102
    bne t1,t0,fail
    li t0,0x100
    bne t2,t0,fail
    csrrwi t1,mcycle,17
    li t0,0x102
    bne t1,t0,fail
    csrrsi t1,mcycle,0
    csrrci t2,mcycle,0
    li t0,17
    bne t1,t0,fail
    bne t2,t0,fail
.global readonly_counter
readonly_counter:
    .word 0xc0029073          /* csrw cycle,t0: read-only even in M. */
    /* Carry from low to high while only cycle is running. */
    li t0,-2
    csrw mcycle,t0
    csrwi mcountinhibit,4
    csrr t1,mcycleh
    li t0,8
    bne t1,t0,fail
    csrwi mcountinhibit,5
    li t0,-1
    csrw mcycleh,t0
    li t0,-2
    csrw mcycle,t0
    csrwi mcountinhibit,4
    csrr t1,mcycleh          /* Full 64-bit wrap, still counting. */
    bnez t1,fail
    csrwi mcountinhibit,5
    li t0,7
    csrw minstreth,t0
    li t0,-2
    csrw minstret,t0
    csrwi mcountinhibit,1
    nop
    csrr s2,minstret          /* NOP counted; read itself not counted yet. */
    csrr t1,minstreth
    li t0,-1
    bne s2,t0,fail
    li t0,8
    bne t1,t0,fail
    /* Explicit live write wins over the writing instruction's increment. */
    li t0,100
    csrw minstret,t0
    csrr t1,minstret
    bne t1,t0,fail
    csrwi mcountinhibit,0
    csrr s2,cycle
    la t0,guard
    lw t1,0(t0)
    csrr t2,cycle
    bleu t2,s2,fail
    li t0,0x13579bdf
    bne t0,t1,fail
#ifdef __riscv_muldiv
    li t0,-29
    li t1,7
    rdcycle s3
    rdinstret s2
    div t2,t0,t1
    rdinstret t3
    rdcycle s4
    addi s2,s2,2
    bne s2,t3,fail
    bleu s4,s3,fail
    li t0,-4
    bne t0,t2,fail
#endif
    /* A synchronous trap is an event, never a retired instruction. */
    csrr s2,minstret
.global machine_ecall
machine_ecall:
    ecall
    addi s2,s2,1
    bne s2,s5,fail
#if UQU_ISA_UMODE
    csrwi mcounteren,5
    la t0,user_allowed
    csrw mepc,t0
    csrw mstatus,zero
    mret
    j fail
user_allowed:
    rdcycle t0
    rdcycleh t1
    rdinstret t2
    rdinstreth t3
.global user_ecall
user_ecall:
    ecall
    csrwi mcounteren,0
    la t0,user_denied
    csrw mepc,t0
    csrw mstatus,zero
    mret
    j fail
.global user_denied
user_denied:
    .word 0xc00022f3          /* csrr t0,cycle: mcounteren.CY=0. */
    csrwi mcounteren,1
    la t0,user_cycle_only
    csrw mepc,t0
    csrw mstatus,zero
    mret
    j fail
user_cycle_only:
    rdcycle t0
.global user_instret_denied
user_instret_denied:
    .word 0xc02022f3          /* csrr t0,instret: mcounteren.IR=0. */
#endif
    li t0,2
#if UQU_ISA_UMODE
    li t0,5
#endif
    bne s10,t0,fail
    li a0,0
    jr s0
fail:
    li a0,1
    jr s0
.balign 4
handler:
    csrr s5,minstret          /* First handler instruction observes pre-state. */
    addi s10,s10,1
    csrr t0,mepc
    addi t0,t0,4
    csrw mepc,t0
    li t0,0x1800
    csrs mstatus,t0          /* Continue in M after either U-mode trap. */
    mret
.section .data,"aw",@progbits
.balign 4
guard: .word 0x13579bdf
.section .uqu.traps,"a",@progbits
.balign 4
.global uqu_expected_traps,uqu_expected_traps_end
uqu_expected_traps:
    .word readonly_counter,2,0xc0029073
    .word machine_ecall,11,0
#if UQU_ISA_UMODE
    .word user_ecall,8,0
    .word user_denied,2,0xc00022f3
    .word user_instret_denied,2,0xc02022f3
#endif
uqu_expected_traps_end:
.option pop
