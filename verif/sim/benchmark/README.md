# Native benchmark execution

`uqu_benchmark_tb.sv` instantiates the actual core, supplies inactive interrupts/
XIF and immediate fence acknowledgements, and exposes only the memory ports and
small passive retirement/counter/trap observations needed by the driver.
It includes a passive BPU observer, without RVFI, CSR observers or trace
modules. Core ports are unchanged.

`main.cpp` drives the single clock directly through Verilator's C++ API. It
loads the image prepared by the shared ELF loader, runs two reset edges and
models independent OBI ports with immediate grants and fixed response latency.
An ordered response queue permits two outstanding instruction requests and one
data request; latency elapses independently for every queued transaction.
Response data is captured at grant; stores update shared RAM then, and a
simultaneous instruction read observes RAM before the data store. Completion
waits for the matching `tohost` store to retire after its response. This matches
the checked Python agents' ordering. Missing RAM bytes read as zero.

The executable writes final RAM and a small `native.json` containing total
cycles/instructions, timer boundaries and completion/failure diagnostics.
It also snapshots the shared BPU monitor after both timer retirement edges.
The Python adapter derives `bpu-stats.json` over the same `(start, stop]`
window, validates the instruction-count delta and publishes the statistics in
benchmark JSON and HTML reports. Counts exclude squashed/faulting instructions;
redirect events do not estimate a branch penalty. Rate denominators and scope
are defined in the [benchmark specification](../../../doc/uqu_spec.bench.md#31-passive-branch-prediction-statistics).
The Python adapter validates the timer delta and CoreMark CRCs after execution,
then produces the common benchmark/report/JUnit artifacts. No per-cycle Python,
VPI, cocotb, pyuvm, waveform or instruction-trace activity occurs in fast mode.

Build/run through `make benchmark` or `make benchmark-run`; commands and knobs
are in the [CoreMark guide](../../sw/benchmark/coremark/README.md). HDL selection
continues through Bender's `rtl` target, including configured optional IP.
The Make helper is `../common/benchmark_fast.py`. C++ and simulator tool identity,
build command, source/binary hashes and host execution time are retained.

Unit checks for memory-image encoding, mode selection and imports without
verification packages run in `make test-runner`. To additionally exercise the
compiled RV32I driver's latency, completion, watchdog and trap handling:

```sh
UQU_FAST_NATIVE=/absolute/path/to/fast-run/obj/uqu_benchmark \
  .venv/bin/python -m unittest discover -s verif/sim/common/tests -p test_benchmark_fast.py -v
```

Backend qualification compares both modes on the same ELF, configuration and
memory settings. The initial RV32I CoreMark profiles match exactly, including
timer points and whole-program counts. Fast execution deliberately has a smaller
validation scope than checked execution; use checked mode and the architectural
regressions for RTL verification.
