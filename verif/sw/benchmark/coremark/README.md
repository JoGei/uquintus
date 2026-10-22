# CoreMark RTL port

This port uses the unmodified [EEMBC CoreMark](https://github.com/eembc/coremark)
sources at the revision and archive SHA-256 in [lock.json](lock.json).
The fetched source cache retains the upstream Apache-2.0 license. No upstream
source or Git submodule is checked into this repository.

## Build and run

The default fast mode needs Python/PyYAML for build/report orchestration,
Bender, Verilator, GNU Make, a host C++ compiler and a RISC-V GNU compiler with
matching RV32 libgcc multilibs. The compiled simulator itself has no Python,
cocotb, pyuvm, VPI or tracing dependency. Checked mode additionally needs
`verif/requirements.txt`. Compiler discovery uses
`RISCV_CC`, then `$RISCV/bin`, then `PATH`, as in the software tests. The initial
benchmark build requires GCC; Clang/compiler-rt integration remains open.

```sh
make benchmark-fetch
make benchmark CONFIG=rv32i RISCV_CC=riscv-none-elf-gcc
make report
```

For an offline fetch, pass `BENCHMARK_ARCHIVE=/path/to/pinned-source.tar.gz` to
`benchmark-fetch`. Fetching verifies the archive checksum; builds/runs never
fetch implicitly. Changes in the cached sources are rejected.

`make benchmark` builds and runs both `performance` and `validation` seed
profiles. Use `BENCHMARK_PROFILE=performance` or `validation` to select one.
`benchmark-build` and `benchmark-run` split compilation from execution;
`benchmark-run` requires a successful matching manifest, unchanged ELF and
recorded build inputs. A failed rebuild invalidates the latest manifest.

`BENCHMARK_MODE=fast` is the default: a small SystemVerilog wrapper and native
C++ driver execute the actual RTL, with final CRC validation and lightweight
completion, trap, watchdog and timer-window checks. It writes no instruction
trace and runs no instruction oracle, RVFI collector or per-edge CSR model.
Python runs only before/after the executable. `JOBS=4` controls native compilation;
a compatible binary is shared across profiles within one invocation.

Use `BENCHMARK_MODE=checked` for the original cocotb/pyuvm environment with
instruction, RVFI, CSR and per-edge counter checking:

```sh
make benchmark-run CONFIG=rv32i BENCHMARK_MODE=checked
```

The `performance`/`validation` seed profiles are independent of this execution
mode. Both profiles validate their expected CRCs in either mode. `WAVES=1` and
`REFERENCE=spike` require checked mode; the fast runner rejects them explicitly.

`CONFIG` selects the complete hardware YAML. `BENCHMARK=coremark` selects this
software port. Adapt [config.yml](config.yml) for iteration count, compiler
flags, watchdog and fixed memory latencies; rebuild after changes. Both
standard seed profiles and the 2000-byte dataset are currently required.
RV32I uses the compiler's integer runtime for arithmetic absent from the ISA.
`CONFIG=rv32im` enables native M operations; this recompiles for the selected ISA
and is consequently a different binary. Native Zfinx configurations can run
this integer workload, but it does not measure floating-point performance.

The defaults are `-O2`, one iteration, static allocation, one context and a
5,000,000-cycle whole-program watchdog. No LTO, C library, OS, allocator, UART
or interrupts are used. The port uses the common 64 KiB linker/startup setup
with a 4 KiB stack. ELF loading initializes data and BSS.

## Measurement contract

Both OBI ports use independent agents, immediate grants and a fixed configured
number of rising-edge intervals from grant to response, including store
responses. Default `imem_latency: 1` and `dmem_latency: 1` mean the next rising
edge; zero-cycle responses are unsupported. Fence acknowledgements are
immediate. This is an explicit cacheless memory model, not a SRAM/SoC claim.
Checked mode randomizes inactive bus payloads; fast mode drives inactive data
to zero. Neither changes the active transaction schedule. Ordinary ELF
regressions retain random memory waits.

`start_time()` and `stop_time()` each read `mcycle`; global instruction labels
allow the selected harness to identify their retirement edges. The interval is
`(start, stop]`: start-marker retirement excluded, stop-marker retirement
included. Startup, dataset initialization, CRC reporting, RAM logging and
`tohost` completion are outside it. Timer call/return and bookkeeping overhead
inside the interval are included consistently, without subtracting an estimate.
The monitor independently counts clock edges and retired instructions and
checks that the observed `mcycle` difference equals the cycle count. Counters
must remain enabled; missing/repeated/reordered markers fail. Each interval
must be shorter than 2^32 cycles; modular subtraction handles one low-word wrap.

The upstream program writes integer/string diagnostics to a RAM buffer through
the port's `ee_printf`. The checker validates exact seed/list/matrix/state CRCs
for each profile, iteration count, dataset size and software-reported ticks.
The unchanged upstream `main()` returns zero even for CRC errors, so successful
`tohost` completion alone never qualifies as benchmark validation.

No operating frequency is assumed and `time_in_secs()` returns zero. Upstream
therefore deliberately prints its minimum-duration warning and `Errors detected`.
The checker permits only that duration warning, requires all CRC checks to
pass and rejects other error diagnostics, missing fields and log overflow.
These are **cycle-only RTL measurements**, not reportable CoreMark scores.
The official [run/reporting rules](https://github.com/eembc/coremark#run-rules)
include a minimum execution duration and further conditions.

## Artifacts and comparisons

Software builds are retained under:

```text
build/uquintus-<hw>/sw/benchmark/coremark/build-<timestamp>-<id>/<profile>/
```

`suite.json` in the parent selects the most recent build without replacing old
artifacts. Each RTL execution has a fresh directory under:

```text
build/uquintus-<hw>/verilator/benchmark/coremark/fast-<profile>-seed<seed>-<id>/
build/uquintus-<hw>/verilator/benchmark/coremark/test-execute-seed<seed>-<id>/  # checked
```

Both modes retain `benchmark.json`, `benchmark.log`, native `report.json`, JUnit,
the ELF and build/tool metadata. Fast mode retains `native.json`, `native.log`
and initial/final RAM images. Checked mode additionally retains full RVFI and
per-edge counter evidence. A fast pass certifies the stated workload checks;
it does not certify per-instruction architectural correctness.
The shared HTML report's Benchmarks category shows workload cycles, retired
instructions, CPI, cycles/iteration, PT_LOAD footprint and executable-segment
bytes (the latter includes any read-only data in that executable segment).
Whole-program `cycles`/`retired` metrics remain separately labeled.

The comparison context includes the workload/profile, iteration count, memory
model, compiler/flags/ISA/ABI, integer runtime hash, source pin, execution mode,
validation scope and measurement
definition. ELF and RTL/agent hashes are retained. Start by comparing identical
ISA/compiler/workload/memory settings across `none` and `static_not_taken`
hardware configurations. To keep the exact same ELF for a microarchitecture
comparison, use an already built profile:

```sh
make benchmark-run CONFIG=<other-hw> BENCHMARK_PROFILE=performance \
  ELF=build/uquintus-rv32i/sw/benchmark/coremark/build-<timestamp>-<id>/performance/program.elf
```

ELF reuse permits differences in `MUA_` parameters; other parameters must match.
The runner still verifies software inputs, source pin, profile, ELF and memory
settings, and records the configuration actually simulated.
`SEED` labels fast runs; that driver has no randomized timing. Use `SEED=2`
in checked mode to check repeatability with different inactive bus noise; fixed timing should
give identical workload cycles for the same ELF/configuration. Increasing the
memory latencies is a separate experiment.

Optional `BENCHMARK_MODE=checked REFERENCE=spike SPIKE=/path/to/pinned/spike` adds architectural replay;
Spike's own execution timing is not a source of performance measurements.
Use checked runs when changing RTL or investigating a mismatch, and fast runs
for routine benchmark/configuration sweeps. CRC checks are workload validation,
and do not replace the architectural verification suite.

## Initial checked baseline

On 2026-10-22, the `rv32i` configuration with prediction `none`, GCC 13.2.0,
`-O2`, one iteration and one-cycle responses on both memory ports produced:

| Seed profile | Workload cycles | Retired instructions | CPI |
| --- | ---: | ---: | ---: |
| performance | 3,489,633 | 757,486 | 4.606861 |
| validation | 3,743,144 | 810,947 | 4.615769 |

Both profiles passed the known CRC checks, per-instruction oracle, RVFI trace
checks and per-edge cycle/retirement-counter checks. These are initial cycle-only
measurements for the recorded configuration and memory model. Raw run metadata
retains exact ELF, RTL/agent hashes, compiler commands and window boundaries;
subsequent RTL changes require new measurements.

The native fast backend reproduced these exact windows, instruction counts,
CRC results and whole-program completion counts using the same ELFs and memory
settings. Native execution took about 2 seconds per profile on the development
host, excluding compilation, compared with roughly 20 minutes in checked mode.
These wall times are simulator throughput observations, not processor performance.
