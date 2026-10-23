# Core-owned CV-X-IF lifetime controller

[`uqu_xif_ctrl.v`](../../../src/uquintus/uqu_xif_ctrl.v) owns interface ID
reservation, retraction, pending kills and drain readiness. Instruction payloads
and accepted offloads stay in the core's ordinary DE/EX/MEM/WB slots. No offload
queue, retirement queue or result reordering buffer is added.

Three-bit IDs increment when first presented, including requests later retracted
or rejected. A DE reservation keeps its ID while backpressured. An eight-bit
live bitmap prevents reuse or wrap past the oldest outstanding transaction;
holes from younger cancellations cannot bypass that oldest ID. Rejected requests
still require their standard commit/kill notification. Unhandshaken requests may
retract without a notification; surviving accepted requests release only on
matching WB retirement, and killed requests release on the kill notification.

DE cleanup and simultaneous EX/MEM/DE flushes set pending kill bits, retained
after those slots disappear. WB's existing commit arbiter gives an initial WB
commit notification priority, then sends one targeted kill per clock with
implicit readiness. A live DE ID remains stable while another ID awaits cleanup.
New reservations wait while registered kill notifications remain pending.

On interrupt drain, DE retracts or kills its speculative offload while keeping
the core-owned DE instruction/PC for restart. EX/MEM/WB offloads finish normally.
IRQ entry waits for all live IDs and accepted memory work to finish. Reset clears
tracking and requires the connected coprocessor to discard its corresponding
pre-reset work under the shared reset integration contract.

WB provides backpressure directly; there is no result buffer. Commit permission
does not depend on results. A matching valid result may complete in the same
cycle as permission, or later. Result readiness does not depend on packet fields.
Wrong ID/hart/destination or unadvertised write enables do not retire or modify
GPRs; these are integration protocol violations, not invented CPU exceptions.
The standard-channel test agent detects violations (or explicitly injects and
checks containment of malformed results).

The initial core profile offloads uncompressed instructions only. Native C
instructions remain usable with XIF enabled, but the standard compressed offload
channel, shared LSU and coprocessor execution traps remain deferred. No private
memory/fault/completion sidebands are introduced.

Future shared-LSU access, multiple outstanding data transactions, response/effect
ordering and partial-completion considerations are recorded in the
[deferred memory contract](../../../doc/uqu_spec.interfaces.md#511-deferred-shared-lsu-concurrency-and-side-effects).
They do not change this controller or the current single-outstanding data port.

```sh
make test COMPONENT=xif_ctrl CONFIG=rv32i_xif
make test COMPONENT=xif_ctrl CONFIG=rv32i
make test COMPONENT=core CONFIG=rv32i_xif TEST=xif
make lint COMPONENT=core CONFIG=rv32i_xif
```

Standalone tests cover four reservations, held IDs, permission versus retirement,
retraction, simultaneous targeted kills, surviving older work, wraparound with
younger holes, exhaustion and reset. The core test additionally uses a behavioral
coprocessor and independent retirement oracle, randomized memory/issue timing,
three-source dependencies, no-write completion, paired writes and ignored x0/x1,
malformed results, memory-fault cleanup and precise IRQ cancellation/reissue.
RV32E tests include compliant rejection and defensive cleanup of deliberately
noncompliant acceptance. Two-source/forwarding-disabled/retention configurations
use the same test. The custom opcodes are verification fixtures, not a new
advertised ISA extension or Spike model.

`xif-agent.json` retains transaction observations with test names and local clock
indices; `xif.jsonl` records actual custom retirements with standard RVFI epoch/
order correlation, all three consumed operands and both architectural writes.
See the [core guide](../core/README.md) and [RVFI profile](../../common/README.md).
