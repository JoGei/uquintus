# Fetched-word buffer

[uqu_if_buffer.v](../../../src/uquintus/uqu_if_buffer.v) is a FIFO of aligned,
unexpanded instruction-memory words. `MUA_IF_BUFFER_WORDS` defaults to 2 and
supports every integer capacity of at least 2, including non-power-of-two depths.
The module is independent of `ISA_C` and compressed-decoding placement.

```sh
make test COMPONENT=if_buffer CONFIG=rv32i
make lint COMPONENT=if_buffer CONFIG=rv32i
make test COMPONENT=if_prefetch CONFIG=rv32ic
```

Use `PYTHON=.venv/bin/python` for the repository environment. To explore another
depth, pass a complete hardware YAML file with the desired
`MUA_IF_BUFFER_WORDS` using `CONFIG=/path/to/profile.yml`. The
[manifest](../../../config/sim/if_buffer.yml) uses the shared runner and Bender.

## Interface and ownership

| Ports | Contract |
| --- | --- |
| `clk_i`, `rst_ni` | One clock; active-low synchronous reset of pointers and occupancy only. |
| `flush_i` | Invalidates the whole queue on the edge and immediately suppresses input readiness and both output validities. |
| `clear_i` | Clears the queue on the edge without masking current outputs/readiness. IF uses this when accepting a predicted-taken head; it has priority over pushes/pops, so no sequential word survives. Tie low for ordinary FIFO use. |
| `push_valid_i`, `push_ready_o` | Insert one word on `valid && ready`. A full queue is ready if its current head is being popped on the same edge. |
| `push_addr_i[31:0]`, `push_data_i[31:0]`, `push_error_i` | Returned word address, raw bytes and retained word-level error. Low address bits are ignored; only aligned addresses are stored/exposed. Failed words expose zero data. |
| `pop_i` | Release one existing head word on the edge. The parent qualifies this with actual instruction transfer and the aligner's `drop_word_o`. Empty pops are ignored. |
| `word0_valid_o`, `word0_addr_o[31:0]`, `word0_data_o[31:0]`, `word0_error_o` | Oldest stored word. |
| `word1_valid_o`, `word1_addr_o[31:0]`, `word1_data_o[31:0]`, `word1_error_o` | Second-oldest stored word, including ring wraparound. |

Words become visible only after insertion; there is no empty bypass. A push plus
an empty pop retains the new word. A full push/pop returns the old head before
the edge and replaces it with the new tail after the edge. Invalid read windows
expose zero address/error; data is unqualified stored-byte lookahead. Flush suppresses validity immediately without masking these bytes before the edge. A held head remains stable through tail insertions
until pop, flush or reset. Payload arrays are not reset.

The FIFO does not validate sequential addresses or match words to the current
instruction PC. IF control guarantees that word0 contains the PC and word1 is
its consecutive successor before connecting them to the
[aligner](../if_aligner/README.md). The parent advances PC and releases a word
only when the selected instruction transfers. Consuming a low-half compressed
instruction does not pop its word. Errors remain word metadata until selection;
the FIFO does not issue exceptions, inspect prefixes, or discard errors early.

## Prefetch capacity and redirects

The FIFO is storage within the prefetch path. IF control owns the instruction
PC, next fetch address, request holds, redirects, and fault containment.
The [ifetch engine](../ifetch/README.md) owns one memory transaction and its
private registered result slot. PMP remains core-owned.

With the current single writer and one outstanding transaction, IF can reserve
space without another reservation register in the FIFO:

1. Start a native fetch only when the engine is ready and `push_ready_o` is high.
2. Increment the sequential fetch address on that native acceptance.
3. Feed the engine result into the FIFO's push channel. Until that insertion,
   no other transaction can write the FIFO, and pops can only create more room.

The engine's in-flight/retained word uses the reserved capacity; its private
result register does not authorize an extra prefetched word beyond the configured
capacity. The [real-component fixture](../if_prefetch/README.md) checks
`buffered words + engine busy <= MUA_IF_BUFFER_WORDS` every active cycle.
Changing the number of writers or outstanding requests requires explicit new
capacity accounting.

Flush both buffer and fetcher together on an accepted redirect/invalidation.
The FIFO drops its contents immediately; the fetcher preserves an already
presented OBI request through grant and drains its stale response without
inserting it. The new fetch pointer may be installed while that drain finishes,
but a replacement transaction waits for the engine to become ready. The FIFO
alone cannot distinguish stale results or cancel bus work. Coordinated reset
must likewise prevent pre-reset responses from reaching a new transaction.

## Verification

- `directed`: empty pops/no bypass, fill/full backpressure, simultaneous full
  replacement, repeated ring wraps, ordered head/successor reads, address
  alignment/wraparound, repeated addresses, error payload suppression and holds.
- `randomized`: 8,192 cycles per seed checked against a deque, with arbitrary
  addresses/data/errors, pushes/pops, periodic flush/reset and occupancy coverage.
- `control`: flush and reset at every occupancy, concurrent push/pop cancellation,
  repeated invalidation, hidden stale payload, and refill.

Depths 2, 3, 4, 5 and 8 are exercised through complete hardware configurations.
The separate prefetch fixture checks actual fetch/buffer/aligner integration for
C disabled/enabled. These tests do not constitute a complete IF stage or core.
