# Native core ELF execution

This target reuses the actual core/RVFI wrapper and `CoreTest` pyuvm environment
from [`../core/`](../core/README.md). The independent OBI agents share one sparse,
byte-addressed RAM; the instruction oracle has its own copy, updated at
retirement. Existing operand, instruction, CSR and RVFI checks remain active.

Build the supplied C smoke program with an externally provided compiler:

```sh
make sw CONFIG=rv32i RISCV_CC=clang
make test COMPONENT=core_elf CONFIG=rv32i \
  ELF=build/uquintus-rv32i/sw/smoke/program.elf SEED=7
```

`PYTHON=.venv/bin/python` selects an existing verification virtual environment.
Alternatively set `RISCV_CC=riscv32-unknown-elf-gcc` or a compiler path; automatic
discovery searches `$RISCV/bin` and then `PATH` for bare-metal GCC or Clang.
Compiler family/version and effective target are probed and recorded.
Clang requires an external LLD. Neither Make target
installs tools or invokes containers. `SW=smoke` is the default program; build
inputs live in [`verif/sw/`](../../sw/README.md).

`make sw` derives `-march` and `-mabi` from the complete hardware configuration,
and writes the ELF, linker map, compiler log, input hashes and build metadata to
`build/uquintus-<hw>/sw/<program>/`. Compiler versions and the exact command are
recorded; a supported/pinned distribution of those external tools remains an
environment follow-up. GCC is needed for RV32E if the provided Clang lacks the
ILP32E backend.

Use the same config when executing. The simulator target accepts external ELFs
with the contract below; building a program is a separate step. For example,
build with `CONFIG=rv32ic` and run that ELF with any of the three matching
`rv32ic*` compressed-decoding profiles.

## ELF and execution contract

- Little-endian RISC-V ELF32 `ET_EXEC`, already statically linked. Load
  `PT_LOAD` file bytes and zero every `p_memsz - p_filesz` tail, including BSS.
  Physical and virtual segment addresses must match. Entry must be word-aligned
  and within an executable segment; it drives `boot_addr_i` during reset.
- Retain a symbol table defining an 8-byte-aligned, initially zero `tohost`
  object occupying eight bytes in writable loadable memory. The first version
  requires an aligned `SW` to its low word: zero waits, `1` passes, and
  `(code << 1) | 1` reports nonzero failure code `code`. Its upper word stays
  zero. Host syscalls, console output and `fromhost` communication are deferred.
- Completion is recognized from the checked, retired store, after its bus
  response. A granted request alone cannot report success. Illegal partial or
  upper-word completion stores and unsupported completion values fail the run.
- Software initializes every GPR before reading it, including saved registers
  spilled by compiled code. The provided startup does this. Unexpected traps
  fail with PC/cause/value diagnostics. Declared synchronous traps and optional
  Spike comparison are described below; general privileged-suite adapters remain open.
- The model uses flat identity addressing with zero reads for unwritten sparse
  RAM and no implicit ELF page permissions. ELF segment permissions validate
  entry/completion storage; they do not configure PMP or create bus faults.
  The supplied linker uses 64 KiB starting at `0x80000000`, including a 4 KiB
  stack reservation. Other ELF memory maps are allowed within RV32 addressing.
- Reject malformed/truncated images, overlapping segments, address overflow,
  dynamic linking/TLS, and images larger than the 16 MiB file/load-image limit.
  Check compressed and reduced-register ABI flags against `ISA_C`/`ISA_E`, and
  reject hardware floating-point/TSO flags. ELF flags alone do not describe all
  required ISA extensions; the program and selected hardware must still match.

`MAX_CYCLES=100000` is the default watchdog after reset, independent of the
processor's architectural behavior. Grants and response delays remain seeded
and randomized on both ports. Use `WAVES=1` to request waveforms.

Every run has an isolated directory under
`build/uquintus-<hw>/verilator/core_elf/`. It retains `program.elf`, its source
path/SHA-256/entry/segment/watchdog metadata in `run.json`, `execution.json`,
`rvfi.jsonl`, simulator/build logs and `results.xml`. Software failure, watchdog
expiry and checker errors produce a nonzero Make exit and retain artifacts.
`execution.json` includes status, failure detail, exit code, total cycles
(including reset), retirement count and last/next PC. See `simulation.log` for
full checker diagnostics. These runs are software regressions, not formal proofs
or completed architectural certification.

## Negative fixtures

These commands are expected to fail:

```sh
make sw CONFIG=rv32i SW=fail RISCV_CC=clang
make test COMPONENT=core_elf CONFIG=rv32i \
  ELF=build/uquintus-rv32i/sw/fail/program.elf
make sw CONFIG=rv32i SW=hang RISCV_CC=clang
make test COMPONENT=core_elf CONFIG=rv32i MAX_CYCLES=600 \
  ELF=build/uquintus-rv32i/sw/hang/program.elf
```

The first reports exit code 7; the second expires the execution watchdog.
Loader/protocol tooling tests also run without a compiler or simulator through
`make test-runner`. External ISA suites and reference-model adapters can reuse
the loader and execution environment; the
[pinned riscv-tests adapter](../../sw/riscv_tests/README.md) uses this target for
independent ELF runs with compatible simulator-build reuse.

Select `REFERENCE=spike` to compare a successful native run with the pinned external
ISA simulator. Discovery, supported events and retained first-mismatch evidence
are defined in the [reference guide](../../reference/README.md).

## Declared synchronous traps

By default an ELF must execute without trapping. Tests may instead embed a kept
`.uqu.traps` section, delimited by global `uqu_expected_traps` and
`uqu_expected_traps_end` symbols. Each three-word entry contains PC, cause and
trap value, in expected event order:

```asm
.section .uqu.traps, "a", @progbits
.balign 4
.global uqu_expected_traps, uqu_expected_traps_end
uqu_expected_traps:
    .word my_ecall, 11, 0
    .word bad_load, 4, buffer+1
uqu_expected_traps_end:
```

The common linker retains this section even with garbage collection. Sites must
be aligned executable ELF addresses. Supported causes are 0, 2, 3, 4, 6, 8 and
11; duplicate PCs must declare the same cause/value and each arrival at a declared
site must trap. Table data is validated before simulator build and copied with
the ELF. Unexpected sites, wrong causes/values, reordered, missing or extra traps
fail. `execution.json` records declared and observed events. Full RAM comparison
at completion additionally detects stores absent from the architectural trace.

`make sw SW=traps CONFIG=rv32i` builds the assembly test in
[`verif/sw/traps/main.S`](../../sw/traps/main.S). Run it through the usual ELF
target, optionally with `REFERENCE=spike`. It checks nine M-mode trap cases,
plus four U-mode cases when `ISA_UMODE=1`. C configurations replace the two
IALIGN=32 branch-target cases with 16-bit illegal and C.EBREAK cases. Each fault
has a following poison store skipped by the handler; a RAM guard, destination
sentinel and trap count are checked before completion. The MRET sequential path
also contains a poison store. The program requires the full integer register set.
