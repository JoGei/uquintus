/* Negative fixture: the testbench cycle watchdog must terminate this program. */
int main(void)
{
    for (;;)
        __asm__ volatile ("" ::: "memory");
}
