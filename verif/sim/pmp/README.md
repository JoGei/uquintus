# Core-owned shared PMP checker

`src/uquintus/uqu_pmp.v` is a combinational Verilog-2005 checker for the fixed
sixteen-entry, G=0 PMP profile in [architecture, Section 8.1](../../../doc/uqu_spec.arch.md#81-internal-pmp-and-memory-fault-boundary).
The [core](../core/README.md) owns one instance. It consumes CSR-owned PMP state
once and IF/MEM access addresses/control independently, then returns each stage's
permission result. Shared region decoding feeds separate concurrent comparison,
priority and permission logic. Core integration includes CSR storage, write
legalization/locking and effective-privilege selection. This standalone
regression checks the permission block; core tests cover its pipeline use.

| Port/parameter | Meaning |
| --- | --- |
| `ISA_PMP` | Zero (default): constant allow with checking logic excluded. One: enable all sixteen entries. Other values fail elaboration. |
| `pmpcfg_i[127:0]` | Sixteen configuration bytes: entry i occupies `[8*i +: 8]`; R/W/X bits 0/1/2, A bits 4:3, L bit 7. Bits 6:5 ignored. |
| `pmpaddr_i[511:0]` | Sixteen 32-bit architectural address encodings; entry i occupies `[32*i +: 32]`. Address bits above the core bus width are retained for comparisons. |
| `if_addr_i[31:0]` | IF access's original byte address, before bus alignment. |
| `if_size_i[1:0]` | IF log2 byte count: 0=one, 1=two, 2=four; 3 unsupported. |
| `if_priv_m_i` | Current execution privilege: one for M-mode, zero for U-mode. |
| `if_allow_o` | IF permission result; execute permission is implicit. |
| `mem_addr_i[31:0]` | MEM access's original effective byte address, before bus alignment. |
| `mem_size_i[1:0]` | MEM log2 byte count, encoded as on IF. |
| `mem_access_i[2:0]` | Required R/W/X bits in configuration order: load `001`, store `010`. Every requested bit must be permitted. |
| `mem_priv_m_i` | Effective data privilege: one for M-mode, zero for U-mode. Caller accounts for MPRV/MPP independently of IF. |
| `mem_allow_o` | MEM permission result. Each stage qualifies its own output with a live access. |

The module has no clock, reset, storage, bus, or transaction handshake. The core
parent connects CSR-owned PMP state to this single block. IF and MEM do not own
PMP instances. Sixteen generated region decoders consume only CSR inputs; the base IF/MEM
generated access checkers consume the same decoded bounds plus their own
address/control. No request arbitration, shared transaction state, or cross-port
backpressure is required. CSR serialization must
keep the settings consistent with each checked access; an accepted LSU access
already retains its local access-denial decision.

The checker implements OFF, TOR, NA4 and NAPOT, including TOR's raw predecessor
address when that predecessor is OFF or uses another mode. A reversed or empty
TOR interval matches nothing. NAPOT sizes from eight bytes through the largest
encodings are supported; wide bounds do not alias onto low 32-bit addresses.

The lowest-numbered entry touching any byte wins. Partial coverage fails even
for an unlocked M-mode access; another entry cannot supply the missing bytes.
For a complete match, unlocked M-mode bypasses R/W/X permissions; locked M-mode
and U-mode require all requested permissions. No match permits M-mode and denies
U-mode, including when all entries are OFF. These rules follow the pinned
[RISC-V privileged specification](https://docs.riscv.org/reference/isa/v20260120/priv/machine.html).
CSR write-lock behavior is separate from the checker's use of L.

With checking enabled, unsupported size, an empty access mask, and an access
extending beyond the 32-bit bus address space return deny. Alignment is checked
by the owning stage: MEM must retain the LSU's misalignment-before-access-fault
priority. The CSR unit must supply legalized configuration bytes; W=1/R=0 is a
reserved architectural encoding, not a separate checker policy.

MEM will convert `!mem_allow_o` to LSU `req_access_fault_i` at native acceptance.
That fault is distinct from the controller's `request_permit_i`: denial completes
locally, while permission waits until older instructions are safe before bus
presentation. IF will use `if_allow_o` to suppress denied fetches and retain fault metadata for
normal instruction assembly and precise exception handling. No PMP state or
privilege signals are added to OBI.

Run the disabled checker with the baseline configuration:

```sh
make test COMPONENT=pmp CONFIG=rv32i
make lint COMPONENT=pmp CONFIG=rv32i
```

For the enabled checker, copy a complete hardware YAML configuration and change
`ISA_PMP` to `1`, then pass its filename using `CONFIG=<path>`. Other parameters
must remain explicitly present. Both modes use the same tests:

- `directed`: every entry position, address mode, legal R/W/X combination,
  privilege and lock state; NAPOT sizes/boundaries, full-width encoded bounds,
  TOR empty/reversed ranges, invalid controls, and top-of-address-space accesses.
- `priority`: overlapping allow/deny entries, every pair of entry positions,
  unlocked M-mode versus lower locked entries, partial coverage at either end
  of an access, and all-OFF default behavior.
- `randomized`: 4,096 mixed sixteen-entry configurations, three accesses each,
  including random and region-boundary addresses; reproducible using `SEED`.
- `concurrent`: simultaneous fetch/data accesses with opposite permission
  results; changes to one port while the other remains held; independent
  privileges, sizes and region selections; shared CSR updates with held inputs;
  and 2,048 random independent IF/MEM request pairs.

The Python reference decodes intervals mathematically and tests each accessed
byte independently for both ports on every sample. IF always requests execute
permission; MEM supplies its separate requirement mask. Explicit directed expectations additionally check priority,
partial-match rejection and unmatched-mode behavior. No CSR or bus behavior is
claimed by these standalone tests.

## Replay queries

When `MUA_BTB_IDATA_DEPTH > 0`, an additional bank checks the aligned
`replay_addr_i` as a four-byte execute access under `replay_priv_m_i`. With
`ISA_C=1`, a second bank checks `(replay_addr_i+4) mod 2^32`. Results occupy
`replay_allow_o[0]` and `[1]`; inactive banks are hardwired allowed. All banks
share CSR region decoding and evaluate concurrently with IF continuation and
MEM. The core passes effective depth zero when prediction/BTB is disabled.
There is no checker instance inside IF. The interval-model suite checks every
enabled replay bank alongside its original IF/MEM comparisons.
