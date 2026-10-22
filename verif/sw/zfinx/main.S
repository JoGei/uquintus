/* Directed RV32 Zfinx ISA checks. Every result is also compared with Spike.
 * No floating-point ABI, compiler-generated FP, or separate f-register state. */
.option push
.option norvc
.section .uqu.traps, "a", @progbits
.balign 4
.global uqu_expected_traps, uqu_expected_traps_end
uqu_expected_traps:
.section .text, "ax", @progbits
.balign 4
.set expected_count, 0

.macro CHECK reg, expected
    li t0, \expected
    bne \reg, t0, fail
.endm
.macro FLAGS expected
    csrr a1, fflags
    CHECK a1, \expected
.endm
.macro BAD name, encoding
.global \name
\name:
    .word \encoding
    sw zero, 0(gp)           /* Must be skipped by the trap handler. */
    .pushsection .uqu.traps, "a", @progbits
    .word \name, 2, \encoding
    .popsection
    .set expected_count, expected_count+1
.endm
/* Walking every architectural GPR includes ra/sp/gp; no stack access occurs
 * until those values have been restored. x5 needs a different check scratch. */
.macro CHECK_REG number, expected
    .if \number == 5
        li tp, \expected
        bne x\number, tp, fail
    .else
        li t0, \expected
        bne x\number, t0, fail
    .endif
.endm
.macro WALK number
    li t1, 0x3f800000
    li t2, 0x40000000
    fadd.s x\number, t1, t2, rne
    .if \number == 0
        CHECK_REG \number, 0
    .else
        CHECK_REG \number, 0x40400000
    .endif

    .if \number == 7
        li s1, 0x40000000
        li x\number, 0x3f800000
        fadd.s a0, x\number, s1, rne
    .else
        li t2, 0x40000000
        li x\number, 0x3f800000
        fadd.s a0, x\number, t2, rne
    .endif
    .if \number == 0
        CHECK a0, 0x40000000
    .else
        CHECK a0, 0x40400000
    .endif

    .if \number == 6
        li s1, 0x3f800000
        li x\number, 0x40000000
        fsub.s a0, s1, x\number, rne
    .else
        li t1, 0x3f800000
        li x\number, 0x40000000
        fsub.s a0, t1, x\number, rne
    .endif
    .if \number == 0
        CHECK a0, 0x3f800000
    .else
        CHECK a0, 0xbf800000
    .endif

    li a0, 0xdeadbeef         /* FMA's third source is rs3, not old rd. */
    .if \number == 6
        li a1, 0x3f800000
        li t2, 0x40000000
        li x\number, 0x40400000
        fmadd.s a0, a1, t2, x\number, rne
    .elseif \number == 7
        li t1, 0x3f800000
        li a1, 0x40000000
        li x\number, 0x40400000
        fmadd.s a0, t1, a1, x\number, rne
    .else
        li t1, 0x3f800000
        li t2, 0x40000000
        li x\number, 0x40400000
        fmadd.s a0, t1, t2, x\number, rne
    .endif
    .if \number == 0
        CHECK a0, 0x40000000
    .else
        CHECK a0, 0x40a00000
    .endif
.endm

/* Half-ULP ties make each encoded/dynamic rounding choice observable. */
.macro ROUND mode, number, positive, negative, signed_positive, signed_negative
    li t1, 0x3f800000
    li t2, 0x33800000
    fadd.s a0, t1, t2, \mode
    CHECK a0, \positive
    li t1, 0xbf800000
    li t2, 0xb3800000
    fadd.s a0, t1, t2, \mode
    CHECK a0, \negative
    li t1, 0x3fc00000
    fcvt.w.s a0, t1, \mode
    CHECK a0, \signed_positive
    li t1, 0xbfc00000
    fcvt.w.s a0, t1, \mode
    CHECK a0, \signed_negative
    csrwi frm, \number
    li t1, 0x3f800000
    li t2, 0x33800000
    fadd.s a0, t1, t2, dyn
    CHECK a0, \positive
    li t1, 0xbf800000
    li t2, 0xb3800000
    fadd.s a0, t1, t2, dyn
    CHECK a0, \negative
.endm

/* Independent Spike execution checks all rounding-capable encodings in each
 * mode, with distinct source registers and inexact arithmetic/conversions. */
.macro ROUND_OPS mode
    li t1, 0x3f800001
    li t2, 0x40400000
    li s1, 0x33800000
    fadd.s a0, t1, s1, \mode
    fsub.s a0, t1, s1, \mode
    fmul.s a0, t1, t1, \mode
    fdiv.s a0, t1, t2, \mode
    fsqrt.s a0, t2, \mode
    fmadd.s a0, t1, t1, s1, \mode
    fmsub.s a0, t1, t1, s1, \mode
    fnmsub.s a0, t1, t1, s1, \mode
    fnmadd.s a0, t1, t1, s1, \mode
    fcvt.w.s a0, t1, \mode
    fcvt.wu.s a0, t1, \mode
    li t1, 0x01000001
    fcvt.s.w a0, t1, \mode
    fcvt.s.wu a0, t1, \mode
.endm

.global main
main:
    la t0, saved_return
    sw ra, 0(t0)
    li t0, 0x7800            /* Attempt FS=Dirty; Zfinx must keep FS=Off. */
    csrw mstatus, t0
    csrr t1, mstatus
    CHECK t1, 0x1800
    csrr t1, misa
    li t0, 0x10028          /* F, D, Q must all remain zero. */
    and t1, t1, t0
    bnez t1, fail
#if UQU_ISA_ZFINX
    csrw fcsr, zero
#ifdef __riscv_32e
    .irp reg,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
#else
    .irp reg,0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31
#endif
        WALK \reg
    .endr
    la sp, _stack_top
    li t1, 0x3fc00000
    li t2, 0x40100000
    li s1, 0xbf000000
    fadd.s a0, t1, t2, rne
    CHECK a0, 0x40700000
    fsub.s a0, t1, t2, rne
    CHECK a0, 0xbf400000
    fmul.s a0, t1, t2, rne
    CHECK a0, 0x40580000
    fdiv.s a0, t1, t2, rne
    CHECK a0, 0x3f2aaaab
    FLAGS 1
    fsqrt.s a0, t2, rne
    CHECK a0, 0x3fc00000
    fmadd.s a0, t1, t2, s1, rne
    CHECK a0, 0x40380000
    fmsub.s a0, t1, t2, s1, rne
    CHECK a0, 0x40780000
    fnmsub.s a0, t1, t2, s1, rne
    CHECK a0, 0xc0780000
    fnmadd.s a0, t1, t2, s1, rne
    CHECK a0, 0xc0380000
    fsgnj.s a0, t1, s1
    CHECK a0, 0xbfc00000
    fsgnjn.s a0, t1, s1
    CHECK a0, 0x3fc00000
    fsgnjx.s a0, s1, s1
    CHECK a0, 0x3f000000
    fmin.s a0, t1, t2
    CHECK a0, 0x3fc00000
    fmax.s a0, t1, t2
    CHECK a0, 0x40100000
    feq.s a0, t1, t2
    CHECK a0, 0
    flt.s a0, t1, t2
    CHECK a0, 1
    fle.s a0, t1, t2
    CHECK a0, 1
    fclass.s a0, t1
    CHECK a0, 64
    fcvt.w.s a0, t1, rne
    CHECK a0, 2
    fcvt.wu.s a0, t1, rne
    CHECK a0, 2
    li t1, -3
    fcvt.s.w a0, t1, rne
    CHECK a0, 0xc0400000
    li t1, -1
    fcvt.s.wu a0, t1, rne
    CHECK a0, 0x4f800000
    /* All sources and the destination may name the same register. */
    li t1, 0x3fc00000
    fmadd.s t1, t1, t1, t1, rne
    CHECK t1, 0x40700000

    ROUND rne,0,0x3f800000,0xbf800000,2,-2
    ROUND rtz,1,0x3f800000,0xbf800000,1,-1
    ROUND rdn,2,0x3f800000,0xbf800001,1,-2
    ROUND rup,3,0x3f800001,0xbf800000,2,-1
    ROUND rmm,4,0x3f800001,0xbf800001,2,-2
    ROUND_OPS rne
    ROUND_OPS rtz
    ROUND_OPS rdn
    ROUND_OPS rup
    ROUND_OPS rmm
    .irp rounding,0,1,2,3,4
        csrwi frm, \rounding
        ROUND_OPS dyn
    .endr
    csrwi frm, 0

    /* Every FCLASS category, using integer loads of exact bit patterns. */
    la a2, classes
    li a3, 1
1:  lw t1, 0(a2)
    fclass.s a0, t1
    bne a0, a3, fail
    addi a2, a2, 4
    slli a3, a3, 1
    li t0, 1024
    bne a3, t0, 1b

    csrw fflags, zero
    li t1, 0x7fc12345
    li t2, 0xbf800000
    fsgnj.s a0, t1, t2
    CHECK a0, 0xffc12345     /* Sign injection preserves a NaN payload. */
    fadd.s a0, t1, t2, rne
    CHECK a0, 0x7fc00000     /* Arithmetic uses canonical NaN. */
    feq.s a0, t1, t1
    CHECK a0, 0
    FLAGS 0
    flt.s a0, t1, t2
    CHECK a0, 0
    FLAGS 16
    csrw fflags, zero
    li t1, 0x7f800001
    fmin.s a0, t1, t2
    CHECK a0, 0xbf800000
    FLAGS 16
    csrw fflags, zero
    li t1, 0x80000000
    fmin.s a0, t1, zero
    CHECK a0, 0x80000000
    fmax.s a0, t1, zero
    CHECK a0, 0
    FLAGS 0
    li t1, 0x00800000
    li t2, 0x3f7fffff
    fmul.s a0, t1, t2, rne
    CHECK a0, 0x00800000     /* Unbounded-exponent rounding remains tiny. */
    FLAGS 3
    csrw fflags, zero
    li t1, 0x00800001
    li t2, 0x3f7ffffe
    fmul.s a0, t1, t2, rne
    CHECK a0, 0x00800000     /* This unbounded result rounds to normal. */
    FLAGS 1
    csrw fflags, zero
    li t1, 1
    li t2, 0x3f000000
    fmul.s a0, t1, t2, rne
    CHECK a0, 0
    FLAGS 3
    li t1, 0x7f7fffff
    li t2, 0x40000000
    fmul.s a0, t1, t2, rne
    CHECK a0, 0x7f800000
    FLAGS 7                 /* Sticky UF|OF|NX. */
    li t1, 0x3f800000
    fdiv.s zero, t1, zero, rne
    FLAGS 15                /* Writing x0 still accrues DZ. */
    li t1, 0xbf800000
    fsqrt.s zero, t1, rne
    FLAGS 31

    /* All six CSR access forms and alias preservation. */
    csrwi fcsr, 0
    li t1, 0x45
    csrrw a0, fcsr, t1
    CHECK a0, 0
    csrr a0, frm
    CHECK a0, 2
    csrr a0, fflags
    CHECK a0, 5
    csrsi fflags, 8
    csrr a0, fcsr
    CHECK a0, 0x4d
    csrci fflags, 1
    li t1, 16
    csrrs a0, fflags, t1
    CHECK a0, 12
    csrrc a0, fflags, t1
    CHECK a0, 28
    csrr a0, fcsr
    CHECK a0, 0x4c
    csrwi frm, 4
    csrr a0, fcsr
    CHECK a0, 0x8c
    csrrw zero, fflags, zero /* Suppressed read, explicit clear. */
    csrr a0, fcsr
    CHECK a0, 0x80
    csrw fcsr, zero
#endif
    la sp, _stack_top
    la gp, guard
    la t0, handler
    csrw mtvec, t0
    li s0, 0
#if UQU_ISA_ZFINX
    li t1, 0x3f800000
    li t2, 0x40000000
    BAD bad_rm5, 0x00735553
    BAD bad_rm6, 0x00736553
    csrwi frm, 5
    BAD bad_dynamic5, 0x00737553
    csrwi frm, 6
    BAD bad_dynamic6, 0x00737553
    csrwi frm, 7
    BAD bad_dynamic7, 0x00737553
    csrwi frm, 0
    BAD bad_fmt_d, 0x02730553
    BAD bad_fmt_h, 0x04730553
    BAD bad_sqrt_source, 0x58730553
    BAD bad_sgnj_function, 0x20733553
    BAD bad_fcvt_long, 0xc0230553
    BAD bad_flw, 0x00032507
    BAD bad_fsw, 0x00732027
    BAD bad_fmv_x_w, 0xe0030553
    BAD bad_fmv_w_x, 0xf0030553
#if UQU_ISA_UMODE
    la t0, user
    csrw mepc, t0
    csrw mstatus, zero
    mret
    sw zero, 0(gp)
user:
    csrw fcsr, zero          /* Legal in U despite FS=Off. */
    li t1, 0x3f800000
    li t2, 0x33800000
    csrwi frm, 3
    fadd.s a0, t1, t2, dyn
    CHECK a0, 0x3f800001
    FLAGS 1
.global user_exit
user_exit:
    ecall
    sw zero, 0(gp)
    .pushsection .uqu.traps, "a", @progbits
    .word user_exit, 8, 0
    .popsection
    .set expected_count, expected_count+1
#endif
#else
    BAD disabled_fadd, 0x00730553
    BAD disabled_fma, 0x48730543
    BAD disabled_fflags, 0x00102573
    BAD disabled_frm, 0x00202573
    BAD disabled_fcsr, 0x00302573
#endif
    li t0, expected_count
    bne s0, t0, fail
    lw t1, 0(gp)
    CHECK t1, 0xdeadbeef
    li a0, 0
    j done
fail:
    li a0, 1
done:
    la t0, saved_return
    lw ra, 0(t0)
    ret
.balign 4
handler:
    addi sp, sp, -16
    sw t0, 0(sp)
    sw t1, 4(sp)
    sw t2, 8(sp)
    addi s0, s0, 1
    csrr t0, mepc
#if UQU_ISA_ZFINX && UQU_ISA_UMODE
    la t1, user_exit
    bne t0, t1, 1f
    li t1, 0x1800
    csrs mstatus, t1         /* Return the U ECALL to M. */
1:
#endif
    addi t0, t0, 8
    csrw mepc, t0
    lw t0, 0(sp)
    lw t1, 4(sp)
    lw t2, 8(sp)
    addi sp, sp, 16
    mret
.section .rodata, "a", @progbits
.balign 4
classes:
    .word 0xff800000,0xbf800000,0x80000001,0x80000000,0,1,0x3f800000,0x7f800000,0x7f800001,0x7fc00000
.section .data, "aw", @progbits
.balign 4
saved_return: .word 0
guard: .word 0xdeadbeef
.section .uqu.traps, "a", @progbits
uqu_expected_traps_end:
.option pop
