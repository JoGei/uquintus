# Spike differential reference

The ELF flow can run the externally supplied Spike simulator after successful
native simulation. The native Python instruction/CSR oracle remains active.
`REFERENCE=none` is the default; select `REFERENCE=spike` explicitly:

```sh
export RISCV="$HOME/tools/rvgnu_install"
make sw CONFIG=rv32i PYTHON=.venv/bin/python
make test COMPONENT=core_elf CONFIG=rv32i REFERENCE=spike \
  ELF=build/uquintus-rv32i/sw/smoke/program.elf PYTHON=.venv/bin/python
make riscv-tests CONFIG=rv32im REFERENCE=spike PYTHON=.venv/bin/python
make report PYTHON=.venv/bin/python
```

`SW=reference_csr` additionally exercises register/immediate CSR write/set/clear,
read-only access forms, suppressed reads, and the harness's hart ID.

Compiler discovery includes `riscv-none-elf-gcc`. Spike discovery uses the explicit
`SPIKE` argument/environment variable, then `$RISCV/bin/spike`, then `PATH`.
An explicit missing executable is an error; there is no installation or container
invocation. The runner requires an ELF-consuming component for this option.

## Qualified binary and execution

[`spike.lock.json`](spike.lock.json) pins the qualified external executable's
SHA-256, help banner and adapter profile. The initial installed tool identifies
itself as `1.1.1-dev`, without an available source revision. That revision remains
unknown; the binary hash identifies the exact tested build. Other builds require
an explicit pin update and adapter requalification. This is a binary pin, not a
claim that the current upstream source produced it. Report records retain the
pin, executable/resolved paths, command, ISA, privilege mode and memory settings.

The adapter uses Spike's documented `-l` and `--log-commits` observations:
[upstream simulator](https://github.com/riscv-software-src/riscv-isa-sim),
[commit-log implementation](https://github.com/riscv-software-src/riscv-isa-sim/blob/master/riscv/execute.cc).
Its format is not assumed stable across arbitrary builds. Unknown log lines or
effects fail parsing. No proxy kernel is used.

The initial profile uses one hart (ID 5, matching the native harness), configured
M or M/U privilege, matching I/E/M/C/Zicsr/Zifencei settings, PMP disabled, and the
native linker RAM at `0x80000000..0x8000ffff`. Both models load the same ELF, with
zero-filled segment tails. Startup must initialize GPRs before reading them;
the checker does not accept Spike's zeroed reset GPRs as evidence for unreset
core registers. RAM holes are initially zero. ELF `fromhost` services are rejected.

Spike runs for exactly five ROM-bootstrap instructions, the number of observed
native instructions, and one lookahead instruction. Each bootstrap PC/encoding,
privilege and hart is checked before excluding it. The lookahead checks the
last retired instruction's next PC. Missing/extra commits fail; arbitrary prefix
searching or trace resynchronization is forbidden. A 30-second process watchdog
retains failure diagnostics. The existing RTL cycle watchdog is independent.

## Initial comparison scope

Every retirement is compared for original instruction bits (including 16-bit C),
PC, next PC, privilege and GPR writes. Architectural source register addresses
are independently decoded and their consumed values checked against prior Spike
writes. Memory addresses and load/store direction/size are compared with Spike
and instruction-derived byte masks. Stores update a separate byte image from
Spike's logged values; loads compare selected RVFI response bytes with that image
as well as checking the loaded GPR against Spike. Unselected bus lanes are not
architectural data. Compressed LW/SW/LWSP/SWSP are included.

Deterministic `mtvec`, `mscratch`, `mepc`, `mcause`, `mtval` and `mhartid` accesses
are supported. Explicit CSR writes match Spike's logged effects; RVFI read/write
masks and read values match the prior deterministic state. Other CSRs and SYSTEM
operations are rejected. In particular, counter reads cannot be compared by
assuming functional-model steps equal processor cycles.

Traps, injected interrupts, multiple reset epochs, PMP, FPU, atomics, XIF, debug,
host I/O and memory outside this RAM are not supported by this first profile.
Encountering them fails explicitly rather than silently skipping observations.
Full CSR/WARL, trap and interrupt synchronization remain follow-ups under the
broader Spike verification requirement. Native regressions continue checking
those core features independently; this adapter is not architectural certification
or formal proof.

## Evidence and checker tests

Each differential ELF run retains `spike.json`, `spike.log`,
`spike-process.log`, the copied ELF and `rvfi.jsonl`. The JSON records pass/fail,
compared instruction count or the first mismatching field, index, expected/actual
values and both full observations. Raw traces preserve surrounding context.
Failure marks the ELF's JUnit case and overall run failed; suite execution
continues with subsequent ELFs and fails the aggregate command.

Report context includes the reference binary hash so runs with and without
Spike cannot hide each other's outcomes. HTML details include reference identity,
status and artifact links, subject to the normal report size limit. Traces that
exceed that limit remain at their recorded run paths.

`make test-runner` tests deliberate PC/instruction/GPR/source/memory/CSR corruption,
missing commits, bootstrap mismatch, unsupported events/formats, discovery, binary
qualification and process timeout. `make test-report` checks that absent/failed
Spike evidence cannot be presented as a successful differential run.
