# Contributing to uquintus

uquintus is a configurable RV32 processor targeting open-source ASIC flows. Contributions should preserve clear component ownership, instruction visibility and explicit interface contracts while supporting microarchitecture experiments.

## Design and coding conventions

Start with the [specification index](doc/uqu_spec.md), [RTL style guide](doc/uqu_spec.style.md), [verification specification](doc/uqu_spec.verif.md) and [build specification](doc/uqu_spec.build.md). Follow agreed requirements; proposals and deferred features remain explicitly identified as such. Update the relevant specification and component guide when changing a contract.

Project-owned synthesizable RTL uses Verilog-2005, including wrappers and adapters. SystemVerilog is allowed for verification and imported IP under the documented exception. Use matching `uqu_` module/file names, explicit nets, named connections and the agreed signal and parameter conventions.

Core RTL lives in `src/uquintus/`, wrappers in `src/wrap/` and adapters in `src/adapt/`. Component tests belong in `verif/sim/<component>/`; reusable simulation agents, models and runners belong in `verif/sim/common/`. Component manifests live in `config/sim/`, and complete hardware presets in `config/`. Register HDL sources and dependencies through Bender.

## Development and validation

Provide GNU Make, Bender, Verilator, a C++ compiler and Python externally. Imported IP and physical-design flows have additional requirements documented in the relevant guides. The Makefile does not install tools or manage containers.

For the Python simulation environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r verif/requirements.txt
```

Run checks appropriate to the component and configuration being changed:

```sh
make lint PYTHON=.venv/bin/python COMPONENT=alu CONFIG=rv32im
make test PYTHON=.venv/bin/python COMPONENT=alu CONFIG=rv32im
make test PYTHON=.venv/bin/python COMPONENT=core CONFIG=rv32i
make report PYTHON=.venv/bin/python
```

Use `TEST=<name>` and `SEED=<number>` for targeted, reproducible runs. See `make help`, the [shared simulation guide](verif/sim/common/README.md) and each component's README for supported tests and dependencies. Use cocotb with pyuvm for component and core regressions, with independent reference models.

For behavioral changes, cover the affected behavior and relevant configurations. Include stalls, backpressure, faults and cancellation where the contract needs them. State which checks ran and which remain untested; documentation-only changes need link and formatting checks rather than RTL simulation.

For timing, area or benchmark claims, compare matched configurations, tools, constraints and workloads. Report execution cycles separately from frequency, and identify the implementation stage and remaining violations. Generated artifacts belong under `build/`; include a concise result summary and commands in the contribution. `make report` collects retained artifacts into the shared HTML report.

## Issues and pull requests

For a bug report, include the expected and observed behavior, hardware preset or parameter values, tool versions, command and seed, plus relevant diagnostics. A small reproducer helps distinguish a core defect from an integration issue.

Keep each commit focused on one logical change. A pull request should explain the motivation, resulting behavior, validation and material limitations. Link related issues and document architecture or interface decisions where they are defined. Preserve upstream notices when importing code; see [LICENSE](LICENSE) for the repository's license text.

## Commit messages

Use an emoji prefix, a brief lower-case subject ending in a colon, a blank line, then three or four lines summarizing the motivation/cause, change and effect:

```text
<emoji> <brief>:

<details>
```

Start the first detail sentence in lower case as a continuation of the subject's colon. Capitalize subsequent sentences normally. Preserve conventional casing for identifiers and acronyms such as `RV32`, `LSU` and `MUA_` parameters. Hard line breaks are allowed. The details are optional for sufficiently small and clear commits.

| Prefix | Type |
| --- | --- |
| 🐛 | Bug fix |
| 🔥 | Hotfix |
| 💡 | Feature |
| 📝 | Documentation |
| ⚙️ | CI and build automation |

For example:

```text
💡 decouple fetch requests from memory responses:

response-dependent request generation limited fetch timing.
Track two ordered outstanding requests with reserved response capacity.
Preserve redirect draining, request stability and benchmark cycle counts.
Improve request timing without adding a fetch startup cycle.
```
