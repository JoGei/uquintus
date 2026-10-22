# Bare-metal verification programs

`common/crt0.S` initializes unreset GPRs, the global/stack pointers and a trap
vector, calls `main`, and writes its result to `tohost`. `main` returns zero for
success and a nonzero test code for failure. `common/link.ld` places the program
in 64 KiB RAM at `0x80000000`, reserving the final 4 KiB for a 16-byte-aligned
stack. ELF loading provides initialized data and zeroed BSS; no C library,
allocator, constructor processing or argument/environment setup is supplied.

Programs:

| `SW` | Purpose |
| --- | --- |
| `smoke` | Initialized data, zeroed BSS, constants read through the data port from the executable segment, dependent loops, calls/stack, FENCE, and M arithmetic when selected. |
| `reference_csr` | Deterministic CSR register/immediate write, set, clear and read forms, plus hart ID 5; compatible with the initial Spike reference profile. |
| `traps` | Declared illegal/ECALL/EBREAK and alignment traps, MRET, optional M/U transitions, destination/RAM sentinels and flushed-store checks; RV32I register set required. |
| `interrupts` | ELF-declared software/timer/external IRQs, masking/priority, memory/division stalls, direct/vectored entry, MRET and optional U mode; RV32I register set required. |
| `fail` | Deliberately return 7 to exercise software failure reporting. |
| `hang` | Deliberately loop forever to exercise the testbench watchdog. |

Build through `make sw CONFIG=<hw> SW=<program> RISCV_CC=<compiler>`.
The shared Make helper lives in `verif/sim/common/software_build.py`; this
directory contains software sources and linker/startup files.
Programs provide exactly one `main.c` or `main.S`; both receive
`UQU_ISA_UMODE` from the selected configuration. Compiler/ISA
selection, generated artifacts and simulation commands are described in the
[ELF execution guide](../sim/core_elf/README.md).

The [pinned riscv-tests adapter](riscv_tests/README.md) adds external instruction
regressions without submodules. Both flows use shared external-compiler discovery
through `RISCV_CC`, `$RISCV/bin` or `PATH`, and record compiler family/version and
effective target for reporting.
