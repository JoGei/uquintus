# Instruction-word fetch engine

[uqu_ifetch.v](../../../src/uquintus/uqu_ifetch.v) is the IF-owned, single-word
OBI transaction engine. It has private request/result storage, independent of
the future prefetch buffer, [instruction aligner](../if_aligner/README.md) and
parent-owned IF/DE register.
It implements no ISA decoding, PMP rules, CSR storage or redirect arbitration.

```sh
make test COMPONENT=ifetch CONFIG=rv32i
make test COMPONENT=ifetch CONFIG=rv32i SEED=42
make lint COMPONENT=ifetch CONFIG=rv32i
make test COMPONENT=ifetch_pmp CONFIG=rv32i_pmp
```

Use `PYTHON=.venv/bin/python` for the repository environment. The
[manifest](../../../config/sim/ifetch.yml) selects three cocotb/pyuvm suites.
The leaf has no hardware parameters. `ISA_C` and the compressed-decode strategy
do not change its aligned 32-bit word interface.

## Request and protection contract

| Port | Meaning |
| --- | --- |
| `clk_i`, `rst_ni` | Single clock, active-low synchronous reset of control state only. |
| `flush_i` | Discard current work/results; finish any already presented bus transaction. |
| `req_valid_i`, `req_ready_o` | Accept one private word request on an active edge with both high. |
| `req_addr_i[31:0]` | Byte address of the containing fetch word; bits 1:0 are ignored. |
| `req_access_fault_i` | Completed external protection-denial decision for that aligned four-byte word, sampled at request acceptance. |
| `request_permit_i` | Permission to start new external work; accepted work may wait privately for it. |
| `busy_o` | Private request, transaction or retained-result storage occupied, including killed bus work draining. |
| `res_valid_o`, `res_ready_i` | Transfer the registered word completion on an active edge with both high. |
| `res_addr_o[31:0]` | Captured aligned word address, qualified by result validity. |
| `res_data_o[31:0]`, `res_error_o` | Registered word and combined protection/bus error; data is zero on error. Invalid results expose all-zero fields. |

The **core owns one shared `uqu_pmp`**. The future IF parent queries its IF
port with `{req_addr_i[31:2],2'b00}`, size 2 (four bytes), execute permission and
current fetch privilege. It supplies `!if_allow_o` as `req_access_fault_i`.
The MEM parent independently queries the same checker for its LSU's actual
address, size, read/write access and effective privilege. Configuration/address
CSRs connect only to that core-owned checker. Neither transaction engine
instantiates it or carries privilege attributes on OBI.

The denial decision must be ready before request acceptance and is latched
with that request. Later changes to query inputs cannot alter its outcome.
Core control remains responsible for serialization and invalidation when
architectural protection/privilege state changes. Permission to start work is
separate from protection: a denied request produces a registered error word
without a bus request, even while `request_permit_i` is low.

Request alignment here is word selection, not instruction-PC alignment.
For example, a request at 0x1002 reads word 0x1000. The caller must check that
same containing word through PMP. The later aligner determines which instruction
halfwords are used. A failed word is not yet an architectural trap: IF associates
the failure with a surviving instruction, selects cause 1 and the correct
faulting portion's byte address. Unused/discarded words cause no trap.

## Bus and retained completion

The native bus is read-only: `imem_req_o`, `imem_addr_o[31:0]`,
`imem_gnt_i`, `imem_rvalid_i`, `imem_rdata_i[31:0]`, `imem_err_i`.
Full-OBI constant write controls belong in the wrapper. There is no response
backpressure, ID, retry or internal timeout.

On private acceptance, an allowed and permitted request presents its captured
address in the following cycle. Otherwise it waits privately until an active
edge observes permission. Once presented, request and address remain stable
until grant regardless of permission changes, stalls or flush. The response
must arrive at least one cycle after grant, following the native OBI profile.
Grant may already be high when a request is presented.

Every live response is captured at the active edge regardless of consumer
readiness. Result validity follows in the next cycle; there is no combinational
bus-response bypass. Address/data/error remain stable until consumption or
flush. Error is sampled only with response valid. The single private result
slot reserves response capacity: no replacement request is accepted while a
transaction or retained result occupies it. There is a return-to-idle cycle
before accepting replacement work; this baseline prioritizes simple control.
Prefetch-buffer integration must account for this storage and outstanding work;
`MUA_IF_BUFFER_WORDS` itself is not implemented by this leaf.

## Flush and reset

| Current phase | Flush behavior |
| --- | --- |
| Idle | Suppress private acceptance. |
| Private permission wait | Cancel without asserting a bus request. |
| Request presented, before grant | Keep request/address stable; wait for grant, then drain the response. |
| Awaiting response | Accept and discard the eventual response, including errors. |
| Retained completion | Suppress transfer and discard it. |

Flush on the grant or response edge follows the same rules. Repeated flushes
cannot release outstanding ownership early. New-target requests wait for
`req_ready_o`; redirects and target selection belong to the IF/core controller.

Reset clears transaction control, may withdraw a request, and does not wait
for pre-reset bus work. Integration must prevent stale responses after reset
under the coordinated reset contract. Request address, data and error storage
have no reset; validity prevents their use until initialized.

## Verification

- `directed`: low-bit word selection, address extremes, latched protection
  denials, permission waits, preasserted grant, bus errors, response retention
  and ignored idle bus activity.
- `randomized`: 512 transactions per seed with independent request addresses,
  data, protection decisions, grant/response delays and consumer backpressure.
- `control`: flush at every phase and on grant/response edges, repeated killed
  drains, blocked replacement requests, reset/recovery and long waits without
  timeout/retry. Common checks enforce stable presented requests/results and
  safe invalid outputs on every cycle.

The [shared-PMP fixture](../ifetch_pmp/README.md) connects one real core-owned
checker to both real engines. Standalone and fixture lint use Verilog-2005.
Synthesis finds 67 storage bits, only four with synchronous reset; no latches,
combinational bus-response-to-result path or flush-to-bus withdrawal path.
The [word buffer](../if_buffer/README.md) and
[prefetch fixture](../if_prefetch/README.md) add real fetch/buffer/aligner
integration with capacity reservation, fault containment and redirect draining.
Production [IF](../if/README.md) and its [parent-register fixture](../if_pipeline/README.md)
add configured expansion and accepted DE branch feedback. Full-core integration,
RVFI and software-level verification remain pending.
