/* Check initialized data, loader-zeroed BSS, rodata through LSU, and calls/stack. */
static volatile unsigned int initialized = 0x13579bdfu;
static volatile unsigned int cleared[17];
static const volatile unsigned char pattern[] = {0x12, 0x80, 0xff, 0x39};

__attribute__((noinline)) static unsigned int accumulate(unsigned int value)
{
    volatile unsigned int local[4];
    for (unsigned int n = 0; n < 4; ++n)
        local[n] = value + pattern[n];
    return local[0] + local[1] + local[2] + local[3];
}

int main(void)
{
    if (initialized != 0x13579bdfu)
        return 1;
    for (unsigned int n = 0; n < 17; ++n) {
        if (cleared[n] != 0)
            return 2;
        cleared[n] = n + 3;
    }
    if (accumulate(cleared[9]) != 4u * 12u + 0x12u + 0x80u + 0xffu + 0x39u)
        return 3;
#ifdef __riscv_muldiv
    unsigned int a = cleared[9];
    unsigned int b = cleared[4];
    if (a * b != 84u || a / b != 1u || a % b != 5u)
        return 4;
#endif
    __asm__ volatile ("fence" ::: "memory");
    return 0;
}
