/* Loader supplies initialized data and zeros PT_LOAD tails, including BSS. */
.section .text.init, "ax", @progbits
.balign 4
.global _start
_start:
    /* GPR payload is unreset; initialize even callee-saved registers before
       compiled code can save their old values onto the stack. */
    li x1, 0
    li x3, 0
    li x4, 0
    li x5, 0
    li x6, 0
    li x7, 0
    li x8, 0
    li x9, 0
    li x10, 0
    li x11, 0
    li x12, 0
    li x13, 0
    li x14, 0
    li x15, 0
#ifndef __riscv_32e
    li x16, 0
    li x17, 0
    li x18, 0
    li x19, 0
    li x20, 0
    li x21, 0
    li x22, 0
    li x23, 0
    li x24, 0
    li x25, 0
    li x26, 0
    li x27, 0
    li x28, 0
    li x29, 0
    li x30, 0
    li x31, 0
#endif
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop
    la sp, _stack_top
    la t0, _unexpected_trap
    csrw mtvec, t0
    call main
.global _exit
_exit:
    beqz a0, 1f
    slli t0, a0, 1
    ori t0, t0, 1
    li t1, 1
    bne t0, t1, 2f
    li t0, 3             /* A nonzero exit must never encode success. */
    j 2f
1:  li t0, 1
2:  la t1, tohost
    sw t0, 0(t1)
3:  j 3b
.balign 4
_unexpected_trap:
    li a0, 127
    j _exit

.section .tohost, "aw", @progbits
.balign 8
.global tohost
.type tohost, @object
.size tohost, 8
tohost:
    .dword 0
