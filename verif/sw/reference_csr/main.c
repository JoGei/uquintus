/* Deterministic CSR coverage for the initial Spike comparison profile. */
int main(void)
{
    unsigned int old, value;
    __asm__ volatile ("csrrw %0, mscratch, %1" : "=r" (old) : "r" (0x12345678u));
    if (old != 0) return 1;
    __asm__ volatile ("csrrs %0, mscratch, %1" : "=r" (old) : "r" (0x80u));
    if (old != 0x12345678u) return 2;
    __asm__ volatile ("csrrc %0, mscratch, %1" : "=r" (old) : "r" (0x8u));
    if (old != 0x123456f8u) return 3;
    __asm__ volatile ("csrr %0, mscratch" : "=r" (value));
    if (value != 0x123456f0u) return 4;
    __asm__ volatile ("csrwi mscratch, 7");
    __asm__ volatile ("csrrsi %0, mscratch, 8" : "=r" (old));
    if (old != 7) return 5;
    __asm__ volatile ("csrrci %0, mscratch, 1" : "=r" (old));
    if (old != 15) return 6;
    __asm__ volatile ("csrr %0, mscratch" : "=r" (value));
    if (value != 14) return 7;
    __asm__ volatile ("csrr %0, mhartid" : "=r" (value));
    if (value != UQU_HART_ID) return 8;
    __asm__ volatile ("csrw mscratch, zero");
    return 0;
}
