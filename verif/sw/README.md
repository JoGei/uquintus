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
| `fail` | Deliberately return 7 to exercise software failure reporting. |
| `hang` | Deliberately loop forever to exercise the testbench watchdog. |

Build through `make sw CONFIG=<hw> SW=<program> RISCV_CC=<compiler>`.
The shared Make helper lives in `verif/sim/common/software_build.py`; this
directory contains software sources and linker/startup files. Compiler/ISA
selection, generated artifacts and simulation commands are described in the
[ELF execution guide](../sim/core_elf/README.md).

The [pinned riscv-tests adapter](riscv_tests/README.md) adds external instruction
regressions without submodules. Both flows use shared external-compiler discovery
through `RISCV_CC`, `$RISCV/bin` or `PATH`, and record compiler family/version and
effective target for reporting.
