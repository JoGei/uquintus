/* Cycle-only RTL port. Upstream Embench algorithms and verifiers are unchanged. */
#include <stdint.h>
#include <stdlib.h>
#include "support.h"

volatile char uqu_bench_log[4096];
volatile uint32_t uqu_bench_log_size;
volatile uint32_t uqu_bench_log_overflow;
static uint32_t start_ticks, stop_ticks;

__attribute__((noinline)) void start_trigger(void)
{
    uint32_t ticks;
    __asm__ volatile (".global uqu_bench_start\n"
                      "uqu_bench_start:\n\tcsrr %0, mcycle" : "=r"(ticks) :: "memory");
    start_ticks = ticks;
}

__attribute__((noinline)) void stop_trigger(void)
{
    uint32_t ticks;
    __asm__ volatile (".global uqu_bench_stop\n"
                      "uqu_bench_stop:\n\tcsrr %0, mcycle" : "=r"(ticks) :: "memory");
    stop_ticks = ticks;
}

static void put_char(char value)
{
    if (uqu_bench_log_size < sizeof(uqu_bench_log) - 1)
        uqu_bench_log[uqu_bench_log_size++] = value;
    else
        uqu_bench_log_overflow = 1;
}

static void put_string(const char *value)
{
    while (*value) put_char(*value++);
}

static void put_number(uint32_t value)
{
    char digits[10];
    unsigned count = 0;
    do { digits[count++] = '0' + value % 10; value /= 10; } while (value);
    while (count) put_char(digits[--count]);
    put_char('\n');
}

/* Library/assertion failures use the existing tohost failure convention. */
__attribute__((noreturn)) void exit(int status)
{
    __asm__ volatile ("mv a0, %0\n\tj _exit" :: "r"(status) : "a0", "memory");
    __builtin_unreachable();
}

__attribute__((noreturn)) void abort(void) { exit(126); }
__attribute__((noreturn)) void __assert_func(const char *file, int line,
                                           const char *function, const char *expression)
{
    (void)file; (void)line; (void)function; (void)expression;
    exit(125);
}

int main(void)
{
    initialise_benchmark();
    warm_caches(WARMUP_HEAT);
    start_trigger();
    volatile int result = benchmark();
    stop_trigger();
    int correct = verify_benchmark(result);

    put_string("Embench workload: " UQU_EMBENCH_NAME "\n");
    put_string("Iterations: "); put_number(1);
    put_string("Local scale: "); put_number(UQU_EMBENCH_SCALE);
    put_string("Workload scale: "); put_number(CPU_MHZ);
    put_string("Warmup: "); put_number(WARMUP_HEAT);
    put_string("Verified: "); put_number((uint32_t)correct);
    put_string("Cycles: "); put_number(stop_ticks - start_ticks);
    return correct == 1 ? 0 : 1;
}
