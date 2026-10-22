/* Cycle-only RTL port. The upstream benchmark algorithms remain unmodified. */
#include "coremark.h"
#include <stdarg.h>

#if PERFORMANCE_RUN
volatile ee_s32 seed1_volatile = 0;
volatile ee_s32 seed2_volatile = 0;
#elif VALIDATION_RUN
volatile ee_s32 seed1_volatile = 0x3415;
volatile ee_s32 seed2_volatile = 0x3415;
#else
#error "Select exactly one supported CoreMark seed profile"
#endif
volatile ee_s32 seed3_volatile = 0x66;
volatile ee_s32 seed4_volatile = ITERATIONS;
volatile ee_s32 seed5_volatile = 0;
ee_u32 default_num_contexts = 1;

static ee_u32 start_ticks, stop_ticks;
/* A RAM log avoids a simulated UART and its timing effects. */
volatile char uqu_bench_log[4096];
volatile ee_u32 uqu_bench_log_size;
volatile ee_u32 uqu_bench_log_overflow;

__attribute__((noinline)) void start_time(void)
{
    ee_u32 ticks;
    __asm__ volatile (".global uqu_bench_start\n"
                      "uqu_bench_start:\n\tcsrr %0, mcycle" : "=r"(ticks) :: "memory");
    start_ticks = ticks;
}

__attribute__((noinline)) void stop_time(void)
{
    ee_u32 ticks;
    __asm__ volatile (".global uqu_bench_stop\n"
                      "uqu_bench_stop:\n\tcsrr %0, mcycle" : "=r"(ticks) :: "memory");
    stop_ticks = ticks;
}

CORE_TICKS get_time(void) { return stop_ticks - start_ticks; }

/* No operating frequency is assumed. Upstream emits its short-duration
   warning; the RTL checker validates CRCs and reports cycles, never a score. */
secs_ret time_in_secs(CORE_TICKS ticks) { (void)ticks; return 0; }

void portable_init(core_portable *p, int *argc, char *argv[])
{
    (void)argc;
    (void)argv;
    p->portable_id = 1;
}

void portable_fini(core_portable *p) { p->portable_id = 0; }

static void put_char(char c)
{
    if (uqu_bench_log_size < sizeof(uqu_bench_log) - 1)
        uqu_bench_log[uqu_bench_log_size++] = c;
    else
        uqu_bench_log_overflow = 1;
}

static void put_unsigned(unsigned long value, unsigned base, unsigned width, char pad)
{
    char digits[32];
    unsigned n = 0;
    do {
        digits[n++] = "0123456789abcdef"[value % base];
        value /= base;
    } while (value);
    while (width > n) { put_char(pad); --width; }
    while (n) put_char(digits[--n]);
}

/* Only integer/string formats used by the pinned upstream are needed. */
int ee_printf(const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    while (*fmt) {
        if (*fmt != '%') { put_char(*fmt++); continue; }
        ++fmt;
        char pad = ' ';
        unsigned width = 0;
        if (*fmt == '0') { pad = '0'; ++fmt; }
        while (*fmt >= '0' && *fmt <= '9') width = width * 10 + (*fmt++ - '0');
        int is_long = *fmt == 'l';
        if (is_long) ++fmt;
        char kind = *fmt++;
        if (kind == 's') {
            const char *s = va_arg(args, const char *);
            while (*s) put_char(*s++);
        } else if (kind == 'u' || kind == 'x') {
            unsigned long value = is_long ? va_arg(args, unsigned long) : va_arg(args, unsigned int);
            put_unsigned(value, kind == 'x' ? 16 : 10, width, pad);
        } else if (kind == 'd') {
            long value = is_long ? va_arg(args, long) : va_arg(args, int);
            unsigned long magnitude = (unsigned long)value;
            if (value < 0) { put_char('-'); magnitude = 0ul - magnitude; }
            put_unsigned(magnitude, 10, width, pad);
        } else if (kind == '%') {
            put_char('%');
        } else {
            uqu_bench_log_overflow = 1;
        }
    }
    va_end(args);
    return 0;
}
