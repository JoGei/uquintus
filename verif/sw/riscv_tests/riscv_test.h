/* uquintus bare-metal execution environment for unchanged upstream ISA tests.
 * No privileged probing or upstream env submodule is required. crt0.S supplies
 * initialized GPRs, mtvec, main entry, and retired-store tohost completion.
 */
#ifndef UQU_RISCV_TEST_H
#define UQU_RISCV_TEST_H

#define RVTEST_RV32U
#define RVTEST_RV64U
#define TESTNUM gp
#define RVTEST_CODE_BEGIN \
    .section .text, "ax", @progbits; \
    .balign 4; .global main; main:
#define RVTEST_CODE_END
#define RVTEST_PASS li a0, 0; j _exit
#define RVTEST_FAIL mv a0, TESTNUM; bnez a0, 1f; li a0, 1; 1: j _exit
#define RVTEST_DATA_BEGIN .balign 16; .global begin_signature; begin_signature:
#define RVTEST_DATA_END .balign 16; .global end_signature; end_signature:

#endif
