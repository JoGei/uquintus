# RTL performance benchmarks

Each benchmark has its own directory containing its port, pinned upstream
revision, workload configuration and build instructions. Shared fetching,
compiler discovery and simulator invocation live in `verif/sim/common/`.

- [CoreMark](coremark/README.md): initial integer workload, both standard seed
  profiles, CRC validation and cycle-only RTL measurements.
- [Embench-IoT](embench/embench-iot/README.md): pinned Embench 1.0, all 19 workloads,
  upstream self-checks, integer and software floating-point cycle measurements.

Sources are fetched explicitly into `build/deps/`; no submodule is added.
Benchmark configurations here describe software and the simulated memory
environment. Hardware configurations remain in top-level `config/`.

Run `make benchmark-fetch`, then `make benchmark CONFIG=<hw>` using externally
provided tools. `make report` collects the resulting native benchmark records
into `build/report/benchmark/index.html`. These measurements describe the
selected core and simulated environment, including the compiler and memory
latency. They do not establish an official benchmark score or a silicon speed.

`BENCHMARK_MODE=fast` defaults to a compiled Verilator driver without Python
callbacks or instruction traces. `BENCHMARK_MODE=checked` uses cocotb/pyuvm with
the instruction oracle, RVFI and per-edge counter checks. Both modes validate
the workload self-checks and use the same memory/timer contract; the report records
their distinct validation scopes. Fast execution needs no cocotb/pyuvm install.
