# Performance-simulation integration

The [usage guide](../../docs/uqu_guide.perfsim.md) covers tool setup, configuration sweeps, memory profiles, validation, diagnostics and host-cost measurements. The [specification](../../docs/uqu_spec.perfsim.md) defines supported behavior and limits.

| Location | Responsibility |
|---|---|
| `config_frontend.py`, `model.py`, `memory.py` | Shared core-YAML resolution, CorePerfDSL generation and external environments. |
| `models/` | Pipeline description and native frontend, BPU, hazard, memory and architectural-policy models. |
| `native/`, `map_explorer.py`, `block_schedule.py` | ETISS driver, block extraction/composition and scheduler bindings. |
| `patches/`, `dependencies.py`, `requirements-*.txt` | Pinned upstream integration and generator environments. |
| `rtl/`, `rtl.py`, `tests/`, `test_*.py` | RTL reference harness and component/model checks. |
| `calibrate.py`, `compare.py`, `compare_map.py`, `validate_platform.py` | Matched RTL accuracy workflows. |
| `benchmark_cost.py`, `accelerate.py` | Native host-cost comparisons, including explicit legacy reference modes. |

The Make entry point is `verif/sim/common/perfsim.py`. Generated models, traces, reports and study metadata belong under `build/`; investigation narratives are consolidated into the guides under `docs/`.
