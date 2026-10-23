# Embench-IoT on uquintus

This port runs all 19 workloads in the stable upstream
[Embench 1.0 release](https://github.com/embench/embench-iot/tree/embench-1.0),
revision `0466a18e4f6b47e19598d7c6ba72916d54b68f65`. The complete archive is
checksum-pinned in `lock.json`; fetch it explicitly into `build/deps/`, without
submodules. Build/run never downloads sources or installs dependencies.
The one archive exclusion is an unused native-host configuration symlink,
`config/native/chips/default`; no benchmark or support source is excluded.
The cached source tree retains upstream license notices and `COPYING`.
The [initial RV32IMC results](RESULTS.md) record all 19 passing workloads,
per-workload cycles/CPI and separate arithmetic-group means.

```sh
make benchmark-fetch BENCHMARK=embench/embench-iot
make benchmark BENCHMARK=embench/embench-iot \
  CONFIG=rv32imc_bimodal_idata_unroll32
make report
```

Compiler discovery uses `RISCV_CC`, then `$RISCV/bin`, then `PATH`. Supply
GNU Make, Bender, Verilator, a C++ compiler and the repository's Python
dependencies externally. GCC must provide matching RV32 ILP32 `libgcc.a`,
`libc.a` and `libm.a`; their resolved paths and hashes are recorded alongside
the compiler family/version/ISA/ABI/options. These are real runtime libraries;
the upstream dummy libraries are not used. Pass
`BENCHMARK_ARCHIVE=<tar.gz>` to the fetch target for an offline archive.

The initial complete hardware preset uses RV32IMC, full forwarding, IF
decompression, a 16-entry bimodal direction table, a 16-entry direct-mapped
BTB with six packed instruction halfwords per entry, and shared iterative
MUL/DIV with `MUA_MULDIV_ITERUNROLL=32`. Fully unrolled MUL takes one EX cycle;
DIV still has its specified setup and completion phases. This is an explicit
experiment preset, without assigning a Greek-letter profile or changing other
presets.

The comparison preset `rv32imc_bimodal_idata_parallel_div1` changes only MUL to
`parallel` and the iterative divider's unroll factor to 1. Reuse the first
preset's exact executable suite for a controlled microarchitecture comparison:

```sh
make benchmark-run BENCHMARK=embench/embench-iot \
  CONFIG=rv32imc_bimodal_idata_parallel_div1 \
  BENCHMARK_REUSE_SUITE=build/uquintus-rv32imc_bimodal_idata_unroll32/sw/benchmark/embench/embench-iot/suite.json
make report
```

`BENCHMARK_REUSE_SUITE` accepts a successful software `suite.json` with matching
workload settings, pin and software-visible hardware parameters. Microarchitecture
parameters may differ; every executable and recorded software input is still
checked. The execution manifest records both configurations and the source
suite. Use `benchmark-run` to avoid rebuilding the executable suite.

`BENCHMARK_PROFILE=all` builds/runs every workload. A workload name or a
comma-separated subset selects individual programs, for example:

```sh
make benchmark BENCHMARK=embench/embench-iot \
  CONFIG=rv32imc_bimodal_idata_unroll32 BENCHMARK_PROFILE=crc32,ud
```

| Arithmetic on RV32IMC | Workloads |
| --- | --- |
| Integer | `aha-mont64`, `crc32`, `edn`, `huffbench`, `matmult-int`, `nettle-aes`, `nettle-sha256`, `nsichneu`, `picojpeg`, `qrduino`, `sglib-combined`, `slre`, `statemate`, `ud`, `wikisort` |
| Software floating point | `cubic`, `minver`, `nbody`, `st` |

The manifest explicitly lists every upstream translation unit and its local
scale factor. Builds check complete coverage against the pinned source tree.
The four floating-point workloads run through software emulation on RV32IMC;
they are not evidence of hardware FPU execution. Keep their comparisons
separate from the integer workloads.

The port preserves upstream initialization, one warmup invocation
(`WARMUP_HEAT=1`), one timed `benchmark()` call and the unchanged upstream
`verify_benchmark()`. `CPU_MHZ=1` retains upstream workload scaling; it is not
a claim about processor frequency. Each workload's original
`LOCAL_SCALE_FACTOR` determines the number of kernel repetitions in that
timed call. The RAM log must identify the workload/scale/warmup, report an
exact verification result of `1` and match the independently observed cycle
window. An unverified result of `-1` fails. Initialization, warmup, verification
and logging are outside the timed window. Timer-call overhead is included.

The default fast native Verilator mode checks completion, traps, watchdog,
counter enable, measurement boundaries, software-cycle agreement and workload
self-check output. `BENCHMARK_MODE=checked` retains the shared cocotb/pyuvm,
instruction oracle and RVFI checks; it is substantially slower. Both modes
use immediate instruction/data grants and one-cycle responses by default.
Each program has a 200-million-cycle whole-execution watchdog and the shared
64 KiB linker layout; linker overflow or failed workloads must not be silently
removed from the suite.

Results live in `build/uquintus-<hw>/verilator/benchmark/embench/embench-iot/`.
Each run retains `report.json`, `benchmark.json`, `benchmark.log`, BPU
statistics, software metadata, source/ELF hashes and execution evidence.
The parent `suite-*/suite-results.json` records the requested workloads,
upstream membership, per-workload outcomes and report directories. A failed
workload does not prevent attempting the remaining selection.
`build/report/benchmark/index.html` presents cycles, retired instructions,
CPI, code/loaded-memory size and branch statistics for each workload.
These are cycle-only RTL measurements, not an official Embench speed/size
score. No normalized suite ratio is available until a matching reference is
declared and measured. Do not drop a failed required workload from a suite
aggregate.

## Prediction diagnostics

To retain a compact whole-execution retirement trace, add `BENCHMARK_TRACE=1`
to a fast-mode `benchmark-run`. This is optional; the normal benchmark keeps
its existing warmup, repetition counts and timer window. Each `retire.bin`
starts with `UQUTRC01`, followed by little-endian records of three 32-bit
values: simulation cycle, instruction PC and original instruction bytes.
The runner checks retirement totals and timer-marker ordinals, then records
the trace's size and SHA-256. Failed or truncated traces cannot qualify a run.
Checked mode already retains RVFI and rejects this fast-mode option.

```sh
make benchmark-run BENCHMARK=embench/embench-iot \
  CONFIG=rv32imc_bimodal_idata_parallel_div1 BENCHMARK_TRACE=1 \
  BENCHMARK_REUSE_SUITE=build/uquintus-rv32imc_bimodal_idata_unroll32/sw/benchmark/embench/embench-iot/suite.json
python verif/sim/common/benchmark_prediction.py \
  --suite <printed-execution-directory>/suite-results.json \
  --output build/investigations/embench-prediction --jobs 2
```

The analyzer produces standalone `index.html`, `summary.json` and per-workload
JSON. Default paired direction/target capacities are 16, 64, 256, 1,024 and
unlimited; two asymmetric cases isolate the 16-entry direction or target
table. Both tables follow the current tagged direct-mapped indexing and
online training rules. Models retain startup/warmup or start empty at timer
entry. For nsichneu, an additional empty model separates the first timed
kernel pass from steady repetitions and the final loop exit. Measured kernel
intervals also distinguish the first visit after boot from timed repetitions.

These are architectural-path prediction models. They omit speculative
training, actual instruction-data capture and fetch timing; prior target
execution is only a replay opportunity. They cannot establish hypothetical
CPI, area, frequency or a preferred hardware configuration. Whole-window
empty-state averages still amortize repeated kernels. See the
[nsichneu analysis](ANALYSIS_NSICHNEU.md) for the repetition effect and results
from all 19 workloads.
