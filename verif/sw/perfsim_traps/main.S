/* Reuse the architectural self-check with an independently timed window. */
#define main fault_test
#include "../traps/main.S"
#undef main
.section .text, "ax", @progbits
.option norvc
.balign 4
.global main, uqu_bench_start, uqu_bench_stop
main:
    mv s3, ra
uqu_bench_start:
    csrr t3, mcycle
    call fault_test
uqu_bench_stop:
    csrr t3, mcycle
    jr s3
