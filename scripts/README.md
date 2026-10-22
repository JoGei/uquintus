# Build reporting

```sh
make report PYTHON=.venv/bin/python
```

Open [`build/report/index.html`](../build/report/index.html) directly in a browser.
The report is a static artifact: HTML/CSS/JavaScript, a Markdown summary, a JSON
dataset and selected supporting files. It needs no server, network requests,
frontend package manager or additional Python packages beyond the existing
PyYAML dependency. `make test-report` checks its collector and generated output.

`report.py` owns cross-flow collection/rendering; assets live in `report_assets/`.
Simulation invocation helpers remain in `verif/sim/common/`; the
[ORFS synthesis producer](../impl/asic/README.md) lives under `impl/asic/common/`.

## Collection and updates

Raw outputs remain under `build/uquintus-<hw>/<target>/`. The collector reads
existing `run.json`, `results.xml`, `execution.json`, configuration snapshots
and software `build.json`. Run `make report` again after any flow to refresh the
merged report. This first version does not automatically launch reporting from
every test, nor run tests or synthesis while collecting.

```text
build/report/
  index.html                 # Status and collection diagnostics
  index.md                   # Compact linked Markdown summary
  configurations.html        # Matrix and interactive parameter comparison
  regression/index.html      # Component test runs
  test/index.html            # Native core and ELF runs
  lint/index.html
  software/index.html
  synthesis/index.html       # ORFS mapped synthesis and preplacement measurements
  formal/index.html
  benchmark/index.html
  runs/<id>.html             # Results, cases, metrics, provenance, artifacts
  artifacts/<id>/...         # Bundled supporting files
  assets/                    # Local styles and interactive controls
  data.json                  # Versioned merged dataset
  .nojekyll
```

Generation builds a replacement site before replacing the previous one;
concurrent reporter processes serialize through `build/.report.lock`. Each
refresh rebuilds the view from retained artifacts, avoiding a shared append-only
database or flow-specific HTML writers. Deleting raw runs removes their evidence
on the next refresh. `make clean` removes both builds and reports. Keeping history
between CI jobs requires retaining/importing raw artifact directories; deploying
only the generated site does not supply inputs to the next collection.

The complete directory can later be served by GitHub Pages, including at a
project URL prefix: all links are relative and supporting files are bundled.
Publication/deployment and CI retention are separate follow-ups. No publishing
workflow is installed or executed by `make report`.

## Reading results

- Every HTML page has a collapsible label legend; badges also provide tooltip
  explanations. Run outcomes (`passed`, `failed`, `error`, `running`, `skipped`,
  `not reported`) are separate from recorded-input evidence (`match`, `changed`,
  `unknown`). A changed input identifies historical evidence, not a failed test.
- The configurations page and its comparison selectors show current core
  presets plus snapshots used by core-level flows. Component-only experiments
  remain in category pages, run details and JSON, without populating the core
  configuration matrix. Configuration entries in `data.json` carry a `scope`
  (`core` or `component`); the landing count covers core configurations.
- Configuration names are paired with a SHA-256 fingerprint of the recorded
  parameter object. Legacy simulation records use the complete `config.yml`
  snapshot when available; selected RTL parameters alone cannot identify the
  full hardware configuration. Current presets with no evidence show
  **not reported**, separately from failed, running or skipped runs.
- Latest-per-scenario selects only the newest retry with the same configuration
  snapshot, kind, component, target, selection, seed, ELF/workload and comparison
  context. It does not combine partial suites into full-suite success or replace
  another seed's failure. Full history remains available. The matrix aggregates
  these independent latest outcomes, with errors/failures taking priority.
- Passed legacy test metadata must have matching successful JUnit evidence.
  Unreadable/malformed records appear as collection issues; inconsistent
  successful records show **error**. A failed build without JUnit remains failed.
- Input hashes are compared with files available at generation time. `match`
  means only the recorded files match. Existing records usually cover HDL and
  headers, not Python testbench changes, and have no recorded Git revision.
  Missing records/revisions are **unknown**; the workspace revision shown on the
  landing page is not attributed to historical runs. Legacy chronology uses
  metadata modification times and is labeled accordingly.
- The negative ELF fixtures remain failed software tests in this report. An
  expected-failure regression needs a producer that checks the expected failure
  and reports that check's outcome; the reporter does not infer expectations.
- Case timings are simulation/test wall times. ELF execution cycles and retired
  counts are diagnostics, not benchmark scores. Synthesis, formal and benchmark
  pages remain empty until those flows supply results.

Small metadata, configuration files, JUnit, logs and linker maps are bundled
(512 KiB per file by default). Waveforms, ELF binaries and raw RVFI streams remain
in their original run directories and are labeled as omitted; they receive no
broken links into a developer's filesystem. Future producers can explicitly
request other supporting artifacts. Override the size limit through
`python scripts/report.py --artifact-limit <bytes>`.

## Common record for future flows

A producer may write `report.json` in its own run directory under
`build/uquintus-<hw>/<target>/`. That file takes precedence over legacy metadata
in the same directory. It is the reporting integration point for future
synthesis, formal and benchmark flows; native tool outputs remain authoritative
supporting artifacts. Example (illustrative, not a measured uquintus result):

```json
{
  "schema_version": 1,
  "kind": "synthesis",
  "status": "passed",
  "configuration": {
    "name": "rv32i",
    "parameters": {"ISA_E": 0, "...": "complete resolved hardware configuration"}
  },
  "component": "uqu_core",
  "target": "orfs_sky130",
  "selection": "synth",
  "seed": null,
  "started_at": "2026-10-21T12:00:00+00:00",
  "finished_at": "2026-10-21T12:01:00+00:00",
  "revision": "producer-recorded Git revision and dirty-state identifier",
  "input_scope": "RTL, headers, constraints and flow configuration",
  "input_sha256": {"src/uquintus/uqu_core.v": "SHA-256 of actual consumed source"},
  "context": {
    "platform": "sky130",
    "library_revision": "pinned library identifier",
    "corner": "tt",
    "clock_period_ns": 20,
    "stage": "synthesis",
    "tools": "pinned ORFS/Yosys revisions"
  },
  "metrics": [{"name": "cell_area", "value": 1234.5, "unit": "um2"}],
  "artifacts": ["synthesis.log", "metrics.json"]
}
```

Required fields are `schema_version`, `kind`, `status`, `configuration` (name and
parameters), `component`, `target` and `selection`. Supported kinds match the
seven category directory names above. Status is `passed`, `failed`, `error`,
`running` or `skipped`. Optional timestamps must include a timezone; `seed` is an
integer or null. Metrics are a list of named finite numeric values with explicit
unit strings. Artifact paths must stay inside that run directory.

Optional `workload` identifies benchmark/program inputs and participates in
scenario identity. A producer must identify all materially relevant comparison
conditions in `context`: PDK/library/corner, constraints, stage and tools for PPA;
workload/input, compiler/flags/toolchain, measurement definition and environment
for benchmarks; property set, assumptions, solver, bound/strategy for formal.
Record source revision/dirty state and complete consumed-input hashes. These
records do not make an absent flow implemented or certify verification coverage.

Optional `configuration_scope: "core" | "component"` explicitly identifies the
scope for custom wrappers or component-level implementation flows. Without it,
the known `core`, `core_elf`, `uqu_core`, `riscv-tests` components and software
builds supply core-level evidence; other components do not promote their
experimental configurations into the core configuration view. Current presets
from `config/*.yml` are always included, even without core run results.

Test-suite producers may name a relative `results_file` instead of `results.xml`
and declare `required_tests` plus `excluded_tests` (name/reason objects). A passed
suite must have matching JUnit names, every required case passed, and only
explicitly excluded cases skipped. Those skips remain visible and do not count
as passes. The riscv-tests adapter supplies this cohort summary alongside its
independent ELF runs. Structured `compiler_info` and `upstream` fields are shown
with tool provenance; attached software build metadata is bundled when available.

Comparison bars use only passed latest records with a nonempty, exactly matching
context, metric name and unit. Missing/different contexts are never merged into
one performance comparison. Producers are responsible for complete context;
the report cannot infer whether differently configured experiments are comparable.

Differential ELF records include the reference identity in `reference` and the
reference binary hash in comparison context. The report links `spike.json`,
`spike.log` and `spike-process.log` subject to artifact limits, and requires
successful Spike evidence for a declared differential pass.

Spike v2 records include the adapter profile in comparison context and retain
the bounded read-only debugger commands/state snapshots. Report metrics expose
`spike_compared_traps` and `spike_compared_mrets` alongside instruction counts.

Spike v3 adds `spike_compared_interrupts` and bundles `interrupts.json` plus
`spike-irq-build.json`/`.log` for input and SDK/helper provenance. Interrupt entries
do not count as instructions; they remain visible as separate trace events.
