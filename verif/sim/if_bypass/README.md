# IF word-buffer bypass policy

[uqu_if_bypass.v](../../../src/uquintus/uqu_if_bypass.v) is an IF-owned wrapper
around the existing [registered FIFO](../if_buffer/README.md). Its word ports
match that FIFO; it adds no sequential state. `MUA_IF_BUFFER_WORDS` still sets
the FIFO capacity, including non-power-of-two depths.

`MUA_REDIRECT_BYPASS` independently combines `if_buffer` (bit 0),
`redirect_request` (bit 1), and `ifetch_result` (bit 2). `none` is zero/default;
all eight canonical combinations are accepted. This wrapper uses only bit 0;
the request and result bits are handled by IF steering and `uqu_ifetch`.
With bit 0 clear, windows show only stored words. With it set, a valid input
can occupy an empty first window, or the second window when exactly one word
is stored. This input is an ifetch completion: registered by default, or a live
memory response if `ifetch_result` is also selected. The policy applies to boot,
redirect and sequential refills, independently of prediction and C decoding.

On `push_valid && push_ready`, the wrapper accepts the input exactly once:

- If a live first word is fully consumed by `pop_i`, discard it without storage.
- Otherwise retain the incoming address/data/error in the FIFO, including a
  held candidate or a word whose low compressed half alone was consumed.
- A live second word is retained even if `pop_i` removes the stored head;
  a crossing instruction can therefore use it without losing its remaining half.

`flush_i` and reset mask outputs immediately. `clear_i` is synchronous: the
current token remains visible, then all stored old-stream words are discarded.
Failed words carry their aligned address/error and zero data. Full FIFOs still
support simultaneous stored-head removal and input acceptance; they do not
forward input ahead of stored data.

```sh
make test COMPONENT=if_bypass CONFIG=rv32i
make test COMPONENT=if_bypass CONFIG=rv32imc_bimodal_idata_parallel_div1_ifbuf_bypass
make test COMPONENT=if CONFIG=rv32imc_bimodal_idata_parallel_div1_ifbuf_bypass TEST=fresh_fetch_latency
```

The component shares the FIFO's deque scoreboard for directed, randomized and
reset/flush/clear tests. `live_words` checks immediate consumption, retention
under stalls, a crossing instruction's second word, errors and prediction clear.
IF-stage tests additionally cover mixed instruction lengths, all compressed
strategies, protection/fault association, prediction/replay and delayed grants.
