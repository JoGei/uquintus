# Pinned riscv-tests integration

This integration consumes unchanged upstream instruction test bodies and scalar
macros from [`riscv-tests`](https://github.com/riscv-software-src/riscv-tests),
pinned by [`lock.json`](lock.json) to commit
`3df703cd52d5f0d8224e3c50bf03c6cb70efff98` and archive SHA-256
`26f60be0c065cae656e1bd6c23677693461d8c78380ae654ec2dceb770282981`.
The source cache is generated under `build/deps/`; no Git submodule, Git checkout,
or tracked copy of upstream tests is added. Only ISA sources, README and LICENSE
are extracted. The upstream `env` submodule and unrelated debug/benchmark trees
are not used.

## Fetch, build and run

```sh
# Explicit network operation, once after make clean or a lock update:
make riscv-tests-fetch

# Discover an external compiler, build applicable programs, and execute them:
make riscv-tests CONFIG=rv32i
make riscv-tests CONFIG=rv32im SEED=37
make riscv-tests CONFIG=rv32ic SEED=41

# Select specific full upstream names:
make riscv-tests CONFIG=rv32i RISCV_TESTS=rv32ui-p-add,rv32ui-p-addi
make riscv-tests CONFIG=rv32i_zifencei RISCV_TESTS=rv32ui-p-fence_i

# Build and execution may also be separate:
make riscv-tests-build CONFIG=rv32i
make riscv-tests-run CONFIG=rv32i
make report
```

Use `PYTHON=.venv/bin/python` if verification dependencies live in that existing
environment. `BENDER`, `SIM`, `SEED`, `WAVES` and `MAX_CYCLES` retain their normal
meanings. `riscv-tests-run` executes the last successfully built selection;
`RISCV_TESTS` selects programs during the build step. The combined target always
rebuilds the requested selection before execution.

Fetching checks the archive SHA-256 before extraction and rejects unsafe paths
and ISA links. Existing caches are checked against their extraction inventory;
modified/missing/added files fail validation. Remove a damaged
`build/deps/riscv-tests-<commit>/` directory and fetch again. For offline use:
`make riscv-tests-fetch RISCV_TESTS_ARCHIVE=/path/to/source.tar.gz`.
Build/run targets do not implicitly download sources, install/build compilers,
or start containers. The explicit HTTP fetch requires network access and has a
finite timeout.

## Compiler discovery and reporting

The shared `verif/sim/common/toolchain.py` helper serves both `make sw` and
`riscv-tests`. Discovery precedence is:

1. Explicit `RISCV_CC=<executable>`, including an absolute executable path.
2. `$RISCV/bin/`, treating `RISCV` as an installation root.
3. `PATH`.

In each automatic search location, try `riscv32-unknown-elf-gcc`, then
`riscv64-unknown-elf-gcc`, then `clang`. A 64-bit-prefixed GCC is valid if it
supports the requested RV32 ISA/ABI. Clang receives an explicit RISC-V target
and requires externally supplied LLD. An invalid explicit compiler or failed
target probe is an error, not a silent fallback.

Derive `-march`/`-mabi` from complete hardware YAML. Query the full `--version`
banner, use predefined macros to identify GCC versus Clang, numeric version
and `__riscv_xlen=32`, and query the effective target with `-dumpmachine` using
the same target options. Record executable/resolved path, family, numeric/full
version, target, ISA, ABI and exact build command in `compiler_info` and build
metadata. Versions describe the supplied tool; no compiler distribution is
pinned or provisioned by this integration.

Each simulation copies matching software build metadata, including compiler
identity and source pin, into its own directory. Reporting exposes these fields
alongside simulator provenance. Different compiler families/versions and
upstream revisions remain separate comparison contexts.

## Environment and applicability

[`riscv_test.h`](riscv_test.h) maps upstream environment macros to `main` and the
existing `_exit`/`tohost` convention. [`crt0.S`](../common/crt0.S) initializes
unreset GPRs, calls the body in machine mode and reports its upstream failure
number. The standard linker, shared memory, RVFI/CSR observations, independent
Python execution oracle and seeded OBI timing remain active. Upstream test
bodies are not patched; the upstream `p` runtime's privileged probing is replaced
by this local bare-metal environment. These are adapted `-p-` instruction
regressions, not the unmodified upstream privileged runtime or certification.

The initial scope is the pinned `rv32ui`, `rv32um` and `rv32uc` Makefrag lists:

| Test group / case | Policy |
| --- | --- |
| `rv32ui` | Run applicable base integer tests. |
| `rv32ui-p-ma_data` | Exclude: expects misaligned accesses to succeed; uquintus traps them. Native trap tests check this policy separately. |
| `rv32ui-p-fence_i` | Include with `ISA_ZIFENCEI=1`; tests real self-modifying code. |
| `rv32um` | Include with `ISA_M=1`. |
| `rv32uc` | Include with `ISA_C=1`, using the selected compressed microarchitecture. |
| RV32E | Reject: upstream tests use x16–x31. |
| Supervisor/VM, A/F/vector and other groups | Outside this initial adapter's scope. |

Default RV32I runs 40 tests; RV32IM runs 48; RV32IC runs 41. Disabled/incompatible
cases have explicit reasons in the manifest and JUnit summary. Explicitly
selecting an excluded/unknown case fails. Partial selections are reported as
such; other unselected tests are not claimed as executed. Exclusions are not
passes.

## Artifacts and execution

ELFs, maps, logs and per-test `build.json` use
`build/uquintus-<hw>/sw/riscv-tests/<upstream-name>/`. `suite.json` freezes the
program list, ELF hashes, full hardware parameters, compiler identity, pin and
exclusions. Execution rejects changed ELFs, different parameters or a changed
lock.

The component runner builds one simulator per compatible cohort. Reuse requires
matching source/header contents, source/include order, parameters, top, language
options, simulator version and waveform setting. Each ELF then gets a fresh
simulator process and isolated `core_elf/` run with its upstream scenario name,
copied ELF/build metadata, JUnit, `execution.json`, logs and RVFI trace. A selected
failure does not prevent later tests from running, and fails the suite command.

Suite summaries use
`build/uquintus-<hw>/<sim>/riscv-tests/suite-seed<seed>-<id>/`, containing
`report.json`, `suite-results.xml` and frozen `suite.json`. HTML reporting shows
cohort and individual executions separately. Declared exclusions appear as
skipped cases; required cases must all pass. Suite and ELF histories remain
distinguishable.

This suite complements component and pipeline/error/reset tests. Spike and
architectural certification tests remain separate goals.
