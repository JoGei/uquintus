# Prefetch integration fixture

[uqu_if_prefetch_tb.v](uqu_if_prefetch_tb.v) connects the real
[fetch engine](../ifetch/README.md), [word buffer](../if_buffer/README.md) and
[aligner](../if_aligner/README.md). Its verification-only controller owns the
instruction PC, sequential fetch pointer and one-bit fault-delivery containment.
It starts a fetch only when the engine is ready and the buffer has capacity,
continues prefetching while instruction consumption is stalled, and gates word
release with actual instruction transfer. It does not implement `uqu_stage_if`.

```sh
make test COMPONENT=if_prefetch CONFIG=rv32i
make test COMPONENT=if_prefetch CONFIG=rv32ic
make lint COMPONENT=if_prefetch CONFIG=rv32ic
```

Use `PYTHON=.venv/bin/python` for the repository environment. Parameters are
`ISA_C` and `MUA_IF_BUFFER_WORDS`; all compressed implementation strategies use
the same raw-word path. The [manifest](../../../config/sim/if_prefetch.yml)
uses the shared runner and Bender.

`fetch_enable_i` models a control hold on starting requests; `request_permit_i`
independently controls the fetcher's private wait before presenting OBI.
`instr_ready_i` models downstream backpressure. `flush_i` clears the FIFO and
fault containment, installs `redirect_addr_i` as the next instruction PC and its
containing word as the next fetch address, and flushes the engine. An old
presented request drains before the new transaction can start.

The external `req_access_fault_i` stands for the completed core-owned PMP
decision. No checker is instantiated or moved into IF. The separate
[shared-PMP fixture](../ifetch_pmp/README.md) verifies real simultaneous IF/LSU
checks. This fixture tests local denial without replacing that protection test.

The Python scoreboard maintains independent word and reservation deques,
sequential pointers, delayed memory responses and known instruction bytes. It
compares instruction selection against the shared byte-window oracle, checks
head/successor addresses, and asserts that buffered words plus the fetcher's
busy transaction never exceed the configured capacity. Presented ungranted
requests must retain their addresses across all control changes.

- `stream`: 256 known native/mixed-length instructions across 32-bit address
  wraparound, randomized grants/response delays and downstream stalls, exact
  capacity fill while stalled, request holds, halfword reuse, sequential fetch
  addresses and no duplicate word requests or instruction transfers.
- `faults`: local PMP denial without OBI, errored first words, exactly one fault
  transfer followed by containment, and with C enabled, a low-half compressed
  instruction ignoring an errored successor before the crossing instruction
  reports that successor fault at address zero.
- `redirects`: cancellation of private permission waits, flush before grant,
  at grant, awaiting response, at response, with a registered result and with a
  buffered word; repeated flush, killed error drain, replacement at the correct
  target including upper-half targets, and coordinated reset/recovery.

Depths 2, 3, 4, 5 and 8 are covered with C disabled/enabled. There is no decoder,
decompressor, IF/DE register, predictor, privileged controller, debug controller,
FENCE.I handshake or architectural retirement in this fixture. Those integrations
remain with the production IF/core work.
