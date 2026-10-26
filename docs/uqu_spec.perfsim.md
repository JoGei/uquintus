# Performance-simulation specification

**Status:** Implemented experimental integer model. Estimates require qualification for the measured hardware/workload/environment combination.

[Usage and interpretation](uqu_guide.perfsim.md) · [Architecture](uqu_spec.arch.md) · [Benchmarks](uqu_spec.bench.md) · [Build](uqu_spec.build.md)

## Purpose

Perfsim shall support fast microarchitecture exploration from the same complete core YAML used by RTL. ETISS shall supply CoreDSL-derived functional execution; CorePerfDSL shall define pipeline timing and upstream MAPExplorer shall execute composed max-plus schedules. RTL remains the timing reference and the existing Spike flow remains the independent ISA reference. Area, power and maximum frequency shall not be inferred from the ISS.

The integration follows the CorePerfDSL performance-simulation and MAP-DSE work described in [TCAD/ESWEEK 2024](https://doi.org/10.1109/TCAD.2024.3445255) and [ASPDAC 2027](https://doi.org/10.1145/3840404.3848185). Dependency revisions and archive checksums shall come from [the lock file](../config/perfsim/upstream.lock.json), including transitive sources. Acquisition shall use explicit checked archives without Git submodules, preserve upstream licenses and leave downloaded originals unchanged. Research results for other cores shall not be advertised as uquintus measurements.

## Configuration and functional identity

`CONFIG=<preset-or-YAML-path>` shall use the shared complete-schema validator and selector catalog. One resolved plan shall drive both CorePerfDSL generation and native external-model bindings. Inspection shall work without ETISS or generator installation. Every execution shall retain the complete hardware configuration, encoded selectors, functional identity, model identity, coverage and external environment.

One functional execution may serve several `MUA_` configurations only when ISA, hart/integration settings, ELF, initial memory and external functional inputs agree. RV32I and RV32E require separate executables and executions. Timing-dependent MMIO, asynchronous inputs or software that uses timing values to alter its measured path shall not be silently shared.

The loader shall reuse little-endian ELF32 initialized/zero-filled segments, entry point, executable ranges and the existing `tohost` convention. Execution shall check completion, workload self-checks, host-time/instruction watchdogs and declared traps. Unsupported profiles and instructions shall fail explicitly.

| Input | Model treatment |
|---|---|
| `ISA_E`, `ISA_M`, `ISA_C`, `ISA_UMODE`, `ISA_PMP`, `HART_ID` | Functional ISA/policy and execution identity; relevant timing parameters derive from the same selection. |
| MUL/DIV choice and iterative unroll | Execution latency, resource ownership and split MEM/EX2 result timing. |
| Forwarding master/path bits and DE retention | Finite producer windows, operand admission and capture policy. |
| Branch predictor, direction/BTB capacities, replay halfwords | Reference-clocked prediction, training, capture, replacement and recovery. |
| IF word capacity and redirect bypasses | Finite fetch queues, request/response ownership and refill paths. |
| FF/latch GPR implementation; compressed-decode route/placement | Recorded as cycle-equivalent; physical consequences remain for implementation. |
| External memory profile | Timing-environment identity, independent of core hardware YAML. |

Inactive settings shall normalize out of timing identity where they cannot affect behavior. Coverage shall distinguish modeled, cycle-equivalent, inactive and unsupported fields. A descriptive label is not an accuracy qualification.

## Canonical scheduling contract

The canonical contract is `map_dse`; its version and source identities shall be recorded with results. The default backend is `map_explorer`. It shall reuse upstream block extraction, instruction-matrix construction/multiplication, block composition/optimization and MAPExplorer resource groups, delay vectors, branch groups and timing combinations. Tracked adaptations shall apply only to private build copies and address explicit core mappings or demonstrated generator/runtime defects.

Actual control flow, measurement markers, synchronous events and completion shall delimit blocks as appropriate. Markers shall not become branch-training events merely because they delimit scheduling. Extraction shall preserve cross-channel blocks. Profiles shall bind ELF, functional configuration, normalized trace schema, operand mappings and extractor identity. Every PC shall have immutable instruction/event identity; missing or changed identities shall fail without a hidden instruction-scheduler fallback. Missing monitor fields shall be zero initialized without replacing explicit ISA mappings. Architectural operand checks shall not depend on optional timing-graph edges.

The schedule shall represent IF, DE, EX, MEM/EX2 and WB, single issue, in-order retirement and downstream backpressure. Store data is required in EX. Data requests issue in MEM and complete in WB; load operands require registered visibility. Split multiplication becomes available in MEM/EX2 and has no EX1 product bypass. Native MUL operations are independent; software MAC encoding remains outside this profile.

CSR/fence/return serialization shall match RTL admission and completion rather than assume an extra DE drain. Pass-through instructions still occupy the physical EX transit. Precise faults shall suppress effects and recover at their architectural boundary. Pipeline, register availability/admission, serialization and candidate PC timestamps shall remain explicit scheduling state.

Shared resource models shall consume the functional trace and configuration, returning delays from an independent reference calendar. They shall not receive IF/DE or other scheduled-combination timestamps. The calendar shall account for frontend storage, EX/MEM/WB occupancy, operand admission and event ordering. Exact idle skipping shall stop before any possible state transition. Branch models shall use functional successors to select predicted/resolved scheduling candidates.

External models may evaluate per instruction; their outputs shall be reused across compatible timing states, while actual timing-vector updates occur at completed blocks. Histories may share only when their effective component parameters and reference timing agree. Different arithmetic, memory or forwarding occupancy can require different frontend/BPU histories even with equal table sizes. Runtime reporting shall expose model evaluations, sharing counts, composed updates and covered model-instructions.

The upstream delay vector is bounded to 100 byte entries. Ordinary instructions use fetch/admission delays; memory operations additionally use grant/response delays. Composition shall split consistently at actual capacity across variants. Combined waits and positive symbolic delays shall be range checked; overflow shall fail explicitly.

The legacy `queue` contract and project `block`/history-sharing adapter may remain explicit reference modes. They shall be labeled separately and shall not inherit the canonical contract's qualification. The instruction scheduler of `map_dse` shall provide the same-contract oracle.

## Forwarding and operand retention

`MUA_FORWARDING` shall gate EX-to-DE, MEM-to-DE, MEM-to-EX and WB-to-EX independently. WB-to-DE follows the master. Branch/JALR and CSR sources must be ready in DE; native EX consumers may enter under the same future-bypass guarantee as RTL. x0 shall never acquire a dependency. Youngest pending writers shall block older results and RF fallback, including when the younger route is disabled or not yet ready.

Producer availability shall preserve finite EX/MEM/WB windows rather than a single monotonic ready time. Raw memory responses shall not become bypass values. Retention shall preserve operands captured while DE is held; continuous resolution shall revisit the current producer/RF state. For example, retaining a younger EX result can let a two-source branch proceed when an older source later becomes ready, even if the younger source's intervening MEM route is disabled. Retention may be cycle-equivalent with full or globally disabled forwarding.

The hazard resource shall publish additional admission wait without scheduling-state feedback. Its positive `wait+1` encoding shall pair with a base biased by minus one so zero wait adds no cycle. Register and admission semantics shall be preserved by both instruction schedules and composed matrices.

## Frontend, prediction and replay

The reference calendar shall model finite native request/result/word storage, ordered outstanding requests, held presented requests, response reservations and killed-response drain. Live response arrival shall not invent a request credit where RTL requires registered release. Consumer backpressure, branch request hold and redirect replacement shall match the selected bypass policy.

Prediction shall model tagged saturating direction counters, direct-mapped targets and packed original-encoding replay prefixes. BPU history depends on reference IF/DE event order. DE training before lookup shall be visible; same-edge lookup/update shall preserve read-before-write behavior and simultaneous prefix capture. A lookup shall remain held through IF backpressure. Local prediction clear and global recovery shall preserve their distinct source-consumption and credit-release rules.

Predicted targets shall pay normal transport or use available replay. A target equal to fallthrough shall not incur a steering penalty. Corrections shall use DE advance, including operand/backend pressure. Already prefetched fallthrough instructions shall not be charged an unconditional redirect wait. Original lengths, straddling C32 instructions, prefix capacity and replay-to-memory handoff shall remain explicit. No benchmark-specific correction factor shall replace these semantics.

## Memory environments

`PERFSIM_MEMORY=<YAML>` / `--memory <YAML>` shall select an external environment; omission shall use the fixed instruction/data latency arguments. Each independent `imem` / `dmem` port shall define all fields:

```yaml
imem:
  grant_pattern: [1, 0, 1, 1]
  response_cycles: [1, 3, 2, 1]
  cache: {lines: 0, line_bytes: 16, hit_cycles: 1, miss_cycles: 8}
dmem:
  grant_pattern: [1]
  response_cycles: [2]
  cache: {lines: 16, line_bytes: 16, hit_cycles: 1, miss_cycles: 8}
```

Grant availability shall be periodic from slot zero on the first post-reset edge. Without caching, `(byte_address >> 2) % len(response_cycles)` selects delay. Responses shall remain ordered, at most one per port per cycle. MEM grant and WB response resources shall permit the same overlapping ownership as RTL. Profiles shall reject malformed geometry, no-future-grant patterns and response delays outside 1..254 cycles; combined waits remain subject to native bounds.

`lines: 0` disables caching. The optional placeholder shall be a cold direct-mapped blocking tag array with power-of-two geometry. Read misses install tags and block grants through fill; stores update backing memory at grant, use hit/miss latency and do not allocate on misses. It shall not hold architectural data or imply dirty lines, writeback, bursts, MSHRs, coherence, cache RTL or a PPA model. Cache timing shall remain external to the core YAML.

## Architectural policy and events

RV32E shall expose E rather than I in `misa`, accept separately compiled `ilp32e` software and reject actual x16–x31 register operands before effects occur. CSR immediate fields are not register operands. Normal arithmetic semantics shall remain in CoreDSL/ETISS.

The native adapter shall implement the sparse RTL CSR map, read/write suppression, privilege checks, WARL behavior, PMP locks and M/U state transitions. Unreset PMP address payloads shall not acquire invented reset values. PMP shall use the core's sixteen G=0 entries, TOR/NA4/NAPOT, first-match/whole-access checks, machine lock behavior and data MPRV. Denied loads/stores shall cause no memory effect.

Synchronous faults shall use the existing ELF-embedded ordered `(PC, cause, mtval)` manifest. Unexpected, missing or extra events shall fail. Illegal decoder fallbacks shall be monitored explicitly. Faults and MRET shall carry event identity, terminate blocks, suppress normal effects and recover at WB while respecting older occupancy. Fault events shall remain in execution traces but shall not count as retired instructions. The no-interrupt WFI behavior is a nop.

Trap policy shall update `mepc`, `mcause`, `mtval` and `mstatus`, enter BASE for synchronous exceptions even with vectored `mtvec`, and implement serialized MRET. An ETISS successor PC alone shall not substitute for pipeline recovery timing.

Functional `mcycle` values shall not be treated as scheduled-core cycles. Uninhibited cycle reads shall be restricted to recognized measurement markers and shall not steer the measured path. Frozen cycle values, functional retirement counters and CSR policy remain deterministic. CSR/PMP hooks may execute in native C++; there shall be no Python instruction callback or scheduling-timestamp callback into shared models.

## Supported scope and explicit limits

The current integer profile covers RV32I/E with optional M/C, supported forwarding/frontend choices, external memory timing, basic cache stubs and declared synchronous M/U/PMP scenarios. F/Zfinx, A, Fence.i, XIF, asynchronous IRQ injection, external bus-error injection, debug, hardening and writable/self-modifying code remain unsupported and shall not silently receive generic latency.

Trap/PMP timing currently requires prediction disabled. PMP additionally requires the default immediate-grant, one-cycle, uncached instruction environment. Local fetch-fault transport has a known one-cycle directed-test discrepancy; arbitrary permission changes affecting prefetched words and longer/cacheable denied-fetch transport remain unqualified. Immutable per-PC event identity excludes fault-then-success retries at the same PC.

## Validation and reporting

Qualification shall separate software correctness, exact functional instruction prefixes, architectural events, same-contract schedule equivalence and RTL cycle accuracy. Measurement markers select WB completion `(start, stop]`; otherwise whole execution includes fill/drain. Counter-formatting code after stop may follow different paths and shall not invalidate an otherwise matched measured prefix.

`PERFSIM_VERIFY_SCHEDULING=1` shall advance independent instruction schedules and compare timing state at completed block boundaries, without feeding the oracle into models or scheduling. Numeric instruction-matrix products shall independently check composed code. Component regressions shall compare frontend/BPU/hazard behavior against actual RTL and CSR/PMP/memory policy against independent oracles.

Matched RTL studies shall agree on complete hardware parameters, ELF, environment, software self-checks, original encodings, retired window and declared trap sequence before reporting timing error. Matrix qualification defaults to 0.1% mean and 0.5% worst absolute relative cycle error. The directed platform validator defaults to 0.5%, with an explicit one-cycle short-test allowance. Changed budgets shall be recorded; failed or excluded required cases shall not disappear from aggregates. Passing one profile shall not qualify another or promote a Pareto candidate automatically.

Native cost trials shall use fresh processes, common CPU affinity, repeated samples and tracing/reference checks disabled, with expected counts and software outcomes checked on every trial. Build/extraction/JIT costs shall be distinguished from native runtime; suite speedup shall divide summed runtimes rather than average speedups.

Artifacts shall remain under `build/uquintus-<hw>/perfsim/`, content-addressed model/profile caches and generated study directories. Reports shall retain configuration/environment snapshots, source/tool/executable/profile identities, commands, checks, raw results and failed outcomes. Estimates shall have a separate report category and explicit coverage/calibration status. Dated run inventories and experimental chronology belong in build artifacts rather than source specifications or flow directories.
