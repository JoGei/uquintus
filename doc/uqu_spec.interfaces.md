# uquintus Core Interfaces

**Status:** First specification draft finalized, 2026-10-20

Core integration contracts, native memory ports, and optional extension/debug interfaces.

[Specification index](uqu_spec.md) · [Architecture](uqu_spec.arch.md) · [Interfaces](uqu_spec.interfaces.md) · [Verification](uqu_spec.verif.md) · [Build](uqu_spec.build.md) · [Style](uqu_spec.style.md)

Agreed requirements remain binding. Explicit proposals retain their status, and
TBD items remain implementation or integration follow-ups. Finalizing this draft
does not imply that the documented hardware or build infrastructure exists.

## 1. External instruction and data memories

**Status:** Agreed

Instruction memory and data memory shall not be part of the core. The core shall
expose a separate interface for each:

| Interface | Core access | Purpose |
| --- | --- | --- |
| `imem` | Read only | Fetch instructions in the IF stage. |
| `dmem` | Read and write | Access data for loads and stores in the MEM stage. |

The surrounding system shall provide the memories or connect these interfaces
to a memory subsystem. The core shall not issue writes through `imem`.

The standalone [LSU](../verif/sim/lsu/README.md) implements the native data port
and its transaction/completion handling. The [MEM stage](../verif/sim/mem/README.md)
owns the LSU and connects it to the parent pipeline/protection boundary.
Full-core integration and instruction-memory RTL remain separate work.

Both core-facing memory interfaces shall use 32-bit byte addresses and 32-bit
data. The `imem` interface shall return a 32-bit instruction-data word per read
response. The `dmem` interface shall provide 32-bit read and write data and four
byte-enable bits, one for each eight-bit data lane. Byte ordering and data-lane
mapping are defined in [architecture, Section 14](uqu_spec.arch.md#14-little-endian-byte-ordering). Every `dmem` request shall present the
containing word's aligned byte address, `{effective_addr[31:2], 2'b00}`;
`dmem_addr[1:0]` shall therefore be zero. Byte enables shall select the accessed
bytes within that word. The address remains a byte address, not a word index.

The LSU shall retain the original effective byte address and its offset for
alignment/protection checks, subword data selection, and informative fault
reporting through `mtval`. Aligning the external address shall not change the
instruction's effective address or permit a misaligned access that [architecture, Section 7](uqu_spec.arch.md#7-trap-on-misaligned-data-accesses)
requires to trap. Subword byte-enable and data-lane handling are defined in
[architecture, Section 14](uqu_spec.arch.md#14-little-endian-byte-ordering).

Both interfaces shall support variable latency through request/response
handshakes. The core shall accommodate memory wait states so that the surrounding
system can provide different memory hierarchies, including external caches.

The baseline native memory ports shall use the following declarations. All
directions are relative to the core; handshake and completion behavior shall
follow the rules in this section.

| Port | Direction | Width | Meaning |
| --- | --- | --- | --- |
| `imem_req_o` | Output | 1 | Instruction read request. |
| `imem_addr_o` | Output | 32 | Word-aligned instruction byte address. |
| `imem_gnt_i` | Input | 1 | Instruction request grant. |
| `imem_rvalid_i` | Input | 1 | Instruction response valid. |
| `imem_rdata_i` | Input | 32 | Instruction response word. |
| `imem_err_i` | Input | 1 | Instruction response error, sampled with response valid. |
| `dmem_req_o` | Output | 1 | Data access request. |
| `dmem_we_o` | Output | 1 | Write enable: one for stores, zero for loads. |
| `dmem_addr_o` | Output | 32 | Word-aligned data byte address. |
| `dmem_wdata_o` | Output | 32 | Store data placed in the selected byte lanes. |
| `dmem_be_o` | Output | 4 | Data byte enables. |
| `dmem_gnt_i` | Input | 1 | Data request grant. |
| `dmem_rvalid_i` | Input | 1 | Data response valid, including store completion. |
| `dmem_rdata_i` | Input | 32 | Data response word for loads. |
| `dmem_err_i` | Input | 1 | Data response error, sampled with response valid. |

The read-only instruction interface shall omit write-enable, write-data, and
byte-enable outputs. A wrapper connecting it to a full OBI interface shall
supply constant read controls (`we = 0`, `be = 4'b1111`, and inactive write
data). Neither native port shall expose response-ready backpressure. Future
atomic and integrity fields shall remain deferred under the feature profiles
below; this baseline table shall not select those fields.

Once a port asserts `req`, it shall keep `req` asserted and its request payload
stable until an active clock edge accepts `req && gnt`. The payload includes
the address and all implemented request control fields, plus write data and
byte enables where applicable. Pipeline stalls, flushes, and redirects shall
not withdraw or replace an asserted request before grant. The reserved response
capacity and request ownership shall remain tracked until the request is
accepted and its response is handled, except under the reset contract in
[interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset).

A wrong-path instruction fetch that is awaiting grant shall finish its request
handshake, then accept and discard its eventual response. Its response error
shall not cause an architectural trap. A redirect shall not replace that
request's address with the new target while `req` is asserted. Precise-effect
ordering and permission checks shall gate data requests before they are
asserted, as required in [architecture, Section 7](uqu_spec.arch.md#7-trap-on-misaligned-data-accesses), [architecture, Section 8.1](uqu_spec.arch.md#81-internal-pmp-and-memory-fault-boundary) and [architecture, Section 9.2](uqu_spec.arch.md#92-early-exception-containment-and-wb-trap-entry); request persistence
shall not authorize a younger data side effect that those rules prohibit.

The baseline shall allow at most one accepted request awaiting completion per
memory port. The ports shall be independent, allowing one instruction fetch and
one data access to be outstanding simultaneously. Each accepted request,
including a store, shall receive a completion response unless the core is reset
under the integration contract in [interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset).

The memory system may grant a request in the first cycle in which it is
presented; `gnt` may already be asserted before `req`. Request acceptance shall
occur only at an active clock edge with both signals high. The corresponding
response shall arrive one or more cycles after that grant. Grant and completion
of the same transaction shall not occur in the same cycle. These timing rules
shall apply to both ports and to both loads and stores. They shall not impose
an upper bound on grant or response latency, and shall not prohibit completion
of an older transaction in the cycle a different transaction is granted when
the outstanding-request and capacity rules permit.

This limit applies to the core-facing ports; external caches and memory systems
may perform multiple downstream transactions internally. Multiple outstanding
instruction fetches may be considered as a later optimization.

Instruction requests shall always fetch word-aligned 32-bit words. An internal
prefetch/alignment buffer shall handle instruction selection and assembly,
including halfword-aligned and word-crossing instructions when `ISA_C = 1`, as
defined in [architecture, Section 15](uqu_spec.arch.md#15-aligned-instruction-fetch-and-internal-assembly).

The initial core memory interfaces shall use **Open Bus Interface (OBI)
version 1.6.0**, as defined by the
[pinned OBI v1.6.0 specification](https://github.com/openhwgroup/obi/blob/072d9173c1f2d79471d6f2a10eae59ee387d4c6f/OBI-v1.6.0.pdf).
The baseline port list, access granularity, and handshake rules are fixed
below. Future atomic/integrity profiles and external error-side-effect
guarantees remain implementation or integration follow-ups against that version.

Both native OBI ports shall omit transaction identifier signals (`aid`, `rid`)
and user-defined payload signals (`auser`, `wuser`, `ruser`). The core shall not
require ID or user-field width parameters or metadata storage for those fields.
Responses shall be associated with each port's single outstanding request.
Interconnects, protocol adapters, and integration wrappers may add any IDs or
user metadata required by the surrounding system and shall handle their
association outside the native core interface. Connections to a fuller OBI
interface shall use the v1.6.0-defined omission/tie-off rules. This decision
shall not remove functional transaction identifiers required by CV-X-IF.

The native OBI profile shall allow future configurable atomic-operation
support, corresponding to the planned `ISA_A` feature in [architecture, Section 2](uqu_spec.arch.md#2-isa-and-microarchitecture-configuration-parameters). Atomic
request attributes and the applicable response status, such as `atop` and
`exokay`, shall be specified when that feature is implemented. Atomics shall
remain disabled by default. The core/LSU and external memory system shall
together provide the selected ISA's atomicity and ordering requirements;
exposing atomic bus signals alone shall not constitute ISA A support. The
implementation milestone, reservation handling, exact signal profile, and
external atomic-capability requirements remain TBD.

`MUA_HARDENED` shall select future OBI interface integrity support on both
ports. Its agreed minimum scope shall include generation of outgoing protocol
parity/checksum signals and checking of incoming parity/checksum signals under
OBI v1.6.0. It shall default to `0` and its implementation shall be deferred.
Exact signals, widths, checksum coverage, disabled-port declarations/tie-offs,
fault reporting/recovery, and any hardening beyond the OBI interfaces remain
TBD. This feature shall preserve the no-response-backpressure contract; any
integrity signals for omitted constant-valued protocol signals shall follow
the selected OBI profile. Atomic and integrity features shall remain separate
configuration choices. Neither enabled future setting shall be accepted before
the corresponding implementation is supported, as required in [architecture, Section 2](uqu_spec.arch.md#2-isa-and-microarchitecture-configuration-parameters).

The core shall support one error input per port, `imem_err_i` and `dmem_err_i`.
Bus-side error reporting shall be optional independently for each port. If the
connected bus does not report errors, integration logic shall tie the
corresponding core error input low; a protocol-specific wrapper may omit that
signal from its external interface. No separate core configuration parameter is
required for this tie-off.

Error status shall be sampled with the corresponding `rvalid` response and
retained with that response until consumed. An error response shall complete
the transaction rather than leave it outstanding. For a surviving native
instruction, a failed instruction fetch shall produce an instruction access
fault, a failed load a load access fault, and a failed store a store/AMO access
fault, following the precise-exception rules in [architecture, Section 9](uqu_spec.arch.md#9-precise-synchronous-exceptions) and the
[RISC-V machine-level specification](https://docs.riscv.org/reference/isa/priv/machine.html).
Failed load data shall not be written to its destination register. Discarded
fetches shall not produce architectural exceptions. Custom-operation memory
fault reporting through the core is deferred under the standard-only
profile in [interfaces, Section 5.1](uqu_spec.interfaces.md#51-initial-standard-only-scope-and-deferred-memory-features). Tying error inputs low shall not disable exceptions detected internally
by the core.

PMP permission checks and effective-privilege handling shall remain inside the
core as defined in [architecture, Section 8.1](uqu_spec.arch.md#81-internal-pmp-and-memory-fault-boundary). The native memory ports shall not expose
privilege attributes or PMP configuration/status for external enforcement.
The core-owned two-port PMP block shall consume IF/MEM access addresses and
control and return each stage's permission result; CSR state connects only to
that block, with shared region decoding internal to it.
The core shall consume external bus-error responses and combine them with
internally detected access failures under its precise-exception contract.

The core shall not implement internal bus timeouts on either memory port.
Request-grant and response waits shall have no core-imposed cycle limit. A
prolonged wait shall not by itself generate an exception, cancel a transaction,
or cause the core to retry it. An unresponsive memory system may therefore
block execution indefinitely, subject to the separately defined reset contract.

Any required timeout detection and recovery shall reside in the surrounding
memory system or bus adapter. Such logic may report a failed access through
the optional error-response mechanism. Handling of late downstream responses
after an externally generated timeout shall be the responsibility of that
external logic; the core shall still observe one completion per accepted
request unless reset under [interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset). The detailed external timeout policy
remains outside the core contract.

Both OBI ports shall omit response backpressure: no `rready` output shall be
required, equivalent to keeping response readiness asserted. Every `rvalid`
response shall be accepted on the active clock edge, independently of pipeline
stalls. Accepting a response shall not require advancing its instruction.

Before asserting a request, the core shall reserve sufficient capacity to
retain its response data and any completion status until consumed. Existing
pipeline or fetch-buffer storage may provide this capacity; a separate buffer
is not required. The core shall not issue another request when retained,
unconsumed responses leave insufficient capacity for its eventual response.
This capacity rule applies in addition to the one-outstanding-request limit.

Response capture and accepted-transaction tracking shall remain active during
pipeline stalls. A flush shall not cancel an accepted bus transaction: its
response shall still be accepted and, if the associated instruction has been
discarded, discarded without producing an architectural result or trap.
Reset shall clear core transaction tracking; integration shall prevent stale
responses from reaching the core after reset, as defined in [interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset).

Wishbone, AXI, TileLink, and other external bus interfaces may be added later.
The agreed native-core and adapter architecture is defined in [interfaces, Section 7](uqu_spec.interfaces.md#7-native-obi-core-and-protocol-variants).

## 2. Single clock domain

**Status:** Agreed

All sequential logic in the core shall operate in one clock domain, driven
by the `clk_i` input. The core-facing instruction and data memory interfaces shall be synchronous to
that clock. The three machine interrupt inputs shall also be synchronous to
the core clock, as specified in [interfaces, Section 4](uqu_spec.interfaces.md#4-external-machine-interrupt-sources).

Any clock-domain crossings to external buses, caches, memories, or interrupt sources shall be
handled outside the core by the surrounding system or integration wrappers.
The default reset convention is defined in [interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset).

The initial portable pipeline RTL shall express register holds through update
enables on logic clocked by `clk_i`; it shall not instantiate explicit pipeline
clock gates. Enable conditions shall preserve the existing local stall and
global control contracts: a held stage shall not unnecessarily stop older
stages from draining, and required bus-response capture shall remain active.
Machine cycle counting shall continue during stalls unless inhibited under
[architecture, Section 12](uqu_spec.arch.md#12-machine-cycle-and-instruction-retirement-counters). Synchronous reset shall take priority over normal update enables.

ASIC synthesis may transform suitable groups of enabled registers into
integrated clock-gating implementations, provided the documented functional,
reset, and timing behavior is preserved. Such gates shall derive from the core
clock and shall not introduce an independent asynchronous clock domain.
Clock-gating insertion shall require appropriate flow configuration and
technology mapping; its availability or use shall not be assumed merely from
selecting ORFS. The
[Yosys clockgate pass](https://yosyshq.readthedocs.io/projects/yosys/en/v0.55/cmd/clockgate.html)
is a reference for this synthesis transformation. Target-specific mapping,
clock-tree treatment, and implementation verification remain flow details.

Explicit clock control needed by the latch-based register file shall be
permitted and isolated inside that backend under [architecture, Section 17](uqu_spec.arch.md#17-integer-register-file-implementation). Its clock
phases, gate behavior, and technology-specific implementation shall remain
separate from pipeline control and preserve the common register-file contract.

## 3. Active-low synchronous reset

**Status:** Agreed

The default core reset input, `rst_ni`, shall be active-low and synchronous
to the core clock.
Reset shall be sampled on the active clock edge and take priority over normal
state updates, stalls, and enables. The core clock shall run while reset is
applied.

Integration shall assert reset across at least one rising core-clock edge,
meeting the receiving registers' setup and hold requirements. One such edge
shall be sufficient to establish the core's documented reset state; no
multi-cycle reset sequence shall be required by the core. The reset entry
address shall meet setup and hold timing at each edge on which it is sampled
during reset. Any longer reset duration required by external memories,
interconnects, or other system components shall be an integration requirement.

Reset coverage shall include architectural, control, and pipeline state, using
a minimal, explicitly documented set of reset registers:

| State | Required reset behavior |
| --- | --- |
| Architectural | Establish the reset PC, M-mode entry, and documented register and CSR reset values consistent with the selected ISA. |
| Machine trap vector | Reset `mtvec` to `32'h00000000` (Direct mode, BASE zero), independently of the reset entry address input ([architecture, Section 10](uqu_spec.arch.md#10-direct-and-vectored-trap-dispatch)). |
| Machine trap and scratch CSRs | Reset `mscratch`, `mepc`, `mcause`, and `mtval` to `32'h00000000` ([architecture, Section 18](uqu_spec.arch.md#18-native-csr-instruction-execution)). |
| Machine status | Reset `MIE`, `MPIE`, `MPRV`, and `TW` to zero and `MPP` to M-mode; hardwire `FS` to Off (`0`), including when Zfinx is enabled ([architecture, Section 8](uqu_spec.arch.md#8-bare-metal-execution-with-configurable-user-mode)). |
| Machine interrupt enables | Reset `mie.MSIE`, `.MTIE`, and `.MEIE` to zero; pending indications reflect external levels after reset release ([interfaces, Section 4](uqu_spec.interfaces.md#4-external-machine-interrupt-sources)). |
| Floating-point control/status, with `ISA_ZFINX = 1` | Reset `fcsr` to zero, selecting round to nearest, ties to even, with accrued exception flags cleared; `frm` and `fflags` aliases reflect the same state. No separate FP register file or additional integer-register reset requirement ([architecture, Section 8](uqu_spec.arch.md#8-bare-metal-execution-with-configurable-user-mode)). |
| WFI interception | Reset `mstatus.TW` to zero; hardwire it to zero in M-only configurations ([architecture, Section 11](uqu_spec.arch.md#11-wfi-as-a-no-op)). |
| Machine counters and inhibit control | Reset both 64-bit counters (`mcycle`, `minstret`) and `mcountinhibit.CY`/`.IR` to zero, enabling counting after reset ([architecture, Section 12](uqu_spec.arch.md#12-machine-cycle-and-instruction-retirement-counters)). |
| User counter permissions, when enabled | Reset `mcounteren.CY` and `.IR` to zero, disabling U-mode counter reads until M-mode grants access ([architecture, Section 13](uqu_spec.arch.md#13-user-visible-counters-and-firmware-emulated-time)). |
| PMP configuration, when enabled | Clear every implemented configuration byte to zero, leaving all entries OFF and unlocked with permission bits cleared ([architecture, Section 8.1](uqu_spec.arch.md#81-internal-pmp-and-memory-fault-boundary)). |
| PMP address registers, when enabled | Leave `pmpaddr*` storage unreset with no guaranteed reset value; firmware initializes required bounds before enabling entries ([architecture, Section 8.1](uqu_spec.arch.md#81-internal-pmp-and-memory-fault-boundary)). |
| Control | Establish a defined idle/startup state and inactive memory requests. |
| Pipeline | Establish an empty, deterministic startup state, including cleared valid bits and defined control state. |
| Memory transaction tracking | Clear outstanding-request and retained-response validity for both ports; do not wait for pre-reset transactions to drain. |

The surrounding integration shall handle requests and transactions that were
pending before reset. It shall prevent responses from pre-reset transactions
from reaching the core after reset release or being mistaken for responses to
new requests. Coordinated reset, external draining, or isolation may be used;
the mechanism is an integration choice. The core shall not retain transaction
history across reset or perform a post-reset drain of old transactions. Reset
shall not imply that external writes or device side effects have been undone.

The register list and reset values shall be explicit so verification can check
the reset contract. Simulation shall apply the actual reset sequence rather
than rely on blanket zero initialization. Tests shall cover arbitrary state
before reset and reset during execution.

The reset entry address shall be provided through the 32-bit `boot_addr_i`
input rather than an RTL parameter. The core shall sample it on active clock edges while reset is
asserted to establish the reset PC. Changing this input after reset shall not
redirect instruction execution. Integration shall supply a four-byte-aligned
address, with `boot_addr_i[1:0] = 2'b00`, in every configuration, including
when `ISA_C = 1`. The port shall remain a full 32-bit byte address. This boot
alignment requirement shall not restrict subsequent instruction addresses:
with C enabled, execution shall continue to support halfword-aligned
instructions and branch/jump targets under the configured ISA.

The core clock/reset inputs shall use these agreed names:

| Signal | Meaning |
| --- | --- |
| `clk_i` | Core clock. |
| `rst_ni` | Active-low synchronous core reset. |
| `boot_addr_i[31:0]` | Four-byte-aligned reset entry byte address. |

Exact register coverage and values beyond those already specified, and external
reset conditioning, remain TBD. Naming conventions are defined in the
[RTL style guide](uqu_spec.style.md).

## 4. External machine interrupt sources

**Status:** Agreed

The core shall expose separate inputs for the standard machine software, machine
timer, and machine external interrupt sources. Their pending and enable behavior
shall follow the selected privileged ISA's `mip`, `mie`, and `mstatus` rules.

| Interrupt source | Core input | Width | External responsibility |
| --- | --- | --- | --- |
| Machine software | `irq_software_i` | 1 | Generate the software interrupt indication. |
| Machine timer | `irq_timer_i` | 1 | Maintain the timer and compare logic and generate the timer interrupt indication. |
| Machine external | `irq_external_i` | 1 | Collect and arbitrate device interrupt sources and present the external interrupt indication. |

All three interrupt inputs shall be active-high and level-sensitive. The
core-facing levels shall meet the core clock's setup and hold requirements.
Asynchronous interrupt sources shall be synchronized by the surrounding system
or an integration wrapper before reaching the core. The core shall not require
internal IRQ synchronizers. Source capture and any pulse stretching needed to
provide these level-sensitive inputs shall be integration responsibilities;
the core shall not guarantee capture of asynchronous or short interrupt pulses.

The corresponding pending bits shall reflect their input levels, independently of
whether interrupt delivery is enabled; they shall not be sticky edge-capture
latches inside the core:

| Source | Pending bit in `mip` | Writable enable bit in `mie` |
| --- | --- | --- |
| Machine software | `MSIP` (bit 3) | `MSIE` (bit 3) |
| Machine timer | `MTIP` (bit 7) | `MTIE` (bit 7) |
| Machine external | `MEIP` (bit 11) | `MEIE` (bit 11) |

The three enable bits shall be writable by M-mode software and shall reset to
zero. Delivery shall additionally follow the applicable privilege and global
interrupt-enable rules. Masking a source shall not clear its pending indication.
An asserted input after reset release shall be visible as pending even though
the corresponding enable bit resets to zero.

The three pending bits shall be read-only fields of `mip`. Otherwise permitted
CSR writes to these fields shall be ignored; CSR reads, trap entry, and `MRET`
shall not clear them. Firmware shall clear each interrupt through its external
source or controller so that the corresponding input deasserts. A source that
remains asserted shall remain pending and can cause another interrupt when
eligible. Normal CSR privilege/access checks shall still apply. See the
[RISC-V machine interrupt registers](https://docs.riscv.org/reference/isa/priv/machine.html).

Only bits 3, 7, and 11 shall be active in `mie` and `mip` for this draft.
Every other bit, including supervisor and platform-specific interrupt fields,
shall read zero and ignore otherwise permitted writes. These constant fields
shall require no writable storage and shall not cause an exception solely
because software writes a nonzero value to them; normal CSR privilege and
access checks shall still apply. No additional direct interrupt sources shall
be required. Additional device sources shall be aggregated outside the core
and delivered through the machine external interrupt input.

The timer and interrupt controller shall reside outside the core. Their
memory-mapped registers, device routing, and any source-specific acknowledgement
or completion operations belong to the surrounding system. The core shall
provide architectural interrupt handling and trap entry.

CLIC/ACLIC support shall be outside the scope of this specification draft. The
core shall not require their additional interrupt identity/priority interfaces,
controller CSR extensions, hardware-managed priority preemption, interrupt
jump-table loads, or automatic context save/restore. No CLIC/ACLIC configuration
parameter or reserved integration interface shall be required. Such support
shall not be a committed later milestone; any future addition shall require an
explicit design decision and a pinned specification revision.

This exclusion shall preserve the agreed standard machine software, timer, and
external interrupt inputs and Direct/Vectored `mtvec` modes. The external timer
and interrupt-controller implementation shall remain an integration choice;
PLIC-style external-interrupt delivery shall not imply a requirement to build
a PLIC inside the core. Software-managed nesting under the baseline privileged
ISA shall not be excluded by this decision.

When an interrupt is eligible, the core shall stop issuing new instructions and
allow instructions already executing in EX/MEM/WB to drain. Interrupt entry
shall wait for those native and custom operations and accepted data-memory
transactions to finish. A pending interrupt shall not cancel, suspend, or
restart those draining operations. Older instructions in MEM and WB shall
continue to drain under the normal backpressure rules. An accepted speculative
XIF offload still held in DE shall instead follow the eviction rule below.

A synchronous exception from an instruction already in EX/MEM/WB shall take
priority over the pending interrupt, following [architecture, Section 9](uqu_spec.arch.md#9-precise-synchronous-exceptions). A faulting operation
shall report its exception and terminate according to its fault contract;
successful execution of the faulting instruction is not required before taking
its exception. This priority shall not extend to an unexecuted instruction
still held in DE.

Interrupt entry shall occur at a precise instruction boundary, with `mepc`
identifying the next instruction to execute on return. Instructions beyond that
boundary shall not commit architectural effects. Interrupt eligibility shall
be checked against the current pending and enable state, including changes made
by completing instructions, according to the selected privileged ISA.

The interrupt drain boundary shall be entry into EX. Once interrupt draining
begins, no new DE-to-EX transfer or new XIF issue shall be accepted. Native
instructions already in EX, MEM, or WB shall continue toward completion under
the rules above; a waiting native DE instruction shall remain unexecuted and
shall not redirect fetch or perform its ordinary execution action during the
drain.

An eligible interrupt shall take priority over a synchronous exception
recognized on the instruction still in DE, including `ECALL`, illegal-instruction
detection, or a fetch exception carried into DE. This rule shall also apply
when the DE exception and interrupt eligibility are recognized in the same
cycle: no DE-to-EX transfer, including an exception-token transfer, shall
occur on that interrupt-drain boundary. Older EX/MEM/WB exceptions shall
retain their priority and may supersede interrupt entry during the drain.
The DE exception shall not update trap CSRs or count as retired if the
instruction is discarded for interrupt entry.

If interrupt eligibility ceases before entry, normal execution or exception
handling shall resume from that first unexecuted instruction, preserving its
fault metadata or fetching it again as appropriate. The instruction shall
not be skipped. Interrupt eligibility checks after `MRET` and writes to
relevant interrupt-control CSRs shall precede admission of subsequent
instructions, including a potentially faulting return-target instruction,
as required by the pinned privileged ISA.

If interrupt entry proceeds, `mepc` shall identify that waiting DE instruction,
which shall be discarded from the pipeline and fetched again after return.
If DE is empty, `mepc` shall instead identify the next architecturally
unexecuted instruction using the tracked control-flow state, not an aligned
or speculative prefetch-request address. Synchronous fault priority and
interrupt eligibility re-evaluation shall remain unchanged.

With `XIF = 1`, an offload already accepted but still held in DE when draining
begins shall be evicted through the CV-X-IF kill mechanism. It has not received
WB commit permission. The core shall notify the coprocessor using
`commit_valid = 1` and `commit_kill = 1` for the corresponding identifier
before interrupt entry, preserving the selected interface's ordering rules
and notifications for older offloads. The killed instruction shall receive no
permission to commit, produce no result transaction or architectural write,
and shall not count as retired. The core shall not wait for its speculative
arithmetic computation to finish. A request not yet accepted may instead be
retracted under the interface rules.

The evicted instruction's PC shall remain the first unexecuted PC used for
interrupt `mepc`, and normal return shall fetch and issue that instruction
again under the ordinary identifier rules. Eviction shall not advance the
architectural resume point. If eligibility changes and interrupt entry does
not proceed, execution shall likewise resume from that first unexecuted PC;
the canceled instruction shall not be silently skipped or reused as a live
accepted transaction. Detailed recovery sequencing remains an implementation
choice.

DE offloads shall remain safe to kill: they shall leave no irreversible memory
or device effects. Any permitted speculative transactions already accepted
shall retain the tracking needed for completion/discard without architectural
results or faults from the killed instruction. Killing the offload shall not
cancel those transactions or imply that their external effects can be undone.
Any independently connected coprocessor memory path shall enforce this
requirement under [interfaces, Section 5.1](uqu_spec.interfaces.md#51-initial-standard-only-scope-and-deferred-memory-features) without extra core interface signals;
shared-LSU access shall remain deferred. Offloads already in EX/MEM/WB shall continue to follow the
finish-before-interrupt policy, even if commit permission has not yet been
granted; an offload granted commit permission shall never subsequently be
killed.

Interrupt latency shall include remaining execution and memory wait times,
including those of custom operations. No fixed maximum latency is promised
without bounds on operation completion and external-memory response times.

The input names and drain/exception arbitration rules above are agreed.
Native controller sequencing is implemented in
[architecture, Section 3.2.1](uqu_spec.arch.md#321-core-owned-pipeline-control-implementation).
Full-core source/state wiring and optional XIF/debug cleanup remain integration
work; required architectural priorities shall follow the pinned privileged ISA.

## 5. CV-X-IF custom extension interface

**Status:** Optional CV-X-IF v1.0.0, disabled default, parallel decoding, and a
standard-only core/coprocessor connection agreed; result delivery shall be in
issue order; shared-LSU access and coprocessor-generated execution traps deferred

The connection between the core and coprocessor shall use only signals and
packet fields defined by the selected ratified CV-X-IF v1.0.0 interface.
No uquintus-specific memory-request, memory-completion, fault, progress, or
other auxiliary channel or sideband shall be added to that connection.
Plain-Verilog representations of the standard interface shall preserve this
boundary. Earlier memory-integration requirements that depend on such
additions are deferred under [interfaces, Section 5.1](uqu_spec.interfaces.md#51-initial-standard-only-scope-and-deferred-memory-features) and shall not override it.

The `XIF` RTL parameter shall select CV-X-IF support at elaboration/synthesis
time. With `XIF = 1`, the design shall provide a custom extension interface based on the ratified
[CV-X-IF v1.0.0 release](https://github.com/openhwfoundation/core-v-xif/releases/tag/v1.0.0)
and its multi-interface offload model. The initial core connection shall use
the standard-only scope in [interfaces, Section 5.1](uqu_spec.interfaces.md#51-initial-standard-only-scope-and-deferred-memory-features); shared-LSU access and
coprocessor-generated execution traps shall be deferred. Independent
coprocessor memory paths remain system-integration concerns under that scope.
The remaining optional interface features and implementation details remain TBD.

With `XIF = 0`, extension-specific logic shall be excluded at elaboration or
eliminated by synthesis. The core shall not issue extension requests, depend on
extension responses, or stall waiting for an extension. Instructions unsupported
by the configured native ISA shall raise an illegal-instruction exception when
they reach execution. Disabling `XIF` shall not disable native ISA features
selected through other parameters. XIF ports shall remain present with the same
declarations in both enabled and disabled configurations. When disabled, all
core-driven XIF outputs shall be tied to deterministic inactive values, and all
XIF inputs shall be ignored. Wrappers may hide unused XIF ports.

The default shall be `XIF = 0` (disabled).

With `XIF = 1`, native and extension instruction recognition shall operate in
parallel within DE. Instruction bits shall be presented concurrently to both
decoders; the extension's instruction recognition shall not wait for the native
decoder's unsupported-instruction result or for `issue_valid`. Recognition
results and the issue handshake shall qualify the final offload decision.
This shall not require an additional pipeline stage. DE may stall for operand
dependencies or extension backpressure.

With `ISA_E = 1`, the unavailable-integer-register checks in [architecture, Section 2](uqu_spec.arch.md#2-isa-and-microarchitecture-configuration-parameters) shall
also apply to custom instructions, including used third-source and paired-write
destinations. The attached coprocessor shall be RV32E-aware and reject encodings
whose actually used sources or written destinations name `x16`–`x31`, even when
it must reject without waiting for unavailable operands. Such instructions shall
follow the normal illegal-instruction trap path. Checks shall not reject
immediate or unused fields merely because their bit patterns resemble unavailable
register indices.

This is an integration requirement: the standard issue response identifies
used registers, and its fields shall not feed combinationally back into CPU
issue/register request outputs. DE shall defensively validate accepted
read/write requirements. If a noncompliant coprocessor accepts an unavailable
register, the core shall contain the instruction, issue its standard kill
notification and transfer an illegal-instruction token only after cleanup is
acknowledged by the core/WB arbiter. No proprietary coprocessor signal or
architectural effect shall result from the invalid acceptance.

Instruction issue and operand delivery shall both occur in DE using the coupled
[CV-X-IF register interface](https://docs.openhwgroup.org/projects/openhw-group-core-v-xif/en/v1.0.0/x_ext.html#register-interface)
configuration, `X_ISSUE_REGISTER_SPLIT = 0`. Issue and register transactions shall
use matching identifiers and coupled valid/ready handshakes. Operand availability
shall be indicated through `rs_valid`; the coprocessor shall wait for the operands
the instruction actually uses, without requiring unused operands to be available.
Available operands shall follow the configured forwarding and hazard policy.
Once valid within a transaction, an operand shall remain valid and stable until
the transaction completes or is retracted under the interface rules. If an
accepted offload remains held in DE because the next stage cannot accept it,
the core shall remember acceptance and shall not issue it a second time.

Each XIF source operand shall be 32 bits wide. The interface profile shall fix
`X_RFR_WIDTH = 32` and `X_DUALREAD = 0`; paired-register source reads shall not
be supported. These fixed profile values shall not be independently configurable.
Optional paired-register result writes remain independent of source width.

The `XIF_NUM_RS` elaboration parameter shall select two or three XIF source
operands and shall default to `3`. With `XIF_NUM_RS = 3`, custom ternary operations
shall use the destination register's value as one source
before the instruction writes it, using the shared `rd`/third-source field at
instruction bits `[11:7]`. The other sources use the standard `rs1` and `rs2`
fields at `[19:15]` and `[24:20]`. Using `rs0` to denote the destination source:

```text
rs0 = old value of rd
rd <- fn(rs0, rs1, rs2)
```

CV-X-IF calls this third source `rs3`: interface operands `rs[0]`, `rs[1]`, and
`rs[2]` shall carry `rs1`, `rs2`, and the old value of `rd`, respectively.
Dependency detection and optional forwarding shall cover all requested sources,
including an earlier instruction's pending write to `rd`. Sharing the encoding
field does not eliminate the need to access three source values.

The third integer register-file read port shall be shared with native Zfinx
instructions under [architecture, Section 17](uqu_spec.arch.md#17-integer-register-file-implementation). It shall be present whenever `ISA_ZFINX = 1`
or (`XIF = 1` and `XIF_NUM_RS = 3`). All three requested source values shall be
readable in the same DE cycle, subject to operand availability. XIF-specific
operand delivery and dependency/forwarding logic shall be active only when
`XIF = 1` and `XIF_NUM_RS = 3`; disabling XIF shall not remove a port required by
Zfinx. Three-source custom operations shall still require `XIF = 1` and
`XIF_NUM_RS = 3`.

The `XIF_DUALWRITE` elaboration parameter shall enable paired-register writeback
and shall default to `0`. With `XIF_DUALWRITE = 0`, an XIF instruction may write
one 32-bit destination register (`X_RFW_WIDTH = 32`). With `XIF_DUALWRITE = 1`,
the interface shall carry 64-bit results (`X_RFW_WIDTH = 64`) and may write an
even/odd register pair selected by an even `rd`, following CV-X-IF's write-enable
rules. A paired write targeting `x0`/`x1` shall be ignored in its entirety.
Single-register writes shall remain supported when dual writeback is enabled.

A paired write shall still have one result transaction and retire as one
instruction. Dependency handling shall account for both destinations, while
only the primary even `rd` result shall be eligible for WB-to-DE/WB-to-EX
forwarding under [architecture, Section 4](uqu_spec.arch.md#4-configurable-operand-forwarding). Consumers of the secondary odd `rd + 1` result
shall wait for register-file visibility. This forwarding restriction shall
not serialize the paired architectural writes: both shall still update
together as specified below. Dual-write-specific core logic shall be included only when
`XIF = 1` and `XIF_DUALWRITE = 1`. In that configuration, the integer register file
shall provide two write ports so both destinations of a paired result update
on the same clock edge in one WB cycle. The second write port and its
XIF-specific control logic shall be excluded at elaboration or eliminated by
synthesis when either feature is disabled. The two ports shall serve the same
retiring instruction; they shall not permit two instructions to retire in one
cycle. Retirement and interrupt entry shall not expose a partially completed
paired write; trace and RVFI coverage of both destination updates shall be
specified explicitly.

The integration shall support multiple offloaded instructions in flight.
Single-issue, in-order execution shall not impose a one-offload-in-flight limit.
Each live offload shall be tracked by its CV-X-IF identifier and the instruction
metadata required for dependency handling, flushes, completion, and in-order
retirement. An older offload awaiting completion shall not by itself require
serialization of all later independent offloads; dependencies, available
pipeline/tracking capacity, and interface backpressure may still cause stalls.
The blocking native multi-cycle EX policy in [architecture, Section 3](uqu_spec.arch.md#3-classical-five-stage-pipeline) shall not impose a
one-offload-in-flight limit on CV-X-IF.

Offloaded instructions shall remain represented in the normal pipeline slots
through WB, carrying their PC, validity, CV-X-IF identifier, and required
instruction metadata. They shall not leave the pipeline to wait in a separate
retirement queue. WB shall hold an offloaded instruction until its matching standard result is
available. No separate coprocessor memory-completion input shall be required
by the initial profile. A late result shall
backpressure predecessor stages as their available slots fill; younger
instructions shall not retire past the waiting instruction. Result acceptance,
architectural writeback, and retirement shall occur exactly once.

Holding pipeline state shall not stop coprocessor execution, result delivery,
or the handling of accepted memory transactions needed to complete the waiting
instruction. Exact result handshaking and any buffering for backpressure remain
TBD.

The coprocessor shall deliver results in accepted issue order, excluding killed
instructions. Rejected and killed instructions shall not produce result
transactions. Only the oldest accepted, non-killed offload still awaiting its
result may be presented on the result interface. This applies even when an
instruction does not write a core register. Native and offloaded instructions
shall retire together in program order.

This result-ordering restriction is part of the uquintus integration profile;
CV-X-IF itself permits out-of-order result delivery. If a coprocessor completes
computations out of order internally, it or its integration adapter shall
restore the required order before presenting results to the core. The core
shall not be required to reorder coprocessor results. This restriction shall
not serialize offload issue until the previous instruction's result arrives.

The core shall support up to four accepted live offloads, one in each of DE,
EX, MEM, and WB. Native instructions occupying those slots shall reduce the
available offload capacity. The design shall not add a separate offload or
retirement queue to extend this limit. Buffers used to retain an existing
instruction's result shall not create additional accepted instruction slots.

The interface profile shall fix `X_ID_WIDTH = 3`, providing eight identifier
values. This shall be a fixed profile setting rather than an additional
externally configurable hardware parameter. A simple sequential identifier
counter shall supply new issue transactions, wrapping within the three-bit
space subject to the selected CV-X-IF identification and ordering rules.
An identifier shall be reserved when a new issue request is first presented,
including before acceptance, and shall remain associated with that transaction
and its instruction as it progresses through the pipeline.

The same identifier shall accompany related issue, operand, commit/kill, and
result transactions. The core shall stall new issue if no next identifier
can safely be used, even when an instruction slot is otherwise available.
It shall not reuse an identifier belonging to a live interface transaction or
violate the protocol's relative-age/wraparound constraints. Release/reuse
shall follow the applicable completion, rejection, retraction, and kill rules;
pending notifications and residual custom-memory tracking shall not be confused
with a later instruction reusing the same identifier. Killed instructions shall
not wait for a result transaction under the existing kill contract.

Successful WB commit permission shall remain in program order. Kill
notifications may identify a younger speculative instruction while an older
offload continues toward WB. Result identifiers shall be matched against the
appropriate WB instruction under the agreed in-order result profile. These
identifiers shall not require a result-reordering structure or additional
per-instruction sequence tags for pipeline visibility. See the
[CV-X-IF identification rules](https://docs.openhwgroup.org/projects/openhw-group-core-v-xif/en/v1.0.0/x_ext.html#identification).
Exact result buffering and detailed identifier-state implementation remain
implementation work.

For a surviving accepted offload, the core shall grant CV-X-IF commit permission
when the instruction reaches WB and all older instructions have completed.
It shall signal `commit_valid = 1` with `commit_kill = 0` for the corresponding
identifier exactly once, independently of `result_valid` or result availability.
If WB remains stalled awaiting the result, the permission shall not be repeated.
The coprocessor may compute speculatively before this permission, subject to
CV-X-IF's commit/kill rules. The core shall not wait for a result before granting
the permission required to produce that result.

Commit permission shall not itself retire the instruction. Architectural
writeback and retirement shall wait for its matching standard result
completion under the initial profile in [interfaces, Section 5.1](uqu_spec.interfaces.md#51-initial-standard-only-scope-and-deferred-memory-features). Flushed instructions shall follow the kill contract instead
of receiving permission to commit; kill notification need not wait for WB.
Permission to commit shall preserve the existing precise-trap and commit/kill
contracts.

Following the [CV-X-IF issue protocol](https://docs.openhwgroup.org/projects/openhw-group-core-v-xif/en/v1.0.0/x_ext.html#issue-interface),
when `XIF = 1`, instructions not recognized as legal by the core shall be offered for offload.
The extension decodes `issue_req.instr` and responds with `issue_resp.accept`,
operand-read requirements, and writeback information. Rejection at an issue
handshake shall lead to an illegal-instruction exception if the instruction
reaches execution; `issue_ready = 0` means backpressure, not rejection.

### 5.1. Initial standard-only scope and deferred memory features

**Status:** Ratified CV-X-IF v1.0.0 retained; shared-LSU access and
coprocessor-generated execution traps deferred

The initial XIF profile shall use the unmodified CV-X-IF v1.0.0 channels
and packet fields. That revision includes neither memory-request/result
channels nor an execution-exception field in its result packet. See the
[CV-X-IF interface specification](https://docs.openhwgroup.org/projects/openhw-group-core-v-xif/en/v1.0.0/x_ext.html).

An offloaded instruction shall not request accesses through the core LSU or
`dmem` port in this profile. It shall pass through EX and MEM subject to
ordinary pipeline capacity and control, without waiting for a separate
coprocessor memory-completion signal. At WB, commit permission and the
matching standard result transaction shall provide the existing completion
sequence. No additional memory, fault, progress, or completion sideband shall
be introduced.

Coprocessor-generated execution traps shall not be supported by this initial
profile. Rejection of an unsupported instruction at issue shall still use the
core's existing illegal-instruction path; rejection shall not be treated as
an execution-time exception report. Accepted, surviving offloads shall
complete through the standard result interface. Any instruction-defined
error/status values returned as ordinary register data shall follow that
custom instruction's software contract; no universal error encoding or
automatic conversion of result data into a CPU trap shall be required.

A coprocessor may have an independently connected system-level memory path
outside the core/CV-X-IF connection. Such integration shall preserve
speculative kill safety, ordering, protection, and completion requirements
without additional core interface signals or coprocessor-generated CPU traps.
All work required for a surviving instruction's architectural completion
shall be complete when its standard result transaction completes. The core
shall not independently observe that memory path's progress or errors, and
internal core PMP shall not be assumed to protect it. Detailed private-memory
integration remains outside the initial core interface profile.

The earlier shared-LSU routing, multi-access MEM sequencing, custom memory
fault reporting, and partial-effects-on-trap policy shall be deferred outside
this initial profile. D-053, D-054, D-089 through D-091, and D-232 retain
their earlier design intent in the decision record, with status updated by
D-234. The partial-effects policy shall not be an active exception to the
baseline precise synchronous trap rules. Selecting this scope shall not
implicitly replace it with an implemented all-or-nothing memory engine.

Future shared-memory or execution-trap support shall require an explicit
compatible interface/profile decision under the pinned-specification policy.
The current standard-only constraint shall remain in force.

The implemented WB endpoint and core-internal kill arbitration are documented
in the [WB guide](../verif/sim/wb/README.md). They use only standard flattened
commit/result fields at the coprocessor boundary; DE issue/identifier tracking
remains core-parent integration work.

### 5.2. RTL and interrupt-completion contracts

The synthesizable interface shall follow the
[RTL language requirements](uqu_spec.style.md#2-language-and-source-files),
including when adapting CV-X-IF's SystemVerilog examples.

Custom operations that have advanced beyond DE shall follow the
completion-before-interrupt policy in [interfaces, Section 4](uqu_spec.interfaces.md#4-external-machine-interrupt-sources). An accepted speculative
offload still held in DE shall instead be killed and reissued under that
section's eviction rule. A draining custom operation shall be considered
finished for interrupt entry when its matching standard result transaction
completes. Any independently connected coprocessor memory work required for
that completion shall be the coprocessor/integration's responsibility under
[interfaces, Section 5.1](uqu_spec.interfaces.md#51-initial-standard-only-scope-and-deferred-memory-features), without an additional core completion or fault input.
Interrupt-driven cancellation or suspension of EX/MEM/WB offloads shall not
be required. Native core faults and speculative kills shall retain their
existing handling. Operation identity, context switching, and any independent
memory integration shall preserve the standard interface and its documented
scope. The core's `dmem` outstanding-transaction limit shall remain unchanged.

The interrupt contract shall distinguish issue, permission to commit, and result
completion. CV-X-IF commit/kill support shall not be interpreted as a guarantee
that an operation can be canceled after it has been allowed to commit or that
accepted external memory side effects can be undone.
This interrupt policy does not remove commit/kill handling required for
speculative instructions discarded by a redirect or an older exception.
The DE-only eviction rule shall use the same
[CV-X-IF commit/kill contract](https://docs.openhwgroup.org/projects/openhw-group-core-v-xif/en/v1.0.0/x_ext.html#commit-interface);
kill notifications shall be observed before interrupt entry, and killed
offloads shall never wait for or generate a result-interface completion.

## 6. Optional hardware debug and external debug module

**Status:** Minimal optional execution-based hardware debug, external-module
integration, RISC-V Debug 1.0 baseline, disabled default, and external-halt
draining agreed; detailed interface and event arbitration TBD

The `DEBUG` elaboration parameter shall select hardware debug support. When
enabled, the core shall support halt/resume, single stepping, and architectural
register access through an external Debug Module (DM). The DM and debug
transport shall reside in the surrounding system, outside the processor core.
The core shall expose the control and status signals and access paths required
to integrate that DM. The default shall be `DEBUG = 0` (disabled).

The initial debug implementation shall be minimal: provide the required Debug
1.0 behavior and the state/resources needed by the selected execution-based DM
integration, including the agreed halt/resume, single-step, and register-access
capabilities. Hardware instruction breakpoints and data watchpoints (`Sdtrig`)
shall be outside the initial scope. No configurable trigger bank shall be added
to the initial core.

Debug shall prioritize minimal hardware size and implementation effort.
Functionally useful halt/resume, stepping, and architectural access shall be
sufficient; debug command throughput and entry/exit performance shall not be
optimization goals. Slow serialized debug execution shall be acceptable.
Integration shall reuse the normal datapath, CSR machinery, and memory ports
rather than add duplicate access paths for debug performance. The existing
agreed debug behavior and Debug 1.0 compliance shall remain requirements.
For remaining optional features and implementation choices, prefer omission
or the simplest compliant fixed behavior. Detailed choices shall be resolved
with the selected external DM integration; they shall not expand the initial
debug scope without an explicit design decision.

The interface contract shall cover debug entry requests, halted/running status,
resume coordination, reset/availability reporting, single-step control, and
access to architectural registers and required debug state. Exact port names,
directions, handshakes, and synchronization shall be defined against the selected
DM implementation. Candidate names such as `debug_req_i`, `debug_halted_o`, and
`debug_running_o` are examples, not a finalized port list.

Hardware debug shall use the
[execution-based implementation model](https://docs.riscv.org/reference/debug/implementations.html).
On debug entry, the core shall save the resume PC in `dpc`, update `dcsr`, and
execute debug code supplied by the external DM. The DM shall provide the debug
ROM, program buffer, and associated memory-mapped control/data resources.
System integration shall make those resources reachable through the existing
`imem` and `dmem` paths and provide the required debug-memory access attributes.

Architectural register access shall use debug instruction execution through the
normal datapath. A dedicated external register-file access port shall not be
required. Resume shall follow the selected debug specification's `dret`
behavior. Debug operation therefore depends on a functioning instruction
execution path.

An external halt request received during normal execution shall use a
drain-before-halt policy with the same EX-entry boundary as interrupt draining.
Once halt draining begins, no new DE-to-EX transfer or XIF issue shall be
accepted. Native and custom instructions already in EX/MEM/WB shall finish
under their normal progress and precise-exception rules. Older stages shall
remain able to drain, and accepted memory responses shall remain serviceable.
The halt request shall not cancel or restart those executing operations or
accepted memory transactions.

An accepted speculative XIF offload still held in DE shall be killed using
the standard CV-X-IF mechanism, as for interrupt draining in [interfaces, Section 4](uqu_spec.interfaces.md#4-external-machine-interrupt-sources).
The kill notification shall complete before debug entry; no result or
architectural register update shall be expected from the killed operation.
An unaccepted DE offload request may be retracted under the interface rules.
The first unexecuted instruction shall remain the architectural resume point.

Once the required drain completes and debug entry is selected, the core shall
save that resume PC in `dpc`, update the required debug state, discard waiting
younger instructions, and redirect to the external debug-entry address. The
saved PC shall follow architectural control flow after draining, rather than
the address of a speculative or word-aligned fetch request. Resume shall
continue to follow `dret` and the current `dpc` value, which debug software may
modify.

At a precise boundary where the required older work has drained and both an
external debug halt and an interrupt are eligible for entry, debug halt shall
take priority. The core shall enter debug execution and save the next
unexecuted PC in `dpc` before executing an interrupt handler. It shall not
perform interrupt trap-entry updates to `mepc`, `mcause`, or `mstatus` for the
deferred interrupt. Pending indications shall continue to follow their external
sources; debug entry shall not clear them or create an additional interrupt
latch. On resume, interrupt eligibility shall be reevaluated against the
then-current pending, enable, and privilege state before admitting subsequent
normal instruction execution, subject to the single-step interrupt mask below.
Debug software may change that state or `dpc`.

If an older instruction in EX/MEM/WB raises a synchronous exception while
draining for an external debug halt, the core shall first complete its normal
exception entry at WB under [architecture, Section 9](uqu_spec.arch.md#9-precise-synchronous-exceptions). This shall update `mepc`, `mcause`,
`mtval`, and the required privilege/status state once, without normal retirement
or destination writes from the faulting instruction. Younger instructions
shall be discarded under the precise-exception rules.

The pending external halt shall then enter debug before the first instruction
of that trap handler executes. `dpc` shall identify the architectural
synchronous trap-handler entry address; `dcsr` shall reflect the post-trap
privilege state and the external-halt entry cause. The recorded faulting PC
and cause shall remain inspectable through `mepc` and `mcause`. Resume through
`dret`, unless debug software changes the relevant state, shall continue at
the trap-handler entry. No deferred exception shall need to be replayed across
debug mode. This rule concerns a fault raised before debug entry, rather than
an exception during debug instruction execution, which uses the separate
debug-exception address below.

With `DEBUG = 1`, `dcsr.stepie` shall be hardwired to zero; otherwise permitted
writes shall not change it. Interrupts shall be masked while single stepping
with `dcsr.step = 1`, without clearing `mie`, `mstatus.MIE`, or pending
indications in `mip`. Those indications shall continue to follow the normal
source-level contract. Interrupt-enabled single stepping shall not be part of
the initial profile.

On resume with `dcsr.step = 1`, the core shall execute one architectural
instruction and reenter debug when that instruction completes. A multi-cycle
MUL/DIV, FPU operation, or XIF offload shall still count as one instruction;
the core shall wait for its required completion and WB updates rather than
counting execution cycles or internal handshakes as steps. Younger instructions
shall not execute or issue XIF work before step completion. A successful
instruction shall retire once, and `dpc` shall record its architectural next
PC, including a resolved control-flow target where applicable.

If fetching or executing the stepped instruction causes a synchronous exception,
the core shall perform normal exception entry and reenter debug before any
trap-handler instruction executes, with `dpc` at the handler entry. The
faulting instruction shall not retire or increment `minstret`. Debug cause
selection shall follow Debug 1.0, including the priority of other supported
debug-entry causes over ordinary step completion. Exact controller sequencing
and arbitration wiring remain implementation details.

With `DEBUG = 1`, `dcsr.stopcount` shall be hardwired to one; otherwise permitted
writes shall not change it. Hart-local `mcycle` and `minstret` shall not increment
while executing in Debug Mode, including debug ROM and program-buffer
instructions, or on an `EBREAK` that enters Debug Mode, following Debug 1.0.
This shall gate implicit counter increments without blocking permitted explicit
CSR access. Debug mode shall not reset the counters or their inhibit state.
During a stepped instruction outside Debug Mode, normal counting shall resume
subject to `mcountinhibit`; a successfully retired instruction shall contribute
one `minstret` increment when enabled, and a faulting instruction none. Counters
shall freeze again on reentry to Debug Mode. This policy shall apply only to
hart-local counters, not to external timer or system-time resources.

Debug entry shall wait for required executing native/custom operations and
accepted memory transactions to complete. An unresponsive memory system or
executing coprocessor may therefore delay entry indefinitely; this policy
shall not introduce an abort, timeout, or rollback path. The priority above
shall apply after the required older work has resolved, including exception
entry under the rule above. Remaining arbitration among debug causes and
reset-halt sequencing remain to be specified under Debug 1.0; single-step
execution shall follow the policy above.
The drain policy shall not permit discarding an older instruction's unresolved
exception.

The debug-entry address and the debug-exception address shall each be supplied
through a 32-bit core input, rather than an RTL parameter. Candidate names are
`debug_entry_addr_i` and `debug_exception_addr_i`. The first selects the debug
code entry point; the second selects the handler for exceptions during debug
instruction execution. Both shall satisfy the configured instruction alignment.
The inputs shall be ignored when `DEBUG = 0`. Exact sampling/stability
requirements, debug-memory mapping, required debug CSR details,
and exact DM handshakes remain TBD.
For an example of execution-based integration, see the
[PULP debug-module core interface](https://github.com/pulp-platform/riscv-dbg/blob/master/doc/debug-system.md#core-interface).
This architecture shall preserve the existing external-memory boundary and
single-clock core requirement.

When `DEBUG = 1`, hart debug behavior and the external-DM integration contract
shall conform to the applicable requirements of the ratified
[RISC-V Debug Specification 1.0](https://docs.riscv.org/reference/debug/v1.0/).
External-halt draining shall follow the policy above. Remaining debug-event
arbitration, full-core debug CSR integration, disabled core-port behavior, and
verification coverage remain TBD. Optional enhancements beyond the minimal
profile are deferred. Project-owned synthesizable debug RTL shall remain plain
Verilog under the language rules in the style guide.

The implemented WB/CSR debug endpoint uses DCSR/DPC plus one dscratch0, with
stepie=0, stopcount=1, stoptime=0 and mprven=1. See the
[WB guide](../verif/sim/wb/README.md) for accepted entry/DRET/EBREAK bindings.
The future core controller still owns drain/step sequencing, Debug Mode and
external-DM address routing; this component support is not complete hart/DM
integration.

## 7. Native OBI core and protocol variants

**Status:** PicoRV32-style native core, protocol-specific top levels, and
reusable adapters agreed; exact module names and future protocol profiles TBD

The design shall follow the interface-variant pattern used by
[PicoRV32](https://github.com/YosysHQ/picorv32): a native-interface processor core,
protocol-specific processor top levels, and reusable protocol adapters. OBI
shall be uquintus's native and default interface. The default processor top
shall expose separate OBI `imem` and `dmem` ports directly and shall be usable
without a protocol adapter.

Every bus variant shall instantiate the same configurable processor core.
Future Wishbone, AXI, TileLink, or other variants shall translate the native OBI
ports in wrapper/adapter modules, without duplicating pipeline logic or adding
external-protocol selection to the processor pipeline. Adapters shall also be
usable independently of the processor top level. Module and file organization
shall follow the [RTL style guide](uqu_spec.style.md#3-identifiers-and-symbols).

| Illustrative module | Responsibility |
| --- | --- |
| `uqu_core` | Default processor top with native OBI `imem` and `dmem`; implement the ISA, privilege, pipeline, register-file, XIF, and debug configuration. |
| `uqu_wishbone` | Future processor variant combining the native core with OBI-to-Wishbone conversion. |
| `uqu_axi` | Future processor variant combining the native core with OBI-to-AXI conversion; exact AXI profile TBD. |
| `uqu_tilelink` | Future processor variant combining the native core with OBI-to-TileLink conversion. |
| `uqu_obi_to_<protocol>` | Reusable adapter module for a selected external protocol; exact names TBD. |

Wrapper top levels shall expose and forward the core's supported configuration
parameters and non-memory integration interfaces. The external bus shall be
selected by the top-level module at build/elaboration time. Protocol conversion,
buffering, and any instruction/data port arbitration shall reside in the
wrapper or its adapters. Adapters shall preserve the native core's ordering,
completion, error, byte-lane, and outstanding-request contracts. The core-facing
OBI contract and configured ISA shall remain consistent across variants.

The first implementation milestone shall use the default native OBI top. Other
bus variants are future additions; their implementation order, exact protocol
versions, and whether a wrapper retains separate instruction/data ports or
combines them into a shared external port remain TBD.

## 8. External fence synchronization

The execution and retirement rules are in [architecture, Section 19](uqu_spec.arch.md#19-conservative-data-memory-fence) and [architecture, Section 16](uqu_spec.arch.md#16-optional-instruction-fetch-fence).

### 8.1. Data/I/O fence handshake

**Status:** Agreed; system-specific ordering actions remain integration work

The surrounding memory system and adapters shall preserve the required
externally observable ordering. Receiving an OBI completion shall not by itself
be assumed to establish every required ordering guarantee if external buffers
or separate memory paths can reorder accesses. The core shall expose the
following synchronous interface, independently of the instruction-fetch fence
interface in [architecture, Section 16](uqu_spec.arch.md#16-optional-instruction-fetch-fence):

| Signal | Direction | Meaning |
| --- | --- | --- |
| `fence_req_o` | Output | A live FENCE at WB requests completion of the required external data-memory and device-I/O ordering. |
| `fence_ack_i` | Input | Integration confirms that the required ordering condition is satisfied. |

After older instructions and relevant data accesses finish, the live fence at
WB shall assert `fence_req_o` and hold it while waiting. It shall not wait for
acknowledgement before asserting the request, and ordinary pipeline stalls
shall not withdraw it. An active clock edge with both signals high shall
complete the synchronization and allow the fence to retire once, releasing
serialization. Pending acknowledgement shall keep WB and younger execution
blocked while permitting required external progress.

No address or predecessor/successor payload shall be exposed: this interface
requests the conservative full barrier already specified above. Integration
shall coordinate any required buffered-write draining, separate custom-memory
paths, and external ordering before acknowledging. If the memory system already
provides all required guarantees, it may tie `fence_ack_i` high for immediate
completion when the request is presented. Reset shall drive the request low.
The ports shall be present in every core configuration because base-ISA FENCE
is mandatory. Exact system-specific ordering actions and reset handling of
pending external synchronization remain integration requirements to document.

The `fence_*` handshake shall serve ordinary data/I/O FENCE operations; the
`fencei_*` handshake shall serve FENCE.I. Acknowledgement on one interface shall
not complete a request on the other. Integration may coordinate their actions
internally while preserving their separate completion conditions.

### 8.2. Instruction-fetch fence handshake

**Status:** Agreed; system-specific synchronization actions remain integration work

The core shall expose the following synchronous external synchronization
interface:

| Signal | Direction | Meaning |
| --- | --- | --- |
| `fencei_req_o` | Output | A live FENCE.I at WB requests the external instruction/data synchronization required before subsequent fetching. |
| `fencei_ack_i` | Input | Integration confirms that the required synchronization is complete. |

After older instructions and relevant data accesses finish, a live `FENCE.I` at
WB shall assert `fencei_req_o`. The request shall remain asserted while awaiting
acknowledgement; ordinary pipeline stalls shall not withdraw it. Completion
shall occur on an active clock edge with both request and acknowledgement high,
coordinating the single retirement, internal invalidation, and successor
redirect defined in [architecture, Section 16](uqu_spec.arch.md#16-optional-instruction-fetch-fence). The core shall not wait for acknowledgement before
asserting the request, and a held instruction shall not repeatedly retire.

The handshake shall carry no address payload: it requests the conservative
synchronization required for subsequent instruction execution by this hart.
The surrounding memory system shall coordinate any required cache/buffer
maintenance, preceding-write visibility, and pending instruction-fetch fills
before acknowledging. Its contract shall ensure that late activity cannot
reintroduce stale instruction data after synchronization. Clearing only the
core's prefetch buffer shall not be assumed sufficient for every external
memory hierarchy.

If no external maintenance is needed and the integration already provides the
required visibility, it may tie `fencei_ack_i` high, allowing completion in the
first cycle the request is presented. Both ports shall remain declared when
`ISA_ZIFENCEI = 0`; the request shall be driven low and the acknowledgement
ignored. Reset shall also drive the request inactive. Exact per-system
maintenance actions, reset handling of pending external maintenance, and
integration-specific synchronization sequencing remain to be documented.

## 9. Hart identification input

**Status:** Agreed

The core shall expose a 32-bit `hart_id_i` input. The read-only `mhartid` CSR
shall return this value. Hart identity shall be an integration input rather
than an RTL parameter, allowing identical synthesized core instances to be
assigned different hart IDs.

Integration shall provide a valid hart ID before reset release and hold it
stable while the core operates, including while stalled or in Debug Mode.
Changing hart identity during execution shall not be supported. The interface
shall not require internal storage for the ID; the CSR may read the stable input
directly.

Integration shall assign IDs that are unique within the execution environment,
with one hart assigned ID zero, as required by the
[RISC-V machine-level specification](https://docs.riscv.org/reference/isa/priv/machine.html).
A single-hart system shall therefore tie `hart_id_i` to zero. Protocol-specific
processor wrappers shall expose or connect this input consistently with the
native top level.

## 10. Baseline functional interface index

This table collects the agreed port names for the first milestone. Directions
are relative to the core; the referenced sections remain authoritative for
behavior, timing, and integration requirements.

These native ports are implemented by `src/uquintus/uqu_core.v`; its
[integration guide](../verif/sim/core/README.md) records connections and current
feature guards. Optional core XIF/debug adapters and the FPU remain unfinished.

| Function | Port(s) | Direction | Width | Definition |
| --- | --- | --- | --- | --- |
| Clock | `clk_i` | Input | 1 | [interfaces, Section 2](uqu_spec.interfaces.md#2-single-clock-domain) |
| Reset | `rst_ni` | Input | 1 | [interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset) |
| Boot entry | `boot_addr_i` | Input | 32 | [interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset) |
| Hart identity | `hart_id_i` | Input | 32 | [interfaces, Section 9](uqu_spec.interfaces.md#9-hart-identification-input) |
| Interrupt sources | `irq_software_i`, `irq_timer_i`, `irq_external_i` | Input | 1 each | [interfaces, Section 4](uqu_spec.interfaces.md#4-external-machine-interrupt-sources) |
| Instruction request | `imem_req_o`, `imem_addr_o` | Output | 1, 32 | [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories) |
| Instruction handshake | `imem_gnt_i`, `imem_rvalid_i` | Input | 1 each | [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories) |
| Instruction response | `imem_rdata_i`, `imem_err_i` | Input | 32, 1 | [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories) |
| Data request controls | `dmem_req_o`, `dmem_we_o`, `dmem_be_o` | Output | 1, 1, 4 | [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories) |
| Data address and write data | `dmem_addr_o`, `dmem_wdata_o` | Output | 32 each | [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories) |
| Data handshake | `dmem_gnt_i`, `dmem_rvalid_i` | Input | 1 each | [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories) |
| Data response | `dmem_rdata_i`, `dmem_err_i` | Input | 32, 1 | [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories) |
| Data/I/O fence request | `fence_req_o` | Output | 1 | [Data/I/O fence handshake](uqu_spec.interfaces.md#81-dataio-fence-handshake) |
| Data/I/O fence acknowledgement | `fence_ack_i` | Input | 1 | [Data/I/O fence handshake](uqu_spec.interfaces.md#81-dataio-fence-handshake) |
| Instruction fence request | `fencei_req_o` | Output | 1 | [Instruction-fence handshake](uqu_spec.interfaces.md#82-instruction-fetch-fence-handshake) |
| Instruction fence acknowledgement | `fencei_ack_i` | Input | 1 | [Instruction-fence handshake](uqu_spec.interfaces.md#82-instruction-fetch-fence-handshake) |

The instruction-fence ports remain declared but inactive in the first milestone
with `ISA_ZIFENCEI = 0`. Integration may tie each bus-error input low if that
port's memory system has no error reporting, and may tie `fence_ack_i` high
when it already guarantees the required ordering.

This is the baseline functional interface index, not a complete declaration
of every optional-interface pin. XIF ports shall retain the declarations and
inactive behavior already required in [interfaces, Section 5](uqu_spec.interfaces.md#5-cv-x-if-custom-extension-interface) with `XIF = 0`. Debug
integration declarations and disabled-port behavior remain subject to the
minimal implementation policy in [interfaces, Section 6](uqu_spec.interfaces.md#6-optional-hardware-debug-and-external-debug-module). No new trace ports, optional
interface signals, or enabled features are selected by this index.

## 11. OBI profile summary

**Status:** Baseline profile agreed; future optional fields and integration guarantees open

The authoritative baseline OBI version, native ports, request persistence,
grant/response timing, capacity, errors, and timeout rules are in [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories).
Reset and stale-response integration are defined in [interfaces, Section 3](uqu_spec.interfaces.md#3-active-low-synchronous-reset); instruction
assembly and byte-lane interpretation are in [architecture, Section 15](uqu_spec.arch.md#15-aligned-instruction-fetch-and-internal-assembly) and [architecture, Section 14](uqu_spec.arch.md#14-little-endian-byte-ordering).

The initial profile omits transaction IDs and user fields and has no response
backpressure. Atomic and integrity fields are deferred with their planned
feature settings; their future profiles shall not expand the baseline port
list implicitly. Remaining system-specific guarantees are listed below.

## 12. Integration follow-ups

| Area | Remaining work |
| --- | --- |
| Memory system | Document faulting-transaction side effects, device-access guarantees, external timeout recovery, and coordinated reset/stale-response isolation for each integration. |
| Fences | Specify cache/write-buffer and separate-memory-path ordering/visibility actions, late-fill handling, and reset during external maintenance; preserve the two agreed handshakes. |
| CV-X-IF | Exact plain-Verilog declarations/adapters, optional standard features, result buffers, identifier reuse/notification wiring, and verification mapping for paired results. |
| Independent coprocessor memory | Enforce integration-level protection, ordering, completion, and speculative-kill safety without new core/CV-X-IF sidebands; shared-LSU access and execution traps remain deferred. |
| FPU/reset | Reconcile a selected imported unit's internal reset/flush behavior with the synchronous core reset and immediate cancellation contracts. |
| Debug | Select a compatible external DM and resolve minimal port/CSR declarations, disabled behavior, reset-halt, address stability, memory attributes, and remaining debug-cause arbitration using the simplest compliant implementation. |
| Other wrappers | Specify future protocol variants and optional atomic/integrity profiles only when implementing those separately selected features. |

The baseline memory/IRQ names, widths, request persistence, grant/response
timing, no-response-backpressure rule, and interrupt/debug drain policies are
fixed above. Their implementation details shall not reopen those decisions.

## 13. Decision record

Decision IDs are shared across the [specification set](uqu_spec.md#document-index).
Superseded and deferred rows preserve history; current topic requirements and
later decisions determine the active contract.

| ID | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-003 | Keep instruction and data memories outside the core; expose separate read-only `imem` and read/write `dmem` interfaces. | Define a core boundary that leaves memory implementation to the surrounding system. | Agreed |
| D-014 | Support variable latency through request/response handshakes on both memory interfaces. | Keep the core flexible with respect to the external memory hierarchy, including external caches. | Agreed |
| D-015 | Use OBI for the initial instruction and data memory interfaces, with other external bus protocols as future integration options. | Establish the initial protocol while allowing the surrounding system's interface requirements to evolve. | Agreed |
| D-016 | Allow one outstanding transaction per memory port and use a blocking MEM stage; instruction and data ports may operate concurrently. | Keep baseline memory control simple while supporting variable latency and independent instruction and data accesses. | Agreed |
| D-024 | Use one clock domain for the core and its memory interfaces; handle clock-domain crossings outside the core. | Keep core timing and control within a single synchronous domain. | Agreed |
| D-027 | Default to active-low synchronous reset with minimal, documented coverage of architectural, control, and pipeline state. | Establish a clear startup state and a reset contract that can be checked in verification. | Agreed |
| D-028 | Supply the reset entry address through a 32-bit input, sampled during synchronous reset. | Let the surrounding system supply the boot address. | Agreed |
| D-050 | Expose separate machine software, timer, and external interrupt inputs; keep the timer and interrupt controller outside the core. | Support standard machine interrupts while keeping system interrupt generation and routing outside the processor. | Agreed |
| D-051 | Complete executing native and custom operations and accepted data-memory transactions before interrupt entry; prioritize synchronous exceptions from those instructions. | Keep interrupt entry simple without abort/restart or suspend/resume machinery; accept operation- and memory-dependent latency. | Agreed; EX-entry boundary and speculative DE-only XIF eviction clarified by D-228 and D-229 |
| D-052 | Plan a custom extension interface and account for potentially long-running operations in its interrupt contract. | Support experimentation with custom operations without prematurely fixing their interface or completion policy. | Agreed; standard-only initial profile fixed by D-234 |
| D-053 | Use ratified CV-X-IF v1.0.0's multi-interface offload model and allow memory-accessing custom operations through a separately specified memory addition. | Pin the offload baseline while keeping the additional memory contract explicit. | Ratified v1.0.0 retained; shared-LSU access and coprocessor execution traps deferred under D-234 |
| D-054 | Support extension memory access through the main core LSU and existing `dmem` port, while allowing extensions to use a separate memory path. | Provide shared LSU access without making it mandatory; preserve the existing `dmem` outstanding limit and define separate-path responsibilities explicitly. | Deferred outside the initial standard-only profile by D-234 |
| D-061 | Use 32-bit byte addresses and 32-bit data on both memory ports, with four byte enables on `dmem`. | Define the native core memory widths and byte-lane mask independently of the external memory hierarchy. | Agreed |
| D-074 | Perform native and extension instruction recognition in parallel within DE when CV-X-IF is enabled. | Avoid requiring serial decoder evaluation or an additional pipeline stage; preserve operand and interface backpressure handling. | Agreed |
| D-075 | Make CV-X-IF an optional feature selected through the `XIF` elaboration parameter. | Allow configurations without extension logic or dependence on an attached coprocessor. | Agreed; disabled default selected in D-076 |
| D-076 | Default `XIF` to `0` (disabled). | Enable coprocessor integration explicitly when needed. | Agreed |
| D-077 | Retain XIF port declarations when disabled; tie core-driven outputs to deterministic inactive values and ignore inputs. | Keep module connections consistent across configurations; wrappers may hide unused ports. | Agreed |
| D-078 | Support multiple CV-X-IF offloaded instructions in flight, retaining single issue and in-order retirement. | Allow overlap through a pipelined coprocessor without an artificial one-offload limit. | Agreed; capacity and identifier profile defined by D-231; buffering details TBD; result order defined in D-079 |
| D-079 | Require coprocessor results in accepted issue order, excluding killed instructions, with architectural retirement in program order across native and offloaded instructions. | Keep result ordering outside the core while preserving pipelined offload issue. | Agreed |
| D-080 | Retain offloaded instructions in normal pipeline slots through WB; hold WB for a late result and propagate backpressure without a separate retirement queue. | Preserve the five-stage in-order pipeline while allowing overlapping offloads within available slots. | Agreed; detailed result handshaking TBD |
| D-081 | Grant CV-X-IF commit permission once at WB after all older instructions complete, independently of result availability; retire only after completion. | Preserve precise execution and avoid waiting for a result that requires commit permission first. | Agreed |
| D-082 | Perform CV-X-IF issue and operand delivery together in DE using `X_ISSUE_REGISTER_SPLIT = 0`. | Use the decode-stage operand path and coupled interface handshakes without a separate operand-delivery stage. | Agreed |
| D-083 | Support three XIF source operands with `XIF_NUM_RS = 3`; custom ternary instructions read the old destination value through the shared `rd`/third-source field, alongside `rs1` and `rs2`. | Support `rd <- fn(old_rd, rs1, rs2)` without a separate custom third-source encoding field. | Agreed; conditional third read port defined in D-084 |
| D-084 | Allow `XIF_NUM_RS` to select two or three sources; implement the third integer read port and its XIF-specific dependency/forwarding logic only when `XIF = 1` and `XIF_NUM_RS = 3`. | Read three operands together in DE only in configurations that need them. | Updated by D-236: the third port is also required by Zfinx |
| D-085 | Default `XIF_NUM_RS` to `3`. | Provide three-source capability when XIF is enabled without adding the third read port when XIF is disabled. | Agreed; third-port presence now also depends on Zfinx under D-236 |
| D-086 | Make paired-register XIF writeback configurable through `XIF_DUALWRITE`, defaulting to `0`; include dual-write logic only when both XIF and dual writeback are enabled. | Allow custom instructions to return a register pair while keeping the default single-destination writeback path. | Agreed; two write ports selected in D-087; verification mapping TBD |
| D-087 | Provide two integer register-file write ports only when `XIF = 1` and `XIF_DUALWRITE = 1`; update both destinations of a paired result in one WB cycle. | Preserve throughput and simultaneous paired updates while retaining one retiring instruction per cycle. | Agreed |
| D-088 | Fix each XIF source operand at 32 bits with `X_RFR_WIDTH = 32` and `X_DUALREAD = 0`; do not support paired-register source reads. | Keep source accesses at the core's native register width while retaining optional paired-register result writes. | Agreed |
| D-089 | Allow custom memory requests before WB commit permission on either the shared LSU or a separate memory path, preserving precise-trap and kill contracts. | Permit memory activity to overlap pipeline execution rather than universally waiting until WB. | Memory integration deferred outside the initial profile under D-234; standard speculative kill safety retained |
| D-090 | Give the MEM instruction exclusive ownership of the shared LSU; hold a custom instruction in MEM until its shared-LSU work completes, with no further shared-LSU requests from WB. | Serialize native and custom LSU use through the existing pipeline stage rather than independent competing requesters. | Shared-LSU integration deferred outside the initial profile by D-234 |
| D-091 | Allow multiple sequential LSU accesses for one custom instruction while it holds MEM, retaining one outstanding `dmem` request and allowing older WB work to drain. | Support multi-access custom operations through existing pipeline backpressure; retire the operation once. | Shared-LSU multi-access sequencing deferred outside the initial profile by D-234 |
| D-092 | Make hardware debug optional through `DEBUG`, supporting halt/resume, single stepping, and architectural register access when enabled. | Permit hardware debugging without requiring it in every core configuration. | Agreed; disabled default defined in D-095; minimal profile defined in D-098 |
| D-093 | Expose the core control/status signals and access paths required by an external Debug Module; keep the DM and transport in system integration. | Define an integration boundary without embedding the debug module in the processor core. | Agreed; exact ports and debug implementation TBD |
| D-094 | Use ratified RISC-V Debug Specification 1.0 as the baseline when hardware debug is enabled. | Define standard hart debug behavior and the requirements for external-DM integration. | Agreed; minimal profile defined in D-098; detailed interface TBD |
| D-095 | Default `DEBUG` to `0` (disabled). | Enable hardware debug explicitly for configurations that require an external Debug Module. | Agreed |
| D-096 | Use execution-based hardware debug with debug ROM, program buffer, and control/data resources supplied by the external DM through the existing memory paths. | Reuse the core's instruction execution datapath for architectural register access and debug operations. | Agreed; exact DM integration and memory mapping TBD |
| D-097 | Supply debug-entry and debug-exception addresses through separate 32-bit core inputs. | Let system integration choose the locations of external debug code and its exception handler. | Agreed; exact signal names and sampling/stability contract TBD |
| D-098 | Keep initial hardware debug minimal; defer Sdtrig hardware breakpoints/watchpoints and additional optional enhancements, with no initial configurable trigger bank. | Provide the agreed external-DM debugging essentials without expanding debug hardware scope. | Agreed |
| D-108 | Follow PicoRV32's native-core/protocol-top-level/adapter pattern, using separate OBI instruction/data ports as uquintus's native and default interface. | Reuse one configurable processor across future external bus variants and provide reusable protocol conversion outside the pipeline. | Agreed; exact module names and future protocol profiles TBD |
| D-109 | Omit response backpressure on both native OBI ports; reserve response capacity before issuing requests and always accept responses despite pipeline stalls. | Decouple bus completion from pipeline advancement while retaining responses until consumed and draining obsolete accepted transactions. | Agreed; reset integration defined by D-112 |
| D-110 | Support error-response inputs on both core memory ports, mapping native fetch/load/store failures to access faults; make bus-side error reporting optional per port, with absent error signals tied low at integration. | Support fault-reporting memory systems while retaining a simple connection to buses without error reporting. | Agreed; external error-side-effect guarantees remain integration work; custom execution traps deferred by D-234 |
| D-111 | Omit internal bus timeouts on both memory ports; leave timeout detection and recovery to the external memory system or bus adapter. | Preserve unrestricted variable latency without core timeout counters, automatic retries, or fabricated completions. | Agreed; external logic must preserve the core-facing completion contract |
| D-112 | Clear core memory-transaction tracking on reset; require integration to handle pending pre-reset transactions and prevent their responses from reaching the core after reset release. | Allow deterministic core restart without retaining transaction history or internally draining old requests. | Agreed; external mechanism is an integration choice |
| D-116 | Expose a stable 32-bit `hart_id_i` input and return its value through read-only `mhartid`. | Allow multiple instances of the same synthesized core to have distinct integration-assigned identities. | Agreed |
| D-188 | Exclude CLIC/ACLIC support from this draft without committing to a later implementation; retain the standard machine interrupt inputs and Direct/Vectored trap dispatch, with external controller selection left to integration. | Keep baseline interrupt handling simple and require a separate decision before adding advanced interrupt architecture features. | Agreed |
| D-189 | Use active-high, level-sensitive software/timer/external interrupt inputs reflected in read-only `mip.MSIP`/`.MTIP`/`.MEIP`, without sticky edge capture; clear pending sources externally and provide writable `mie.MSIE`/`.MTIE`/`.MEIE` bits resetting to zero. | Keep interrupt source ownership outside the core and separate pending state from delivery enables. | Agreed; synchronous input contract defined by D-190 |
| D-190 | Require the machine interrupt inputs to be synchronous to the core clock; handle asynchronous-source synchronization and any required source capture/pulse stretching in the surrounding integration or wrapper. | Keep the processor's interrupt boundary within its single clock domain without internal IRQ synchronizers. | Agreed |
| D-192 | Pin OBI v1.6.0 as the reference protocol for both native memory ports; define the remaining optional-signal profile and detailed timing against that version. | Give memory-interface implementation and verification a fixed protocol baseline. | Agreed; baseline names/profile and handshake timing fixed by D-193, D-194, D-197, and D-249; future fields deferred |
| D-193 | Hold each asserted OBI request and its payload stable until grant despite stalls, flushes, or redirects; retain ownership/capacity and complete then discard wrong-path fetches, except under the separate reset contract. | Preserve the bus handshake while keeping pipeline cancellation independent of request acceptance and completion. | Agreed |
| D-194 | Allow grant in the first presented request cycle, with the corresponding response one or more cycles after grant; prohibit same-cycle grant and completion of the same transaction for both reads and writes. | Define separate request and response timing while preserving variable latency and permitted overlap between different transactions. | Agreed |
| D-197 | Omit transaction IDs (`aid`, `rid`) and user fields (`auser`, `wuser`, `ruser`) on both native OBI ports; allow integration logic to add external metadata and retain functional CV-X-IF identifiers. | Keep the core's one-outstanding-request memory interfaces simple without constraining interconnect metadata outside the core. | Agreed |
| D-198 | Present word-aligned byte addresses on dmem, select subword lanes through byte enables and shifted data, and retain the original effective byte address inside the LSU for checks, load extraction, and mtval. | Keep the bus word-oriented while preserving byte-granular instruction semantics and accurate fault information. | Agreed |
| D-207 | Expose synchronous `fencei_req_o`/`fencei_ack_i` with no address payload; hold a live WB fence's request until an active-edge handshake, allow immediate acknowledgement when visibility is already guaranteed, and retain inactive ports when Zifencei is disabled. | Provide an explicit completion contract for external instruction/data synchronization across different memory hierarchies. | Agreed; per-system maintenance/reset requirements remain to be documented |
| D-208 | Expose separate synchronous `fence_req_o`/`fence_ack_i` in every configuration, with no address or predecessor/successor payload; hold the live WB FENCE request until acknowledgement and allow high acknowledgement tie-off when ordering is already guaranteed. | Let integration satisfy external data/I/O ordering without conflating it with instruction-fetch synchronization or requiring overly strong OBI completion semantics. | Agreed; per-system ordering/reset requirements remain to be documented |
| D-213 | Support only machine software, timer, and external interrupt bits in `mie` and `mip`; hardwire all other bits to zero and ignore otherwise permitted writes, with additional device sources aggregated externally. | Match the three agreed interrupt inputs without additional local or supervisor interrupt state. | Agreed |
| D-214 | Require synchronous reset to cover at least one rising core-clock edge, with reset and the sampled reset entry address meeting setup/hold timing; require no multi-cycle core reset sequence and leave longer external-component reset requirements to integration. | Define a minimal reset timing contract that is straightforward to implement and verify. | Agreed |
| D-215 | Name the clock/reset inputs `clk_i`, `rst_ni`, and 32-bit `boot_addr_i`; require a four-byte-aligned boot byte address in every configuration, without restricting subsequent halfword-aligned execution when C is enabled. | Finalize the basic integration port names and a simple boot alignment contract. | Agreed |
| D-216 | Express initial portable pipeline holds through register update enables without explicit pipeline clock-gate instantiations; permit functionally equivalent synthesis-inserted gating and isolate explicit clock control needed by the latch register file inside that backend. | Keep pipeline RTL and verification simple while preserving ASIC power optimization and the latch-storage option. | Agreed; target-specific gating implementation and verification details TBD |
| D-228 | With XIF disabled, stop new DE-to-EX transfers when interrupt draining begins, complete native instructions already in EX/MEM/WB, and use the first unexecuted instruction's PC as interrupt mepc. | Define a precise drain boundary while leaving a waiting DE instruction for execution after interrupt return. | Agreed; extended to XIF by the DE-only eviction rule in D-229 |
| D-229 | On interrupt draining, kill an accepted speculative XIF offload still held in DE before interrupt entry, preserve its PC for reissue, and leave EX/MEM/WB offloads subject to completion before entry; preserve no-side-effect kill semantics and accepted-memory completion tracking. | Apply the EX-entry drain boundary to XIF without waiting for speculative DE computation or canceling committed operations. | Agreed; detailed notification/recovery sequencing and custom-memory enforcement remain implementation/interface work |
| D-230 | Forward a matching valid XIF result at WB through enabled WB-to-DE/WB-to-EX paths before register-file write visibility; for paired results, forward only primary even `rd` from the lower 32 bits and retain hazard tracking for the secondary odd destination until it is readable from storage. | Reuse the existing single-destination forwarding network while preserving simultaneous paired writeback and correct secondary-destination dependencies. | Agreed |
| D-231 | Support up to four accepted live XIF offloads in DE/EX/MEM/WB with fixed `X_ID_WIDTH = 3`; use sequential identifiers reserved at issue presentation, carried with pipeline instructions, and reused only under the protocol's completion/kill and wraparound rules, stalling issue when necessary. | Identify related offload transactions and targeted kills while retaining simple in-order tracking without a separate offload queue or result-reordering structure. | Agreed; detailed identifier-state and result-buffer implementation remains open |
| D-232 | Permit documented partial memory/device effects when a later access of the same live multi-access custom instruction faults, with explicit recovery/retry semantics and no core rollback; retain normal register-write suppression, WB trap ordering, and no-effect guarantees for speculative kills and younger instructions. | Support custom multi-access operations without requiring all-or-nothing memory effects, while making partial completion visible in the instruction's software contract. | Deferred outside the initial profile by D-234; no all-or-nothing memory engine selected in its place |
| D-233 | Permit only standard CV-X-IF v1.0.0 signals and packet fields on the core/coprocessor connection; prohibit additional memory, completion, fault, or progress sidebands and reopen prior memory/fault plans that require them. | Preserve an unmodified standard coprocessor interface rather than introduce uquintus-specific channels. | Agreed; initial scope fixed by D-234 |
| D-234 | Retain unmodified ratified CV-X-IF v1.0.0 and initially defer shared-LSU access and coprocessor-generated execution traps; use the standard result transaction as offload completion, with no extra memory/fault/completion sidebands. | Keep the standard coprocessor connection simple without adopting legacy interfaces or requiring a custom fault protocol. | Agreed; earlier multi-access and partial-effects-on-trap plans remain deferred design intent |
| D-242 | Prioritize an eligible interrupt over an exception recognized on an instruction still in DE, blocking its DE-to-EX transfer and saving its PC for re-execution; retain exception priority for instructions already in EX/MEM/WB and required interrupt checks after MRET and relevant CSR writes. | Apply the existing EX-entry interrupt boundary consistently without allowing a DE exception barrier to block interrupt draining. | Agreed; interrupted DE exception metadata is discarded with its instruction; if interrupt entry is canceled, resume at the same unexecuted instruction |
| D-243 | For external debug halt requests, stop DE-to-EX transfers and XIF issue, finish EX/MEM/WB operations and accepted memory transactions, kill speculative XIF work still in DE, then save the first unexecuted PC in dpc and enter debug execution. | Reuse the interrupt drain boundary and avoid separate abort/restart machinery while accepting completion-dependent debug-entry latency. | Agreed; halt-versus-interrupt priority defined by D-244 and single stepping by D-246; remaining event arbitration, reset-halt, and detailed DM handshakes remain open |
| D-244 | At a precise boundary after required older work has resolved, prioritize an external debug halt over an eligible interrupt; save the next unexecuted PC in dpc, perform no trap-entry updates for the deferred interrupt, and reevaluate interrupt eligibility on resume. | Allow debug inspection before interrupt handling changes architectural state without clearing or separately latching the interrupt source. | Agreed; draining-exception ordering defined by D-245; other debug-cause arbitration remains open |
| D-245 | If an older instruction faults while draining for an external debug halt, complete normal exception entry at WB, then enter debug before any trap-handler instruction executes, with dpc at the trap-handler entry and debug state reflecting the post-trap privilege and external halt. | Preserve precise fault state for inspection without carrying a deferred exception across debug mode; resume normally into the trap handler. | Agreed; single-step policy defined by D-246; other debug-cause priority and reset-halt remain open |
| D-246 | Hardwire dcsr.stepie to zero and mask interrupts during single stepping; execute one architectural instruction through its required completion/WB updates, then reenter debug, or complete exception entry and reenter debug before handler execution if it faults. | Keep single stepping predictable and minimal across native, multi-cycle, floating-point, and custom instructions without interrupt-enabled stepping support. | Agreed; machine interrupt state is preserved; other debug-cause priority follows Debug 1.0 |
| D-247 | Hardwire dcsr.stopcount to one, suppressing implicit hart-local counter increments in Debug Mode and on EBREAK entry, while retaining permitted explicit CSR access and normal mcountinhibit-controlled counting during stepped instructions. | Keep debug ROM and program-buffer execution out of application counter measurements with a simple counter-enable condition. | Agreed; external system-time resources are unaffected |
| D-248 | Prioritize minimal debug hardware size and implementation effort over performance; accept slow serialized debug access, reuse existing datapath/CSR/memory resources, and omit optional enhancements or choose the simplest compliant fixed behavior. | Provide a functionally useful debugger without making debug a project focus or adding performance-oriented hardware. | Agreed; remaining details resolved with the selected DM under existing contracts and Debug 1.0 |
| D-249 | Finalize baseline native imem/dmem port names and widths in [interfaces, Section 1](uqu_spec.interfaces.md#1-external-instruction-and-data-memories), with read-only imem, dmem write controls and byte enables, grant and response-valid handshakes, 32-bit addresses/data, and one response error input per port. | Make the existing memory-interface behavior concrete for core RTL and wrappers without introducing response backpressure or future optional bus fields. | Agreed; full OBI instruction-side write controls are supplied as constants by the wrapper |
| D-250 | Name the three one-bit core interrupt inputs irq_software_i, irq_timer_i, and irq_external_i; retain the agreed active-high, level-sensitive, core-clock-synchronous behavior. | Finalize interrupt integration names consistently with the signal naming convention and existing mip mapping. | Agreed; baseline functional interface collected in [interfaces, Section 10](uqu_spec.interfaces.md#10-baseline-functional-interface-index) |
| D-281 | Require an RV32E-aware coprocessor to reject encodings using unavailable GPRs according to actual read/write requirements; defensively kill and fault any invalid accepted response through standard cleanup. | Preserve RV32E legality and standard signal-dependency rules without response-to-request combinational gating or rejecting unused high fields. | Agreed; clarifies RV32E XIF integration in Section 5; DE checks/cleanup under D-280; complete core arbitration remains pending |
