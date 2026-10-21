# uquintus Architecture

**Status:** First specification draft finalized, 2026-10-20

ISA and microarchitecture requirements for the configurable RV32 core.

[Specification index](uqu_spec.md) · [Architecture](uqu_spec.arch.md) · [Interfaces](uqu_spec.interfaces.md) · [Verification](uqu_spec.verif.md) · [Build](uqu_spec.build.md) · [Style](uqu_spec.style.md)

Agreed requirements remain binding. Explicit proposals retain their status, and
TBD items remain implementation or integration follow-ups. Finalizing this draft
does not imply that the documented hardware or build infrastructure exists.

## 1. Fixed 32-bit architecture

**Status:** Agreed

The core shall implement a 32-bit RISC-V architecture (RV32), with the integer
register width fixed at `XLEN = 32`. Supporting RV64 or selecting between RV32
and RV64 through an RTL parameter is outside the scope of the core.

The core shall support RV32I as the default base ISA and RV32E as an optional
base selected through `ISA_E`. ISA configuration is defined in [architecture, Section 2](uqu_spec.arch.md#2-isa-and-microarchitecture-configuration-parameters).
Memory interface widths are defined separately in [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories).

The normative ISA baseline shall be the **20260120 editions** of the RISC-V
Unprivileged and Privileged Architecture manuals, available in the
[versioned ISA manuals](https://docs.riscv.org/reference/isa/v20260120/index.html).
The applicable base ISA, selected extensions, and privilege features shall follow
those editions. Additional extensions and changes to the pinned baseline shall
require an explicit design decision; publication of a newer edition shall not
automatically change the core's requirements. Separately pinned interface and
debug specifications shall retain their agreed versions.

## 2. ISA and microarchitecture configuration parameters

**Status:** Agreed

The default integer base shall be RV32I. Every configuration shall implement
**Zicsr version 2.0**, including the six standard CSR instructions (`CSRRW`,
`CSRRS`, `CSRRC`, and their immediate variants). Zicsr shall not have an optional
RTL parameter or YAML selector. Its accesses shall follow the privilege and
register-specific rules and the serialized WB implementation in [architecture, Section 18](uqu_spec.arch.md#18-native-csr-instruction-execution).
See the [Zicsr specification](https://docs.riscv.org/reference/isa/unpriv/zicsr.html).

The default software ISA string shall be `rv32i_zicsr`. An RV32E configuration
without optional instruction extensions shall use `rv32e_zicsr`. Software
builds and verification shall include mandatory Zicsr when describing the
implemented instruction set. These software ISA strings shall not prescribe
hardware configuration filenames, which remain user-selected identifiers under
[build, Section 2](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets).

Base selection and optional extensions shall be selected through RTL parameters
at elaboration/synthesis time:

| Parameter | Default | ISA selection | Capability when enabled |
| --- | --- | --- | --- |
| `ISA_E` | `0` (disabled) | E base instead of I | Select RV32E with 16 integer registers (`x0`–`x15`) instead of RV32I's 32. |
| `ISA_M` | `0` (disabled) | M | Hardware integer multiplication and division. |
| `ISA_C` | `0` (disabled) | C | Compressed instructions. |
| `ISA_ZFINX` | `0` (disabled) | Zfinx 1.0 | Single-precision floating-point computation using integer registers; selected floating-point implementation goal. |
| `ISA_F` | `0` (disabled) | F, deferred | Future floating-point support with a separate register file; enabled setting unsupported until implemented. |
| `ISA_A` | `0` (disabled) | A, planned | Future configurable atomic instructions and corresponding memory-interface support; implementation and detailed profile deferred. |
| `ISA_ZIFENCEI` | `0` (disabled) | Zifencei | Instruction-fetch synchronization through `FENCE.I`. |
| `ISA_PMP` | `0` (disabled) | Privileged PMP feature | Internal physical memory permission checks and PMP configuration CSRs ([architecture, Section 8.1](uqu_spec.arch.md#81-internal-pmp-and-memory-fault-boundary)). |

The default integer base shall therefore be RV32I, with
`ISA_E = ISA_M = ISA_C = ISA_ZFINX = ISA_F = 0`.
`ISA_ZIFENCEI` shall also default to `0`; user-mode configuration is defined in
[architecture, Section 8](uqu_spec.arch.md#8-bare-metal-execution-with-configurable-user-mode). CV-X-IF integration is selected separately through `XIF`
([interfaces, Section 5](uqu_spec.interfaces.md#5-cv-x-if-custom-extension-interface)); enabling that interface does not itself define a software ISA
extension.

`ISA_ZFINX` shall select ratified Zfinx version 1.0 under the pinned ISA
baseline. It shall provide the floating-point computation instructions using
integer registers and the standard `fcsr`, `frm`, and `fflags` CSRs. Floating-point
values shall use ordinary integer loads and stores; separate FP-register
loads/stores and integer/FP register-transfer instructions shall not be added.
The target shall support both RV32I and RV32E configurations. Examples are
`rv32i_zicsr_zfinx` and `rv32e_zicsr_zfinx`; the default configuration shall remain
`rv32i_zicsr`. See the
[Zfinx specification](https://docs.riscv.org/reference/isa/v20260120/unpriv/zfinx.html).

Zfinx shall not require XIF to be enabled. Its blocking-EX integration is
defined in [architecture, Section 3.3](uqu_spec.arch.md#33-native-zfinx-execution-and-fpu-implementation); its arithmetic implementation, latencies, and detailed
status-update sequencing remain TBD. As with other planned features, enabling
it shall be rejected until its implementation is supported by a documented
milestone.

Full F support shall be deferred in favor of Zfinx to avoid a separate 32-by-32-bit
floating-point register file in the targeted edge processor. `ISA_F` shall remain
in the configuration catalog for future work; all configurations shall explicitly
set it to zero until implemented. An enabled setting shall fail configuration
validation. `ISA_F` and `ISA_ZFINX` shall be mutually exclusive configuration
choices. Earlier F-specific register-file and reset decisions shall remain
historical design intent, not requirements for the Zfinx implementation.

`ISA_A` shall provide a configuration path for future native atomic-extension
support. Its enabled implementation, detailed ISA dependencies, and memory
ordering/reservation contract remain TBD. Until implemented and verified for a
supported milestone, only `ISA_A = 0` shall be accepted; enabling it shall fail
configuration validation rather than silently provide non-atomic behavior or
advertise an unimplemented extension. Hardware configurations shall explicitly
set this planned parameter to zero in the meantime.

`ISA_E` shall select an alternative base ISA rather than add an extension to RV32I.
Both bases retain `XLEN = 32`; `x0` remains hardwired to zero. Encodings that name
`x16`–`x31` as integer registers are reserved in RV32E. With `ISA_E = 1`, an
instruction that uses any unavailable integer source or destination register
shall raise an illegal-instruction exception, without executing or being
offloaded through CV-X-IF. The check shall use the instruction's actual integer
register operands; immediate fields and unused register fields shall not cause
false faults. Invalid register indices shall not alias `x0`–`x15` through
truncation. With `ISA_ZFINX = 1`, floating-point instructions shall use the same
available integer registers: `x0`–`x31` with RV32I or `x0`–`x15` with RV32E.
Unavailable-register checks shall include each used Zfinx source, including
`rs3`, and its destination. These distinctions follow the
[RISC-V RV32E specification](https://docs.riscv.org/reference/isa/unpriv/rv32e.html).

Each enabled parameter shall provide the corresponding architectural feature,
including its required behavior and dependencies. Supported combinations shall
account for interactions between enabled extensions. The selected ISA shall be
documented for software builds and verification.

Unsupported parameter values or combinations shall cause a build failure with
a clear diagnostic identifying the offending parameters and violated constraint.
The build shall not silently change requested settings or omit requested
features. Configuration checks shall run before simulation or synthesis
proceeds with an unsupported design. The checking mechanism remains TBD and
shall preserve the language rules for project-owned RTL and imported IP in the
[style guide](uqu_spec.style.md#2-language-and-source-files).

The documented supported configuration set may expand across implementation
milestones. A feature planned in this specification but not yet implemented
shall not be accepted as an active configuration. Documented inactive settings,
such as XIF subparameters when `XIF = 0`, may remain accepted and have no effect
as specified; inactivity alone shall not make such a configuration invalid.

For example, leaving `ISA_E`, `ISA_M`, `ISA_C`, `ISA_ZFINX`, and `ISA_F` at zero selects
`rv32i_zicsr`; enabling `ISA_M` alone selects `rv32im_zicsr`; enabling `ISA_M`
and `ISA_C` selects `rv32imc_zicsr`. Enabling `ISA_E` alone selects
`rv32e_zicsr`, and enabling `ISA_E` and `ISA_M` selects `rv32em_zicsr`.

The extension meanings follow the standard
[RISC-V ISA extension naming conventions](https://docs.riscv.org/reference/isa/unpriv/naming.html).
Additional extensions, supported combinations, implementation algorithms,
latency, throughput, and pipeline handling
remain TBD. Optional ISA extensions shall follow the first implementation
milestone ([overview, Section 3](uqu_spec.md#3-first-implementation-milestone)); their implementation order and detailed milestones
remain TBD.

### 2.1. Hardwired ISA identification

**Status:** Agreed

The `misa` CSR shall return a hardwired 32-bit value derived from the supported
RTL configuration. It shall not require writable ISA-selection state or permit
runtime extension switching. Its value shall remain constant through reset and
execution for a given elaborated configuration.

| Field | Required value |
| --- | --- |
| `MXL` | `1`, identifying RV32. |
| `I`, `E` | `I = 1, E = 0` for the default base; `I = 0, E = 1` when the RTL parameter `ISA_E = 1`. |
| `M`, `C` | Reflect the corresponding implemented and enabled `ISA_M` and `ISA_C` parameters. |
| `F`, `D`, `Q` | `0` for Zfinx configurations; full F support is deferred, so `F` shall remain zero until a future supported F implementation. |
| `A` | `0` until atomic support is implemented; subsequently reflect supported, enabled `ISA_A`. A planned configuration parameter alone shall not advertise the extension. |
| `U` | Reflect the RTL parameter `ISA_UMODE`; the `M` extension bit shall not represent machine privilege mode. |
| `S` | `0`; supervisor mode is not supported initially. |
| Other bits | Follow the selected ISA's encoding; unimplemented and reserved feature bits shall read zero. |

The presence of Zicsr, Zfinx, Zifencei, and other multi-letter extensions shall not be encoded
by inventing additional `misa` bits. The `X` bit shall identify actual
non-standard ISA extensions, not merely the presence of an enabled CV-X-IF
connection. Custom-extension identification and its integration configuration
remain TBD.

Hardwired fields shall ignore otherwise permitted M-mode CSR writes and retain
their configured value. The implementation shall not classify such a write as
illegal solely because the value is constant: `misa` occupies a read-write CSR
address and may implement constant WARL fields. Normal CSR privilege and access
checks shall still apply. See the
[RISC-V machine-level specification](https://docs.riscv.org/reference/isa/priv/machine.html).

### 2.2. Microarchitecture configuration parameters

**Status:** Agreed; selector encodings and details marked TBD remain open

The following elaboration-time parameters select microarchitecture while
preserving the configured ISA's behavior. Their naming conventions are defined
in the [RTL style guide](uqu_spec.style.md#3-identifiers-and-symbols).

| Parameter | Choices | Default |
| --- | --- | --- |
| `MUA_FORWARDING` | `0`: stall-only dependencies; `1`: enable forwarding subject to individual path controls. | `1` |
| `MUA_FORWARD_EX_TO_DE` | `0`: disable same-cycle EX-result forwarding to DE; `1`: enable it when the producer result is available; inactive when `MUA_FORWARDING = 0`. | `1` |
| `MUA_FORWARD_MEM_TO_DE` | `0`: disable MEM-result forwarding to DE; `1`: enable it when the producer result is available; inactive when `MUA_FORWARDING = 0`. | `1` |
| `MUA_FORWARD_MEM_TO_EX` | `0`: disable MEM-result forwarding to EX; `1`: enable it when the producer result is available; inactive when `MUA_FORWARDING = 0`. | `1` |
| `MUA_FORWARD_WB_TO_EX` | `0`: disable WB-result forwarding to EX; `1`: enable it when the producer result is available; inactive when `MUA_FORWARDING = 0`. | `1` |
| `MUA_DE_OPERAND_RETENTION` | `uqu_hazard` option: `0`: continuously resolve DE sources; `1`: retain correctly resolved DE operands while their instruction waits. | `0` |
| `MUA_C_IMPL` | `decompress`: expand into base instructions, then use the main decoder; `decode_compressed`: directly decode compressed instructions in parallel with the main decoder. Inactive when `ISA_C = 0`. | `decompress` |
| `MUA_C_DECOMPRESS_STAGE` | `if`: expansion before IF/DE; `de`: expansion after IF/DE and before the main decoder. Inactive when `ISA_C = 0` or `MUA_C_IMPL = decode_compressed`. | `if` |
| `MUA_BRANCH_PREDICTOR` | `none`, `static_not_taken`; additional implementations TBD. | `none` |
| `MUA_REGFILE_IMPL` | `ff`: flip-flop storage; `latch`: latch storage. | `ff` |
| `MUA_IF_BUFFER_WORDS` | Integer capacity of at least `2` in 32-bit fetch words; non-power-of-two capacities supported. | `2` |
| `MUA_HARDENED` | `0`: no OBI parity/checksum generation/checking requirement; `1`: planned hardened implementation including OBI parity/checksum generation and checking on both ports; enabled setting unsupported until implemented. | `0` |
| `MUA_MUL` | `parallel`, `parallel+stages+2`, or `iterative`; iterative unrolling set by `MUA_MULDIV_ITERUNROLL`; inactive when `ISA_M = 0`. | `iterative` |
| `MUA_DIV` | `iterative`; unrolling set by `MUA_MULDIV_ITERUNROLL`; inactive when `ISA_M = 0`. | `iterative` |
| `MUA_MULDIV_ITERUNROLL` | Integer factor 1, 2, 4, 8, 16, or 32 for the shared iterative chain; 1 means no unrolling; inactive when `ISA_M = 0`. | `8` |

Enumerated selectors use readable YAML labels translated into integer RTL
values through the canonical definition in [build, Section 2](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets); their exact numeric
encodings are defined for MUL/DIV, compressed decoding, branch prediction and
the register file in `config/selectors.json`. Predictor encodings are
`none = 0` and `static_not_taken = 1`.
`MUA_MULDIV_ITERUNROLL` is an integer factor passed to RTL
unchanged. Every hardware configuration shall explicitly set all parameters,
including inactive ones, under [build, Section 2](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets).

`MUA_DE_OPERAND_RETENTION` is implemented by the standalone hazard unit in
Section 4.2 and accepted as an explicit integer boolean by the component runner.
All hardware presets shall set it; existing presets use zero, and
`config/rv32i_retained.yml` selects one for comparison. Core/stage integration
remains pending.

Compressed-decode selectors shall also be set explicitly when inactive. Their
labels shall still be validated and mapped through the canonical catalog.
`MUA_C_IMPL` uses `decompress = 0`, `decode_compressed = 1`;
`MUA_C_DECOMPRESS_STAGE` uses `if = 0`, `de = 1`. The three effective C-enabled
paths and parent payload rules are defined in Section 15.1. Presets
`rv32ic`, `rv32ic_decompress_de` and `rv32ic_decoder_c` select them respectively.
All three paths are implemented in IF/DE with parent-register tests in
Section 15.5. Complete-core integration remains pending.

`MUA_HARDENED` is a planned future feature. Every hardware configuration shall
explicitly set it to zero until its implementation is supported. An enabled
setting shall fail validation before simulation or synthesis until then.
Its agreed OBI-integrity scope and remaining details are defined in [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories);
the parameter shall not imply a completed or fully specified hardened core.

## 3. Classical five-stage pipeline

**Status:** Agreed

The core shall follow the classical five-stage RISC pipeline described by David
Patterson.

The core shall be single-issue and in-order: at most one instruction shall issue
per cycle, and instructions shall issue and execute in program order.

The pipeline stages shall be arranged in this order:

| Stage | Name | Responsibility |
| --- | --- | --- |
| IF | Fetch | Fetch instructions through the instruction memory interface. |
| ID | Decode | Decode instructions, read source registers, resolve conditional branches, and calculate `JAL`/`JALR` jump targets. |
| EX | Execute | Perform arithmetic and logic operations and calculate effective addresses for memory accesses. |
| MEM | Memory | Perform load and store accesses through the data memory interface. |
| WB | Write back | Write instruction results to the register file when required. |

The MEM stage shall be blocking: a native load or store shall remain in MEM
until its data memory transaction completes. Younger instructions shall stall
behind it. Custom shared-LSU access shall be deferred under [interfaces, Section 5.1](uqu_spec.interfaces.md#51-initial-standard-only-scope-and-deferred-memory-features);
initial XIF offloads shall pass through MEM without requesting LSU work and
shall wait for their standard result completion at WB.

Base integer ALU operations shall complete in one EX execution cycle once their
operands are available. This shall include addition/subtraction, bitwise logic,
signed and unsigned comparisons, and immediate and register-controlled logical
and arithmetic shifts for both the RV32I and RV32E bases. Hazards and downstream
backpressure may still hold the instruction in EX; they shall not require
additional ALU execution steps.

When `ISA_M = 1`, `MUA_MUL` shall select the integer multiplier implementation
at elaboration time. Its readable YAML choices shall select a parallel or
iterative implementation family, translated into integer RTL settings under
[build, Section 2](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets):

| `MUA_MUL` value | Implementation contract |
| --- | --- |
| `parallel` | Infer a parallel multiplier using the Verilog `*` operator initially; produce the result in one EX execution cycle once operands are available. |
| `parallel+stages+2` | Partition parallel multiplication across two computation stages with an internal register boundary; execute in exactly two EX cycles. |
| `iterative` | Use the shared iterative radix-2 datapath with unroll factor `F = MUA_MULDIV_ITERUNROLL`; execute in exactly `32 / F` EX cycles. This is the default. |

The selection shall apply to `MUL`, `MULH`, `MULHU`, and `MULHSU`, with the
signedness and result selection defined by the
[RISC-V M-extension specification](https://docs.riscv.org/reference/isa/unpriv/m-st-ext.html).

For the parallel family, the stage count shall describe computation stages,
not merely delay registers after a complete combinational multiplier. Internal
registers shall partition the arithmetic path. Initial support shall be limited
to `parallel` and `parallel+stages+2`; other explicit stage counts shall fail
configuration validation. The initial two-stage implementation computes the
low-16-bit partial product in stage one, then computes and combines the upper
partial product in stage two, with an internal register boundary between those
computations. No particular Booth encoding, array structure, or
Wallace/Dadda reduction tree is required for the initially inferred multiplier.

The integer parameter `MUA_MULDIV_ITERUNROLL` shall select the shared iterative
unroll factor `F`, with supported values `1`, `2`, `4`, `8`, `16`, and `32` and
a default of `8`. Factor one shall mean no unrolling. Selecting `iterative`
shall use this parameter; it shall not implicitly select factor one. Iterative
MUL and DIV shall not have independent unroll settings or embedded
`+unroll+<factor>` selector suffixes.

For iterative multiplication, the arithmetic iteration count shall be `32 / F`;
factor 32 shall fully unroll those iterations. Operand preparation and sign
handling shall be integrated
combinationally into the first iteration, and final accumulation, sign
correction, and result selection into the last iteration. There shall be no
additional setup or completion cycles. All four multiplication instructions
shall therefore execute in exactly `32 / F` EX cycles once operands are
available, including one cycle at factor 32. Unroll factor shall describe
multiplier bits processed per iteration, not a Booth radix or a count of
internal register stages. The initial iterative implementation sign-extends
the multiplicand as needed and subtracts its selected contribution at the signed
multiplier's final bit; the combined accumulator/multiplier state is right-shifted
after each step. Full unrolling shall not prescribe a particular parallel
reduction tree. Generate constructs may implement the selected unroll factor.

All multiplier configurations shall have operand-independent execution
latency, with the same fixed cycle count for all four multiplication
instructions within a selected implementation. No operand-dependent early
completion shall be permitted. Multi-cycle multiplication shall retain EX under
the blocking policy below; internal registers shall not add architectural
pipeline stages or permit younger instructions to pass it. Hazards and downstream
backpressure may still extend the instruction's residence in EX without
requiring additional multiplication work. `MUA_MUL` shall default to `iterative` so MUL and DIV share the iterative
arithmetic chain.

Multiply instructions shall execute independently. The core shall not fuse a
`MULH`/`MULHU`/`MULHSU` instruction with a following `MUL`, or reuse a previous
instruction's product to satisfy a later multiplication. Each instruction shall
perform its own multiplication using the selected implementation and retain
its specified fixed execution latency and separate architectural retirement.

Similarly, `MUA_DIV` shall configure one iterative integer-divider family at
elaboration time for `DIV`, `DIVU`, `REM`, and `REMU`. Its currently supported
readable YAML value and default shall be `iterative`, using
`F = MUA_MULDIV_ITERUNROLL` for the unroll factor.

The unroll factor shall specify how many successive binary division steps
are implemented combinationally per iteration. Factor one shall reuse one
step per iteration; factor 32 shall fully unroll the 32 division steps.
Division shall use a magnitude-based setup phase of `ceil(2 / F)` EX cycles,
followed by `32 / F` iteration cycles and one completion cycle for sign
correction and result selection. The total execution latency, once operands
are available, shall be exactly `ceil(2 / F) + 32 / F + 1` EX cycles.
The ceiling is mathematical ceiling division; an RTL integer expression may
use `(2 + F - 1) / F` for this setup count.

With `F = 1`, the EX-owned shared arithmetic instance shall prepare the dividend
and divisor magnitudes sequentially in two setup cycles. With `F >= 2`, two
existing arithmetic slices shall prepare those independent magnitudes in
parallel during one setup cycle. Setup steering shall supply each slice's
operand independently and capture both results and the original operand signs;
it shall not instantiate additional data adders or negation units. The
completion cycle shall correct the sign of the selected quotient or remainder,
or pass through the selected unsigned result, using shared arithmetic.

| Unroll factor F | Setup | Iterations | Completion | Total EX cycles |
| --- | --- | --- | --- | --- |
| 1 | 2 | 32 | 1 | 35 |
| 2 | 1 | 16 | 1 | 18 |
| 4 | 1 | 8 | 1 | 10 |
| 8 | 1 | 4 | 1 | 6 |
| 16 | 1 | 2 | 1 | 4 |
| 32 | 1 | 1 | 1 | 3 |

Architectural special-case results, including division by zero and signed
overflow, shall use the same setup, iteration, and completion schedule as other
operands. Unsigned instructions and cases requiring no sign correction shall
also reserve these phases. Hazards and downstream backpressure may still
extend the instruction's residence in EX. All four
division/remainder instructions shall take exactly the configured number of
execution cycles, independent of operand values, signedness, or special cases.
No early termination or early result-availability indication shall be exposed,
including for division by zero, zero dividends, or signed overflow. Multi-cycle
execution shall retain the blocking EX policy below.

Division and remainder instructions shall execute independently. The core
shall not fuse a `DIV`/`DIVU` instruction with a `REM`/`REMU`, or reuse a
previous instruction's quotient or remainder to satisfy a later instruction.
Each instruction shall perform its own computation and retain the specified
fixed execution latency and separate architectural retirement.

The defaults `MUA_DIV = iterative` and `MUA_MULDIV_ITERUNROLL = 8` shall give
a fixed divider execution latency of six EX cycles when `ISA_M = 1`.
The default `MUA_MUL = iterative` shall give four multiplication cycles
with that unroll setting, sharing the same arithmetic slices as division. This default shall exercise and demonstrate the
unroll configuration.

Iterative multiplication and division shall reuse the EX ALU's add/sub
datapath. With `MUA_MULDIV_ITERUNROLL = 1`, all iterative data arithmetic,
including operand preparation, accumulation, subtraction, and any arithmetic
sign correction, shall use that shared datapath. No dedicated MUL/DIV data
adder, subtractor, multiplier, or arithmetic negation unit shall be instantiated
for that iterative configuration. Intermediate registers, operand/result
multiplexers, fixed-shift wiring, bit manipulation, and iteration/control logic
may remain in MUL/DIV. The shared ALU interface shall provide the carry/borrow
and guard bits needed by the selected algorithms; an ordinary truncated
32-bit result alone shall not constrain the implementation.

For an unroll factor greater than one, the first iterative arithmetic step
shall use the EX-owned arithmetic instance shared with the ALU. One chain of
`F - 1` additional configurable
add/sub-and-fixed-shift slices shall implement the remaining steps. With
`MUA_MUL = iterative` and `MUA_DIV = iterative`, both operations shall use this
same chain and the same unroll factor. Separate chains shall not be generated
for MUL and DIV. Factor one shall generate no additional arithmetic slices.

With `MUA_MUL = parallel` or `parallel+stages+2` and `MUA_DIV = iterative`,
only division shall use the shared iterative chain; multiplication shall use
its separate parallel datapath and retain its selected stage-count contract.
The initial shared chain uses the 33-bit `uqu_arith` primitive, with
MUL/DIV-specific state, fixed shifts, and input selection in `uqu_muldiv`.

ALU sharing shall preserve the fixed execution latencies specified above.
The initial divider uses magnitude-based restoring division, while iterative
multiplication handles signs in its conditional add/subtract steps. Operand
preparation and final correction shall not silently introduce
dedicated data adders at factor one or cycles beyond the specified MUL and DIV
schedules. Only the
instruction occupying EX shall own the shared datapath during native MUL/DIV
execution; older MEM/WB instructions shall remain able to drain under the
existing pipeline rules.

These constant-time requirements shall govern native multiply/divide execution
from the start of EX computation to result availability. Operand waits,
downstream backpressure, and retirement waits remain governed by the existing
pipeline contracts. Completed results shall remain available and stable until
accepted, without repeating the operation.

Configuration translation shall validate the family labels, stage count, and
shared unroll factor and supply
integer RTL settings, consistently with [build, Section 2](uqu_spec.build.md#2-shared-core-configuration-and-separate-build-targets). Verilog generate
constructs instantiate the selected number of arithmetic steps. The implemented
selector encodings are recorded in `config/selectors.json`. Both
selectors shall affect
microarchitecture without changing the software-visible M-extension behavior.
With `ISA_M = 0`, `MUA_MUL`, `MUA_DIV`, and `MUA_MULDIV_ITERUNROLL` shall have
no active hardware effect; every hardware configuration shall still explicitly
set all three parameters, including when inactive. Floating-point operations
and custom-operation timing remain separately defined or TBD.

A native multi-cycle execution instruction shall remain in EX until its result is
ready and MEM can accept it. While EX is occupied, backpressure shall hold
younger instructions in decode and propagate toward fetch as needed. EX being
busy shall not itself stall older instructions in MEM or WB; those stages shall
continue subject to their own readiness and dependencies. The execution unit
shall continue the work needed to finish the held instruction.

When a successor stage drains while its predecessor cannot supply a new
instruction, its instruction-valid state shall become empty. A held instruction
shall transfer to its successor only once per accepted transfer; holding a stage
shall not duplicate execution, writeback, or memory requests. Accepted memory
responses shall remain serviceable while EX is busy.
Offloaded instructions shall retain their normal pipeline slots through WB;
WB shall wait if an offloaded instruction's result is late ([interfaces, Section 5](uqu_spec.interfaces.md#5-cv-x-if-custom-extension-interface)).
CV-X-IF issue and operand delivery shall occur together in DE, and commit
permission shall be granted at WB, as defined in [interfaces, Section 5](uqu_spec.interfaces.md#5-cv-x-if-custom-extension-interface). Interrupt entry shall
wait for executing operations to finish, as defined in [interfaces, Section 4](uqu_spec.interfaces.md#4-external-machine-interrupt-sources).

Operand forwarding shall be configurable as defined in [architecture, Section 4](uqu_spec.arch.md#4-configurable-operand-forwarding). Branches and
`JAL`/`JALR` jumps shall resolve in decode as defined in [architecture, Section 6](uqu_spec.arch.md#6-resolve-branches-and-jumps-in-decode). Hazard detection
implementation details remain open; the operand admission, forwarding paths,
and dependency-stall behavior are specified in [architecture, Section 4](uqu_spec.arch.md#4-configurable-operand-forwarding).

Pipeline instruction state shall use the priority reset > flush > stall > normal
update. A flush shall invalidate the affected instruction and disable its future
side effects even when that stage is stalled. Invalid payload registers may
retain their values. Flush generation shall identify the instructions to discard;
a younger branch redirect shall not discard an older instruction in MEM.

Flushing pipeline instruction state shall not cancel an accepted memory
transaction. The core shall retain the transaction tracking needed to handle its
completion, discarding a stale instruction-fetch result when appropriate.

### 3.1. Common native execution-unit handshake

**Status:** Request/result handshake and immediate affected-operation flush
cancellation for native ALU/MUL/DIV/FPU agreed; exact payloads and adapters TBD

Native arithmetic execution units connected to EX shall use the common
request/result interface and handshake rules in the
[RTL style guide](uqu_spec.style.md#6-handshakes-and-control-events).
Once a computation has started, the unit shall continue toward completion
despite downstream backpressure and
retain its completed result until accepted.

EX shall track request acceptance so a held instruction starts computation
only once. The blocking EX policy permits at most one live native arithmetic
operation at a time. An accepted result shall be transferred or retained by
the pipeline exactly once; result acceptance shall not itself be architectural
retirement. Reset shall prevent stale results from being associated with another
instruction.

A flush that discards the instruction owning a native ALU/MUL/DIV/FPU operation
shall cancel that operation immediately at the active clock edge, following
`reset > flush > stall > normal update`. Cancellation shall take priority over
computation progress and request/result acceptance, including while the pipeline
is stalled or a completed result is blocked. The unit shall clear its busy or
active state, pending-result validity, and associated request tracking, releasing
the arithmetic resources without waiting for computation to finish. Arithmetic
payload registers need not be cleared once their validity is removed.

Request and result handshakes for the affected instruction shall be suppressed
while its flush is asserted, so neither `req_fire` nor `res_fire` occurs for it
on the cancellation edge. At and after cancellation, it shall produce no
accepted result, forwarding event, or architectural side effect, and no delayed
result shall be attributed to a later request. After the cancellation edge the
unit shall be idle and able to
accept a new operation under the normal handshake rules. Where specified for
native ALU/MUL/DIV, fixed-latency requirements shall apply to operations that
survive without cancellation; FPU latency shall follow [architecture, Section 3.3](uqu_spec.arch.md#33-native-zfinx-execution-and-fpu-implementation).
Flush routing shall identify the actual owning instruction; a redirect or
flush affecting only younger instructions shall not cancel an older EX operation.

This native arithmetic cancellation shall preserve the existing contracts for
accepted memory transactions, CV-X-IF commit/kill, and interrupt entry. A pending
interrupt shall continue to wait for executing operations under [interfaces, Section 4](uqu_spec.interfaces.md#4-external-machine-interrupt-sources).
The FPU shall follow this same cancellation contract, including suppression
of its result and accrued exception flags. Any imported FPU or adapter shall
clear the affected operation's busy state and pending-result validity and
release EX at the cancellation edge, without waiting for the computation to
finish. No stale result or status shall be attributed to a later instruction.

A single-cycle unit shall support request and result transfer on the same
clock edge, with combinational result availability during that EX cycle. The
interface shall not require an extra request or result register stage.
Execution latency shall continue to count EX computation cycles as specified
in [architecture, Section 3](uqu_spec.arch.md#3-classical-five-stage-pipeline), including the first request cycle; handshake plumbing shall
not add setup or completion cycles. Fixed result availability and later
acceptance under backpressure shall remain distinct.

ALU and iterative MUL/DIV use of EX-owned shared arithmetic shall use internal operand/result
connections for each arithmetic step; it shall not create a new instruction
request or add a handshake cycle for every iteration. The exact payload widths,
unit adapters, and status fields remain TBD. OBI and CV-X-IF shall retain their
separately specified interface contracts.

### 3.2. Control organization

**Status:** Central global arbitration, local stage/unit control, and separate
hazard/forwarding logic agreed; detailed event interfaces and sequencing TBD

The core shall use the following division of control responsibilities:

| Block | Responsibility |
| --- | --- |
| Central controller | Arbitrate global control events, select the accepted redirect, determine affected-instruction flushes, and coordinate trap/interrupt entry and required pipeline draining. Optional debug events shall join this arbitration under their selected debug contract. |
| Local stage and unit controllers | Manage normal valid/ready transfers, stage occupancy, arithmetic progress, and memory request/response tracking; apply the central controller's applicable flush and drain controls. |
| Hazard/forwarding block | Determine operand dependencies, result availability, bypass selections, and required dependency stalls under the configured forwarding policy. |
| CSR module | Own architectural CSR storage and update logic, decode accesses, enforce access checks, provide CSR read/modify/write behavior, and report exceptions; expose state and accept explicit update events ([architecture, Section 18](uqu_spec.arch.md#18-native-csr-instruction-execution)). |

Stages and units shall report relevant events and readiness to the central
controller. Global event priority and redirect selection shall have one
authoritative arbitration point. Event detection and target computation may
remain local: branch comparison and `JAL`/`JALR` target calculation shall remain
in DE, and the central controller shall permit a combinationally selected DE
redirect without requiring an additional pipeline stage or registered
arbitration cycle.

Arbitration shall preserve precise exceptions and instruction age. A younger
DE branch shall not override recovery for a known older MEM fault, and its
redirect shall not discard older EX/MEM/WB instructions. Trap entry shall wait
for the older work required by [architecture, Section 9](uqu_spec.arch.md#9-precise-synchronous-exceptions) and finalize synchronous trap entry
at WB under [architecture, Section 9.2](uqu_spec.arch.md#92-early-exception-containment-and-wb-trap-entry); interrupt entry shall follow the completion policy
in [interfaces, Section 4](uqu_spec.interfaces.md#4-external-machine-interrupt-sources). Detailed eligibility and priority rules for
simultaneous global events, including optional debug, remain TBD.

Local backpressure shall hold predecessor stages while allowing older stages
to drain. Central drain or flush control shall identify the affected stages
and instructions, preserving accepted-memory completion tracking and the
native arithmetic cancellation contract. The hazard/forwarding block shall
remain separate from global event arbitration; arithmetic and memory protocol
state machines shall remain within their respective units. Module names,
exact event payloads, and central-controller state encoding remain TBD.

### 3.3. Native Zfinx execution and FPU implementation

**Status:** Blocking EX integration and immediate flush cancellation agreed;
inactive interface stub available; FPU implementation selection open

Native Zfinx operations shall execute through an FPU attached to EX,
independently of CV-X-IF. The owning instruction shall remain in EX until its
result and associated status are ready and MEM can accept them. EX occupancy
shall hold younger instructions through normal predecessor backpressure;
older MEM/WB instructions shall continue to drain, and accepted memory
responses shall remain serviceable. Internal FPU registers shall not add
architectural pipeline stages or permit another native operation to bypass
the held instruction.

The FPU integration shall use the common native request/result handshake in
[architecture, Section 3.1](uqu_spec.arch.md#31-common-native-execution-unit-handshake), with an adapter if needed. An instruction shall start once;
completed result data and status shall be retained together until accepted.
Operands shall follow the three-read-port and common hazard/forwarding rules
in [architecture, Section 17](uqu_spec.arch.md#17-integer-register-file-implementation) and [architecture, Section 4](uqu_spec.arch.md#4-configurable-operand-forwarding). Dependent instructions shall wait until a qualified
result is available through an enabled route or register-file storage.

The integer destination write and accrued floating-point exception flags
shall update architectural state only when the instruction retires in WB.
Result data and flags shall remain associated with the instruction through
MEM/WB. Faulting or flushed instructions shall produce no destination or
FP CSR updates. The CSR module shall retain ownership of `fcsr` and its
aliases under [architecture, Section 18](uqu_spec.arch.md#18-native-csr-instruction-execution). An owning-instruction flush shall immediately
cancel the FPU operation under [architecture, Section 3.1](uqu_spec.arch.md#31-common-native-execution-unit-handshake), even while stalled or holding a
completed result.

FPU computation latency shall be defined by the selected backend and its
configuration and may depend on operand values. The core shall not require
operand-independent FPU timing or pad early completion to a fixed cycle count.
Request/result handshaking and pipeline backpressure shall govern progress:
start the operation once, wait for its valid result and status, and retain
them until accepted. EX shall advance only when that instruction's result and
status are available and MEM can accept them. Downstream stalls shall not
restart the operation or lose a completed result. No fixed-latency prediction
shall substitute for the actual result-valid/readiness checks.

Exact operation latencies, arithmetic algorithms, adapter payloads, and
implementation-specific cancellation wiring shall remain TBD until an FPU and
configuration are selected. The native integer MUL/DIV fixed-latency contract
in [architecture, Section 3](uqu_spec.arch.md#3-classical-five-stage-pipeline) shall remain applicable to those units.

The current floating-point scope shall be scalar Zfinx with single-precision
FP32 operands and the required 32-bit integer conversions. Packed SIMD
operations and additional FP formats, including FP8 and FP16, shall be deferred.
An imported FPU's broader capabilities shall not imply additional supported
instructions or require extra format/lane hardware in the initial integration.

**Candidate for evaluation, not selected:** OpenHW's
[CVFPU / FPnew](https://github.com/openhwfoundation/cvfpu) provides configurable
floating-point arithmetic and Bender support. Its
[interface documentation](https://github.com/openhwfoundation/cvfpu/blob/develop/docs/README.md)
describes three operand inputs, rounding-mode input, result/status outputs,
and input/output valid/ready handshakes. This makes an EX adapter a plausible
integration approach; the core would retain instruction decoding, register
access, and architectural CSR updates.

CVFPU is written in synthesizable SystemVerilog, including packages and typed
parameters. Imported IP and its dependencies may retain SystemVerilog under
the exception in the [RTL language rules](uqu_spec.style.md#2-language-and-source-files);
project-owned RTL, including the FPU adapter, shall remain plain Verilog-2005.
The documented asynchronous active-low reset must still be reconciled with the
core's synchronous reset contract. No dependency revision or configuration is
selected; operation coverage, timing, reset/flush behavior, and flow compatibility
remain to be evaluated before implementation selection. An imported FPU shall
meet the immediate cancellation requirement above.

#### 3.3.1. Unimplemented FPU interface

`src/uquintus/uqu_fpu.v` provides a plain-Verilog placeholder for EX integration.
It has the common native request/result handshake, clock, synchronous active-low
reset, and owning-instruction flush ports. Its interface is independent of a
particular FPU backend:

| Payload | Port | Meaning |
| --- | --- | --- |
| Request | `req_op_i[4:0]` | Decoded scalar operation selected in DE, using the internal encoding below. |
| Request | `req_a_i[31:0]`, `req_b_i[31:0]`, `req_c_i[31:0]` | Up to three scalar FP32 or integer source values from the integer register file. |
| Request | `req_rm_i[2:0]` | Effective rounding mode; the caller resolves dynamic rounding through `frm` where applicable. Ignored by operations that do not round. |
| Result | `res_data_o[31:0]` | Destination value for integer-register writeback. |
| Result | `res_fflags_o[4:0]` | Per-instruction exception flags in architectural `fflags` bit order, valid together with result data. |

A future implementation shall retain result data and flags together under
backpressure and discard both on owning-instruction flush. EX shall carry flags
to WB for retirement-qualified CSR accrual; the FPU shall not own `fcsr` storage.
DE shall recognize the instruction and produce `req_op_i`; the future FPU
adapter shall translate that selector into backend controls without decoding
instruction bits again. The scalar FP32 operation encoding is independent of
the backend and of the architectural instruction encoding:

| `req_op_i` | Operation | `req_op_i` | Operation |
| --- | --- | --- | --- |
| `5'd0` | FADD.S | `5'd11` | FSGNJX.S |
| `5'd1` | FSUB.S | `5'd12` | FMIN.S |
| `5'd2` | FMUL.S | `5'd13` | FMAX.S |
| `5'd3` | FDIV.S | `5'd14` | FEQ.S |
| `5'd4` | FSQRT.S | `5'd15` | FLT.S |
| `5'd5` | FMADD.S | `5'd16` | FLE.S |
| `5'd6` | FMSUB.S | `5'd17` | FCLASS.S |
| `5'd7` | FNMSUB.S | `5'd18` | FCVT.W.S |
| `5'd8` | FNMADD.S | `5'd19` | FCVT.WU.S |
| `5'd9` | FSGNJ.S | `5'd20` | FCVT.S.W |
| `5'd10` | FSGNJN.S | `5'd21` | FCVT.S.WU |

Values 22 through 31 are reserved. The instruction names identify the scalar
computation; source and destination values use integer registers under
[Zfinx](https://docs.riscv.org/reference/isa/v20260120/unpriv/zfinx.html).
The three operands and effective rounding mode remain separate payload fields.
Instruction legality, DE decoding, rounding checks, backend-control mapping,
and the actual backend remain implementation work. The stub performs none of
them and does not execute any selector value.

The placeholder supports only `ISA_ZFINX = 0`. It continuously drives
`req_ready_o = 0`, `res_valid_o = 0`, `res_data_o = 0`, and `res_fflags_o = 0`,
including during reset and flush. It contains no state and never accepts or
completes an operation. An instance with `ISA_ZFINX != 0` shall fail elaboration
through the explicitly named `uqu_fpu_zfinx_not_implemented` diagnostic cell.
EX may wire this disabled endpoint. The standalone decoder may recognize
configured Zfinx encodings, but a complete EX/core configuration shall not enable
Zfinx execution until a real backend is provided. The stub shall not advertise implemented
floating-point capability or provide a successful substitute result.

The Bender `fpu` target selects the endpoint; `rtl` also includes it. Functional
floating-point tests and backend dependencies remain deferred. Placeholder
validation covers Verilog parsing, synthesis to constant inactive outputs, and
rejection of enabled elaboration, and is not floating-point functional coverage.

### 3.4. Shared extended arithmetic primitive

The shared combinational add/sub component shall be named `uqu_arith`, in
`src/uquintus/uqu_arith.v`. The parent EX stage shall own one instance shared
by the ALU and the first iterative MUL/DIV step; additional unrolled steps shall
use further instances of the same primitive inside MUL/DIV. Physical sharing shall follow Section 3.

The initial implementation has two 33-bit operands, a subtraction selector,
and a raw carry input. It supplies the low 33 result bits, carry-out beyond
bit 32, and a borrow output. Addition computes `A + B + carry_i`; subtraction
computes `A - B - (1 - carry_i)`, so ordinary subtraction uses `carry_i = 1`.
In subtraction mode, carry-out means no borrow; the borrow output is zero
during addition. These are datapath signals, not architectural condition flags.

The primitive has no clock, reset, state, or instruction handshake. Native
execution handshakes belong to the enclosing execution unit. Bitwise ALU
operations, variable shifts, and comparison/result selection remain in the ALU;
MUL/DIV-specific fixed-shift wiring, operand steering, state, and iteration
control belong to the surrounding MUL/DIV logic. For a signed RV32 operand,
the enclosing logic can compute its magnitude by selecting `a_i = 0`,
`b_i = {operand[31], operand}`, and driving both `sub_i` and `carry_i` with
`operand[31]`. Nonnegative values pass through addition with zero; negative
values are negated by subtraction from zero. Unsigned operands shall instead
be zero-extended and passed through addition with zero. The 33-bit result
represents `abs(-2^31) = 2^31` without signed overflow. Magnitude computation
requires operand/control steering around the existing primitive, with no new
absolute-value operation or dedicated negation datapath. The initial
`uqu_muldiv` implementation uses this steering for divider setup and completion; the divider phase counts are fixed in Section 3.

See the [arithmetic component guide](../verif/sim/arith/README.md) for ports,
carry conventions, and standalone verification scope.

### 3.5. Native MUL/DIV component interface

`src/uquintus/uqu_muldiv.v` shall use the native request/result handshake in
Section 3.1. Its request carries two 32-bit operands and the three-bit
M-instruction `funct3`; its response carries one 32-bit destination value.
The unit shall own at most one accepted instruction, retain a blocked result,
and suppress transfers during reset or owning-instruction flush. It shall
accept no requests when `ISA_M = 0`.

The first arithmetic instance shall remain outside both MUL/DIV and ALU, owned
by their shared parent EX stage.
`arith_use_o` selects MUL/DIV's two 33-bit operands, subtraction control, and
carry-in for that instance; the result and carry-out return combinationally.
This connection shall have no separate ready/valid handshake. EX shall reserve
the resource for the owning instruction so that individual arithmetic steps
cannot stall. MUL/DIV shall instantiate only the additional `F - 1` instances.
The standalone test wrapper supplies slice zero. A separate shared-parent
fixture connects ALU and MUL/DIV around that instance. The EX component also
integrates both units, with boundary registers owned by its parent.

See the [MUL/DIV component guide](../verif/sim/muldiv/README.md) for the complete
port contract, operation encoding, algorithms, timing table, and test commands.

### 3.6. Base ALU and parent-owned arithmetic integration

`src/uquintus/uqu_alu.v` implements base RV32I/E addition, subtraction, logic,
signed/unsigned set-less-than, and all three variable shifts. Every operation
shall offer its result in the request cycle under Section 3.1, with retained
results under backpressure and immediate owning-instruction cancellation.
Its request carries two 32-bit selected operands and a normalized four-bit
operation code; its response carries one 32-bit result. The low operation bits
follow `funct3`, with bit three selecting SUB or SRA. Decode shall normalize
this modifier rather than blindly forwarding an immediate's bit 30. See the
[ALU component guide](../verif/sim/alu/README.md) for the encoding table.

EX shall own the shared `uqu_arith` instance and input mux, with ALU and MUL/DIV
as sibling units. Both units shall expose the same combinational arithmetic
operand/control and result/carry connection. EX shall issue only the owning
unit and retain resource selection throughout computation; return signals may
fan out to both units. Neither ALU nor MUL/DIV shall instantiate slice zero.
MUL/DIV shall retain its `F - 1` additional instances. There shall be no
per-step arithmetic arbitration or handshake and no additional execution cycle
from the mux. A held result shall no longer require the arithmetic instance.

The ALU shall sign-extend operands for signed comparison and examine the 33-bit
subtraction's sign. Unsigned comparison shall zero-extend operands and use the
subtraction's no-borrow carry. ADD/SUB shall return the low 32 result bits.
Logic and shifts shall remain inside ALU, with B[4:0] selecting shift amount.
The initial implementation shares one right barrel shifter using fixed input
and output bit reversal for left shift. Branch comparison and targets remain
in DE; upstream operand selection may use ADD for address, AUIPC, and LUI work.

Standalone wrappers and the
[shared-parent fixture](../verif/sim/exec_arith/README.md) supply the external
arithmetic instance for verification. That fixture demonstrates the module
boundary. The EX component implements ownership tracking; the full processor
pipeline remains pending.

### 3.7. EX stage and parent-owned pipeline registers

`src/uquintus/uqu_stage_ex.v` shall own local execution control, ALU/MUL/DIV/FPU
selection, the first shared arithmetic instance, and its operand mux. It shall
not own DE/EX or EX/MEM pipeline registers, instruction-valid storage, or
instruction-identity/destination metadata. Its parent shall retain the current
instruction and capture EX outputs together with the corresponding metadata.

The stage shall expose `valid_i` for the parent-owned live EX slot, `ready_o`
for permission to fill/replace that slot, and `valid_o`/`ready_i` for transfer
into the parent-owned EX/MEM register. An empty EX slot may accept an instruction
even when EX/MEM is occupied. An occupied slot shall transfer only when its
output is valid and the parent can capture it. Older EX/MEM work shall drain
independently of a busy EX, becoming empty when EX has no new output to supply.

EX may accept a native-unit request before the parent can capture its result.
One local tracking bit shall prevent reissue until transfer or cancellation;
private execution-unit state and retained results shall remain in the units.
Qualified pass-through readiness shall also be retained until transfer.
No additional instruction payload pipeline register shall be introduced in EX.
Parent-owned controls and metadata shall remain associated with the instruction
through stalls. Owning flush/reset shall cancel EX and its units; a younger-only
flush shall not affect older EX work, and an EX-only flush shall not invalidate
an older parent-owned EX/MEM instruction.

The separate forwarding/hazard block and parent shall present decoded controls
and selected operands. Operand readiness shall include store data, independent
of the ALU's address-offset operand. The parent/hazard logic shall retain
correct operands once resolved until transfer or cancellation; EX shall not
add another operand pipeline register. The existing DE admission rule remains
binding: native operands shall be captured or guaranteed available through an
enabled bypass on EX entry. Existing exception tokens shall bypass
operand waits without starting computation. Unsupported unit routing or invalid
normalized ALU/MUL/DIV control codes shall report illegal-instruction cause 2;
an existing exception's cause/tval shall retain priority. EX reports exception
metadata for the normal precise WB path and performs no trap-entry side effects.

Stage completion shall not itself qualify a destination-register bypass. The
parent and forwarding block shall distinguish computed addresses from load
results and recognize that CSR/XIF results become available later. FPU flags
shall remain associated with their instruction until retirement-qualified WB
updates; the current FPU endpoint remains disabled and unimplemented.

See the [EX interface guide](../verif/sim/ex/README.md) for ports, functional-unit
codes, parent-register handshake details, operand retention, and pass-through
semantics. The [parent fixture](../verif/sim/ex_pipeline/README.md) verifies both
boundary registers outside EX, including throughput, metadata, stalls, older
MEM draining, and EX cancellation. Full-core pipeline control and forwarding
remain separate implementation work.

### 3.8. MEM-owned load/store unit

`src/uquintus/uqu_lsu.v` implements the blocking native LSU for the MEM stage.
The LSU owns one access's private request/response tracking and registered
completion; pipeline EX/MEM and MEM/WB storage remains outside the unit.
The MEM stage in Section 3.9 issues each access once, associates its completion
with the parent-held instruction, and transfers result/exception metadata
onward without repeating the transaction.

The unit accepts a native valid/ready request carrying load/store selection,
instruction funct3, effective address, store data, original instruction, and an
internal access-denial indication. A separate `request_permit_i` gates external
request presentation until older instructions are safe under Section 9.2.
Access-denial checks shall be complete at native acceptance. Invalid normalized
control, misalignment, or access denial shall complete with exception metadata
without issuing OBI. Misalignment shall take priority over access denial.

The native OBI data port shall preserve the declarations and transaction rules
in [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories).
The LSU registers its request before presentation, aligns only the bus address,
places byte enables/store data, and retains the original effective address.
Granted loads and stores shall wait for completion. Bus data/error shall be
captured regardless of pipeline stalls; selected/extended load results and
exceptions shall be exposed only after that capture. This provides registered
load-result storage under Section 4 without an external-response bypass.

An owning flush before OBI request presentation may cancel the private access.
Once request is presented, flush shall not withdraw it, including before grant.
The LSU shall finish the grant/response obligation and discard a killed access's
completion without raising a stale exception. Held native completions may be
discarded immediately. `busy_o` shall account for transaction and completion
storage, including killed bus work. Reset may clear this tracking only under
the coordinated system-reset contract. There shall be no bus timeout or retry.

The [LSU component guide](../verif/sim/lsu/README.md) defines ports, fault priority,
request permission, byte lanes, completion timing, and verification. PMP integration,
full-core pipeline control, fences, custom memory operations, atomics, integrity,
and non-OBI bus adapters remain separate implementation work.

### 3.9. MEM stage and parent-owned pipeline storage

`src/uquintus/uqu_stage_mem.v` owns the LSU and one local request-issued bit.
The stage's parent shall own both EX/MEM and MEM/WB registers, their validity,
instruction identity/PC/destinations, and retained payloads. MEM shall not
duplicate these boundary registers or own the core-wide PMP/CSR blocks.
The [MEM component guide](../verif/sim/mem/README.md) defines its ports and tests.

`valid_i` describes the live parent-held EX/MEM instruction. `ready_o` permits
filling an empty slot or replacing its current instruction when
`valid_o && ready_i` transfers it to MEM/WB. The parent shall retain the input
payload while held; `ready_i` describes MEM/WB capacity. A native LSU request
may be accepted while WB is blocked, but this shall not release EX/MEM or
permit repeated issue. The LSU shall retain completion until MEM transfers it.
Non-memory tokens, including arithmetic/FPU results and CSR/XIF/fence tokens,
shall pass through without LSU side effects. Existing exceptions take priority
and shall issue neither LSU work nor a PMP query.

MEM shall expose a combinational protection query containing original effective
address, log2 access size, read/write requirement, and effective data privilege.
The parent shall connect it to the MEM port of its one two-port PMP block and
return permission as `pmp_allow_i`. The parent resolves MPRV/MPP; MEM shall not
receive or store PMP configuration. LSU acceptance captures denial, independently
of the controller's precise-effect `request_permit_i`. No denied native access
shall reach OBI, and misalignment shall retain priority over permission denial.

Successful load data becomes available only from registered LSU completion.
`load_result_valid_o` qualifies a live successful load result independently of
WB readiness. The parent/hazard block still determines destination, instruction
class, youngest-writer priority, and configured forwarding eligibility; stage
completion alone shall not identify a forwardable CSR/XIF result. Memory
operations and exceptions shall not propagate floating-point flag updates.
Pass-through FPU flags remain per-instruction metadata until qualified WB accrual.

An owning MEM flush suppresses transfers/new issue and clears local issue
tracking, while the LSU cancels or drains according to Section 3.8.
`lsu_busy_o` shall remain visible even after EX/MEM validity is cleared. An empty
EX/MEM slot may fill during killed bus work, but its replacement instruction
shall wait for that work to drain before any completion or new LSU acceptance,
including for non-memory/exception tokens. The killed response/error shall
never become the replacement's result. This conservative blocking shall not
prevent an older MEM/WB instruction from draining. A MEM-only flush shall not
clear that older parent register. Reset may abandon bus tracking only under
the existing coordinated system-reset contract.

The [MEM parent-register fixture](../verif/sim/mem_pipeline/README.md) verifies
the actual stage with external EX/MEM and MEM/WB registers and a parent-owned
PMP block, including both PMP configurations. Standalone and fixture tests cover
variable-latency transactions, faults, order/identity, WB backpressure, killed
transaction draining, and recovery. Development Yosys checks confirm only one
top-level tracking state bit plus one LSU, no boundary payload/PMP storage in
MEM, and no combinational OBI-response bypass or flush withdrawal of request.
Full-core WB/controller/fence and hazard/forwarding integration remain pending.

### 3.10. WB stage, commitment, and owned CSR state

`src/uquintus/uqu_stage_wb.v` owns one `uqu_csregfile`, native/CSR result
selection, GPR write generation, and acceptance-qualified architectural events.
It shall own no MEM/WB payload/valid registers. With XIF enabled, one local
bit records that commit permission has been sent for the current WB token;
otherwise all state belongs to the CSR unit. The core parent shall own MEM/WB, the GPR file, current privilege,
global arbitration/serialization, redirects, and the one two-port PMP block.
The [WB component guide](../verif/sim/wb/README.md) defines the initial bindings.

`kind_i[2:0]` selects ordinary result/token (`0`), native CSR (`1`), MRET (`2`),
XIF (`3`), DRET (`4`), or EBREAK (`5`). Disabled XIF/DRET classes are illegal. A live token may wait in
the parent while WB reports its legality. `valid_o && ready_i` shall authorize
either successful retirement or synchronous fault entry. The parent shall
consume that instruction once; a held token shall cause no repeated effects.
An empty slot may fill while the controller withholds commitment. Normal
instructions may retire on consecutive cycles without a local result buffer.
Fence and other serialization requirements shall constrain controller readiness,
not add instruction decoding or independent event arbitration inside WB.

On successful acceptance, native GPR writes, required CSR updates, committed
FP flags, and retirement counting shall belong to that same instruction/edge.
x0 shall never write; actual E-mode destinations x16..x31 shall fault without
aliasing. Unused destination fields shall not fault. A successful CSR returns
its architectural pre-update read value. Ordinary primary destination data may
be advertised through `result_valid_o` while held, but CSR data shall become
forwardable only on successful commitment, since counter read values can change
while waiting. The existing hazard/forwarding block still owns matching and
configured path selection.

Existing exceptions take priority over malformed normalized controls and CSR
access failures. The live `exception_valid_o` report and its PC/cause/tval shall
not depend on controller readiness or accepted external trap input. A reported
fault shall update trap state only when acknowledged through
`exception_fire_o`; it shall not retire or update an ordinary GPR/CSR/FP result.
The controller shall redirect from this accepted event without echoing it
through the external trap input. Legal MRET acceptance shall restore CSR state
and retire once; the parent shall sample pre-edge MPP/mepc for mode/PC changes.

External `trap_i` denotes a previously arbitrated precise architectural event,
normally an interrupt at a drained boundary, not a raw pending interrupt. It
suppresses WB acceptance and updates CSR trap state even while the owning WB
token is canceled. The controller shall prioritize older WB faults before
asserting such an external event and provide a valid current privilege even
with no live MEM/WB token. Reset dominates all events. WB's own accepted
fault/MRET shall consume the token and clear/block younger parent slots; it
shall not be fed combinationally back into its own `flush_i`, which would cancel
the acceptance or form a control loop.

With `XIF=1`, WB sends one standard CV-X-IF commit notification independently
of result/controller readiness, then holds the parent slot until a matching
hart/ID result can be accepted. A result may complete on the notification edge, including a combinational
coprocessor response to permission. Result-ready must be independent of all
incoming result fields/validity, including through parent readiness control.
No result queue is needed under the in-order coprocessor profile. Result
acceptance, both enabled paired writes, and retirement share one edge; only the
primary destination is forwardable. A core-internal younger-kill input shares
the standard commit channel with WB notifications, with WB priority and a ready
signal back to the parent. This adds no coprocessor sideband. Owning flush before
permission sends a kill; an offload already allowed to commit must drain and
shall not be flushed. Issue/ID allocation and younger flush tracking remain
parent responsibilities. Malformed/unmatched result packets cannot retire or
write architectural state; they may handshake/discard because readiness cannot
depend on packet fields. Protocol violations require integration-level recovery
and do not create coprocessor execution exceptions.

With `DEBUG=1`, the CSR unit implements debug-only DCSR/DPC and one dscratch0.
WB accepts already-arbitrated debug-entry events, handles serialized DRET and
EBREAK, and reports debug exceptions without changing machine trap state.
The parent owns Debug Mode, drain/step sequencing and debug address redirects.
DCSR.stepie=0, stopcount=1, stoptime=0, mprven=1; unsupported mode/trigger fields
are zero. EBREAK can enter debug under the M/U controls or end debug code when
already in Debug Mode. DRET restores privilege/PC from pre-edge DCSR/DPC and
clears MPRV on return to U. Full-F/atomic configurations still fail elaboration;
Zfinx CSR wiring does not implement an FPU.

The [WB parent fixture](../verif/sim/wb_pipeline/README.md) verifies a real
MEM/WB slot, sibling FF/latch GPR storage, privilege transitions, delayed XIF
results, paired writes and debug execution through the normal datapath.
Synthesis checks retain zero/one local WB state bits with XIF disabled/enabled,
respectively, and no boundary payload storage. Full-core arbitration/draining,
DE offload tracking, external-DM integration, RVFI and software-level verification
remain separate integration work.


### 3.11. Native decoder and DE ownership

`src/uquintus/uqu_decoder.v` is the combinational native decoder owned by the
DE stage implemented in Section 3.12. It extracts immediate values and register-use/destination
intent, validates encoding/configuration and E-register constraints, and emits
normalized EX, LSU, WB, branch and system controls. Architectural encodings
come from uqu_isa.vh; internal selectors come from uqu_ctrl.vh and are also used
by the relevant EX/WB/ALU consumers. It owns no instruction,
architectural state, operands or handshake. The
[decode guide](../verif/sim/decode/README.md) defines selectors and integration.

DE shall own this decoder, operand selection and branch/target computation,
plus its XIF issue handling. GPR storage shall remain core-owned, read by DE
and written by WB. The core shall also retain IF/DE and DE/EX registers,
instruction identity, shared hazards/forwarding, current privilege/Debug Mode,
and global control. A parent-register fixture is a verification environment,
not a replacement for the production core hierarchy.

Native encoding recognition shall remain distinct from E-register legality:
a recognized native instruction using an unavailable GPR remains a native
exception, not an extension override. Unknown instructions may still be claimed
by XIF through parallel recognition; the decoder shall not own offload acceptance.
Runtime privilege/WFI/rounding checks and branch alignment belong in DE/core;
CSR address/access checks remain at WB. The DE-owned `uqu_decoder_select`
adapter applies the compressed-decode strategy from Section 15.1, supplying
expanded instructions to the main decoder or selecting direct compressed
controls. The parent preserves original bits/length for faults and links.

The decoder supports the base ISA, mandatory Zicsr and system/fence classes,
optional M, Zfinx encoding recognition, Zifencei and debug DRET. FPU execution
remains unimplemented. Tests cover legal and reserved fields, immediate layouts,
actual versus ignored register fields, optional configurations and all control
outputs; synthesis shall retain no decoder state.

### 3.12. Decode stage and parent-pipeline integration

`src/uquintus/uqu_stage_de.v` owns the native decoder and compressed-decode
adapter, branch unit, runtime
legality, operand/control selection and optional CV-X-IF issue state. Its
[component guide](../verif/sim/de/README.md) defines concrete ports, normalized
controls, exception priorities, standard offload fields and integration rules.
GPR storage, the shared hazard unit, IF/DE and DE/EX registers, instruction
identity/original bits/length, current privilege, serialization and global
event/redirect arbitration remain core-owned.

Native DE is combinational around the parent-held instruction. A transfer
requires decoder/runtime legality or a contained exception, the agreed
operand readiness/guarantee contract, downstream capacity and `permit_i` from
central control. Early serialization and exception outputs remain visible
while transfer is blocked; they request containment without architectural
updates. Incoming IF exceptions take priority. Illegal instructions report
original bits, ready taken-target misalignment reports its target, and ECALL
reports the originating privilege's cause. EBREAK remains a WB debug/breakpoint
decision. CSR accesses remain serialized with address/access checks at WB.

DE exports used source addresses and current-use/EX-use masks independently
of branch comparison results and live XIF responses. It accepts resolved values
and readiness from the hazard unit. The core shall retain raw source identities,
values, captured-valid bits and operand selectors with DE/EX; a future EX
guarantee does not validate a stale selected DE operand. Store data remains
separate from the ALU's immediate operand. Dynamic Zfinx rounding is checked
against frm without requiring FS state; native FPU execution remains deferred.

`branch_resolve_o` shall identify only the accepted nonfaulting branch/jump
transfer and qualify taken/next-PC information for the central frontend
controller. An untaken branch also resolves once. Prediction/BTB, fetch resume,
redirect/misprediction arbitration and target PMP checking remain outside DE.

Optional XIF implements coupled issue/register channels and local stable
operand capture, including when hazard-unit DE retention is disabled. An
issue response is sampled once; accepted offloads may wait in DE and then
pass through EX/MEM without reissue or waiting for WB results. Parent-reserved
three-bit IDs and the WB commit/kill arbiter retain their existing ownership.
Rejected or defensively invalid accepted transactions shall receive standard
kill notification through core-internal cleanup arbitration before their fault
token transfers. No proprietary coprocessor channel or execution trap is added.
Flush/drain handling must notify outstanding accepted work and retain ID
lifetime association before discarding parent-owned metadata.

IF may identify an extension-expanded compressed instruction through
`xif_force_i`; DE then re-offloads its expanded instruction even when that
encoding resembles a native instruction. The origin flag is only valid with
C-enabled compressed metadata. Frontend expansion/offload logic itself remains
pending. RV32E-aware coprocessor rejection and defensive core kill semantics
are defined by D-281 in the interface specification.

The [native parent fixture](../verif/sim/de_pipeline/README.md) combines real
IF/DE and DE/EX storage, GPRs and hazard logic around DE, with external EX
computation/MEM/WB producer stubs. It verifies guaranteed EX bypass admission,
held EX operands, register-file fallback, store-data selection, one-time
branch resolution, fault identity and flush. It does not replace the production
core controller or implement XIF ID/kill arbitration.

The initial standalone suites pass across twelve native/optional profiles; the
initial two fixture suites pass across ten forwarding/retention/ISA/GPR profiles. Lint and synthesis
checks infer no latches. Generic optimized native DE state is zero; paired XIF
adds 72 bits with two sources or 105 with three, only local protocol/operand
state. Netlist reachability checks confirm no combinational path from standard
issue/register response inputs to standard issue/register outputs. Full-core
integration, RVFI/Spike and frontend/global event sequencing remain follow-ups.

The compressed-strategy regression adds six DE suites across all three
strategies with I, E+Zfinx and two-/three-source XIF, C-disabled selector cases
and a direct-decoder inactive-placement alias. Exhaustive selected-control and
leaf decoder checks cover all halfwords, and a parent fixture suite verifies
held compressed calls, ALU controls and original fault identity. The fixture
instantiates real IF-mode expansion before IF/DE or real DE expansion/direct
decoding after it, consuming raw compressed inputs in all modes. A mixed-length
stream scoreboard checks both parent registers under backpressure and permission
stalls, with original bits/length, PC wraparound and call links preserved. All native
strategies remain combinational; synthesis confirms that unselected compressed
units are removed and invalid selector encodings fail elaboration.

## 4. Configurable operand forwarding

**Status:** Agreed

Operand forwarding shall be supported as an optional microarchitecture feature
selected through the RTL parameter `MUA_FORWARDING` at elaboration/synthesis
time. It shall default to `1` (enabled); `0` shall select stall-only handling
of data dependencies.

With forwarding enabled, dependent instructions may use available results
before register writeback. Hazard detection shall still stall instructions when
a required result is not yet available or cannot be forwarded.

With forwarding disabled, data dependencies shall be resolved by stalling until
the required operands can be read correctly from the register file. Both
settings shall preserve the behavior required by the configured ISA.

Same-cycle WB-to-DE dependencies shall be handled in the pipeline forwarding
and hazard logic, outside the register-file storage module. With forwarding
enabled, an available WB result may supply a matching DE source before the
register-file write takes effect. With forwarding disabled, DE shall stall
until the required value can be read correctly from storage. This shall cover
native instruction operands, including all three Zfinx FMA sources, decode-stage
branch/jump operands, and all configured XIF sources. Both write destinations of a paired XIF result shall
participate in hazard tracking when dual writeback is enabled, but only its
primary destination shall be forwardable under the XIF rule below; `x0`
shall always supply zero.

Forwarding shall use valid, available producer results. If multiple older
instructions target a source register, the youngest preceding writer shall
determine the operand; an unavailable newer value shall not be replaced by an
older available value. Both register-file backends shall rely on this common
policy and shall not add an independent write-through bypass.

Two additional elaboration-time parameters shall independently control early
forwarding into DE:

| Parameter | Enabled behavior |
| --- | --- |
| `MUA_FORWARD_EX_TO_DE` | Forward an available result from the instruction currently in EX into a dependent DE operand in the same cycle, including the combinational EX-result path. |
| `MUA_FORWARD_MEM_TO_DE` | Forward an available result from the instruction currently in MEM into a dependent DE operand. |

Both parameters shall accept `0` or `1`. `MUA_FORWARDING` shall remain the
master switch: with it disabled, both paths shall be inactive regardless of
their individual settings. Every hardware YAML configuration shall explicitly
set the two parameters, including when inactive. Both shall default to `1`.
All four combinations of the individual path controls shall be supported.
Disabled paths shall be excluded at elaboration or eliminated by synthesis.

With the master switch enabled, DE shall use an enabled EX-to-DE path when
the youngest older writer is in EX and its result is available. Otherwise,
an operand needed in DE shall wait for that same writer to reach an enabled
forwarding source with an available result. If EX-to-DE is disabled, the
consumer may obtain the value when the writer reaches MEM, provided MEM-to-DE
is enabled. If that path is also disabled or the result is unavailable there,
DE shall stall until the writer reaches WB and the existing WB-to-DE path
can supply the value, or until the value can be read correctly from storage.
An enabled path shall never bypass the youngest-writer availability rule by
selecting a stale value from a different, older writer in another stage.

This policy shall cover operands consumed by DE branch comparison, `JALR`
target calculation, and configured XIF source delivery, and shall govern any
other operand forwarding into DE. Merely enabling a path shall not make an
unfinished or faulting result available; in particular, a load's computed
address shall not be forwarded as its loaded data. These selectors shall not
move branch resolution out of DE or require a fixed dependency-stall count
when execution or memory has variable latency. Older stages shall continue
to drain under the existing local backpressure rules.

The independent boolean parameter `MUA_FORWARD_MEM_TO_EX` shall control
forwarding from the instruction currently in MEM to dependent operands
consumed in EX. It shall default to `1` and shall be inactive when the
`MUA_FORWARDING` master switch is zero, regardless of its individual setting.
Every hardware YAML configuration shall explicitly set it, including when
inactive. A disabled path shall be excluded at elaboration or eliminated by
synthesis. Its setting shall be independent of both DE-path controls.

With MEM-to-EX enabled and the required producer result available, adjacent
dependent native ALU instructions shall be able to use that path without an
additional data-dependency stall, even with EX-to-DE disabled. The same
MEM-to-EX operand-selection policy shall apply to native load/store address
calculation in EX. Hazard logic shall distinguish operands needed in DE from
those needed in EX: disabling an early DE path shall not by itself force an
EX consumer to stall when an enabled path can supply the correct value in
time. Other pipeline stalls and result-availability constraints shall still
apply.

With MEM-to-EX disabled, the consumer shall obtain the required value through
another enabled path in time for its use, or stall until it can do so. The
youngest-writer rule and result-validity checks above shall also apply to this
path. An unfinished load shall not supply its effective address as a data
result, and a faulting producer shall not supply a usable result.

The independent boolean parameter `MUA_FORWARD_WB_TO_EX` shall control
forwarding of an available destination-register result from the instruction
currently in WB to dependent operands consumed in EX. It shall default to `1`
and shall be inactive when `MUA_FORWARDING = 0`, regardless of its individual
setting. Every hardware YAML configuration shall explicitly set it, including
when inactive. A disabled path shall be excluded at elaboration or eliminated
by synthesis. Its setting shall be independent of MEM-to-EX and both DE-path
controls; it shall not disable the existing WB-to-DE path.

WB-to-EX shall use the correct available destination value and preserve the
youngest-writer and result-validity rules above. Hazard checks shall include
both destinations of a paired XIF write when enabled, with forwarding limited
to its primary destination under the rule below. An unavailable younger matching writer
shall prevent use of an older matching WB result. With this path disabled,
hazard logic shall use another enabled route that supplies the correct value
in time or stall the consumer until it can do so. Disabling an earlier DE
path shall not by itself require a dependency stall when WB-to-EX can supply
the correct value at EX use.

For example, with forwarding enabled, MEM-to-DE disabled, and no unrelated
stalls, the sequence `add x3, x1, x2; addi x6, x0, 1; sub x4, x3, x5` shall
be able to supply `x3` from the first instruction in WB to the third instruction
in EX through WB-to-EX. The intervening instruction in MEM does not produce
`x3`. The consumer's earlier DE register-file read may still contain the old
value, which shall not be used for the EX computation.

A matching, valid result for the live XIF instruction in WB shall be eligible
for forwarding before the register-file write, once that instruction has
received commit permission and the existing validity/fault checks permit use.
WB-to-DE shall be available under `MUA_FORWARDING`; WB-to-EX shall additionally
require `MUA_FORWARD_WB_TO_EX`. Forwarding shall select the result belonging
to the WB instruction's identifier and its declared, enabled destination.
It shall not require waiting for register-file write visibility or adding an
extra result-register cycle solely for this bypass.

For a single-destination XIF result, the forwardable value shall be its 32-bit
`rd` result. For a paired result, only the primary destination, the even
register `rd` receiving result bits `[31:0]`, shall be forwardable. The second
destination, `rd + 1` receiving result bits `[63:32]`, shall have no operand
bypass. A consumer of that second destination shall wait until the correct
value can be read from register-file storage and captured under the existing
operand-readiness rules. Its pending write shall still participate in
youngest-writer checks, preventing use of an older matching result or stale
register-file data while that value is pending. The existing ignored-write
rules for `x0` and the `x0`/`x1` pair shall remain applicable.

Native integer stores shall resolve their store-data operand in EX through
the same configured forwarding and hazard policy as other EX operands.
Store data shall be selected independently of the address ALU's immediate
operand: `rs1` supplies the address base, while the used `rs2` supplies the
value to store. Enabled MEM-to-EX and WB-to-EX paths shall cover store data,
and a value already obtained correctly in DE may also be carried into EX.
If the required store data is unavailable, the store shall wait rather than
advance to MEM with an unresolved register dependency.

Before an EX-to-MEM transfer, both the effective address and correct store
data shall be ready and retained with the store. MEM shall use this retained
value for the existing byte-lane and bus-request handling; it shall not wait
for a late register producer or require a separate store-data forwarding path
into MEM. This shall preserve the existing request-permission, precise-fault,
and stable OBI payload rules. With forwarding disabled, ordinary dependency
stalls shall supply the same correct value through register-file reads.

A native load shall become available for register-operand forwarding only
after its successful response data and completion status have been captured
in core registers. No direct combinational bypass from the external OBI
response into dependent operand data or readiness shall be required or
permitted. A failed response shall follow the precise exception path and
shall not produce a forwardable load result.

The forwarded destination value shall include the required byte selection and
sign or zero extension. It may be derived from retained response data or a
registered destination value, but shall not depend on the current external
response inputs. Only an enabled path from the stage owning the valid load
result may supply a consumer. Response capture shall remain independent of
pipeline advancement under [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories); this decision shall not require an
additional load-result pipeline stage.

For example, if a successful response is captured at the edge ending cycle
R, the loaded value may first be forwarded during cycle R+1, subject to the
enabled path and pipeline readiness. A dependent instruction shall wait until
its actual operand-use point can receive that value. Grant or response delays,
disabled paths, and other backpressure may extend this wait; no fixed
load-use stall count shall be assumed.

Once a consumer has captured operands for execution or consumed them in a
completed computation, backpressure shall preserve the required operands or
completed result. A producer retiring or moving out of an enabled forwarding
stage shall not make that executing consumer lose its value or fall back to
a stale operand. Each operand shall be resolved using the existing
youngest-writer and availability checks; a captured stale value shall not be
treated as ready merely because it is retained. Waiting DE instructions shall
instead use the selectable continuous-resolution or retention policy in
Section 4.2; continuous resolution may temporarily withdraw source readiness
and stall until a correct value becomes available again.

Stalling instruction movement shall not suppress operand capture needed to
preserve an available value while older instructions drain. Such capture
shall preserve the held instruction's identity and shall not issue it again,
repeat a completed operation, or cause an architectural update. An
implementation may retain a completed result instead of duplicating operand
storage when that result is sufficient for subsequent progress. Reset or a
flush of the owning instruction shall invalidate the associated retained
operand/result validity under the existing priority rules. The rule shall
apply to native operands and preserve the already agreed XIF stable-operand
and one-time-issue contracts.

Normal admission of a native instruction from DE into EX shall require every
actually used EX operand to be correctly captured or guaranteed available
through an enabled forwarding path when it enters EX. If either condition
cannot be established for a required operand, the instruction shall remain
in DE. The core shall not admit it into EX merely to wait there for an
operand whose availability is unknown. EX slot readiness and the existing
control/serialization conditions shall also be required.

An available producer result in EX may satisfy this rule through an enabled
MEM-to-EX path when the producer advances to MEM as the consumer enters EX.
This shall preserve adjacent dependent ALU execution without an extra
dependency stall, including when EX-to-DE forwarding is disabled. The
guarantee shall account for actual producer movement, enabled routes, result
validity, and the retention rules above; enabling all paths alone shall not
establish result readiness.

A load still awaiting its successful registered response, or an offload with
an unavailable result, shall not satisfy the guarantee. A dependent native
consumer shall remain in DE until its required value can be supplied under
this rule. Older stages, execution units, and accepted-response handling shall
continue making progress under their existing contracts. Operands consumed
in DE, including branch and XIF sources, shall still require availability at
their DE use point rather than rely on a later EX bypass. Faulting instructions
shall follow the separate exception-containment and fault-metadata progress
rules rather than wait for ordinary computation operands.

Detailed placement/routing of retained load results and physical operand/result
storage remain implementation details. Floating-point and custom memory operand
profiles shall retain their separately specified or open integration requirements.

### 4.1. Core-to-DE operand availability contract

**Status:** Agreed; DE implementation pending

DE shall expose its source-register addresses and use information to the
core-owned hazard/forwarding logic. The core shall resolve the youngest older
writer and supply operand values and availability through the following DE
inputs; DE shall not independently match individual EX/MEM/WB producers.

| Port | Meaning |
| --- | --- |
| `rs0_i[31:0]`, `rs1_i[31:0]`, `rs2_i[31:0]` | Resolved values for the first, second and third source slots. A value is usable in DE only when its corresponding `rs_ready_i` bit is set. |
| `rs_ready_i[2:0]` | Bit n indicates that source slot n contains the correct value now, from storage, an enabled forwarding path, or a correctly retained operand. |
| `rs_ex_guaranteed_i[2:0]` | Bit n indicates that the correct value for source slot n is guaranteed through an enabled EX bypass when this instruction enters EX. This does not validate the current `rsN_i` value. |

Slot numbers are zero-based interface positions: native architectural rs1,
rs2 and rs3 use slots 0, 1 and 2 respectively. The third slot shall retain the
instruction-specific selection already defined for Zfinx and XIF sources.

For each actually used source, DE shall apply its operand-use point:

- A source consumed in DE, including branch comparison, JALR target calculation
  or XIF source delivery, shall require its `rs_ready_i` bit. An EX guarantee
  alone shall not permit that DE action.
- A native source consumed in EX, including integer store data, shall require
  either its `rs_ready_i` bit or its `rs_ex_guaranteed_i` bit before DE-to-EX
  transfer. Unused sources shall not block transfer.

The masks express operand availability only. EX capacity, serialization and
central event arbitration shall still qualify transfer and any redirect or
offload action. Faulting instructions shall retain their existing exception
progress rules without waiting for ordinary computation operands.

For example, consider these adjacent instructions:

```asm
add x3, x1, x2
sub x4, x3, x5
```

With `MUA_FORWARDING = 1`, `MUA_FORWARD_EX_TO_DE = 0` and
`MUA_FORWARD_MEM_TO_EX = 1`, the following transfer shall be possible without
an additional dependency stall, provided the other operands and stages are
ready:

| Cycle | Producer `add` | Consumer `sub` |
| --- | --- | --- |
| T | In EX with a successful result available; able to advance to MEM. | In DE; source slot 0 may have `rs_ready_i[0] = 0` and `rs_ex_guaranteed_i[0] = 1`. |
| T+1 | In MEM with its result retained. | In EX; obtain x3 through MEM-to-EX forwarding. |

The core shall assert a guarantee only when actual producer movement, valid
results and enabled paths establish it for the accepted DE-to-EX transfer.
An unfinished load or offload with an unavailable result shall not establish
such a guarantee. The masks shall be re-evaluated while DE is held.

When transfer relies on a guarantee without current readiness, the parent
shall preserve the source identity and operand-validity/bypass information
with the DE/EX instruction so EX cannot consume the stale DE value. Subsequent
backpressure shall preserve the correct operand or completed result under the
existing retention rules. A guarantee shall not mark stale operand storage as
valid. DE operand retention, when selected, shall be owned by the core's
hazard unit as defined in Section 4.2. Execution/result retention shall remain
with its existing owning pipeline registers or functional unit.

### 4.2. Core-owned hazard unit and selectable DE operand retention

**Status:** Standalone component implemented; core/stage integration pending

The core shall instantiate `uqu_hazard` to centralize source dependency checks,
youngest-writer selection and configured forwarding for both DE and EX. It
shall implement the DE availability contract in Section 4.1 and resolve EX
source values/readiness through the enabled MEM-to-EX and WB-to-EX paths.
It shall consume source addresses/use information, GPR read values, captured
operand values/validity and producer destination, availability and movement
information from the core-owned pipeline slots. Both destinations of paired
XIF results shall participate in hazards, with only the primary destination
forwardable under the existing XIF policy. No separate scoreboard table is
required by this organization.

#### 4.2.1. Consumer stages and control boundaries

One hazard-unit instance shall serve the following stage responsibilities:

| Stage | Hazard/forwarding responsibility |
| --- | --- |
| DE | Resolve used GPR sources from storage and enabled EX/MEM/WB forwarding, optionally retain resolved values, and provide the current-readiness and EX-guarantee masks. DE-consumed branch/JALR/XIF sources shall require current readiness. |
| EX | Resolve used execution sources from correctly captured operands or enabled MEM/WB forwarding; supply operand values and readiness for first execution acceptance. Cover ALU, MUL/DIV and FPU sources, including a configured third source, and integer store data independently of the address ALU's immediate operand. |
| MEM | Supply producer metadata/results to the hazard unit. No late register-operand forwarding into MEM shall be introduced; the effective address and store data shall already be resolved and retained before EX-to-MEM transfer. |
| WB | Supply pending destination, forwardable result and writeback information. Retirement, GPR/CSR updates and commit/result protocol handling shall remain WB/core responsibilities. |

Producer selection shall be relative to the consumer's age. A DE source shall
consider older writers in EX, MEM and WB, in that order of youngest precedence.
An EX source shall consider older writers in MEM and WB, with MEM taking
precedence. The EX instruction shall not forward from itself or depend on a
younger DE instruction. For any unresolved source, an unavailable youngest
matching writer shall block use of an older matching result or stale storage
value. Unused sources shall not block execution, and x0 shall always supply
zero without a producer dependency.

Pipeline-slot validity and destination intent shall be distinct from result
availability and forwarding eligibility. An outstanding load shall remain a
pending writer without making its effective address forwardable as load data.
Faulting or discarded instructions shall not supply usable values; an older
fault shall follow containment/flush sequencing rather than let a dependent
consumer fall back to stale data. CSR and XIF results shall retain their
existing commitment and result-validity qualifications, including the paired
XIF secondary-destination forwarding restriction.

The parent shall carry the EX consumer's source identities/use information
and captured operand validity with DE/EX. If admission relied on an EX
guarantee, the hazard unit shall resolve that source through the promised
enabled path before execution consumes it. Correctly captured operands may
be used directly. If an operand is unavailable, execution shall not accept
stale data; normal DE admission must already have established the guarantee
instead of intentionally moving an unknown operand wait into EX.

The hazard unit shall supply source values, bypass selections as needed,
per-source readiness and dependency-blocking information. The core shall
connect these to stage operand inputs and the existing EX
`operands_ready_i` qualification. ALU operand selection between register,
immediate, PC and zero shall retain its decoded meaning; forwarding a source
shall not overwrite an immediate or PC operand. Local execution tracking shall
ensure that a held instruction does not issue its functional-unit request again
after its operands have been accepted.

Each stage shall retain ownership of its valid/ready handshake, functional-unit
busy state and local progress. A dependency wait shall hold the consumer and
apply backpressure to its predecessors while permitting older instructions
and accepted-response handling to progress. LSU bus waits and downstream
capacity shall not become additional hazard-unit state machines. The central
controller shall retain serialization sequencing, trap/interrupt/debug drains,
redirect arbitration and flush generation; the hazard unit shall consume the
resulting affected-slot invalidation and movement information. Exact wiring
shall avoid combinational cycles between dependency decisions and transfer
qualification.

#### 4.2.2. Selectable DE operand retention

The elaboration-time boolean `MUA_DE_OPERAND_RETENTION` shall select two
implementations behind the same resolved-value and readiness-mask interface:

| Setting | DE source handling |
| --- | --- |
| `0` (default) | Continuously reevaluate storage and enabled forwarding sources each cycle. Allocate no additional DE operand-retention data or validity registers. If a correct value is temporarily unavailable, withdraw readiness and stall the consumer as required by its operand-use point. |
| `1` | Retain each correctly resolved, used DE source in `uqu_hazard`, with per-source validity associated with the current IF/DE instruction. Once retained, keep that value available while the instruction waits. |

For example, a branch `beq x3, x4, target` may wait for a load producing x4
while x3 is available through WB-to-DE forwarding. In continuous mode, once
the x3 producer retires, its value can be read from the GPR file; no extra
capture is needed for correctness. In retention mode, the hazard unit may
capture x3 before WB drains and continue supplying that retained value.

Retention may also bridge an availability gap: with EX-to-DE enabled and
MEM-to-DE disabled, a source can be forwardable in EX, unavailable while its
producer occupies MEM, and available again in WB. Continuous mode shall wait
if the consumer needs that source during the gap; retention mode may avoid
that wait by keeping the previously obtained value. Neither mode may use a
stale value or bypass a younger matching writer.

In retention mode, source capture shall remain possible while DE is stalled.
Current values shall also be usable without an extra capture cycle. A mere
EX-bypass guarantee shall not validate or capture an unavailable current
value. Retained validity shall be cleared on reset and invalidated when the
owning instruction is flushed, transferred out or replaced; a replacement
instruction shall not inherit the previous instruction's retained operands.
Operand data shall not require reset. A third retention slot shall be omitted
when neither enabled Zfinx nor three-source XIF requires it.

The policy shall be independent of the forwarding master/path parameters;
retention shall never enable a disabled forwarding route. Both policies shall
preserve the same architectural behavior and Section 4.1 contract, while
allowing different stall counts and implementation cost. The core shall retain
ownership of the IF/DE and DE/EX boundary registers and global event control;
the hazard unit's optional retention registers are local state associated with
the IF/DE instruction, not a second instruction queue.

This option shall not remove ordinary DE/EX operand storage, retention required
by executing units, or stable-payload requirements of CV-X-IF handshakes. Any
protocol-required XIF holding state shall be implemented even in continuous
mode. Consumer/lifecycle ports are defined in Section 4.2.4; producer bindings
are documented in the [hazard guide](../verif/sim/hazard/README.md).
XIF holding-state placement remains an integration follow-up.
Verification shall exercise both policies, producer movement through disabled
paths, stalled consumers, flush/replacement, youngest-writer conflicts and
the unchanged EX-bypass guarantees. It shall also cover simultaneous DE/EX
consumers, EX MEM-versus-WB priority, unavailable younger matching writers,
store-data forwarding, configured third sources, and preservation of operands
or results while EX is held. The retention parameter shall affect only DE's
optional source storage; EX forwarding and execution-retention obligations
shall apply in both modes.

#### 4.2.3. Normalized producer descriptors

The core shall supply one normalized producer descriptor for each occupied
EX, MEM and WB slot. Descriptors shall use flattened plain-Verilog inputs;
the hazard unit shall not decode native instruction classes or interpret
LSU, CSR or XIF completion protocols to determine whether a result is usable.
The core shall assemble descriptors from parent-owned pipeline metadata and
the owning stage's qualified completion/result outputs.

Each descriptor shall contain the following independent information:

| Field | Width | Meaning |
| --- | --- | --- |
| Slot valid | 1 | The corresponding pipeline slot holds a live instruction. This is occupancy, not a stage's completed-output-valid indication. |
| Pending destinations | 2 | Per-destination potential write intent while the instruction is pending, independent of its eventual writeback pulse or result availability. Native single-destination operations use only destination 0. |
| Destination 0/1 addresses | 5 each | Architectural GPR addresses whose pending writes participate in matching. The parent normalizes optional paired XIF writes into these two destinations. |
| Result available | 1 | The primary destination's actual architectural result is available now, rather than an intermediate execution value. |
| Result forwardable | 1 | Instruction-specific success, permission and commitment conditions permit forwarding the primary result. Forwarding still requires availability and an enabled route. |
| Result data | 32 | The primary destination's architectural value; only usable when both result qualifications hold. |
| Stage advance | 1 | The instruction actually transfers out of its current slot on this edge. EX/MEM advances move the producer to the next stage; WB advances remove the instruction. |

An invalid slot shall not participate in matching. Pending destination enables
shall exclude ignored writes, including x0 and the ignored XIF x0/x1 pair
under the existing paired-result policy. Destination 1 shall remain
non-forwardable; when unused its pending enable shall be zero. Supplying both
addresses explicitly keeps paired-destination normalization in the core and
avoids instruction-specific destination derivation in the hazard unit.

For a pending matching writer, lack of availability, instruction-specific
forwardability or an enabled route shall block an unresolved consumer; it
shall not make the writer disappear from youngest-writer selection. In
particular, pending destination intent shall not be derived solely from the
WB register-file write pulse or any stage's completed-output-valid signal.
Fault containment and affected-slot invalidation shall retain their existing
priority and shall prevent stale fallback while a dependent instruction
remains live.

For example, an outstanding `lw x3, 0(x1)` in MEM shall report a valid slot
and pending primary destination x3, but no available/forwardable load result.
Its effective address shall not qualify as result data. After a successful
response is registered, the normalized descriptor may advertise the selected
and extended load value under the existing load-forwarding rule. A failed
response shall produce no forwardable result. Similarly, the core shall
withhold CSR and XIF result qualifications until their documented WB
conditions hold.

Stage-advance information shall describe actual movement rather than raw
downstream readiness. Together with available/forwardable results and the
configured routes, it shall support the EX-entry guarantees in Section 4.1.
No additional producer table or result storage is implied by the descriptors;
the pipeline slots remain their source of identity and age. Producer inputs
use stage-prefixed `pending_i`, `rd0_i`, `rd1_i`, `result_available_i`,
`result_forwardable_i`, `result_i` and `advance_i`, with `ex_valid_i`,
`mem_valid_i` and `wb_valid_i` identifying occupancy. The EX validity input is
shared between the producer and consumer roles. The
[hazard guide](../verif/sim/hazard/README.md) defines exact names and behavior;
consumer and lifecycle bindings are defined in Section 4.2.4.

#### 4.2.4. Consumer ports, readiness and retained-operand lifecycle

The hazard unit shall use three explicitly named source slots for each DE
and EX consumer, with zero-based slot numbering as in Section 4.1. Consumer
inputs shall use the following flattened plain-Verilog bindings:

| Input port(s) | Width each | Meaning |
| --- | --- | --- |
| `clk_i`, `rst_ni` | 1 | Core clock and synchronous active-low reset for optional retention validity. Retained data shall not require reset. |
| `de_valid_i` | 1 | The current IF/DE instruction is valid. |
| `de_clear_i` | 1 | Invalidate retention associated with the current DE instruction at the active edge. The core asserts this for transfer out, flush or replacement of that instruction. |
| `de_rs0_addr_i`, `de_rs1_addr_i`, `de_rs2_addr_i` | 5 | Architectural addresses of the DE source slots. |
| `de_rs0_i`, `de_rs1_i`, `de_rs2_i` | 32 | GPR read values for those slots, before hazard-unit forwarding/optional retention selection. |
| `de_rs_used_i` | 3 | Bit n identifies a source actually used by the DE instruction. |
| `de_rs_need_now_i` | 3 | Subset of the used-source mask identifying sources consumed in DE; other used native sources may rely on an EX guarantee. |
| `ex_valid_i` | 1 | The DE/EX instruction is valid; it is also the instruction described by the EX producer descriptor. |
| `ex_rs0_addr_i`, `ex_rs1_addr_i`, `ex_rs2_addr_i` | 5 | Architectural addresses retained with the EX consumer. |
| `ex_rs0_i`, `ex_rs1_i`, `ex_rs2_i` | 32 | Source values carried with DE/EX. A value is already resolved only when its captured-valid bit is set. |
| `ex_rs_used_i` | 3 | Bit n identifies a source actually used by the EX instruction. |
| `ex_rs_captured_i` | 3 | Bit n identifies a correctly captured EX source value; an earlier EX guarantee alone shall not set it. |

The source values and per-source availability outputs shall be:

| Output port(s) | Width each | Meaning |
| --- | --- | --- |
| `de_rs0_o`, `de_rs1_o`, `de_rs2_o` | 32 | Resolved DE source values, connected to the corresponding DE operand inputs in Section 4.1. |
| `de_rs_ready_o` | 3 | Current readiness, connected to DE's `rs_ready_i`. |
| `de_rs_ex_guaranteed_o` | 3 | EX-entry guarantees, connected to DE's `rs_ex_guaranteed_i`. |
| `ex_rs0_o`, `ex_rs1_o`, `ex_rs2_o` | 32 | Resolved EX source values for execution and store-data operand selection. |
| `ex_rs_ready_o` | 3 | Current readiness for EX consumption. |

Readiness shall be per source so branches, XIF source delivery and execution
can apply their own actual use requirements. For DE, every used source marked
need-now shall require current readiness; every other used native source shall
require current readiness or an EX guarantee. EX shall require current
readiness for each source it is about to consume. Unused slots shall not
block progress. Source data without corresponding readiness shall not be
consumed as valid data.

There shall be no general `stall_o` output that controls pipeline movement.
DE and EX shall combine operand availability with local execution conditions;
the core shall qualify transfers with downstream capacity and global control.
Dependency blocking shall therefore remain distinguishable from a stage's
other reasons for waiting. Per-source masks shall not be collapsed into a
single readiness bit before consumers have applied their source-use rules.

When DE retention is enabled, reset shall clear retained validity. Otherwise,
`de_clear_i` or an invalid DE slot shall invalidate the retained operands at
the active edge, taking priority over source capture. Only a valid, uncleared
held instruction may capture newly available used sources; an already retained
correct value shall remain unchanged. When the old instruction transfers and
a replacement arrives on the same edge, clear shall prevent the replacement
from inheriting any old operand validity. The new instruction shall still be
able to use live resolved values without waiting for a capture cycle.

`de_clear_i` shall be a retention-state update condition, not a combinational
operand-output disable. In particular, asserting it for a successful transfer
shall not suppress the current instruction's values or readiness before the
edge. The controller shall separately prevent actions by flushed instructions
and qualify live-slot validity. This separation shall avoid a feedback loop
between readiness, transfer and clearing retained state.

The hazard unit shall contain no additional EX source-retention bank. Existing
parent-owned pipeline storage and functional-unit acceptance/result state shall
preserve EX operands or completed results as required by Section 4.2.1. With
DE retention disabled, retention-specific capture/clear logic and state shall
be omitted; forwarding/readiness behavior and all protocol-required XIF
holding obligations shall remain in force.

#### 4.2.5. Standalone implementation and verification

`src/uquintus/uqu_hazard.v` implements these contracts in plain Verilog with
the shared component runner and `config/sim/hazard.yml`. Its
[component guide](../verif/sim/hazard/README.md) defines source-slot behavior,
normalized producer ports, retention lifecycle and regression commands.
Unavailable/unused source outputs are deterministic zero; used x0 is ready
with value zero, and RV32E-invalid source addresses remain unavailable without
aliasing. The core remains responsible for converting illegal-register cases
and native faults into their appropriate exception/control paths.

EX guarantees are emitted only when a used source is not currently ready and
is not needed in DE. An EX producer must advance to MEM with a qualified result
and MEM-to-EX enabled. A MEM producer may stay in MEM with MEM-to-EX enabled,
or advance to WB with WB-to-EX enabled. WB already supplies current operands
through the master-controlled WB-to-DE path; `wb_advance_i` is retained for
descriptor uniformity without additional guarantee logic. No guarantee
establishes current operand validity or replaces downstream capacity checks.

The component regression checks all sixteen combinations of the four
independent forwarding-path controls in both retention modes, plus the master
disabled and RV32E/Zfinx/two-/three-source paired-XIF profiles. The initial
forty-profile sweep passes all 160 directed, guarantee, lifecycle and
randomized suites. The independent model evaluates ordered producer
transactions and predicted movement; tests include both sides of retention
clock edges and the promised producer-to-EX-consumer transitions.

Yosys optimization retains no storage in continuous mode, 66 bits with two
retained sources or 99 bits with three. No latches are inferred. These counts
measure generic optimized state rather than mapped ASIC PPA. Unsupported
parameter settings fail elaboration through an unresolved configuration-guard
cell. Parent pipeline wiring, the DE stage, central controller sequencing and
XIF issue/holding-state integration remain pending.

## 5. Configurable branch prediction

**Status:** Agreed

Branch prediction shall be optional. The RTL parameter `MUA_BRANCH_PREDICTOR`
shall select whether prediction is enabled and which predictor implementation
is used, at elaboration/synthesis time.

The default prediction mode shall be `none`. This means no branch prediction:
once decode recognizes an unresolved conditional branch or jump, the core shall pause
issuing further instruction fetch requests until the branch resolves. Fetching
shall then proceed along the resolved control flow.

Continuing sequentially past an unresolved branch is static prediction, named
`static_not_taken`, and shall be treated as a distinct predictor choice rather
than as prediction being disabled. In this mode, a taken branch requires
discarding younger instructions on the sequential path.

Even in `none` mode, an instruction fetch may already have been accepted before
decode recognizes the branch. The frontend shall continue to handle its response
and retain its data until consumed or invalidated. An accepted redirect shall
discard buffered old-path data and drain any old transaction as in Section 15.5.

All settings shall preserve the behavior required by the configured ISA.
Misprediction recovery shall redirect instruction fetch and prevent discarded
instructions from changing architectural state. With prediction disabled, the
pipeline shall still handle control hazards correctly.

The two baseline modes are implemented in Section 15.5. Additional predictor
implementations, interfaces and encodings remain TBD. Branch and jump resolution
in decode is defined in [architecture, Section 6](uqu_spec.arch.md#6-resolve-branches-and-jumps-in-decode).

Prediction and resolution are distinct: a BTB-based implementation can predict
a target in the fetch frontend and verify it later when the branch resolves.
Early resolution is therefore not a prerequisite for early target prediction.
See [CVA6 PC generation](https://docs.openhwfoundation.org/projects/cva6-user-manual/03_cva6_design/pcgen_stage.html)
for an example of frontend prediction and later correction.

## 6. Resolve branches and jumps in decode

**Status:** Agreed

Conditional branch target calculation and condition comparison shall both occur
in the decode stage (ID, also referred to as DE). Decode shall contain branch
comparison logic and target-address arithmetic separate from the main EX ALU.

A conditional branch shall resolve in decode once its operands are available
and pipeline control permits it. Hazard handling shall stall decode when a
required operand is unavailable, including when forwarding is disabled.
EX-to-DE and MEM-to-DE forwarding shall follow their independent path controls
in [architecture, Section 4](uqu_spec.arch.md#4-configurable-operand-forwarding); WB-to-DE shall remain available when the forwarding master
switch is enabled. Disabling an earlier path shall make the branch wait for
the required producer value at a later enabled source.

`JAL` and `JALR` shall also resolve in decode. `JAL` uses a PC-relative target;
`JALR` uses `rs1 + immediate`, with the least significant target bit cleared as
required by the ISA. Jump resolution shall follow the same configurable
forwarding and hazard-stall policy as conditional branches. In particular,
`JALR` shall wait when its source register value is not yet available through
the register file or an enabled forwarding path.

A surviving, nonfaulting conditional branch, `JAL`, or `JALR` shall finalize
its DE resolution only when all required operands are ready and the
instruction can make its accepted DE-to-EX transfer. Any required DE
resolution redirect shall be accepted in that same transfer cycle, subject
to central event arbitration and older-instruction fault priority. The
comparison and target logic may evaluate earlier, but shall not redirect
fetch while the instruction remains held in DE. If EX cannot accept the
instruction, DE shall wait, retaining required operand values under [architecture, Section 4](uqu_spec.arch.md#4-configurable-operand-forwarding). On transfer, resolution and any required redirect shall occur once.
No early-redirect bookkeeping shall be required for a branch held in DE.

A fault detected for the instruction shall instead follow the existing early
containment and WB trap-entry rules, without a normal branch redirect. This
DE resolution rule shall preserve optional earlier frontend predictions and
the separate WB trap/return and debug event contracts. It shall not change
the XIF rule that remembers an issue already accepted while its instruction
remains held in DE.

Optional frontend prediction may steer instruction fetch before decode resolves
the branch. Decode resolution shall check any prediction and request correction
when necessary. Discarded instructions shall not change architectural state.

The decode logic's timing shall be evaluated during implementation; no fixed
branch penalty or clock frequency is assumed. Detailed redirect timing, pending
instruction-fetch tracking, and detailed hazard-controller wiring remain
implementation follow-ups; the agreed stall, forwarding, and request-persistence
rules shall remain applicable. Behavior with
prediction disabled is defined by `none` mode in [architecture, Section 5](uqu_spec.arch.md#5-configurable-branch-prediction).


### 6.1. Branch resolution component

`src/uquintus/uqu_branch.v` is the stateless branch/target component owned by
the DE stage. Its [guide](../verif/sim/branch/README.md) defines the
normalized interface and tests. Decoder branch kind/funct3/immediate connect
directly; PC/original length and available source values come from the parent.
The unit implements all six branch comparisons, PC-relative branch/JAL targets,
JALR target formation with bit-zero clearing, and original-length jump links.
All address arithmetic wraps at 32 bits. ISA_C selects IALIGN and permits a
two-byte original-length flag; a 32-bit instruction still increments by four.

Target alignment is checked only for a taken, non-illegal control transfer.
The resolved target remains visible for diagnostic tval even when misaligned,
while successful next-PC/link candidates are suppressed. Reserved conditional
funct3 and compressed-length metadata with C disabled report illegal control.
The enclosing DE stage creates the precise exception metadata and coordinates
its WB handling; the unit generates no architectural event or write itself.

One magnitude comparison serves signed/unsigned conditions, and separate target
and link/fallthrough addition paths avoid borrowing the concurrently active EX
ALU. No clock, pipeline state, predictor or BTB belongs to this component.
Prediction/target buffers belong in the IF frontend and feed carried prediction
metadata; DE/core owns comparison with actual next PC and accepted recovery.
Combinational outputs may remain asserted while DE waits, so transfer and
redirect qualification remain in the parent/stage controller as specified above.

The component regression includes a direct instance and a decoder-fed sibling,
with C disabled/enabled, negative offsets, signed boundaries, PC wraparound,
JALR alignment and two-/four-byte links. Synthesis checks retain no storage.

## 7. Trap on misaligned data accesses

**Status:** Agreed

The baseline shall require naturally aligned loads and stores. The effective
address shall be checked before issuing any `dmem` request for the instruction.

| Access size | Natural alignment |
| --- | --- |
| 8 bits | Any byte address. |
| 16 bits | Address divisible by 2. |
| 32 bits | Address divisible by 4. |

A misaligned load shall raise a load-address-misaligned exception. A misaligned
store shall raise a store-address-misaligned exception. Neither shall issue a
data-memory request, and a misaligned store shall not perform any partial write.
The baseline shall not split misaligned accesses into multiple transactions.
Zfinx software shall transfer floating-point bit patterns through ordinary
integer loads and stores, which follow this same alignment policy. Separate
F-extension loads and stores remain deferred with full F support.

For a native load or store, an address-misaligned exception shall take priority
over an access fault from a PMP permission denial on the same instruction.
The core may reject the misaligned effective address without evaluating PMP
permissions. No bus request shall be asserted for that instruction, and trap
metadata shall retain its original effective byte address. This priority
choice shall not override an older instruction's fault or the applicable
ISA priority of other exceptions. It is permitted by the
[RISC-V synchronous exception priority rules](https://docs.riscv.org/reference/isa/priv/machine.html).

The execution environment may provide software emulation; it is outside the
core. Precise exception handling is defined in [architecture, Section 9](uqu_spec.arch.md#9-precise-synchronous-exceptions); remaining detailed
trap delivery and other implementation-defined exception priorities remain TBD.

The ISA permits this policy; see the
[RV32I load/store specification](https://docs.riscv.org/reference/isa/v20260120/unpriv/rv32.html#_load_and_store_instructions).

## 8. Bare-metal execution with configurable user mode

**Status:** Agreed

The core shall always support machine mode for bare-metal software. The `ISA_UMODE` RTL
parameter shall select user-mode support at elaboration/synthesis time:

| `ISA_UMODE` | Privilege modes |
| --- | --- |
| `0` | Machine mode only. |
| `1` (default) | Machine and user modes. |

The default configuration shall support both M-mode and U-mode. Mandatory
machine-mode support is independent of the `ISA_M` parameter that selects integer
multiplication and division. Supervisor mode and page-based virtual memory are
outside the initial scope; the initial design shall use physical addressing.

M-mode shall provide privileged system control and trap handling. U-mode shall
restrict access to privileged instructions and control/status registers as
required by the selected privileged ISA version when `ISA_UMODE = 1`. With no supervisor
mode, traps from U-mode shall be handled in M-mode. With `ISA_UMODE = 1`, the core shall
support entering U-mode and returning from traps through the standard M-mode
mechanisms. CSR behavior and advertised privilege support shall match the selected
configuration.

`MRET` shall serialize execution and perform its architectural state updates
and return redirect in WB, as defined in [architecture, Section 18.1](uqu_spec.arch.md#181-serialized-mret-at-wb).

The following `mstatus` field reset values shall apply under [interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset):

| Field | Reset value | Meaning |
| --- | --- | --- |
| `MIE` | `0` | Machine interrupts disabled. |
| `MPIE` | `0` | Saved machine interrupt-enable state cleared. |
| `MPP` | M-mode (`2'b11`) | Initial return-privilege state is M-mode. |
| `MPRV` | `0` | Explicit data accesses use the current privilege mode. |
| `TW` | `0` | User-mode WFI interception initially disabled ([architecture, Section 11](uqu_spec.arch.md#11-wfi-as-a-no-op)). |
| `FS`, with `ISA_ZFINX = 1` | Off (`2'b00`), hardwired | Zfinx instructions and FP CSR accesses are not gated by FS. |
| `FS`, without floating-point support | Off (`2'b00`), hardwired | No implemented floating-point state. |

`mstatus.MPP` shall use the following WARL behavior on otherwise permitted
software writes:

| Configuration | Written MPP | Stored/read-back MPP |
| --- | --- | --- |
| `ISA_UMODE = 1` | U (`2'b00`) | U (`2'b00`) |
| `ISA_UMODE = 1` | M (`2'b11`) | M (`2'b11`) |
| `ISA_UMODE = 1` | Unsupported S/reserved (`2'b01` or `2'b10`) | M (`2'b11`) |
| `ISA_UMODE = 0` | Any value | M (`2'b11`), hardwired |

Unsupported written MPP values shall not themselves raise an exception, and
the mapping shall not depend on the previous MPP value. Normal CSR access
checks shall remain applicable. Trap entry and `MRET` shall retain their
architectural privilege-state updates; the software-write mapping shall not
prevent trap entry from recording U-mode or `MRET` from setting MPP to the
least-privileged supported mode in an M+U configuration ([architecture, Section 18.1](uqu_spec.arch.md#181-serialized-mret-at-wb)).

With `ISA_ZFINX = 1`, `fcsr` shall reset to `32'h00000000`:
`frm = 3'b000` (round to nearest, ties to even) and `fflags = 5'b00000`
(no accrued exceptions). The `frm` and `fflags` CSR aliases shall reflect the
same state. `mstatus.FS` shall remain hardwired to Off and shall not cause Zfinx
instructions or otherwise permitted `fcsr`, `frm`, or `fflags` accesses to trap.
Normal CSR privilege/access checks shall still apply. See the
[Zfinx privileged-architecture rules](https://docs.riscv.org/reference/isa/v20260120/unpriv/zfinx.html).

Zfinx shall add no separate floating-point registers and shall not require
initializing integer registers to `+0.0`. Integer register storage shall retain
the minimal-reset policy in [interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset), with `x0` hardwired to zero. Earlier
requirements for reset FS = Initial and zero-initialized `f0`–`f31` apply only
to the deferred full-F design intent (D-185 through D-187); they shall not
apply to Zfinx. Any future implementation of full F shall revisit that profile.

PMP shall be selected through `ISA_PMP`, defaulting to `0`, and follow the
internal structure defined in [architecture, Section 8.1](uqu_spec.arch.md#81-internal-pmp-and-memory-fault-boundary); its enabled profile is described there, while full-core integration remains
pending. Other memory protection
features remain future design choices. U-mode support alone shall not be
described as providing memory isolation without an implemented protection
mechanism.

The privileged ISA baseline is fixed in [architecture, Section 1](uqu_spec.arch.md#1-fixed-32-bit-architecture). CSR behavior, trap
delivery, reset values, and PMP follow the topic requirements below; remaining
CSR field mappings and internal sequencing are implementation follow-ups.
The reset contract is defined in [interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset).
Precise synchronous exception behavior is defined in [architecture, Section 9](uqu_spec.arch.md#9-precise-synchronous-exceptions).
The agreed machine interrupt inputs are defined in [interfaces, Section 4](uqu_spec.interfaces.md#4-external-machine-interrupt-sources).

### 8.1. Internal PMP and memory-fault boundary

**Status:** Internal placement, bus boundary, disabled default, fixed sixteen-entry
capacity, four-byte granularity, all standard address modes, zeroed
configuration bytes and unreset address registers, and zero-valued disabled PMP CSRs agreed;
remaining enabled profile and implementation milestone TBD

PMP shall be a core-internal feature. Its configuration CSRs, effective-privilege
evaluation, and permission checks shall reside within the core. The external
memory interfaces shall not require privilege attributes, PMP rules, or PMP
status to perform these checks on the core's behalf.

The CSR module shall own PMP configuration/address storage and CSR update
semantics under [architecture, Section 18](uqu_spec.arch.md#18-native-csr-instruction-execution).
The pipeline-stage parent, at core scope, shall own one stateless `uqu_pmp`
block. It shall connect CSR-owned PMP state to this block once and route IF and
MEM request addresses/control into its two independent check ports. Each stage
shall consume its corresponding permission result before presenting a memory
request. Neither stage nor the PMP block shall duplicate architectural PMP
storage.

The PMP block shall decode the sixteen regions' bounds/masks once and share
them between independent IF and MEM comparison, priority, and permission logic.
Both checks shall be combinational and concurrent, without arbitration,
request handshakes, or coupling between the requesters. IF/MEM shall not each
instantiate a complete PMP block.

The standalone checker is implemented in `src/uquintus/uqu_pmp.v`. Its packed
inputs carry sixteen eight-bit configuration entries and sixteen 32-bit address
entries, with entry zero in the least significant bits. The IF port consumes
`if_addr_i`, `if_size_i` (log2 bytes), and `if_priv_m_i`, and checks execution
permission implicitly. The MEM port consumes `mem_addr_i`, `mem_size_i`,
`mem_access_i` (R/W/X requirement mask), and `mem_priv_m_i`. Byte addresses and
byte/halfword/word sizes describe the original accesses before bus alignment.
The block produces `if_allow_o` and `mem_allow_o`; each stage qualifies its
result with a live access and generates the appropriate access-fault metadata.
In MEM, `!mem_allow_o` shall feed the LSU's
`req_access_fault_i` before native request acceptance. It shall not replace the
independent precise-effect `request_permit_i` input.

Effective-privilege selection remains outside the checker: IF uses current
execution privilege, while MEM accounts for `MPRV`/`MPP`. CSR write legalization,
lock enforcement on CSR writes (including the preceding TOR bound), and reset
remain CSR-unit responsibilities. The checker uses `L` only to determine whether
matching permissions also constrain M-mode accesses. Full IF/MEM/CSR integration
remains implementation work; standalone checker availability does not establish
complete architectural PMP support. The [PMP component guide](../verif/sim/pmp/README.md)
defines the ports, permission rules, and component regressions.

The elaboration-time parameter `ISA_PMP` shall enable this feature and default
to `0`. With `ISA_PMP = 0`, PMP permission-checking and writable PMP-entry
storage shall be excluded at elaboration or eliminated by synthesis; PMP shall
not deny memory accesses in that configuration. Other core access checks and
external bus-error handling shall remain applicable. With `ISA_PMP = 1`, the
core shall provide the selected PMP CSR and permission-checking profile. Every
hardware YAML configuration shall explicitly set `ISA_PMP`.

With `ISA_PMP = 1`, the core shall implement exactly sixteen configurable PMP
entries, numbered zero through fifteen, preserving the standard priority order.
Their configuration bytes shall occupy RV32 `pmpcfg0` through `pmpcfg3`, with
address state in `pmpaddr0` through `pmpaddr15`. All sixteen entries shall
provide the address modes and permissions specified below.

PMP capacity shall be fixed rather than an external configuration choice.
No external region-count parameter shall appear in the RTL parameter
catalog or shared hardware configuration schema. The optional `ISA_PMP` enable shall remain unchanged. With it
disabled, no writable PMP-entry storage shall be required and the existing
constant-zero CSR behavior shall remain applicable.

When PMP is enabled, its granularity shall be fixed at `G = 0`, corresponding
to `2^(G + 2) = 4` bytes under the standard PMP encoding. All configured
entries shall use this granularity. No externally configurable granularity
parameter is required.

Every configured PMP entry shall support all four standard address-mode
encodings in its `pmpcfg.A` field:

| `A` | Mode | Address matching |
| --- | --- | --- |
| `0` | OFF | Disable address matching for this entry. |
| `1` | TOR | Match a range whose lower bound comes from the preceding PMP address register and whose exclusive upper bound comes from this entry; entry zero uses a lower bound of zero. |
| `2` | NA4 | Match one naturally aligned four-byte region. |
| `3` | NAPOT | Match a naturally aligned power-of-two region of at least eight bytes. |

The standard PMP address encoding and range rules shall apply, as defined in
the [RISC-V machine-level specification](https://docs.riscv.org/reference/isa/priv/machine.html).
Address-mode support shall not require separate hardware configuration
parameters.

With `ISA_PMP = 1`, the core reset defined in [interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset) shall clear every
implemented PMP configuration byte to zero. Each entry shall therefore start
with `A = OFF`, `L = 0`, and `R = W = X = 0`. Reset shall also clear any
previously set lock bits. The `pmpaddr*` storage shall not be reset and shall
have no guaranteed reset value. Firmware shall initialize every address bound
used by an entry before enabling that entry. For TOR, this includes the
preceding address register supplying the lower bound, even if the preceding
entry is OFF; entry zero instead has an implicit lower bound of zero.
Verification shall not assume zero-valued address registers after reset.

With `ISA_PMP = 0`, the standard `pmpcfg*` and `pmpaddr*` CSRs shall remain
accessible to M-mode as constant-zero registers. Reads shall return zero and
otherwise permitted writes shall be ignored without allocating writable entry
storage. Their fields shall behave as constant WARL-zero fields at their
normal read-write CSR addresses; writes shall not trap solely because PMP is
disabled. Normal privilege checks shall still apply, so U-mode accesses shall
raise illegal-instruction exceptions. These native CSR instructions shall
follow the uniform serialization policy in [architecture, Section 18](uqu_spec.arch.md#18-native-csr-instruction-execution).

When PMP is implemented, instruction fetches and LSU accesses shall undergo
the applicable permission checks before an external request is issued. The
checks shall use the access address, size, type, and effective privilege under
the selected privileged ISA. Data accesses shall account for applicable
`mstatus.MPRV`/`MPP` semantics; instruction fetch privilege shall follow the
current execution mode. See the
[RISC-V machine-level specification](https://docs.riscv.org/reference/isa/priv/machine.html).

A denied access shall produce a local instruction/load/store access fault
under the precise-exception rules, without issuing the denied bus access,
creating an outstanding bus transaction, or waiting for an external response.
Speculative fetch fault indications shall follow the buffered fault and flush
rules in [architecture, Section 15](uqu_spec.arch.md#15-aligned-instruction-fetch-and-internal-assembly).

The core shall remain the producer of external memory requests and consumer
of external completion/error responses. A bus error shall be handled as an
access failure reported by the memory system; it shall not substitute for the
core's internal PMP check. Internally detected faults shall remain effective
when bus-side error reporting is absent and the error inputs are tied low.

Custom shared-LSU access shall be deferred under [interfaces, Section 5.1](uqu_spec.interfaces.md#51-initial-standard-only-scope-and-deferred-memory-features). Any future
integration of such accesses shall preserve the same internal permission
checks. Protection of an independently connected coprocessor memory path
shall be a system-integration responsibility outside this initial profile.
The checker follows the standard lowest-numbered any-byte match rule. That
entry must cover the entire access; partial coverage fails even in M-mode with
`L = 0`, without falling back to another entry. A complete match allows M-mode
when unlocked; otherwise all requested permission bits must be set. An unmatched
access succeeds in M-mode and fails in U-mode when PMP is enabled, including
when all entries are OFF. `ISA_PMP = 0` instead permits every access through
the checker and removes its checking logic at elaboration.

The initial PMP CSR field implementation is defined in Section 18.2; its
full-core integration milestone remains pending.

## 9. Precise synchronous exceptions

**Status:** Agreed

Ordinary synchronous instruction exceptions shall be precise. Before entering
the trap handler, all older instructions shall have completed without an
exception. The faulting instruction shall commit no ordinary architectural
result, and younger instructions shall be discarded without architectural
effects. Trap-entry updates to privileged state are required and are distinct
from ordinary instruction results.

The initial standard-only XIF profile shall defer coprocessor-generated
execution traps and the earlier multi-access custom partial-effects-on-trap
policy ([interfaces, Section 5.1](uqu_spec.interfaces.md#51-initial-standard-only-scope-and-deferred-memory-features)). That deferred policy shall not relax the baseline
precise-exception rules. Native instruction behavior and external bus-error
guarantees shall remain governed by their existing contracts.

If multiple in-flight instructions encounter exceptions, the oldest faulting
instruction shall take priority. An exception detected in an earlier pipeline
stage shall not bypass an older instruction whose exception status is unresolved.
Exceptions detected on a discarded execution path shall not be taken.

For synchronous exceptions handled in M-mode, `mepc` shall identify the faulting
instruction and `mcause` shall record the cause. Trap entry shall update the
other required privileged state and redirect execution according to the selected
privileged ISA. Detection shall remain local to the appropriate stage; the
core shall contain the exception immediately and finalize architectural
synchronous trap entry at WB as defined in [architecture, Section 9.2](uqu_spec.arch.md#92-early-exception-containment-and-wb-trap-entry). See the
[RISC-V machine-level specification](https://docs.riscv.org/reference/isa/priv/machine.html).

External bus-error side effects require a separate memory-interface contract.
Precise exception reporting shall not imply that the core can undo an external
write or device side effect. The OBI error-response guarantees, treatment of
already accepted transactions, and any separate asynchronous bus-error reporting
remain TBD. The agreed pre-request rejection of misaligned accesses in [architecture, Section 7](uqu_spec.arch.md#7-trap-on-misaligned-data-accesses) is unchanged.

### 9.1. Informative machine trap value

**Status:** Agreed

Trap entry shall write informative values to the 32-bit `mtval` CSR for
address-misalignment, access-fault, and illegal-instruction exceptions:

| Exception | Value written to `mtval` |
| --- | --- |
| Instruction address misaligned | The instruction target address that violates the configured instruction alignment. |
| Instruction access fault | The address of the faulting portion of the instruction, retaining its byte offset within the aligned instruction-fetch word. |
| Load or store address misaligned | The effective byte address of the attempted data access. |
| Load or store access fault | The effective byte address of the faulting native data access. |
| Illegal instruction | The original faulting instruction bits, right-justified with unused upper bits cleared, subject to the ISA's instruction-length limit for this value. |

For example, with `ISA_C = 1`, if a 32-bit instruction starts at `0x1002` and the
fetch of its second halfword at `0x1004` fails, `mepc` shall contain `0x1002`
and `mtval` shall contain `0x1004`. If the fetch containing its first halfword
fails instead, `mtval` shall contain `0x1002`, although the bus request address
was word-aligned to `0x1000`.

For an illegal 16-bit instruction when `ISA_C = 1`, `mtval` shall contain the
original 16-bit encoding zero-extended to 32 bits, rather than a decompressed
replacement. For a 32-bit instruction it shall contain the original 32-bit
encoding. Unsupported longer instruction encodings shall follow the ISA's
rule to report the shortest of the actual instruction length, ILEN, and XLEN.
This diagnostic policy shall not imply support for executing longer
instructions.

For the baseline's other traps, including interrupts, environment calls, and
`EBREAK` breakpoint exceptions, trap entry shall write zero to `mtval`.
Future extensions that define additional trap-value semantics shall specify
their behavior separately. Outside trap entry, only an explicit CSR write
shall change `mtval`, apart from reset under the documented reset contract.

Fault information shall remain associated with its instruction until trap
arbitration. Discarded instructions and fetches shall not update `mtval`.
These rules follow the
[RISC-V machine-level specification](https://docs.riscv.org/reference/isa/priv/machine.html);
custom-operation memory fault details remain subject to [interfaces, Section 5](uqu_spec.interfaces.md#5-cv-x-if-custom-extension-interface).

### 9.2. Early exception containment and WB trap entry

**Status:** Agreed; exact event interfaces and request-permission timing TBD

Once a synchronous exception is recognized for a live instruction, the central
controller shall establish a pending-exception barrier at that instruction.
Younger instructions shall immediately be blocked from normal issue or
discarded; affected younger arithmetic operations shall be canceled under
[architecture, Section 3.1](uqu_spec.arch.md#31-common-native-execution-unit-handshake). New fetch requests and younger-instruction admission shall stop
while the barrier remains active. Older instructions shall continue to execute,
complete memory work, and retire under their normal readiness rules. The
barrier shall not impose a blanket stall on older EX/MEM/WB instructions.

For an instruction still held in DE, this barrier shall remain subject to
interrupt-first arbitration at the EX-entry boundary in [interfaces, Section 4](uqu_spec.interfaces.md#4-external-machine-interrupt-sources). A
recognized DE exception shall not block an eligible interrupt from starting
or completing its drain. If interrupt entry discards the DE instruction, its
exception metadata and barrier shall also be discarded; it shall be fetched
again at the saved PC after return. An exception token already in EX/MEM/WB
shall retain priority over interrupt entry under the rules below.

The faulting instruction shall carry valid exception metadata, including its
PC, selected cause, and required trap-value information, through the remaining
pipeline stages to WB. It shall perform no further ordinary execution or
side-effecting work: no normal register/CSR write, new data-memory request, or
new offload shall be generated for the exception-marked instruction. Already
accepted memory transactions shall still receive their required completion
handling. Exception metadata shall remain associated with its instruction
during stalls, and the marked instruction shall be allowed to advance as
older stages drain.

For an ECALL recognized in DE, instructions already in EX/MEM/WB are older and
shall finish. Younger instructions shall not follow the ECALL into normal
execution. For a fault recognized in MEM, younger EX/DE/IF work shall be
discarded or prevented from progressing immediately, rather than waiting for
the fault to reach WB.

At WB, once all older instructions have completed successfully, the faulting
instruction shall cause one trap-entry event. The controller shall coordinate
the required privileged-state updates and handler redirect using the recorded
metadata. The faulting instruction shall not retire normally or increment
`minstret`. A younger fault shall never override an older fault. An older
redirect or exception that discards a pending faulting instruction shall also
discard its metadata and barrier. Buffered speculative fetch errors shall not
activate this policy merely because a bus response reports an error; their
association with live instructions and wrong-path removal shall follow
[architecture, Section 15](uqu_spec.arch.md#15-aligned-instruction-fetch-and-internal-assembly).

Before asserting a new `dmem` request, the core shall ensure that every older
instruction has either completed successfully or is proven unable to raise a
subsequent synchronous exception. A younger MEM instruction shall wait if an
older WB instruction still has unresolved fault status, including an offloaded
instruction awaiting required completion. A known older exception shall block
the request immediately, including on the cycle the exception becomes known.
An older instruction's successful resolution may permit the younger request
in that same cycle when the interface timing requirements are met; retirement
alone shall not be required for an instruction already proven fault-free.

This permission gate shall cover both reads and writes, since a data read may
access a device with side effects. It shall be based on instruction age: a
younger pending fault shall not prevent an older memory instruction from
finishing. The core shall prevent unsafe requests before external acceptance;
a later flush shall not be treated as a way to undo an accepted store or
device access. Error-side-effect guarantees for the faulting transaction itself
remain subject to the memory-system contract in [architecture, Section 9](uqu_spec.arch.md#9-precise-synchronous-exceptions).

Any future custom shared-LSU accesses shall preserve the same permission gate;
that feature shall be deferred under [interfaces, Section 5.1](uqu_spec.interfaces.md#51-initial-standard-only-scope-and-deferred-memory-features). Independently connected
coprocessor memory paths shall preserve equivalent protection against effects
from younger or killed instructions through their system-integration contract,
without additional core/CV-X-IF signals. Speculative custom computation may
continue under the existing standard commit/kill rules.

Verification shall cover early ECALL/illegal-instruction containment, a MEM
fault with younger EX work, older WB fault resolution while a younger memory
instruction waits, stores and side-effecting reads, and removal of wrong-path
exception metadata without trap entry.

## 10. Direct and vectored trap dispatch

**Status:** Agreed

The machine trap-vector CSR `mtvec` shall support both standard modes:

| `mtvec.MODE` | Mode | Synchronous exception entry | Interrupt entry |
| --- | --- | --- | --- |
| `0` | Direct | `BASE` | `BASE` |
| `1` | Vectored | `BASE` | `BASE + 4 * cause` |

Here, `cause` is the interrupt cause number, excluding the interrupt flag in
`mcause`. Vectored entries are spaced four bytes apart, including when the C
extension is enabled. Both modes shall support every four-byte-aligned 32-bit
BASE address: all BASE bits (`mtvec[31:2]`) shall be writable, with no additional
Vectored-mode alignment restriction. The implementation shall compute the full
`BASE + 4 * cause` interrupt target rather than constrain BASE to simplify the
target calculation. This support does not add interrupt sources beyond those
specified in [interfaces, Section 4](uqu_spec.interfaces.md#4-external-machine-interrupt-sources).

`mtvec` shall reset to `32'h00000000`: Direct mode with BASE zero, independently
of the reset entry address input. Firmware shall install its desired trap-vector
address before enabling interrupts. Synchronous exceptions occurring before
that initialization shall enter at address zero.

For an otherwise permitted CSR write, MODE values `0` and `1` shall be retained.
Unsupported MODE values `2` and `3` shall be mapped to Direct (`0`), while the
written BASE bits shall be accepted unchanged. The resulting stored value shall
be returned by subsequent reads; this mapping shall not depend on the previous
MODE. An unsupported MODE value shall not itself cause an exception. Normal CSR
privilege and access checks shall remain applicable.

This defines trap entry addresses without prescribing software handler layout
beyond the architectural entry requirements. See the
[RISC-V `mtvec` specification](https://docs.riscv.org/reference/isa/priv/machine.html#machine-trap-vector-base-address-mtvec-register).

## 11. WFI as a no-op

**Status:** Agreed

When permitted by the applicable privilege rules, `WFI` shall execute as a no-op
in the baseline implementation. It shall retire normally and advance execution
to the following instruction without entering a wait state, pausing fetch for
sleep, or requesting clock gating. Normal pipeline hazards and trap handling
shall still apply.

`mstatus.TW` (Timeout Wait) shall reset to zero. With `ISA_UMODE = 1`, M-mode
software shall be able to write it to either zero or one. With `ISA_UMODE = 0`, it
shall be hardwired to zero and otherwise permitted writes shall be ignored.

| Execution privilege | `mstatus.TW` | Required WFI behavior |
| --- | --- | --- |
| M-mode | Either value | Execute as a no-op. |
| U-mode, when enabled | `0` | Execute as a no-op. |
| U-mode, when enabled | `1` | Raise an illegal-instruction exception immediately, without a timeout counter or normal retirement. |

A trapped U-mode `WFI` shall follow the normal early exception containment and
WB trap-entry policy in [architecture, Section 9.2](uqu_spec.arch.md#92-early-exception-containment-and-wb-trap-entry). `TW` shall not affect M-mode `WFI`.
This U-mode permission and immediate-interception policy is permitted by the
selected privileged ISA. The ISA also permits a no-op implementation; see the
[RISC-V WFI specification](https://docs.riscv.org/reference/isa/priv/machine.html).

## 12. Machine cycle and instruction-retirement counters

**Status:** Agreed

The core shall implement the standard machine-mode performance counters:

| Counter | Meaning | RV32 CSR access |
| --- | --- | --- |
| `mcycle` | Core clock cycles, including pipeline stall cycles when counting is enabled. | `mcycle` for bits 31:0; `mcycleh` for bits 63:32. |
| `minstret` | Instructions retired when counting is enabled. | `minstret` for bits 31:0; `minstreth` for bits 63:32. |

Both counters shall have 64-bit precision and support machine-mode writes under
the selected privileged ISA's rules. Faulting and discarded instructions shall
not count as retired; a successfully completed custom instruction shall count
once. See the
[RISC-V hardware performance monitor specification](https://docs.riscv.org/reference/isa/priv/machine.html).

Both 64-bit counters shall reset to zero. The core shall implement the machine
counter-inhibit CSR `mcountinhibit` with M-mode-writable `CY` and `IR` bits:

| Inhibit bit | Value `0` | Value `1` |
| --- | --- | --- |
| `CY` | `mcycle` increments each core clock cycle. | Freeze automatic cycle counting. |
| `IR` | `minstret` increments for successfully retired instructions. | Freeze automatic retirement counting. |

Both inhibit bits shall reset to zero, so counting shall be enabled after reset.
`CY` (bit 0) and `IR` (bit 2) shall be the only writable bits in
`mcountinhibit`. All other bits, including the unused `HPM3` through `HPM31`
controls and bit 1, shall read zero and ignore otherwise permitted writes.
These constant fields shall require no writable storage.
Inhibition shall control automatic counting, without disabling otherwise
permitted explicit counter reads or writes. Counter writes and changes to
inhibit control shall follow the pinned ISA's update-ordering rules and the
serialized WB CSR execution policy in [architecture, Section 18](uqu_spec.arch.md#18-native-csr-instruction-execution).

These machine counters and inhibit controls shall remain implemented with either
value of `ISA_UMODE`. Performance monitoring in the first specification draft shall
be limited to cycle and retired-instruction counts. Additional event counters,
such as branch or stall counters, shall be deferred to a later revision; no
additional event-counting storage, selection logic, or configuration parameters
shall be required by this draft.

The unused machine HPM counter CSRs `mhpmcounter3` through `mhpmcounter31`,
their RV32 high halves `mhpmcounter3h` through `mhpmcounter31h`, and event
selectors `mhpmevent3` through `mhpmevent31` shall return zero on permitted
reads. Otherwise permitted writes shall be ignored without raising an exception
solely because these registers are hardwired to zero. They shall require no
counter or event-selector storage. Normal CSR privilege and access checks shall
still apply. This is the constant-zero implementation permitted by the
[RISC-V hardware performance monitor specification](https://docs.riscv.org/reference/isa/priv/machine.html).
Read-only counter views and U-mode access control are defined in [architecture, Section 13](uqu_spec.arch.md#13-user-visible-counters-and-firmware-emulated-time).

## 13. User-visible counters and firmware-emulated time

**Status:** Counter aliases and access policy agreed; firmware time-source details TBD

With either value of `ISA_UMODE`, the core shall provide the read-only
`cycle`/`cycleh` and `instret`/`instreth` CSR aliases of the corresponding machine
counters. These aliases shall refer to the same underlying counter storage, not
independent counters. M-mode reads shall remain permitted in both M-only and
M+U configurations, independently of `mcounteren`. Writes to these read-only
aliases shall follow the normal CSR access checks; M-mode software shall use
the writable machine-counter CSRs to change counter values.

With either value of `ISA_UMODE`, the read-only `hpmcounter3` through
`hpmcounter31` aliases and their RV32 high halves, `hpmcounter3h` through
`hpmcounter31h`, shall be mapped. M-mode reads shall return zero, matching
the constant-zero machine HPM counters in [architecture, Section 12](uqu_spec.arch.md#12-machine-cycle-and-instruction-retirement-counters), without requiring
additional storage. With `ISA_UMODE = 1`, U-mode reads shall raise an
illegal-instruction exception because the corresponding `mcounteren.HPMn`
permissions are hardwired to zero. Any access requesting a write to these
read-only aliases shall raise an illegal-instruction exception. Normal CSR
privilege checks and Zicsr read/write suppression shall apply.

With `ISA_UMODE = 0`, `mcounteren` (`12'h306`) shall be absent. Explicit CSR
accesses to that address shall raise an illegal-instruction exception under
the unmapped-CSR policy in [architecture, Section 18](uqu_spec.arch.md#18-native-csr-instruction-execution). This shall not remove or inhibit the
machine counters, `mcountinhibit`, or the read-only counter aliases available
to M-mode software.

With `ISA_UMODE = 1`, M-mode shall control U-mode reads through `mcounteren.CY` and `.IR`. A U-mode read
whose corresponding enable bit is clear shall raise an illegal-instruction
exception. These permission bits control access, rather than whether the
underlying counters advance.

With `ISA_UMODE = 1`, `mcounteren.CY` and `.IR` shall reset to zero and shall be
writable by M-mode software. After reset, U-mode reads of `cycle`/`cycleh` and
`instret`/`instreth` shall therefore trap until firmware enables the corresponding
permission bit. This reset state shall not inhibit the underlying counters;
automatic counting shall follow `mcountinhibit` as defined in [architecture, Section 12](uqu_spec.arch.md#12-machine-cycle-and-instruction-retirement-counters).

With `ISA_UMODE = 1`, `CY` (bit 0) and `IR` (bit 2) shall be the only writable
bits in `mcounteren`. All other bits, including `TM` and the unused `HPM3`
through `HPM31` permissions, shall read zero and ignore otherwise permitted
writes. These constant fields shall require no writable storage. U-mode
accesses governed by the hardwired-zero HPM permissions shall therefore trap
as illegal instructions. Normal CSR privilege checks shall remain in effect.

The baseline shall omit hardware `time` and `timeh` CSR support and shall not
require a dedicated timer-value input. Reads of these unimplemented CSRs shall
raise an illegal-instruction exception. With `ISA_UMODE = 1`, `mcounteren.TM`
shall be read-only zero.
M-mode firmware may emulate time reads using the external memory-mapped timer;
that firmware is outside the core and is optional. The machine timer interrupt
input remains supported independently of time-CSR implementation.

Full Zicntr includes `time` as well as `cycle` and `instret`. The core shall
therefore not claim complete hardware Zicntr support. An execution environment
may provide the missing time behavior through emulation, as permitted by the
[RISC-V counter-access rules](https://docs.riscv.org/reference/isa/priv/machine.html).
See also the [Zicntr definition](https://docs.riscv.org/reference/isa/unpriv/counters.html).

Since `ISA_UMODE` defaults to `1`, the default configuration shall include M-controlled
U-mode access to cycle and instruction-retirement counters. Firmware time-source
details remain TBD. Disabling U-mode shall retain the read-only aliases for
M-mode software.

## 14. Little-endian byte ordering

**Status:** Agreed

The core shall support little-endian data accesses only, in both M-mode and
U-mode when implemented. There shall be no selectable big-endian mode. Any
implemented architectural endianness-control fields shall be read-only zero.
Instruction parcels shall also follow the RISC-V little-endian encoding rules.

For a 32-bit bus word with aligned byte address `A`, data bits `[7:0]` correspond
to address `A`, `[15:8]` to `A + 1`, `[23:16]` to `A + 2`, and `[31:24]` to
`A + 3`. `dmem` byte-enable bit `i` shall select the corresponding eight-bit data
lane `i`. This defines lane ordering without requiring every data request's
effective byte address to be word-aligned. The external `dmem` address shall
always be word-aligned as defined in [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories); natural alignment of the
instruction's effective address is defined in [architecture, Section 7](uqu_spec.arch.md#7-trap-on-misaligned-data-accesses).

Let `offset = effective_addr[1:0]`. Native loads and stores shall use these
byte enables on the containing word:

| Access size | Allowed offset | `dmem` byte enables |
| --- | --- | --- |
| Byte | `0`, `1`, `2`, or `3` | `4'b0001 << offset` |
| Halfword | `0` or `2` | `4'b0011 << offset` |
| Word | `0` | `4'b1111` |

For stores, the source value's low byte, halfword, or word shall be placed in
the enabled lanes, shifted left by `8 * offset` bits. Only enabled lanes shall
be written. For loads, the selected bytes shall be returned in their normal
lanes within the 32-bit response, and the LSU shall extract and sign- or
zero-extend the value as required by the instruction. Unselected response lanes
shall not contribute to the architectural load result. Zfinx software shall
use ordinary `LW`/`SW` for single-precision floating-point bit patterns, following
the same word-access convention. Full-F `FLW`/`FSW` support remains deferred.

For example, a byte store of `8'hAA` to effective address `32'h00001001` shall
use bus address `32'h00001000`, byte enables `4'b0010`, and `8'hAA` in write-data
bits `[15:8]` (for example, `32'h0000AA00`). The original effective address
`32'h00001001` shall remain available for the instruction's fault reporting.

For example, storing the word `32'h11223344` at aligned address `A` shall place
bytes `44`, `33`, `22`, and `11` at increasing byte addresses. See the
[RISC-V load/store byte-ordering rules](https://docs.riscv.org/reference/isa/unpriv/rv32.html#load-and-store-instructions).

## 15. Aligned instruction fetch and internal assembly

**Status:** Agreed

Every `imem` request shall use a four-byte-aligned address (`addr[1:0] = 0`) and
return one 32-bit word. The external memory system shall not be required to
return an assembled instruction starting at a non-word-aligned address.

The core shall include an internal prefetch/alignment buffer that retains fetched
words or unused halfwords for instruction assembly and reuse. Instruction PCs
shall obey the configured ISA alignment: four bytes with `ISA_C = 0`, or two bytes
with `ISA_C = 1`. When C is enabled, the buffer shall select 16-bit instructions and
assemble 32-bit instructions that begin in the upper halfword of a fetched word
using the lower halfword of the next word. If that next word is not yet
available, instruction delivery shall wait for it.

For example, a 32-bit instruction at `0x1002` shall be assembled from the upper
halfword of the word fetched at `0x1000` and the lower halfword of the word
fetched at `0x1004`. Already fetched instruction data shall be reusable without
issuing a separate memory request for each instruction.

The microarchitecture parameter `MUA_IF_BUFFER_WORDS` shall select the buffer
capacity in 32-bit fetched words and shall default to `2`. The default shall
provide two word slots for instruction delivery, reuse, and compressed-instruction
assembly. Any integer capacity of at least two shall be supported, including
non-power-of-two values, with either value of `ISA_C`. Values below two and
non-integer settings shall fail configuration validation before simulation or
synthesis. Buffer indexing, occupancy, capacity reservation, and wraparound
shall work for the selected capacity without assuming a power-of-two depth.
Each supported hardware YAML configuration shall set its value explicitly.

Buffering shall preserve the baseline limit of one outstanding `imem` request,
independently of the selected depth. Requests shall reserve response capacity
as required in [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories). Increasing buffer depth shall not increase the
number of permitted outstanding requests. The buffer shall preserve the
instruction PC, length, and fault information needed for correct execution and
tracing. Compressed decoding is defined in [architecture, Section 15.1](uqu_spec.arch.md#151-configurable-compressed-instruction-decoding).
Selected-word assembly and fault portions are defined in Section 15.3; the
fetched-word buffer and prefetch fixture are defined in Section 15.4. Production
IF and accepted redirect handling are defined in Section 15.5; full-core event
arbitration remains integration work.

Fetch shall continue filling available buffer space during downstream pipeline
stalls. A downstream stall alone shall not suppress new instruction requests:
request generation shall instead depend on reserved/free buffer capacity, the
one-outstanding-request limit, and applicable control-flow and synchronization
restrictions. Without a predicted redirect, prefetch shall follow sequential
word addresses. Buffer filling shall not advance stalled decode or execution
instructions.

With `MUA_BRANCH_PREDICTOR` set to `none`, recognizing an unresolved branch or
jump in DE shall stop further requests until resolution, as required in
[architecture, Section 5](uqu_spec.arch.md#5-configurable-branch-prediction). This shall prevent starting further requests, without withdrawing
one already asserted. Redirects and flushes shall invalidate affected buffered
data; an asserted request awaiting grant shall retain its payload and finish
the handshake under [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories). Accepted requests shall still complete and stale
responses shall be accepted and discarded. Fetch shall resume along the corrected
stream when capacity and transaction state permit. A stale request awaiting
grant or completion can therefore delay issuing the corrected fetch.

Prefetched error status shall remain associated with its fetched data. An
error on discarded or unused speculative data shall not by itself cause an
architectural trap; precise fault handling shall follow [architecture, Section 9](uqu_spec.arch.md#9-precise-synchronous-exceptions) and [architecture, Section 9.1](uqu_spec.arch.md#91-informative-machine-trap-value). Integration shall ensure that speculative instruction reads, including
reads beyond instructions ultimately executed, do not cause device read side
effects. Such accesses may return errors under the agreed memory contract.

An existing reference is the
[CV32E40P instruction-fetch design](https://docs.openhwgroup.org/projects/cv32e40p-user-manual/en/latest/instruction_fetch.html),
which uses word-aligned prefetches and internal handling of halfword-aligned
instructions. Its buffer depth and outstanding-request count do not prescribe
those choices for uquintus.

### 15.1. Configurable compressed-instruction decoding

**Status:** Three strategies implemented in IF/DE and checked across actual
parent-owned boundary storage; full-core integration pending

`ISA_C` selects the software-visible extension. Two independent elaboration
selectors configure its implementation without changing the ISA:

| `MUA_C_IMPL` | `MUA_C_DECOMPRESS_STAGE` | Datapath |
| --- | --- | --- |
| `decompress` | `if` (default) | IF selection/assembly → decompressor → IF/DE → main decoder. |
| `decompress` | `de` | IF selection/assembly → IF/DE → decompressor → main decoder. |
| `decode_compressed` | Inactive, but explicitly set | IF selection/assembly → IF/DE → parallel native/compressed decoders → control selection. |

Both selectors shall be inactive when `ISA_C = 0`, with no compressed-decode
hardware retained. Inactive labels shall still be valid and explicitly set in
hardware configurations. Numeric values and defaults are defined in Section 2.2
and `config/selectors.json`. Selecting a strategy shall not add a pipeline stage
or inherently add an instruction cycle. Timing/area evaluation shall compare
complete paths and boundary register costs rather than assume a winner.

`uqu_decompressor` shall remain a separate stateless Verilog-2005 module,
independent of placement. It expands supported 16-bit instructions into 32-bit
base instructions and passes native words unchanged. Its initial/default
placement is IF, after instruction selection/assembly and before IF/DE.
DE placement puts expansion ahead of decoding, register reads, hazard resolution
and branch computation; it may reduce duplicated instruction storage at IF/DE
by registering original bits and deriving the expanded word combinationally.
The prefetch buffer shall store fetched words, not expanded instructions.

`uqu_decoder_c` shall decode supported integer RV32C encodings directly into
the same register-use, immediate, FU, LSU, branch, WB and system controls as
`uqu_decoder`. It shall not construct an intermediate base instruction or
instantiate the decompressor/main decoder. In this strategy, the two full
recognition paths operate in parallel in DE and `uqu_decoder_select` selects
controls from the compressed path for a native compressed token. Selection
shall depend on original length metadata, not an XIF acceptance response.
Operand selection, hazards, runtime checks, branch computation and retirement
remain shared. Recognized compressed instructions using unavailable RV32E
registers shall remain native illegal instructions, never extension overrides.

The IF/DE payload shall follow the selected strategy:

- With `decompress/if`, IF shall preserve the normalized instruction alongside
  original bits, length and fetch/expansion fault metadata. It shall convert an
  unsupported compressed encoding into a cause-2 token with original bits as
  tval, unless an earlier fetch fault applies.
- With `decompress/de` or `decode_compressed`, IF shall retain the original selected
  instruction and fetch metadata. The DE adapter consumes `original_instr_i`
  for native compressed decoding; `instr_i` can share the same parent storage.
  DE shall generate compressed legality faults. IF still determines original
  two-/four-byte length from the prefix for selection and sequential fetching.

All strategies shall preserve original PC, bits and length through the pipeline.
Downstream links and sequential PCs shall use original length: compressed calls
link to PC+2, ordinary calls to PC+4. Original compressed bits shall be
zero-extended for `mtval` and tracing. Fetch faults take priority over compressed
legality; unsupported compressed words shall not execute or be sent raw over
XIF's 32-bit issue channel. A compressed-marked token presented to either DE
compressed path with a native 32-bit prefix shall fault rather than execute.

The decompressor's interface is `instr_i[31:0]` to `instr_o[31:0]`,
`original_instr_o[31:0]`, `compressed_o`, `illegal_o` and advisory `hint_o`.
It owns no clock, reset, handshake, PC or pipeline storage. Unsupported
compressed words yield zero normalized bits and assert `illegal_o`; with C
disabled, both words pass unchanged and all flags are zero. Native 32-bit
legality belongs to the main decoder.

Both implementations shall support integer RV32C and its HINT encodings under
[C version 2.0](https://docs.riscv.org/reference/isa/v20260120/unpriv/c-st-ext.html).
HINT register fields shall retain their corresponding base-operation meaning
for RV32E checks; a HINT annotation shall not bypass register legality.
Canonical C.NOP shall expand normally without setting the decompressor's
noncanonical HINT flag. RV64-only forms, reserved encodings, RV32 custom shifts
with shamt[5]=1 and compressed FP transfers remain unsupported. Zfinx does not
enable compressed FP transfers. The direct decoder need not emit an expanded
instruction or a HINT annotation.

DE shall retain the native/XIF ownership rules in
[interfaces, Section 5](uqu_spec.interfaces.md#5-cv-x-if-custom-extension-interface).
An extension-expanded compressed token marked `xif_force_i` shall bypass the
native compressed paths in every strategy and offer its supplied 32-bit
`instr_i` to XIF, preserving the original bits and length. This remains
core-internal origin metadata, with no added coprocessor signals. The standard
compressed XIF channel and frontend translation/ownership integration are still
pending; these native decoding choices do not implement that channel.

The [decompressor/strategy guide](../verif/sim/decompressor/README.md),
[direct decoder guide](../verif/sim/decode_c/README.md) and
[DE guide](../verif/sim/de/README.md) define concrete ports and regressions.

### 15.2. Instruction-word fetch engine and core-owned PMP

`src/uquintus/uqu_ifetch.v` is the IF-owned, read-only word transaction engine.
Its [component guide](../verif/sim/ifetch/README.md) defines exact ports and
timing. It owns one private request/result slot, not the prefetch buffer,
instruction aligner or core-parent IF/DE register. It has no ISA, prediction,
PMP or compressed-decode parameters.

The requester shall present a containing-word address through `req_addr_i`;
the engine shall capture `{req_addr_i[31:2],2'b00}` and ignore the low bits.
This operation shall not replace instruction-PC alignment checking. The core
shall check that same aligned four-byte word for execute permission using the
IF port of its existing shared `uqu_pmp`, with fetch privilege derived by IF/core.
The resulting denial shall reach `req_access_fault_i` before native acceptance.
The MEM parent shall independently use the other checker port for LSU address,
size, R/W access and effective privilege. PMP configuration/address state shall
connect only to the core-owned checker; neither engine shall instantiate PMP
or expose privilege attributes on the memory bus.

A denied request shall produce a registered error word without asserting the
bus. An allowed request may wait privately for `request_permit_i`, separately
from protection. Once presented on OBI, request/address shall remain stable
through stalls, permission changes and flush until grant. One response slot
shall be reserved, grant/response waits shall have no timeout, and each response
shall be captured regardless of consumer readiness. `res_valid_o`, aligned
`res_addr_o`, `res_data_o` and `res_error_o` shall retain the completion until
consumed or discarded. Bus errors shall be sampled only with response valid;
there shall be no combinational response-data bypass. Data shall be zero on
an error, and all result fields zero while invalid.

Flush shall cancel private permission waits or retained results, but an already
presented request shall still finish its handshake and drain its response.
Discarded words, including their errors, shall produce no result or trap.
Reset shall clear only transaction control under the coordinated bus-reset
contract. IF/core shall own redirect targets, invalidation and request holds.
The later buffer/aligner shall associate each word error with a surviving
instruction and its faulting byte portion before generating cause 1; a word
error alone shall not perform architectural trap entry.

The [shared-PMP fixture](../verif/sim/ifetch_pmp/README.md) connects exactly one
core checker to the real ifetch and LSU engines, checking execute versus R/W
permissions, independent privilege, concurrent bus progress, retained outcomes
and discarded IF error responses. Standalone ifetch tests cover permission,
bus waits/errors, backpressure, killed drains and reset. The aligner is defined
in Section 15.3 and buffering in Section 15.4. The prefetch fixture combines
them; production IF is defined in Section 15.5. Full-core integration remains
pending.

### 15.3. Stateless instruction aligner

`src/uquintus/uqu_if_aligner.v` shall select one original instruction from the
word containing `pc_i` and its consecutive successor. Its sole parameter shall
be `ISA_C`, default zero. The [component guide](../verif/sim/if_aligner/README.md)
defines its exact interface, consumption rules and byte-window regression.
The module shall own no state, buffer, PMP checker, bus transaction or decoder.
The parent shall guarantee the supplied words' address association and retain
PC, word data/errors and pipeline storage until their applicable transfers.

With C disabled, valid aligned PCs shall select a complete 32-bit word without
using prefix or successor inputs. With C enabled, low prefix bits shall select
two or four original bytes. A 32-bit instruction at an upper-halfword PC shall
join that halfword with the next word's lower halfword; delivery shall wait if
the successor is unavailable. Short instructions shall be zero-extended and
shall not require a second word. Compressed legality and all expansion/direct
decode strategy choices remain downstream. Unsupported longer prefixes shall
deliver the core's first 32-bit instruction window, not enable longer execution.

The aligner shall expose candidate validity, original bits, compressed status,
sequential next PC, whether the head word can be released and whether a second
word is needed. The parent shall apply PC/word-consumption suggestions only on
an accepted transfer. Low-halfword compressed instructions shall retain their
word; all other successful selections shall release exactly one head word,
retaining an unused upper halfword of a successor when applicable. Sequential
PC arithmetic shall wrap at 32 bits.

A valid first-word error shall immediately yield an instruction-access-fault
token with cause 1 and tval equal to the original PC, without trusting its data
or waiting for a successor. A successor error shall matter only for a crossing
instruction, with tval equal to PC+2, including wraparound. Invalid-word error
inputs and errors on unused successor data shall be ignored. Incomplete inputs
shall wait without producing instruction/fault data. Fault tokens shall expose
zero instruction/length placeholders, retain PC, propose no word consumption
and preserve their fault metadata for the pipeline. After fault transfer the
parent shall contain it and prevent repeated delivery until redirect/flush.

Misaligned input PCs shall assert a diagnostic and suppress output validity;
the aligner shall not create a replacement architectural misalignment trap.
Branch/jump alignment exceptions remain with their originating DE instruction,
and boot/return/debug PC validation retains its existing ownership. No clock,
reset, ready input or internal acceptance tracking belongs to the aligner.

The implementation and regressions cover C-disabled/enabled selection, all
16-bit prefixes at both halfword positions, missing/error word combinations,
informative fault portions, wraparound, and mixed-length stream consumption
under stalls. Fetch/buffer/aligner integration is covered in Section 15.4;
production IF is implemented in Section 15.5. Architectural verification remains
pending.

### 15.4. Fetched-word buffer and prefetch integration

`src/uquintus/uqu_if_buffer.v` shall store raw aligned fetched words in FIFO
order, retaining address, data and word-level error. Its sole parameter shall
be `MUA_IF_BUFFER_WORDS`, with the capacity rules in Section 15. The same storage
shall serve C-disabled and C-enabled configurations and all compressed-decoding
strategies. The [component guide](../verif/sim/if_buffer/README.md) defines ports
and cycle behavior. The FIFO shall expose its oldest two entries independently
of new input data; it shall not provide an empty combinational bypass.

An input valid/ready handshake shall insert one word. A parent-qualified pop
shall release at most one existing head. Empty pops shall do nothing, including
when an input is accepted on that edge. Full queues shall support simultaneous
head removal and tail insertion. Head/tail pointers shall wrap explicitly at
the configured depth, including non-power-of-two depths. Invalid read windows
shall expose zero fields; error words shall expose zero data. Reset and flush
shall invalidate control only, without resetting payload arrays. During reset
or flush, input readiness and output validities shall be suppressed.

The FIFO shall not own an instruction PC, fetch-address generator, redirect
policy, instruction decoder, PMP checker or bus interface. IF control shall
ensure the oldest word contains the current instruction PC and the second word
is its consecutive successor before supplying the aligner. The parent shall
pop only when an instruction transfer consumes the old head according to
the aligner's suggestion; a low-half compressed instruction shall retain it.
Fault words shall remain associated with their original addresses until used
or discarded. Only the aligner shall turn selected fetch errors into tokens.

IF shall start a native fetch only with an idle engine and free buffer capacity,
including space released by a qualified simultaneous pop. With one outstanding
transaction and no other FIFO writer, this shall reserve space implicitly:
occupancy cannot increase before that engine's result is inserted. The engine's
private response slot shall hold the reserved word, not permit an extra word
beyond the configured capacity. Buffered words plus a busy fetch engine shall
never exceed `MUA_IF_BUFFER_WORDS`. The fetch address shall advance by four only
on native acceptance; the instruction PC shall advance only on accepted
instruction transfer. Consumer stalls alone shall not stop prefetch filling.

On an accepted invalidation/redirect, the parent shall flush both engine and
FIFO, replace the instruction PC and sequential fetch pointer, and prevent any
discarded response from refilling the FIFO. Presented OBI requests shall still
finish and drain under Section 15.2. A replacement request shall wait until
the engine is idle. A transferred fault shall be contained until redirect;
it shall not be delivered repeatedly or advance the instruction PC.

The [prefetch fixture](../verif/sim/if_prefetch/README.md) connects real fetch,
buffer and aligner RTL to a verification-only controller. Deque/byte-window
scoreboards check reservation, address association, independent fetch and
instruction progression, mixed-length reuse, response errors, discarded
transactions and repeated flushes. Capacities 2, 3, 4, 5 and 8 are exercised,
with C disabled/enabled for integration. This does not implement the production
IF stage or IF/DE storage. Production IF, expansion placement and the two
baseline prediction modes are implemented in Section 15.5; privileged control,
debug and FENCE.I arbitration remain core integration work. PMP remains the one
core-owned checker.

### 15.5. Instruction-fetch stage and parent boundary

`src/uquintus/uqu_stage_if.v` shall own the frontend instruction PC, sequential
word-fetch pointer, run state, fault-delivery containment and instances of
`uqu_ifetch`, `uqu_if_buffer`, `uqu_if_aligner` and, when selected, the IF
decompressor. It shall not own the IF/DE register, current privilege, PMP state
or checker, global event arbitration, architectural trap entry or DE branch
execution. The [stage guide](../verif/sim/if/README.md) defines exact ports and
tests. Its parameters shall be `ISA_C`, both compressed strategy selectors,
`MUA_BRANCH_PREDICTOR` and `MUA_IF_BUFFER_WORDS`.

Each active reset edge shall establish a running frontend at the aligned
`boot_addr_i` under the core boot contract. Later boot-input changes shall not
redirect it. An accepted `redirect_valid_i` shall immediately suppress old
delivery and new native acceptance, invalidate the buffer/fetch engine and
install `redirect_addr_i` as the instruction PC with its containing word as
the fetch pointer. Repeated redirects shall replace that target while old bus
work drains. A plain `flush_i` shall invalidate and stop until a redirect, so
it cannot resume an unspecified old stream. Reset shall take priority over
redirect, redirect over plain flush, and all over ordinary transfers. A
presented request shall still retain its address through grant and drain under
Section 15.2; replacement native acceptance shall wait for engine readiness.

`fetch_enable_i` shall control new native acceptance and presentation of private
requests, independently of downstream readiness. `request_permit_i` shall add
private bus-presentation permission, without preventing native PMP denial.
Neither shall retract a presented request. In `none` mode, `branch_pending_i`
shall likewise stop new requests/private presentation for a recognized unresolved
DE branch/jump. `static_not_taken` shall ignore that branch hold and continue
sequential prefetch. Both modes shall retain already fetched words/completions
until consumption or invalidation. Dynamic prediction remains future work.

`permit_i` shall independently gate token delivery. `valid_o && ready_i` shall
be the sole instruction/fault transfer. A successful transfer shall advance PC
by the original length and release a head word only when the aligner indicates
it is fully consumed. Prefetch shall fill reserved capacity during delivery
stalls. The private engine result shall occupy reserved capacity rather than
extend `MUA_IF_BUFFER_WORDS`. `fetch_busy_o` shall report engine transaction
ownership, including private waits, retained results and killed drains; it
shall not report buffered instructions or architectural pipeline occupancy.

IF shall expose original PC/bits/length and normalized instruction separately.
`decompress/if` shall expand after alignment; unsupported compressed encodings
shall yield cause 2 with original bits as tval. `decompress/de` and
`decode_compressed` shall carry raw bits and leave compressed legality to DE.
Fetch faults shall take priority, preserve the aligner's fault-portion address,
and use zero instruction/length placeholders. Native legality and RV32E register
legality shall remain in DE. Invalid/faulting normalized instructions shall be
zero; an expansion fault shall retain original compressed identity.

A transferred IF fault shall hold PC, release no word, block new work and emit
no further token until invalidation/restart. This is local containment, not
trap arbitration; an older redirect shall be able to discard it. Misaligned
current PCs shall raise a diagnostic and suppress selection/new fetches without
reattributing an originating branch/return/debug alignment exception.

For each native acceptance, IF shall issue a combinational core-PMP query with
aligned address, size 2 (four bytes) and supplied current fetch privilege.
`pmp_allow_i` shall not affect query validity/address. The fetch engine shall
capture its denial before any bus presentation. No PMP instance or CSR storage
shall appear inside IF, and no privilege information shall cross OBI. Core
privilege/protection transitions and required invalidations remain externally
controlled.

The [IF/DE fixture](../verif/sim/if_pipeline/README.md) shall register actual IF
outputs in parent-owned storage and feed real DE. It shall test held boundary
metadata, original-length links, taken/not-taken branches and wrong-path faults
in all three compressed strategies. A DE branch accepted for transfer shall
redirect IF in that cycle without echoing a flush into its own DE transaction.
External core events shall retain priority. Full-core debug/trap/FENCE.I
arbitration and the deferred standard CV-X-IF compressed channel remain outside
this implementation; supplied hold, permit, flush and redirect ports shall
support later controller integration.

## 16. Optional instruction-fetch fence

**Status:** DE serialization, WB completion/restart, and request/acknowledgement
interface agreed; system-specific synchronization requirements TBD

The `ISA_ZIFENCEI` RTL parameter shall enable the Zifencei extension and its
`FENCE.I` instruction, and shall default to `0` (disabled). When enabled,
`FENCE.I` shall synchronize subsequent
instruction fetching with preceding writes to executable memory visible to this
hart, according to the selected ISA specification. See the
[RISC-V Zifencei specification](https://docs.riscv.org/reference/isa/unpriv/zifencei.html).

`FENCE.I` shall reuse DE serialization and WB completion control. Once recognized
in DE, it shall block younger execution and stop starting new instruction-fetch
requests while allowing older instructions and relevant native/custom memory
activity to finish. It shall advance through EX/MEM subject to readiness without
an ordinary ALU or LSU data operation. Fetch shall remain held until the required
instruction/data synchronization completes.

At WB, after the preceding work and required external synchronization complete,
the core shall retire `FENCE.I`, invalidate stale prefetched instruction state
and younger pipeline instructions, and redirect fetch to the sequential successor
of the fence (`PC + 4`). Fetch shall restart when the memory-port state permits.
Completion shall count as one retired instruction and release serialization.

An instruction-fetch request already asserted before the hold shall keep its
payload stable and finish its grant handshake under [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories). Accepted
transactions shall still complete; stale responses shall be accepted and
discarded without refilling the buffer, executing, or causing an architectural
trap. A stale request awaiting grant/completion may delay the corrected fetch.
Flushing `FENCE.I` because of an older event shall release its barrier without
normal retirement or its successor redirect; unrelated flushes shall not release
a surviving fence's barrier.

The external request/acknowledgement contract is defined in
[the interface specification](uqu_spec.interfaces.md#82-instruction-fetch-fence-handshake).

## 17. Integer register-file implementation

**Status:** Both flip-flop and latch backends with combinational DE reads agreed;
flip-flop default agreed; initial portable write timing and encoding below,
technology mapping and physical timing closure open

The integer register-file design shall provide both flip-flop and latch
backends, selected at elaboration time through `MUA_REGFILE_IMPL`, with
flip-flop storage as the default.
Both shall provide combinational reads in DE. SRAM-backed implementation
support shall no longer be required. Each backend shall preserve the configured logical
port requirements, including the third read port specified below and simultaneous
paired writes in [interfaces, Section 5](uqu_spec.interfaces.md#5-cv-x-if-custom-extension-interface), and provide the same architectural behavior.
The initial implementation encodes `ff` as `UQU_RF_FF = 0` and `latch` as
`UQU_RF_LATCH = 1`, generated from `config/selectors.json`.

A third 32-bit combinational integer read port shall be implemented when
`ISA_ZFINX = 1` or (`XIF = 1` and `XIF_NUM_RS = 3`). It shall supply three source
values in the same DE cycle without an additional operand-collection cycle,
subject to the normal dependency and downstream-capacity rules. When neither
feature requires it, the extra port and its unused logic shall be excluded at
elaboration or eliminated by synthesis. No new port-count parameter is required.

For native Zfinx fused multiply-add variants (`FMADD.S`, `FMSUB.S`, `FNMSUB.S`,
and `FNMADD.S`), the third read address shall come from the standard independent
`rs3` field at instruction bits `[31:27]`. For three-source custom instructions,
it shall come from `rd` at `[11:7]` under [interfaces, Section 5](uqu_spec.interfaces.md#5-cv-x-if-custom-extension-interface). Source-address selection
shall follow the decoded instruction. All three Zfinx sources shall participate
in the common hazard, forwarding, and retained-operand rules in [architecture, Section 4](uqu_spec.arch.md#4-configurable-operand-forwarding);
register aliases among sources or with the destination shall be allowed.
RV32E availability checks shall cover all used source and destination indices.
The third read port shall not add a write port; optional paired XIF writeback
shall retain its independent configuration.

Register-file storage shall be isolated behind a common interface, with any
technology-specific cells or clock-control implementation kept separate from
the processor datapath and pipeline control. Edge-triggered storage shall follow
the [RTL assignment conventions](uqu_spec.style.md#7-assignments-and-combinational-completeness).
An intentional latch-based register file is permitted as an explicit exception to the prohibition on
unintended latches; its enable phase, write-data timing, and clock control shall
be documented and verified against the core clock. Any explicit clock control
required for this backend shall follow the isolation policy in [interfaces, Section 2](uqu_spec.interfaces.md#2-single-clock-domain).

Writes shall be controlled by WB. Register-file reads shall expose the currently
stored contents, with `x0` supplying zero. Neither backend shall include a
separate combinational bypass from incoming WB write data to its read outputs.
Same-cycle WB-to-DE dependencies shall instead use the common pipeline
forwarding/stall policy in [architecture, Section 4](uqu_spec.arch.md#4-configurable-operand-forwarding).
The initial portable implementations accept writes on rising edges. The latch
backend captures write data in rising-edge flip-flops and per-word enables in
low-phase latches, then updates high-phase data latches. Read outputs reflect
the updated storage after propagation; there is no pre-edge write-data bypass.
Nonzero GPR storage is unreset, and synchronous reset suppresses writes without
clearing stored contents. Physical timing closure and technology mapping remain
open. See the [register-file component guide](../verif/sim/gpregfile/README.md)
for the initial port contract, defensive address/collision behavior, and tests.

### 17.1. IHP SG13G2 macro findings

**Status:** Reference findings checked 2026-10-20 against the published PDK
`main` sources; retained as rationale for selecting flip-flop or latch storage

The [published SRAM catalog](https://github.com/IHP-GmbH/IHP-Open-PDK/tree/main/ihp-sg13g2/libs.ref/sg13g2_sram/verilog)
contains single-port (`1P`) and true dual-port (`2P`) macros. Examples include
`RM_IHPSG13_1P_64x64_c2_bm_bist` and `RM_IHPSG13_2P_64x32_c2`.

The [64x32 dual-port datasheet](https://github.com/IHP-GmbH/IHP-Open-PDK/blob/main/ihp-sg13g2/libs.ref/sg13g2_sram/doc/RM_IHPSG13_2P_64x32_c2.txt)
specifies one-cycle access with rising-edge address/control sampling and
clocked read outputs. Each of the two independent ports supports read, write,
and write-through at its own address. The two ports are two total access ports,
not two independent reads plus two additional writes. The datasheet states that
conflict handling is not included. Same-address cross-port hazards therefore
need an explicit integration contract; same-port write-through is not a
cross-port bypass guarantee. `A_DLY` and `B_DLY` must be tied high.

The [single-port behavioral model](https://github.com/IHP-GmbH/IHP-Open-PDK/blob/main/ihp-sg13g2/libs.ref/sg13g2_sram/verilog/RM_IHPSG13_1P_core_behavioral_bm_bist.v)
likewise implements rising-edge reads/writes, with bit-masked writes and
same-address write-through. These reviewed macros do not provide asynchronous
reads in response to a changing address.

An SRAM implementation would require explicit operand-read scheduling. A single
reviewed macro cannot directly supply the required two or three independent
reads alongside one or two writes in a cycle; replication, banking, or another
timing arrangement would need evaluation. These findings motivated the initial
flip-flop/latch implementation choice. No SRAM register-file mapping is required
by the current specification.

## 18. Native CSR instruction execution

**Status:** CSR instruction read/modify/write in WB and uniform serialization
agreed for the baseline

The Zicsr 2.0 instruction set shall be mandatory in every configuration under
[architecture, Section 2](uqu_spec.arch.md#2-isa-and-microarchitecture-configuration-parameters); it shall not be independently disabled.

Native CSR instructions shall perform their architecturally required CSR read
and update in WB. Any returned GPR value and CSR update shall belong to the same
retiring instruction. ISA-defined read/write suppression and access checks shall
be preserved; faulting or discarded instructions shall not update the CSR or
destination GPR. This stage choice applies to explicit native CSR instructions;
implicit counter advancement and trap/debug state updates shall follow their
own specified contracts.

A dedicated CSR module shall implement CSR address decoding, access checks,
and register-specific read/write behavior, and shall own architectural CSR
storage and its update logic. This ownership shall include machine counters,
implemented PMP configuration/address registers, and floating-point CSR state
when enabled. Read-only aliases shall share their underlying state; constants
and integration inputs such as `mhartid` shall not require duplicated storage.

CSR storage shall be implemented as explicitly decoded architectural state,
with registers only for fields that can change in the selected hardware
configuration. The CSR address space shall not be implemented as a general
address-indexed array of writable 32-bit words. Full-width registers remain
appropriate where all bits carry state, such as `mscratch` and the implemented
counters. Fields that are temporarily read-only because of runtime locking
shall retain their required state; locking shall not be confused with an
elaboration-time constant.

Each CSR's implementation shall identify its stored fields, read-value sources,
write permissions, reset behavior, and WARL/ignored-write rules. Combinational
read decoding shall assemble the architectural 32-bit value from stored fields,
constants, derived values, integration inputs, or aliases of existing state.
Explicit CSR writes and implicit architectural events shall update only their
applicable state fields. Read/modify/write instructions shall operate on the
architectural read value before applying the destination field's write and
legalization rules; omitting constant-bit storage shall not change CSR semantics.
CSR address legality shall remain independent of whether an address requires
storage.

In particular, only CY and IR require storage in `mcountinhibit` and, when
present, `mcounteren`; their other bits are hardwired zero. Hardwired `misa`,
integration-supplied `mhartid`, and supported constant-zero disabled PMP/HPM
registers shall allocate no CSR payload storage. Counter aliases shall reuse
the underlying counter state. Disabled optional-feature state shall be excluded
at elaboration or eliminated by synthesis, preserving its specified mapped or
unmapped CSR behavior. Existing reset and architectural update requirements
remain binding.

The implementation shall expose constants and field write restrictions directly
in RTL rather than rely on synthesis to infer them from software usage.
Representative synthesized CSR configurations shall be inspected for retained
storage: hardwired/reserved fields and disabled features shall not retain
payload flops or memory bits, aliases shall not duplicate state, and every
architecturally mutable field shall remain implemented. Optimization shall
preserve required access checks, side effects, and update arbitration.

Other blocks shall consume the required CSR state through explicit module
outputs and request architectural updates through explicit event connections.
These events shall include the applicable trap/interrupt entry, `MRET`, cycle
and retirement counting, and floating-point exception/status updates. Event
acceptance and update arbitration shall preserve the existing instruction-age,
commitment, reset, and precise-exception rules. The central controller shall
continue to arbitrate global events, and the core-owned two-port PMP block shall
consume the CSR module's PMP state. The module may use internal submodules while
retaining this ownership boundary. The standalone module's initial port/event
contract is defined in Section 18.2; full-controller integration remains pending.

The CSR module shall be able to report an exception for an invalid access.
An explicit CSR instruction targeting an
address outside the documented CSR map shall raise an illegal-instruction
exception. Insufficient privilege, a prohibited write to a read-only CSR, and
other documented CSR access violations shall likewise report the applicable
illegal-instruction exception in the baseline M/U architecture.

The module shall respect Zicsr read/write suppression when determining which
accesses an instruction actually requests. Supported constant-zero registers,
including disabled PMP CSRs and unused machine HPM counters/selectors, shall
remain valid mapped registers with their agreed read/write behavior. Constant
WARL or read-only fields inside a writable CSR shall not make the entire CSR
an illegal write target; the specified ignored-write or WARL mapping shall
apply. Normal privilege checks shall still apply to these mapped registers.

A reported CSR access exception shall suppress the instruction's ordinary CSR
update and destination-register write and shall prevent normal retirement.
The pipeline shall retain its PC and original instruction bits, using those
bits as `mtval` for an illegal-instruction trap under [architecture, Section 9.1](uqu_spec.arch.md#91-informative-machine-trap-value). The
central controller shall arbitrate the exception and finalize architectural
trap entry at WB under [architecture, Section 9.2](uqu_spec.arch.md#92-early-exception-containment-and-wb-trap-entry), including the resulting trap-state CSR
updates. Thus the CSR module's local fault report shall feed the same precise
exception path as faults from other units. Discarded instructions shall have
no CSR access side effects. The initial module ports, fault report, and local
update priorities are defined in Section 18.2; global-event arbitration remains
controller integration work.

Native CSR instruction processing shall complete within one WB processing cycle
once the instruction is eligible to commit. The CSR module shall provide the
read value, access-legality result, and required write-value calculation
combinationally; it shall not add internal wait states or an extra access
pipeline stage. A successful access shall commit its ordinary CSR update and
any destination-register result together on the active clock edge, subject to
the Zicsr read/write suppression rules.

Pipeline backpressure or higher-priority control events may delay commitment.
A held instruction shall not repeatedly update a CSR, and no ordinary CSR write
shall occur for a stalled, flushed, reset, or faulting access. Read/check
evaluation before commitment shall have no architectural access side effects;
the result used shall correspond to the state observed for the actual
commitment. Implicit counter progression shall continue according to its own
rules during pipeline stalls. A fault shall use the existing WB trap path
without an additional CSR-unit wait phase. This timing requirement shall not
remove the DE serialization barrier or change the separate trap/debug event
contracts.

`mscratch`, `mepc`, `mcause`, and `mtval` shall each reset to `32'h00000000`
under the synchronous reset contract in [interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset). These values shall be
independent of the reset entry address input. Subsequent explicit CSR accesses
and trap entry shall follow the applicable register semantics and privilege
checks; zero initialization shall not suppress the informative trap updates
defined in [architecture, Section 9.1](uqu_spec.arch.md#91-informative-machine-trap-value). Firmware shall initialize scratch and return state as
needed before using it.

`mepc` shall retain all upper address bits on otherwise permitted CSR writes,
with low-bit handling derived from the elaborated `ISA_C` setting:

| Configuration | Writable address bits | Hardwired-zero bits |
| --- | --- | --- |
| `ISA_C = 0` | `mepc[31:2]` | `mepc[1:0]` |
| `ISA_C = 1` | `mepc[31:1]` | `mepc[0]` |

Writes to hardwired-zero bits shall be ignored without an exception solely for
their values. Explicit CSR reads and the implicit read by `MRET` shall observe
the same aligned value. These rules shall also apply to the stored trap PC;
the actual offending target address for an instruction-address-misaligned
exception shall instead be reported through `mtval` under [architecture, Section 9.1](uqu_spec.arch.md#91-informative-machine-trap-value).
The alignment setting shall not change at runtime because `ISA_C` is an
elaboration-time option and `misa` is hardwired ([architecture, Section 2.1](uqu_spec.arch.md#21-hardwired-isa-identification)). See the
[RISC-V mepc specification](https://docs.riscv.org/reference/isa/priv/machine.html).

Every native CSR instruction shall act as a pipeline serialization point,
including read-only accesses. Once such an instruction is recognized in DE,
younger instructions shall be prevented from advancing beyond DE until it
retires or its exception/flush is handled. Older instructions shall continue
draining, and the CSR instruction shall progress through the normal pipeline
subject to readiness. Its read/modify/write shall occur in WB after older
instructions complete. Normal younger execution shall resume with the updated
architectural state. Flushing the CSR instruction shall release its pending
barrier under the existing reset/flush/stall priority rules; an unrelated flush
shall not release the barrier of a surviving CSR instruction.

This policy avoids CSR-state forwarding and per-CSR pipeline hazard
classification, at the cost of stalling even independent younger instructions
behind CSR accesses. CSR-specific register semantics and privilege checks remain
required. Optimization of individual CSR classes shall be deferred.

The baseline shall provide the following constant-valued machine CSRs:

| CSR | Address | Presence | Behavior |
| --- | --- | --- | --- |
| `mstatush` | `12'h310` | All configurations | Read zero; ignore otherwise permitted writes. |
| `mconfigptr` | `12'hF15` | All configurations | Read-only zero, indicating that no configuration discovery structure is provided. |
| `menvcfg` | `12'h30A` | `ISA_UMODE = 1` only | Read zero; ignore otherwise permitted writes. |
| `menvcfgh` | `12'h31A` | `ISA_UMODE = 1` only | Read zero; ignore otherwise permitted writes. |

The constant-zero `mstatush` profile shall reflect the selected RV32,
little-endian M/U architecture and its absence of the extensions controlled
by the corresponding high status fields. The zero environment-configuration
CSRs shall select no additional lower-privilege environment behavior. These
constants shall require no writable storage.

Normal CSR privilege checks and Zicsr read/write suppression shall apply.
An access that requests a write to the read-only `mconfigptr` shall raise an
illegal-instruction exception. With `ISA_UMODE = 0`, `menvcfg` and `menvcfgh`
shall be absent, and accesses to their addresses shall raise an
illegal-instruction exception under the unmapped-CSR policy above. Future
extensions that require nonzero or writable fields shall explicitly revise
this baseline profile. See the
[RISC-V machine-level CSR specification](https://docs.riscv.org/reference/isa/priv/machine.html).

### 18.1. Serialized MRET at WB

**Status:** Agreed; detailed controller sequencing TBD

`MRET` shall be a serialization point. Once recognized in DE, it shall block
younger normal execution and new sequential fetch requests while allowing
older instructions to finish. It shall advance through the pipeline subject
to readiness, performing no ordinary ALU or data-memory operation in EX/MEM.
The core shall read the return state and finalize a legal `MRET` in WB after
all older instructions have completed successfully, including earlier CSR
writes. `MRET` shall not require a speculative CSR read or CSR forwarding path.

At WB, a successful `MRET` shall coordinate the architectural return-state
updates and redirect to `mepc` as one retiring instruction. Under the baseline
M/U profile, it shall restore the privilege mode from the old `mstatus.MPP`,
set `MIE` from the old `MPIE`, set `MPIE` to one, and set `MPP` to the
least-privileged supported mode (U with `ISA_UMODE = 1`, otherwise M). When
returning below M-mode it shall also clear `MPRV`. The selected privileged ISA
shall govern any additional applicable return semantics. Interrupt eligibility
shall be re-evaluated immediately after `MRET` using the restored state. See
the [RISC-V machine-level specification](https://docs.riscv.org/reference/isa/priv/machine.html).

The central controller shall discard younger sequential-path instructions and
buffered fetch state at the return redirect. Accepted old-path fetch requests
shall retain completion tracking and have their stale responses discarded.
Return-target fetching and execution shall use the restored privilege state
and the applicable internal PMP checks. If an older exception discards `MRET`,
it shall perform no return-state update, return redirect, or retirement; its
serialization barrier shall be released under the normal flush rules.

An illegal `MRET`, including one attempted in U-mode, shall follow early
exception containment and WB trap entry under [architecture, Section 9.2](uqu_spec.arch.md#92-early-exception-containment-and-wb-trap-entry) instead of
performing a return. A legal, surviving `MRET` shall retire normally and count
as one instruction for `minstret`, subject to applicable counter controls.

Ordinary `ret`, encoded as `JALR`, shall retain DE resolution under [architecture, Section 6](uqu_spec.arch.md#6-resolve-branches-and-jumps-in-decode)
and shall not acquire this serialization policy. With no pipeline stalls, the
WB return redirect occurs three pipeline cycles later than DE resolution for
an otherwise ready `ret`. Older-operation waits, memory latency, and pending
fetch completion may extend the observed return penalty. This timing cost is
accepted to keep privilege-state updates and return control explicit at WB.

Verification shall cover M-mode and U-mode returns where supported, preceding
CSR writes to return state, pending interrupts after state restoration, older
faults discarding `MRET`, and illegal U-mode attempts with no return side effects.

### 18.2. Standalone CSR register-file implementation

`src/uquintus/uqu_csregfile.v` implements the decoded architectural state and
CSR access checks described above. Its [component guide](../verif/sim/csregfile/README.md)
defines the complete implemented CSR map, ports, state budget, event priorities,
and regression scope. It does not own WB pipeline registers, current execution
privilege, trap selection, or redirect arithmetic. The WB stage in Section 3.10
now supplies qualified CSR commitment, retirement and trap/MRET/FP events.
The core parent still serializes instructions, retains current privilege,
arbitrates global events and owns redirects.

A live CSR query returns its required pre-update read value or an
illegal-instruction report combinationally. Explicit writes require a legal
live access and a commitment pulse, with no owning flush. The interface retains
source/destination encoding information so Zicsr suppression is independent of
a register operand's numeric value. There is no extra CSR transaction buffer or
access wait cycle. Synchronous reset has highest priority; accepted trap entry
wins over MRET, and either event suppresses ordinary explicit CSR writes.
Counters and independently committed floating-point events retain their own
qualified updates. A write to either counter half suppresses that counter's
whole implicit increment for the edge; inhibit changes use the old inhibit
state on the write edge. The controller remains responsible for never counting
a faulting or discarded instruction as retired.

The implementation stores MPP as one M/U selector bit, `mtvec.MODE` as one
Direct/Vectored selector, and `mcause` as its interrupt flag plus four low cause
bits. All baseline exception/interrupt causes fit this representation; upper
cause bits read zero, and unsupported WLRL software-write codes deterministically
retain only their low four bits. New causes numbered sixteen or higher shall
require an explicit width/profile revision. PMP configuration stores six bits
per entry with bits 6:5 hardwired zero. Reserved R=0/W=1 writes map to R=0/W=0,
preserving the written A/L/X fields. PMP address payloads remain 32 bits and
unreset; configuration reset clears their locks and leaves every entry OFF.

State allocation is `265 + ISA_C + 5*ISA_UMODE + 8*ISA_ZFINX + 608*ISA_PMP + DEBUG*(67 + ISA_C + 2*ISA_UMODE)`
bits, with no CSR payload memory or duplicated alias state. Representative
Yosys checks confirm the widths and reset coverage, including only 270 state
bits for the default M+U configuration. Tests cover all sixteen combinations
of U/C/Zfinx-CSR/PMP state, with representative I/E/M identification settings.
This is a standalone-component milestone; complete pipeline/CSR/PMP integration
and an operational Zfinx execution backend remain pending. With `DEBUG=1`,
debug-only DCSR/DPC/dscratch0 state and counter freezing follow the
[WB interface guide](../verif/sim/wb/README.md); disabled debug outputs are zero
and debug CSR accesses trap. Full-F and atomic configurations remain unsupported.

## 19. Conservative data-memory fence

**Status:** Full barrier, DE serialization, WB completion, and external
request/acknowledgement interface agreed; system-specific ordering details TBD

The base ISA's `FENCE` instruction shall prioritize minimal implementation effort
over fence throughput or selective ordering. The implementation shall
conservatively order all preceding memory and device-I/O accesses before all
subsequent memory and device-I/O accesses, irrespective of the encoded
predecessor and successor sets. It may apply the same stronger ordering to
`FENCE.TSO` as permitted by the
[RISC-V base integer specification](https://docs.riscv.org/reference/isa/unpriv/rv32).
Selective ordering logic and special fence performance optimizations are not
required for the baseline.

The core shall finish relevant older memory activity before permitting younger
memory accesses to proceed past the barrier. `FENCE` shall reuse the DE
serialization and WB completion control used for native CSR instructions and
`MRET`: once recognized in DE, it shall block younger execution while allowing
older instructions and memory activity to finish. It shall advance through
EX/MEM subject to readiness without an ordinary ALU or LSU data operation, then
retire at WB only after the required memory-ordering conditions are satisfied.

The ordering condition shall cover both native loads/stores and relevant
custom-operation memory activity, including separately connected custom memory
paths. If the integration requires explicit external synchronization, `FENCE`
shall wait for that condition before retirement. Successful completion shall
release the barrier and count as one retired instruction. Flushing a fence
shall remove its barrier without normal retirement, following the existing
age and reset/flush rules; an unrelated flush shall not release a surviving
fence's barrier. Recognition shall not itself initiate any CSR update.

`FENCE` shall not require instruction-prefetch invalidation or provide the
instruction-fetch synchronization of `FENCE.I`. Optional `FENCE.I` support
remains governed by [architecture, Section 16](uqu_spec.arch.md#16-optional-instruction-fetch-fence) and `ISA_ZIFENCEI`.
The external request/acknowledgement contract is defined in
[the interface specification](uqu_spec.interfaces.md#81-dataio-fence-handshake).

## 20. Initial processor identification values

**Status:** Agreed

The initial implementation shall provide the standard identification CSRs with
hardwired zero values:

| CSR | Initial value |
| --- | --- |
| `mvendorid` | `32'h00000000` |
| `marchid` | `32'h00000000` |
| `mimpid` | `32'h00000000` |

These CSRs shall be readable in M-mode and require no writable storage. They
occupy read-only CSR addresses; instructions that attempt to write them shall
raise an illegal-instruction exception under the normal CSR access rules.
Zero identification values are permitted by the
[RISC-V machine-level specification](https://docs.riscv.org/reference/isa/priv/machine.html).

Project-specific vendor, architecture, and implementation identification values
may be defined in a later revision. This initial choice shall not change the
configured ISA reported by `misa` or the integration-supplied hart identity
reported by `mhartid`.

## 21. Implementation follow-ups and deferred scope

The architectural contracts above are agreed. The following details remain to
be resolved when their implementation milestone is undertaken:

| Area | Remaining work |
| --- | --- |
| Execution/control | IF/DE/EX/MEM/WB stages, shared hazards and parent-register/GPR fixtures implemented; connect full-core pipeline/controller sequencing, XIF issue/ID/kill tracking and evaluate timing of enabled forwarding paths. |
| Memory access | MEM/LSU, registered load readiness, IF PMP query and parent-owned PMP routing verified at component/fixture level; connect CSR-owned PMP state, both stages, precise-effect permission control, and fences in the full core. |
| Integer arithmetic | ALU, MUL/DIV, shared arithmetic, EX control, and parent-register fixtures are implemented; full processor pipeline integration remains pending. Preserve fixed execution latencies and physical sharing during integration. |
| Zfinx | Inactive FPU interface stub available; select and pin an FPU/backend configuration, establish exact operation latencies, and validate adapters, reset, flush, rounding, flags, and tool compatibility; retain backend-defined latency and scalar FP32 scope. |
| Register file | Physical timing closure and technology mapping for the initial portable FF/latch backends; preserve logical ports, rising-edge write visibility, and the common pipeline bypass policy. |
| ISA/CSR/PMP | WB owns decoded CSR state/access checks, optional PMP/FP state, counters and accepted trap/MRET updates; integrate with the full-core controller and two-port PMP checker, preserve instruction-age/retirement rules, and connect XIF issue/tracking and the core debug controller to implemented WB endpoints. |
| Frontend | IF owns selected expansion placement, prefetch/fault association, redirect tracking and none/static_not_taken behavior; integrate full-core event arbitration, future dynamic predictors and the deferred standard XIF compressed channel. |
| Milestones | Implementation order and acceptance criteria for optional ISA features, PMP, XIF, latch storage, and non-default configurations after the baseline milestone. |

Full F and its separate register file are deferred in favor of Zfinx. `ISA_A`
and `MUA_HARDENED` are future options whose enabled settings remain unsupported
until implemented. Additional event counters, supervisor mode/virtual memory,
RV64, and packed/additional floating-point formats are outside the initial
implementation scope. Deferred settings do not advertise implemented ISA support.

## 22. Decision record

Decision IDs are shared across the [specification set](uqu_spec.md#document-index).
Superseded and deferred rows preserve history; current topic requirements and
later decisions determine the active contract.

| ID | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-002 | Use the classical five-stage pipeline: fetch, decode, execute, memory, write back. | Follow the classical RISC architecture described by David Patterson. | Agreed |
| D-010 | Support RV32 only, with fixed `XLEN = 32`. | Select a single architectural width rather than supporting parameterized RV32/RV64 configurations. | Agreed |
| D-011 | Make hardware integer multiplication and division optional together through the `ISA_M` parameter. | Select the software-visible M extension as a unit. | Agreed |
| D-012 | Use RV32I as the default base and organize configuration by software-visible ISA features, using `ISA_E`, `ISA_M`, `ISA_C`, and `ISA_F`. | Make configuration reflect the instruction set available to software. | Agreed; floating-point target changed to Zfinx under D-235 |
| D-013 | Use single-issue, in-order execution. | Define the execution model for the classical five-stage pipeline. | Agreed |
| D-017 | Support optional operand forwarding through an RTL parameter, with correct hazard stalls in both settings. | Allow experimentation with forwarding while preserving the configured ISA's behavior. | Agreed |
| D-018 | Make branch prediction optional and its implementation selectable through RTL parameters. | Allow experimentation with predictor implementations while preserving the configured ISA's behavior. | Agreed |
| D-019 | Resolve conditional branches in decode (ID/DE), including comparison and target calculation. | Place branch resolution ahead of EX; evaluate the resulting decode timing during implementation. | Agreed |
| D-020 | Default branch prediction to `none`, pausing further fetch requests for a recognized unresolved branch; treat `static_not_taken` as a separate predictor choice. | Distinguish no prediction from speculative sequential fetching. | Agreed |
| D-021 | Resolve `JAL` and `JALR` in decode using the existing configurable forwarding and hazard-stall policy. | Keep jump resolution in decode while handling register-dependent `JALR` targets correctly. | Agreed |
| D-022 | Trap on misaligned loads and stores before issuing any data-memory request; do not split them in hardware. | Keep baseline memory access handling simple and leave any emulation to the execution environment. | Agreed |
| D-023 | Target bare-metal software with mandatory M-mode, configurable U-mode, and physical addressing; defer PMP and other memory protection choices. | Provide privileged runtime and optional unprivileged application execution without requiring supervisor mode or virtual memory. | Agreed |
| D-038 | Give pipeline instruction state priority reset > flush > stall > normal update. | Ensure a stalled instruction can be discarded without losing a flush; preserve handling of accepted memory transactions. | Agreed |
| D-045 | Default ISA extension parameters to `ISA_M = 0`, `ISA_C = 0`, and `ISA_F = 0`. | Provide RV32I as the default ISA configuration. | Agreed |
| D-046 | Add `ISA_E`, defaulting to `0`, to select RV32E instead of RV32I when enabled. | Allow a reduced 16-register integer base while keeping `XLEN = 32` and RV32I as the default. | Agreed |
| D-047 | Enable operand forwarding by default while retaining the option to disable it. | Use available results before writeback in the default configuration and support stall-only experiments. | Agreed |
| D-048 | Hold native multi-cycle instructions in EX and apply backpressure to predecessor stages; allow older instructions in successor stages to complete. | Keep execution in order while avoiding unnecessary downstream stalls and preserving memory-response handling; custom operation integration remains TBD. | Agreed; native EX policy retained; XIF follows D-234 |
| D-049 | Make ordinary synchronous instruction exceptions precise and prioritize the oldest faulting instruction; define external bus-error side effects separately in the memory-interface contract. | Provide a defined architectural state at trap entry while distinguishing core precision from external transaction guarantees. | Agreed |
| D-055 | Support both standard `mtvec` Direct and Vectored modes. | Allow shared trap dispatch or interrupt-specific vector entries while synchronous exceptions always enter at BASE. | Agreed |
| D-056 | Execute permitted `WFI` instructions as no-ops in the baseline implementation. | Avoid a dedicated sleep/wakeup state while preserving architectural privilege checks and normal instruction retirement. | Agreed |
| D-057 | Implement standard 64-bit machine counters `mcycle` and `minstret`, with RV32 low/high CSR access. | Provide architectural cycle and retired-instruction measurements using standard RISC-V CSRs. | Agreed |
| D-058 | Select user-mode support through `ISA_UMODE`; when enabled, provide cycle/instret CSR views with U-mode reads controlled by M-mode through `mcounteren`. | Make user-mode support configurable while providing standard counter access and privilege controls in M+U builds; full hardware Zicntr support is excluded by D-060. | Agreed |
| D-059 | Default `ISA_UMODE` to `1`. | Retain M+U execution and controlled U-mode cycle/instret counter access in the default configuration. | Agreed |
| D-060 | Omit hardware `time`/`timeh`; trap their reads and leave optional time emulation to M-mode firmware using an external timer. | Avoid a dedicated timer-value input; retain timer interrupts and cycle/instret counters without claiming complete hardware Zicntr support. | Agreed |
| D-062 | Support little-endian data accesses only, with increasing byte addresses mapped to increasing byte lanes of a 32-bit bus word. | Fix byte ordering across supported privilege modes and define consistent memory-port lane numbering. | Agreed |
| D-063 | Use word-aligned 32-bit `imem` requests and an internal prefetch/alignment buffer to select and assemble instructions, including C-enabled word-crossing instructions. | Keep external fetch accesses aligned while supporting compressed instruction streams and reuse of fetched words; retain one outstanding fetch. | Agreed |
| D-064 | Support Zifencei through the `ISA_ZIFENCEI` parameter, with internal fetch-state invalidation and an explicit external-memory synchronization contract. | Allow software to synchronize instruction execution after code writes while preserving the external memory/cache boundary. | Agreed; external handshake defined by D-207 |
| D-065 | Default `ISA_ZIFENCEI` to `0` (disabled). | Keep instruction-fetch fencing optional in the default ISA configuration. | Agreed |
| D-099 | Complete all base integer ALU operations, including shifts, in one EX execution cycle, subject to operand availability and pipeline backpressure. | Keep base integer execution latency uniform in the five-stage pipeline. | Agreed; optional execution-unit latencies remain separate |
| D-100 | Support an SRAM-backed integer register file with technology-specific macro integration isolated from common core logic. | Allow SRAM storage while retaining the configured logical port requirements. | Superseded by D-101; SRAM-backed support no longer required |
| D-101 | Use flip-flop or latch storage with combinational DE reads for the initial integer register file. | Preserve the required operand-read timing and logical ports without an SRAM macro mapping. | Agreed; both backends and default defined in D-103 |
| D-103 | Support both flip-flop and latch register-file backends, selected at elaboration time, with flip-flops as the default. | Provide a portable default and a latch implementation option under the same architectural contract. | Agreed; parameter name defined by [D-135](uqu_spec.style.md#8-style-decision-record), encoding TBD |
| D-104 | Handle WB-to-DE bypassing in pipeline forwarding logic, with dependency stalls when forwarding is disabled; do not add an independent write-through bypass to either register-file backend. | Keep dependency handling centralized and consistent for native operands, decode-stage control flow, and XIF sources and paired destinations. | Agreed; paired XIF forwarding limited to the primary destination by D-230 |
| D-106 | Perform the architecturally required read/modify/write of native CSR instructions in WB, with returned GPR data and CSR updates tied to the same retiring instruction. | Keep explicit CSR execution precise without speculative architectural CSR updates; implicit updates retain their own contracts. | Agreed; uniform baseline serialization defined in D-107 |
| D-107 | Uniformly serialize all native CSR instructions, including read-only accesses: allow older instructions to drain and block younger progression beyond DE until CSR retirement or exception/flush handling. | Avoid CSR-state forwarding and per-CSR pipeline hazard classifications in the baseline. | Agreed |
| D-113 | Implement base-ISA `FENCE` as a conservative full barrier for memory and device-I/O accesses rather than selectively interpreting predecessor/successor sets. | Minimize implementation effort; fence performance is not a priority for the intended use. | Agreed; stage control and interface defined by D-205 and D-208; system-specific ordering details TBD |
| D-115 | Fail builds for unsupported parameter values or combinations, with clear diagnostics identifying the invalid settings and constraint. | Detect configuration mistakes before simulation or synthesis and prevent silent configuration changes or missing requested features. | Agreed; checking mechanism TBD |
| D-117 | Report faulting addresses in `mtval` for instruction/data misalignment and access faults, and original instruction bits for illegal-instruction traps; write zero for the baseline's other traps. | Provide useful software trap diagnostics while preserving precise instruction and fault-address association. | Agreed; custom-memory fault details remain separate |
| D-118 | Hardwire `misa` to a constant derived from the implemented RTL configuration; ignore permitted writes and provide no runtime ISA switching. | Identify the configured ISA without writable extension-selection state. | Agreed; custom-extension identification details TBD |
| D-119 | Initially hardwire `mvendorid`, `marchid`, and `mimpid` to zero as standard read-only identification CSRs. | Use permitted initial values while deferring project-specific identifiers. | Agreed |
| D-139 | Configure instruction-fetch buffer capacity through `MUA_IF_BUFFER_WORDS`, defaulting to two 32-bit word slots while retaining one outstanding fetch request. | Support instruction reuse and assembly with an adjustable buffer size independent of bus concurrency. | Agreed; supported capacities defined by D-217, prefetch policy defined by D-140 |
| D-140 | Continue filling available instruction-buffer space during downstream stalls, subject to capacity, one outstanding request, and control-flow/synchronization restrictions. | Overlap fetch latency with pipeline stalls while retaining precise fault handling and correct redirect recovery. | Agreed; detailed frontend control implementation TBD |
| D-141 | Implement compressed-instruction expansion in a separate module, initially in IF before the IF/DE register, retaining original encoding, PC, length, and fault metadata. | Reuse the native DE decoder and keep decompression placement easy to revisit after timing evaluation. | Native component under D-282; strategies under D-283; IF integration under D-287; full-core integration and timing evaluation pending |
| D-142 | Keep PMP CSRs and permission checks inside the core before memory requests; expose no privilege/PMP attributes for external enforcement, and consume external bus faults through the normal error responses. | Make protection a core responsibility while keeping the memory interface independent of PMP implementation. | Agreed; enable/default defined by D-143 and fixed capacity by D-251; remaining field details and milestone open |
| D-143 | Select internal PMP through `ISA_PMP`, defaulting to `0`; omit permission-checking logic and writable PMP-entry storage when disabled. | Keep PMP optional and preserve the default implementation scope. | Agreed; disabled CSR behavior defined by D-144; fixed sixteen-entry enabled capacity by D-251 |
| D-144 | When `ISA_PMP = 0`, keep standard PMP CSRs accessible in M-mode with reads returning zero and permitted writes ignored; retain normal CSR privilege checks. | Allow software probing without writable PMP-entry storage. | Agreed |
| D-145 | Configure the enabled internal PMP entry count through `ISA_PMP_REGIONS`, with consecutive entries starting at zero; ignore the setting when `ISA_PMP = 0`. | Allow hardware configurations to select PMP capacity while retaining the standard priority structure. | Superseded by D-251: fixed sixteen-entry capacity and no count parameter |
| D-146 | Default `ISA_PMP_REGIONS` to `8`, including as an explicitly set inactive parameter in the initial PMP-disabled configuration. | Provide eight configurable protection regions when PMP is enabled. | Superseded by D-251: fixed sixteen-entry capacity and no count parameter |
| D-147 | Fix PMP granularity at `G = 0` (four bytes) for all configured entries. | Retain fine-grained memory protection without another hardware configuration parameter. | Agreed |
| D-148 | Support OFF, TOR, NA4, and NAPOT in every configured PMP entry, using the standard address-mode encodings and range rules. | Provide all standard PMP address modes without additional hardware configuration parameters. | Agreed |
| D-149 | Reset every implemented PMP configuration byte to zero, clearing mode, lock, and permission bits. | Establish a defined startup state with all entries OFF and unlocked. | Agreed; address-register behavior defined by D-150 |
| D-150 | Leave enabled PMP address storage unreset with no guaranteed reset value; require firmware to initialize all bounds used before enabling an entry, including a TOR entry's preceding lower-bound register. | Follow the minimal-reset policy while establishing valid bounds before protection is activated. | Agreed |
| D-151 | Use a fixed single-cycle EX multiplier for `MUL`, `MULH`, `MULHU`, and `MULHSU` when `ISA_M = 1`, without a multiplier implementation selector for now. | Define multiplication latency while keeping the initial implementation choice fixed. | Superseded by D-152 |
| D-152 | Select single-cycle or internally registered multi-cycle multiplication through `MUA_MUL`, using YAML labels `single_cycle` and `multi_cycle`; retain the blocking EX policy for multi-cycle multiplication. | Allow multiplier timing experiments without changing the ISA or the five-stage pipeline contract. | Selector choices superseded by D-158; blocking EX policy retained |
| D-153 | Select the divider implementation through `MUA_DIV`, applying to signed/unsigned division and remainder; ignore `MUA_MUL` and `MUA_DIV` when `ISA_M = 0` while requiring explicit values in hardware configurations. | Configure multiply/divide microarchitecture independently of enabling the software-visible M extension. | Agreed; current parameter forms/defaults defined by D-158 and D-162; divider timing by D-155 and D-157; selector encodings and initial implementation defined in Sections 3 and 3.5 |
| D-154 | Use one iterative divider family: `MUA_DIV = iterative` means unroll factor one, and `iterative+unroll+<factor>` selects 2, 4, 8, 16, or 32 successive division steps per iteration; factor 32 fully unrolls the division steps. | Explore division latency and combinational depth through one implementation family; allow generate-based RTL without fixing its structure yet. | Unroll configuration syntax superseded by D-162; iteration semantics retained |
| D-155 | Integrate divider operand preparation into the first iteration and result sign correction/selection into the last combinationally, with no extra setup or completion cycles; provide execution latency of `32 / factor` EX cycles, including special-case results within that budget. | Make full unrolling a single-cycle execution option and avoid separate sign-handling cycles. | Superseded by D-261; fixed operand-independent timing retained |
| D-156 | Default `MUA_MUL` to `single_cycle` and `MUA_DIV` to `iterative+unroll+8`, including explicit inactive settings when `ISA_M = 0`. | Use single-cycle multiplication and exercise divider parametrization with a four-cycle baseline when the M extension is enabled. | Multiplier default superseded by D-158; divider/unroll parameter forms superseded by D-162; divider timing superseded by D-261 |
| D-157 | Require fixed, operand-independent native multiplication and division execution latency for each selected implementation; division/remainder always takes exactly `32 / factor` EX cycles, with no early completion or early result availability, including special cases. | Keep multiply/divide execution timing predictable while preserving separate pipeline stall and backpressure contracts. | Operand-independent timing and no early completion retained; divider cycle count superseded by D-261; multiplier timing defined by D-158 and D-159 |
| D-158 | Replace the multiplier outcome selectors with `parallel[+stages+<N>]` and `iterative[+unroll+<factor>]`, defaulting to `parallel`; initially infer parallel multiplication using `*`, partition registered parallel arithmetic across `N` EX cycles, and perform `32 / factor` arithmetic iterations for radix-2 iterative multiplication with factors 1, 2, 4, 8, 16, or 32. | Select multiplier architecture and its configuration while deriving execution timing and retaining constant-time, blocking EX behavior. | Iterative unroll selector syntax superseded by D-162; multiplier default superseded by D-262 and stage count limited by D-164; iterative timing defined by D-159; initial RTL structure and encodings defined in Sections 3 and 3.5 |
| D-159 | Integrate iterative-multiplier preparation/sign handling into the first iteration and final accumulation/correction/result selection into the last, with no extra setup or completion cycles; execute all four multiply instructions in exactly `32 / factor` EX cycles. | Give iterative multiplication the same fixed iteration-to-cycle mapping as division, including single-cycle execution at factor 32. | Agreed; initial iterative algorithm described in Section 3 |
| D-160 | Execute multiply instructions independently, without high/low instruction fusion or reuse of a previous instruction's product. | Retain independent execution, fixed latency, and retirement for every multiply instruction. | Agreed |
| D-161 | Reuse the EX ALU for all iterative MUL/DIV data arithmetic at factor one, including preparation and arithmetic sign correction, with no dedicated data add/sub/multiply/negation units; for unrolling, reuse the first arithmetic step and generate the additional steps as needed. | Eliminate duplicate compute arithmetic when unrolling is disabled while preserving configurable unrolling and fixed execution latency. | Agreed; sharing of additional stages defined by D-163; initial algorithms and arithmetic interface defined in Sections 3 and 3.5 |
| D-162 | Move iterative unrolling into integer parameter `MUA_MULDIV_ITERUNROLL`, accepting 1, 2, 4, 8, 16, or 32 and defaulting to 8; use `MUA_MUL = parallel`, `parallel+stages+<N>`, or `iterative`, and `MUA_DIV = iterative` (default), with no embedded unroll suffixes. | Give iterative multiplication and division one common unroll count, preserving the factor-eight divider default and requiring all hardware configurations to set the factor explicitly even when inactive. | Agreed; parallel stage count limited by D-164; selector encodings defined in config/selectors.json |
| D-163 | Share one iterative chain between MUL and DIV, comprising the EX ALU's first arithmetic step and `F - 1` additional configurable slices, where `F = MUA_MULDIV_ITERUNROLL`; when MUL is parallel, only DIV uses the iterative chain and MUL has its own parallel datapath. | Use the full configured unroll capacity for either iterative operation without separate arithmetic chains or independent factors. | Agreed; initial implementation described in Sections 3.4 and 3.5 |
| D-164 | Limit initial parallel multiplication to `parallel` (one EX cycle, default) and `parallel+stages+2` (two EX cycles with an internal register boundary); reject other explicit stage counts. | Provide one registered parallel option while keeping the implementation scope limited. | Agreed; parallel default superseded by D-262; initial partial-product partition described in Section 3 |
| D-165 | Execute division and remainder instructions independently, without instruction fusion or reuse of a previous instruction's quotient/remainder. | Retain independent computation, fixed latency, and retirement for every division or remainder instruction. | Agreed |
| D-166 | Use common request/result `valid`/`ready`/`fire` handshakes for native arithmetic execution units, with stable blocked payloads, one start and one result per live instruction, and same-edge request/result transfer for single-cycle units. | Integrate arithmetic implementations consistently while preserving fixed execution latency, blocking EX behavior, and correct backpressure handling. | Agreed; ALU/MUL/DIV cancellation defined by D-167; exact payloads, adapters, and status fields TBD |
| D-167 | Immediately cancel an affected native ALU/MUL/DIV operation on its instruction's flush, clearing active/busy, pending-result validity, and request tracking at the active clock edge with priority over stalls, progress, and transfers; suppress stale results and release the unit without waiting for completion. | Discard flushed arithmetic work promptly while preserving instruction ownership, precise side effects, and the separate memory, CV-X-IF, and interrupt contracts. | Agreed; extended to FPU operations by D-239 |
| D-168 | Use one central arbiter/controller for global events, redirects, affected-instruction flushes, and trap/interrupt draining; retain local stage/unit handshake and progress control and a separate hazard/forwarding block, preserving combinational DE branch redirection. | Make global priorities explicit while keeping execution, memory, and dependency control modular. | Agreed; exact interfaces, controller states, and detailed event eligibility/priority TBD |
| D-169 | Contain a live synchronous exception as soon as it is recognized, block or discard younger instructions, let older instructions finish, and carry the faulting instruction's metadata to WB for one architectural trap-entry event without normal retirement. | Keep trap-state updates at one point while preventing younger effects before the exception reaches WB. | Agreed; detailed event interfaces and sequencing TBD |
| D-170 | Gate younger data-memory requests until every older instruction has completed successfully or is proven unable to fault; cover reads, writes, shared-LSU custom accesses, and equivalent irreversible-effect ordering on separate custom paths. | Prevent stores and device reads from escaping before an older fault is resolved, without blocking older work or requiring a custom request's own WB commit permission. | Agreed; exact permission timing and separate-path mechanisms TBD |
| D-171 | Serialize `MRET` from DE, let older instructions finish, and perform return-state reads/updates and the redirect to `mepc` at WB; preserve DE resolution for ordinary `ret`/`JALR` and accept the later `MRET` redirect. | Favor explicit privilege-state updates and simple ordering over trap-return performance. | Agreed; detailed controller sequencing TBD |
| D-172 | Support every four-byte-aligned 32-bit `mtvec.BASE` in Direct and Vectored modes, with all BASE bits writable and no additional Vectored-mode alignment restriction. | Preserve software placement flexibility and compute the full vectored interrupt target without imposing stronger hardware alignment requirements. | Agreed |
| D-174 | Pin the 20260120 Unprivileged and Privileged Architecture manuals for the selected ISA and privilege features; require explicit decisions for additional extensions or baseline changes. | Give implementation and verification a fixed normative ISA reference while retaining separately agreed interface and debug versions. | Agreed |
| D-175 | With `ISA_E = 1`, trap instructions that use unavailable integer registers `x16`–`x31` as illegal, without execution, low-register aliasing, or CV-X-IF offload; check actual operands rather than unused or immediate fields. | Make RV32E register restrictions explicit and consistent across native and custom instructions. | Agreed |
| D-176 | Reset `mtvec` to `32'h00000000` (Direct mode, BASE zero), independently of the reset entry address input; firmware installs its desired vector before enabling interrupts. | Establish a deterministic trap entry at address zero until firmware initializes the trap vector. | Agreed |
| D-177 | Map unsupported `mtvec.MODE` writes (`2` or `3`) to Direct (`0`) while accepting the written BASE, independently of previous MODE; retain supported modes and preserve normal CSR access checks. | Define deterministic WARL behavior and legal readback without trapping solely for an unsupported mode value. | Agreed |
| D-178 | Execute WFI as a NOP in M-mode and in U-mode with `TW = 0`; immediately trap U-mode WFI as illegal with `TW = 1`. Reset TW to zero, make it M-mode writable in M+U configurations, and hardwire it to zero in M-only configurations. | Allow firmware to intercept user-mode WFI with simple privilege checks and no timeout counter. | Agreed |
| D-179 | Reset `mcycle` and `minstret` to zero and implement independently writable `mcountinhibit.CY` and `.IR`, both resetting to zero so counting is enabled after reset. | Provide deterministic counter startup and allow firmware to freeze either counter independently of user-mode read permissions. | Agreed |
| D-180 | In M+U configurations, reset M-mode-writable `mcounteren.CY` and `.IR` to zero so U-mode counter reads initially trap until firmware grants access. | Make lower-privilege counter access an explicit firmware choice while leaving counting controlled independently by `mcountinhibit`. | Agreed |
| D-181 | Retain read-only `cycle`/`cycleh` and `instret`/`instreth` aliases of the existing machine counters in both M-only and M+U configurations, with M-mode reads independent of user-mode access controls. | Keep software counter access consistent across privilege configurations without additional counter storage. | Agreed |
| D-182 | Limit performance monitoring in the first specification draft to cycle and retired-instruction counts; defer additional event counters to a later revision. | Keep the initial monitoring implementation small while retaining the existing cycle/retirement counters and controls. | Agreed; unused machine HPM CSR behavior defined by D-184 |
| D-183 | Reset `mscratch`, `mepc`, `mcause`, and `mtval` to `32'h00000000`, independently of the reset entry address input. | Give software and verification deterministic trap and scratch CSR startup values. | Agreed |
| D-184 | Make unused machine HPM counters 3 through 31, including RV32 high halves, and their event selectors return zero and ignore otherwise permitted writes, while preserving normal CSR privilege/access checks. | Provide the standard constant-zero HPM implementation without additional counter or selector storage. | Agreed |
| D-185 | Reset `mstatus.MIE`, `.MPIE`, `.MPRV`, and `.TW` to zero and `.MPP` to M-mode; reset `.FS` to Initial (`1`) with `ISA_F = 1`, otherwise hardwire FS to Off (`0`). | Establish deterministic privilege and interrupt startup state while allowing implemented floating-point instructions without a firmware FS-enable step. | Non-F reset values retained; full-F FS policy deferred by D-235 |
| D-186 | With `ISA_F = 1`, reset `fcsr` and its `frm`/`fflags` views to zero, selecting round to nearest, ties to even, with no accrued exceptions, while retaining reset FS = Initial. | Give floating-point control and status a deterministic startup state. | Full-F policy deferred; zero-reset FP CSRs retained for Zfinx by D-235 |
| D-187 | With `ISA_F = 1`, provide `32'h00000000` (`+0.0`) as the post-reset value of every floating-point register `f0` through `f31`, without firmware initialization; leave the hardware initialization mechanism open. | Give the enabled floating-point unit a defined initial register state consistent with reset FS = Initial. | Deferred with full F by D-235; no separate FP register file for Zfinx |
| D-191 | Implement Zicsr 2.0 in every configuration without an optional parameter; include it in software ISA descriptions, using `rv32i_zicsr` for the default instruction set. | Explicitly identify the mandatory CSR instructions used by the privileged core and keep software and verification ISA settings consistent. | Agreed |
| D-195 | Keep future atomic-extension and OBI atomic-operation support configurable through planned `ISA_A`, defaulting to zero; reject enabled settings until implemented and defer the detailed atomic ISA/memory profile. | Preserve a configuration path for native atomic instructions and the required memory-system support. | Agreed; implementation deferred |
| D-196 | Add planned `MUA_HARDENED`, defaulting to zero, with future OBI parity/checksum generation and checking on both ports; keep it independent of atomic-extension selection and reject enabled settings until implemented. | Make protocol-integrity support an explicit future microarchitecture feature while leaving its detailed scope and fault handling open. | Agreed; implementation deferred |
| D-199 | Give native load/store address-misaligned exceptions priority over PMP access denial for the same instruction, without requiring a PMP check or issuing a bus request; preserve the original effective address for trap reporting. | Reject unsupported misaligned data accesses early while preserving precise exception ordering. | Agreed |
| D-200 | In M+U configurations, retain written MPP values U (`0`) and M (`3`) and map unsupported values `1` or `2` to M; in M-only configurations hardwire MPP to M. Preserve architectural trap/MRET updates and normal CSR access checks. | Define deterministic privilege-field WARL behavior without storing unsupported return modes. | Agreed |
| D-201 | Hardwire `mepc[1:0]` to zero with C disabled; with C enabled, hardwire bit 0 to zero and allow bit 1 to be written. Retain upper address bits and use the same aligned value for CSR reads and MRET. | Match the configured instruction alignment and preserve halfword-aligned return addresses in compressed-instruction configurations. | Agreed |
| D-202 | Use a dedicated CSR module that checks accesses and reports exceptions; trap accesses outside the documented map as illegal, preserve mapped constant-zero/WARL behavior, and suppress ordinary CSR/GPR updates on faults through the core's precise WB trap path. | Centralize CSR legality and register semantics while retaining one architectural trap-entry mechanism. | Agreed; exact module interface and global-event update sequencing TBD; native access timing defined by D-203 |
| D-203 | Process native CSR instructions in one eligible WB cycle with combinational reads/checks/write calculation and successful updates on the active clock edge; add no CSR-unit wait states and prevent repeated updates while held. | Keep uniformly serialized CSR execution simple while preserving atomic commitment, fault handling, and normal counter progression. | Agreed |
| D-204 | Make the CSR module own architectural CSR storage and updates, including counters and enabled PMP/floating-point CSR state; provide explicit state outputs and event inputs, with the PMP permission checker separate. | Give architectural CSR state one ownership boundary while keeping event detection, global arbitration, and permission checking modular. | Agreed; exact internal interfaces and event arbitration details TBD |
| D-205 | Reuse DE serialization and WB completion for FENCE: block younger execution, let older work finish, and retire only after the required native/custom/external memory-ordering conditions are satisfied. | Reuse existing serialization control for the conservative full barrier while preserving the external ordering contract. | Agreed; interface defined by D-208; system-specific ordering details TBD |
| D-206 | Reuse DE serialization and WB completion for optional FENCE.I; hold new fetches through required synchronization, invalidate stale instruction state at completion, and restart at the fence's successor while draining and discarding stale bus responses. | Reuse serialization control and define the instruction-fetch restart point without assuming internal caches or bypassing external visibility requirements. | Agreed; interface defined by D-207; system-specific synchronization requirements TBD |
| D-209 | Hardwire `mstatush` and read-only `mconfigptr` to zero in every configuration; provide constant-zero `menvcfg` and `menvcfgh` only with U-mode enabled. Ignore otherwise permitted writes to the writable CSR addresses and preserve normal privilege, read-only-address, and unmapped-address checks. | Complete the baseline status/environment/configuration-discovery CSR choices without additional writable state. | Agreed |
| D-210 | Omit `mcounteren` with `ISA_UMODE = 0` and trap accesses to its address as illegal instructions; retain machine counters, `mcountinhibit`, and M-mode access to the read-only counter aliases. | Remove a lower-privilege access-control CSR when no lower privilege mode is implemented, without changing machine-mode counter functionality. | Agreed |
| D-211 | Make CY and IR the only writable bits in `mcountinhibit` and, when present, `mcounteren`; hardwire every other bit to zero and ignore otherwise permitted writes. | Match the cycle/retirement-only counter profile without storing unused inhibit or permission controls. | Agreed |
| D-212 | Map read-only `hpmcounter3` through `hpmcounter31` and their RV32 high halves in every configuration; return zero for M-mode reads, trap U-mode reads through hardwired-zero HPM permissions, and trap accesses requesting writes. | Provide counter aliases consistent with the constant-zero machine HPM counters and the agreed lower-privilege access controls. | Agreed |
| D-217 | Support any integer `MUA_IF_BUFFER_WORDS` capacity of at least two, including non-power-of-two values, in all configurations; retain the default of two and one outstanding fetch request, and reject invalid capacities during configuration validation. | Keep fetch storage configurable while guaranteeing space for instruction assembly across two fetch words. | Agreed |
| D-219 | Add independent boolean `MUA_FORWARD_EX_TO_DE` and `MUA_FORWARD_MEM_TO_DE` controls under the `MUA_FORWARDING` master switch; when an operand is needed in DE, use an enabled available result from its youngest older writer or stall until that writer reaches a later enabled source, retaining WB-to-DE forwarding. | Make the EX-to-DE timing path optional while supporting MEM-to-DE bypass and correct stall-based fallback without using stale older values. | Agreed; defaults defined by D-226; registered load-result rule defined by D-223 |
| D-220 | Add independent boolean `MUA_FORWARD_MEM_TO_EX`, defaulting to one and subordinate to `MUA_FORWARDING`; forward available MEM results to EX consumers or use another valid operand route or dependency stalls when the path is disabled. | Support adjacent dependent native ALU operations without requiring the combinational EX-to-DE path, while allowing experiments with MEM-to-EX bypass disabled. | Agreed; registered load-result rule defined by D-223; stall retention defined by D-224 |
| D-221 | Add independent boolean `MUA_FORWARD_WB_TO_EX`, defaulting to one and subordinate to `MUA_FORWARDING`; forward available WB results to EX consumers with the existing youngest-writer and validity checks, or use another valid route or dependency stalls when disabled. | Supply operands whose producers have advanced beyond MEM without requiring earlier DE forwarding, while retaining independent path configuration. | Agreed; stall retention defined by D-224 |
| D-222 | Resolve native integer store data through the configured operand forwarding/hazard logic in EX and retain it with the effective address before transfer to MEM; require no late store-data forwarding or register-dependency wait in MEM. | Keep register dependency resolution out of the MEM-stage LSU while preserving ordinary byte-lane and bus handling. | Agreed |
| D-223 | Require successful native load responses to be captured in core registers before their data becomes forwardable; forward the correct selected/extended value through enabled paths, with no direct external-response bypass and no fixed load-use stall count. | Separate external response timing from dependent computation while preserving variable-latency memory and precise faults. | Agreed; detailed retained-result placement/routing TBD |
| D-224 | Retain correctly resolved operands needed by a stalled consumer, or its completed result, while older producers drain; allow necessary local capture without advancing or reissuing the held instruction, and invalidate retained validity on owning flush/reset. | Prevent a stalled consumer from losing a forwarded value when its producer leaves the forwarding stage. | DE source-retention requirement superseded by selectable policy D-275; executing-consumer/result retention and protocol stability remain required |
| D-225 | Finalize nonfaulting branch/JAL/JALR resolution and any DE redirect only with the instruction's accepted DE-to-EX transfer, required operands ready, and central arbitration permitting it; wait while held and perform the action once. | Keep DE control flow simple without bookkeeping for an early redirect from a stalled branch. | Agreed; existing prediction, precise-fault, and XIF issue contracts preserved |
| D-226 | Default both `MUA_FORWARD_EX_TO_DE` and `MUA_FORWARD_MEM_TO_DE` to one, retaining their independent disable controls and the `MUA_FORWARDING` master switch. | Enable all currently selectable operand-forwarding paths in the default configuration while preserving timing and stall experiments. | Agreed |
| D-227 | Hold a native consumer in DE until every required EX operand is captured or guaranteed available through an enabled bypass on entry to EX; preserve back-to-back ALU forwarding and reject unknown pending-load/offload availability as a guarantee. | Keep unresolved operand waits out of EX without waiting unnecessarily for register writeback. | Agreed; DE-consumed operands and precise-fault handling retain their own readiness/progress rules |
| D-235 | Make ratified Zfinx 1.0 the floating-point implementation goal through optional `ISA_ZFINX = 0` by default; support RV32I and RV32E, retain zero-reset FP CSRs with FS hardwired Off, and defer full F and its separate register file with `ISA_F = 0` required until implemented. | Provide hardware floating-point computation without another 32-by-32-bit register file while preserving the default RV32I milestone and minimal integer-register reset. | Agreed; blocking-EX integration defined by D-237; implementation and timing remain TBD |
| D-236 | Implement a third combinational integer read port whenever Zfinx or three-source XIF is enabled, sharing the port with instruction-specific selection of independent Zfinx `rs3` or custom old `rd`; cover all used sources with the common dependency and forwarding logic. | Read three operands together in DE and reuse the logic across native floating-point and custom instructions. | Agreed; no extra operand-collection cycle or new port-count parameter |
| D-237 | Execute native Zfinx operations through an FPU attached to EX independently of XIF; hold EX until result/status are ready and MEM can accept them, allow older stages to drain, and commit destination and accrued exception flags at WB with no updates from discarded instructions. | Preserve the five-stage in-order model and reuse native arithmetic backpressure while leaving FPU implementation selection open. | Agreed; imported-IP language exception and FPU cancellation defined by D-238 and D-239; FPU latency policy defined by D-241; CVFPU / FPnew remains a candidate with reset, exact latencies, and tool integration open |
| D-239 | Apply the native immediate owning-instruction flush cancellation rule to the FPU: clear affected busy/result validity at the active edge, suppress result and flag updates, and release EX without waiting for completion; pending interrupts retain completion-before-entry behavior. | Keep FPU flush behavior consistent with native MUL/DIV and prevent stale results or flags from reaching another instruction. | Agreed; imported-unit cancellation wiring and validation remain implementation work |
| D-240 | Focus the current floating-point implementation on scalar Zfinx with FP32 and required integer conversions; defer packed SIMD and additional FP formats, including FP8 and FP16. | Bound the initial FPU integration to the selected ISA rather than adopting every capability offered by an imported unit. | Agreed; latency policy defined by D-241; FPU implementation selection remains open |
| D-241 | Allow backend-defined and potentially operand-dependent FPU latency without fixed-cycle padding; use request/result handshakes and backpressure to start once, retain completed data/status, and advance EX only when the result is available and MEM can accept it. | Keep FPU integration independent of an unselected implementation and configuration while preserving correct blocking pipeline behavior. | Agreed; exact backend latencies remain TBD; native integer MUL/DIV fixed-latency requirements retained |
| D-260 | Name the shared extended add/sub component `uqu_arith`; keep ALU logic/variable shifts and MUL/DIV-specific steering/fixed shifts in their enclosing blocks. | Reuse a small arithmetic primitive while preserving physical ALU sharing for the first iterative step. | Agreed; initial 33-bit implementation and carry convention described in Section 3.4 |
| D-261 | Give DIV/DIVU/REM/REMU exactly `ceil(2/F) + 32/F + 1` EX cycles: two sequential magnitude preparations at F=1 or two parallel preparations in one cycle at F>=2, followed by the iterations and one completion cycle; use existing arithmetic slices and reserve all phases for unsigned and special cases too. | Reuse available unrolled arithmetic for operand preparation while keeping latency operand-independent. | Agreed; supersedes the divider timing in D-155 and D-157; default F=8 gives six cycles; iterative MUL timing remains D-159 |
| D-251 | Fix enabled PMP capacity at sixteen configurable entries, numbered zero through fifteen, and remove the external ISA_PMP_REGIONS parameter; retain optional ISA_PMP with default zero and fixed four-byte granularity. | Provide one standard PMP capacity without region-count configuration or alternative-count implementation work. | Agreed; supersedes D-145 and D-146 |
| D-262 | Default `MUA_MUL` to `iterative` alongside `MUA_DIV = iterative`, retaining `MUA_MULDIV_ITERUNROLL = 8`; preserve parallel multiplication as an explicit configuration option. | Share the iterative arithmetic chain between MUL and DIV in the default M-enabled implementation. | Agreed; supersedes the multiplier defaults in D-158 and D-164 |
| D-263 | Place the first shared `uqu_arith` instance and its input mux in parent EX, with ALU and MUL/DIV as siblings exposing combinational arithmetic ports; retain MUL/DIV's additional `F - 1` slices and existing execution timings. | Make resource ownership explicit in the stage that already owns the executing instruction and keep the unit boundaries independent. | Agreed; supersedes the earlier ALU-owned arrangement; interfaces described in Sections 3.5 and 3.6 |
| D-264 | Keep DE/EX and EX/MEM registers in the EX stage parent; EX owns only local execution control/tracking, its functional units, and the first shared arithmetic instance. | Separate pipeline storage and instruction identity from stage execution while preserving one-time unit issue, backpressure, and age-qualified cancellation. | Agreed; EX component and parent-register fixture described in Section 3.7 |
| D-265 | Instantiate the same stateless PMP checker separately in IF and MEM, consuming PMP configuration/address state owned solely by the CSR unit through core-parent connections. | Check instruction and data accesses independently while sharing implementation and keeping architectural protection state in one place. | Superseded by D-266: core-owned two-port block with shared region decoding |
| D-266 | Place one stateless two-port PMP block in the pipeline-stage parent at core scope; share region decoding from CSR-owned state and perform concurrent independent IF/MEM address, priority, and permission checks. | Share configuration decoding explicitly while preserving simultaneous instruction/data checks and single ownership of architectural protection state. | Agreed; standalone dual-port block implemented, full-core wiring pending |
| D-267 | Implement CSRs as explicitly decoded state fields, allocating storage only for architecturally mutable fields in the selected configuration; assemble read values from state/constants/inputs/aliases and inspect representative synthesized storage. | Avoid a general writable CSR array and storage for hardwired, reserved, aliased, or disabled-feature payloads while preserving all architectural access and update semantics. | Implemented; standalone bindings and measured state budget in Section 18.2 |
| D-268 | Implement the initial decoded CSR register file with one-shot WB commitment, explicit accepted architectural events, compact M/U/mtvec/mcause fields, optional Zfinx/PMP state, reserved PMP W-only writes legalized by clearing W, and explicit rejection of deferred debug/full-F/atomic configurations. | Provide the baseline CSR component with measured configuration-dependent storage while preserving architectural access semantics and leaving global pipeline arbitration in the parent. | Debug restriction superseded by D-271; implemented under D-267; exact bindings and local priorities in Section 18.2 |
| D-269 | Keep EX/MEM and MEM/WB registers in the MEM stage's parent; MEM owns one LSU and local one-shot issue tracking, exposes the parent PMP query, and blocks replacement completion/issue while killed bus work drains without stalling older WB. | Preserve precise transaction/identity association and shared PMP ownership with minimal stage-local control. | Implemented; stage and parent-register fixture in Section 3.9 |
| D-270 | Make WB own the CSR unit and native result/commit logic while MEM/WB, GPR storage, current privilege, arbitration and redirects remain in the core parent; qualify architectural token effects with one acceptance and defer XIF/debug explicitly. | Keep native WB precise and stateless around existing CSR storage, with independent fault reporting and no repeated held-token effects. | XIF/debug deferral superseded by D-271; stage/parent fixture and event contract in Section 3.10 |
| D-271 | Complete WB standard CV-X-IF commit/result and conditional paired-write support, plus debug-only CSR state, EBREAK/DRET and debug exception routing; retain parent-owned pipeline registers, issue tracking, privilege/Debug Mode and global control. | Complete optional WB functionality with one XIF permission bit, no result queue or proprietary coprocessor channels, and compact debug state. | Implemented; extends D-268 and D-270; exact bindings and tests in the WB component guide |
| D-272 | Implement a stateless native decoder under DE, alongside DE-owned operand and branch/target logic; retain core-owned GPR storage, boundary registers and shared control. Separate static native recognition/register legality from XIF recognition and runtime permission checks. | Begin DE with a reusable combinational component and preserve existing stage/parent responsibilities and precise-exception handling. | Decoder implemented in Section 3.11; branch under D-273; DE stage and local XIF issue implemented under D-280; full-core integration pending |
| D-273 | Implement uqu_branch as a stateless DE component for comparisons, targets, links and alignment diagnostics; retain prediction/BTB in IF and transfer-qualified redirects and precise trap sequencing in DE/core. | Reuse native decoder controls while separating execution truth from frontend prediction and keeping branch arithmetic independent of EX. | Implemented; C-disabled/enabled component and decoder-fed tests, Section 6.1 |
| D-274 | Supply DE with three resolved source values, a per-source current-readiness mask and a separate per-source EX-bypass guarantee mask; require current readiness for DE consumption and current readiness or a proven EX guarantee for native EX consumption. | Preserve adjacent dependent execution without requiring EX-to-DE forwarding, while distinguishing usable values from stale inputs and keeping hazard matching in the core parent. | Agreed; contract and dependent ADD/SUB example in Section 4.1; optional DE retention owned by hazard unit under D-275 |
| D-275 | Centralize dependency/forwarding resolution in core-owned uqu_hazard, with boolean MUA_DE_OPERAND_RETENTION selecting continuous DE resolution (0, default) or local per-instruction source retention (1) behind the same DE interface. | Enable area/performance exploration without duplicating stage hazard logic, while preserving youngest-writer checks, EX guarantees and protocol-required holding state. | Implemented standalone under D-279; Section 4.2; supersedes unconditional DE retention in D-224; core/stage integration pending |
| D-276 | Make the core-owned hazard unit serve DE and EX with consumer-relative producer priority, common result qualification and register-source forwarding; preserve local stage handshakes and central global control. | Centralize dependency policy across both consumer stages without introducing late MEM operand waits or mixing bus/execution control into hazard tracking. | Implemented standalone under D-279; Section 4.2.1; MUA_DE_OPERAND_RETENTION affects only optional DE source storage |
| D-277 | Feed the hazard unit normalized EX/MEM/WB producer descriptors containing slot occupancy, up to two pending destinations, primary-result availability/forwardability/data and actual stage advance; assemble these in the core from pipeline metadata and stage outputs. | Keep pending dependencies visible before completion, prevent forwarding intermediate values and separate instruction-specific completion semantics from dependency matching. | Standalone interface implemented under D-279; Section 4.2.3; parent descriptor assembly pending |
| D-278 | Use three explicitly named DE/EX source slots with address/value/use information, a DE need-now mask, EX captured-valid bits and per-source resolved values/readiness; invalidate optional DE retention through de_valid_i/de_clear_i with clear priority at the edge and no combinational output suppression. | Keep operand availability separate from stage stall control and instruction lifetime explicit without introducing a second EX operand bank. | Standalone interface implemented under D-279; consumer/lifecycle bindings in Section 4.2.4 |
| D-279 | Implement the standalone hazard unit with normalized producer inputs, DE/EX source resolution, movement-qualified guarantees and optional DE operand retention; add explicit boolean configuration support and a retained-RV32I preset. | Make the agreed dependency policies executable and testable before assembling DE or the full core. | Implemented; Section 4.2.5 and hazard component guide; forty-profile regression, lint, configuration guards and optimized storage checks; core/stage integration pending |
| D-280 | Implement DE around decoder/branch/runtime checks and hazard-resolved sources, with parent-owned boundary registers and central permission; implement optional standard coupled XIF issue, stable operands, acceptance tracking and core-internal rejected/bad-transaction kill cleanup. | Assemble the agreed stage contract with precise early containment, guaranteed EX bypass metadata and one-time branch/offload actions while keeping core/retirement ownership explicit. | Implemented; Section 3.12; component and native parent-fixture regressions, lint and optimized-state/signal-dependency checks; full-core controller/frontend/XIF ID integration pending |
| D-282 | Implement stateless integer RV32C expansion with explicit original bits, compressed/illegal/HINT flags, C-disabled bypass and unchanged native words; preserve HINT register fields for downstream RV32E checks. | Reuse the decoder and DE, retain precise fault/link identity and eliminate expansion logic when C is disabled. | Implemented; Section 15.1; exhaustive halfword and decoder/DE integration tests; fetch assembly and optional XIF compressed-channel integration pending |
| D-283 | Select compressed decoding through MUA_C_IMPL = decompress or decode_compressed, with MUA_C_DECOMPRESS_STAGE = if or de for expansion placement; default to decompress/if and ignore the selectors when C is disabled. | Compare expansion placement against parallel direct decoding while preserving ISA, original instruction identity, shared DE execution control and standard XIF ownership. | IF/DE paths implemented and tested; Sections 15.1 and 15.5; full-core integration and PPA evaluation pending |
| D-284 | Implement uqu_ifetch as a single-word OBI engine with externally supplied core-PMP denial, latched aligned address, registered retained result/error and persistent killed-request drain; keep one shared core-owned PMP for IF and MEM/LSU. | Build IF transaction handling independently of buffering, assembly, decoding and global control while preserving protection ownership and bus obligations. | Implemented; Section 15.2; standalone and real shared-PMP/LSU fixture tests; aligner under D-285, buffer/prefetch fixture under D-286; production IF under D-287; full-core integration pending |
| D-285 | Implement stateless uqu_if_aligner over two ordered words with original instruction/length, next-PC and qualified-consumption suggestions; contain fetch faults with the correct first/second portion address and leave storage, PMP, decode and transfer control outside. | Separate word selection/assembly from transaction handling and configurable compressed decoding while preserving precise fault identity and word reuse. | Implemented; Section 15.3; C-disabled/enabled exhaustive prefix, error/availability, randomized and stream checks; buffer/prefetch fixture under D-286; production IF under D-287; full-core integration pending |
| D-286 | Implement uqu_if_buffer as a fetched-word FIFO with two read windows, simultaneous pop/push, non-power-of-two capacity and minimal reset; keep prefetch addresses, response reservation and redirect control in IF, verified by a real fetch/buffer/aligner fixture. | Separate storage from instruction selection and bus handling, reserve capacity without duplicate tracking for the one-writer/one-outstanding baseline, and preserve killed-response obligations. | Implemented; Section 15.4; standalone deque tests and C-disabled/enabled prefetch integration at depths 2, 3, 4, 5 and 8; production IF under D-287; full-core integration pending |
| D-287 | Assemble uqu_stage_if around fetch, word storage, alignment and selected IF expansion; own frontend pointers/containment while leaving IF/DE, PMP and global arbitration in the core; implement none/static_not_taken control with canonical encodings 0/1. | Make native frontend behavior concrete with reserved capacity, independent request/delivery holds, precise original instruction identity and persistent stale-transaction draining. | Implemented; Section 15.5; standalone and real IF/DE/DE parent-fixture tests across compressed paths, both branch modes and variable depths; full-core and standard XIF compressed-channel integration remain pending |
