# Canonical PP/Dadda product rows

`MUA_MUL: dadda_mac` uses ordinary signed-corrected partial products and Dadda compression in EX1, exposing exactly two aligned 64-bit rows. `uqu_daddamul_rows` contains no final carry-propagate adder or registers. `gen_daddamul_rows.py` reuses the canonical full-product renderer and the same reduction schedule 28/19/13/9/6/4/3/2. Carries already have their correct weight; no extra shift is applied to row B.

The core owns the two-row boundary and C payload; MEM/EX2's `uqu_mul_finish` fuses late C before its single BK-mapped final addition. Native multiplication uses C=0. EX phase-one completion never advertises a forwardable product. See the [complete contract](../../../docs/uqu_spec.mul.md) and [late-C pipeline](../mac_pipeline/README.md).

```sh
make test COMPONENT=daddamul_rows CONFIG=rv32im_dadda_mac PYTHON=.venv/bin/python
make test COMPONENT=ex_pipeline CONFIG=rv32im_dadda_mac PYTHON=.venv/bin/python
make test COMPONENT=core CONFIG=rv32imc_bimodal_idata_dadda_mac_div1 PYTHON=.venv/bin/python
.venv/bin/python scripts/gen_daddamul_rows.py --check
.venv/bin/python -m unittest discover -s scripts/tests -p test_daddamul_rows_generator.py -v
```

The leaf fixture reconstructs both product halves using the actual MEM/EX2 finisher with C=0. Directed tests cover single-bit partial products and sign boundaries; randomized tests cover all signedness combinations against full-width integer multiplication. Generator tests verify identical compressor definitions and an all-input Yosys product-equivalence miter. Separate tests prove arbitrary-row late-C arithmetic. Backpressure, recurrence, faults and cancellation are covered by stage, parent and core tests. The [implementation guide](../../../docs/uqu_guide.impl.md#evaluate-arithmetic-and-storage-changes) explains the fixed-cut choice and how to measure alternative arithmetic designs.
