"""BPU measurement denominators, serialization and evidence consistency."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bpu_stats import COUNTERS, metrics, statistics, unpack_snapshot, validate


class BpuStatsTests(unittest.TestCase):
    def fixture(self, mode='bimodal', btb='direct_mapped'):
        counts = dict.fromkeys(COUNTERS, 0)
        counts.update(retired_instructions=100, conditional_branches=20,
                      direct_jumps=5, indirect_jumps=5, taken_conditional_branches=12,
                      taken_control_flow=22, de_redirects=8, compressed_control_flow=2)
        if mode != 'none':
            counts.update(direction_predictions=20, direction_mispredictions=4,
                          effective_direction_mispredictions=6, control_flow_predictions=30,
                          control_flow_mispredictions=8)
            if btb != 'none':
                counts.update(btb_lookups=100, btb_hits=25, btb_control_flow_lookups=30,
                              btb_control_flow_hits=24, false_btb_hits=1,
                              target_predictions=18, target_mispredictions=2)
        start = [2**33]*len(COUNTERS)
        stop = [v+counts[k] for k, v in zip(COUNTERS, start)]
        params = dict(MUA_BRANCH_PREDICTOR=mode, MUA_BTB=btb)
        return start, stop, params

    def test_scope_rates_and_disabled_denominators(self):
        args = self.fixture()
        stats = statistics(*args, 100)
        self.assertEqual(stats['rates_percent']['direction_accuracy'], 80)
        self.assertEqual(stats['rates_percent']['effective_direction_accuracy'], 70)
        self.assertAlmostEqual(stats['rates_percent']['target_accuracy'], 100*16/18)
        self.assertEqual(stats['counts']['btb_control_flow_misses'], 6)
        self.assertEqual(validate(stats, args[2], 100), stats)
        for mode, btb in [('none', 'direct_mapped'), ('static_not_taken', 'none'), ('bimodal', 'none')]:
            stats = statistics(*self.fixture(mode, btb), 100)
            self.assertIsNone(stats['rates_percent']['btb_hit_rate'])
            self.assertIsNone(stats['rates_percent']['target_accuracy'])
            self.assertFalse(any(m['name'] == 'bpu_target_accuracy' for m in metrics(stats)))
            self.assertEqual(stats['rates_percent']['direction_accuracy'] is None, mode == 'none')

    def test_full_width_packed_counter_order(self):
        values = [2**40+i for i in range(len(COUNTERS))]
        packed = sum(value << (64*i) for i, value in enumerate(values))
        self.assertEqual(unpack_snapshot(packed), values)
        for bad in (-1, True, 1 << (64*len(COUNTERS))):
            with self.subTest(bad=bad), self.assertRaises(ValueError): unpack_snapshot(bad)

    def test_invalid_snapshots_and_counts_are_rejected(self):
        start, stop, params = self.fixture()
        for key, value in [('retired_instructions', 99), ('btb_hits', 101),
                           ('false_btb_hits', 0), ('direction_mispredictions', 21),
                           ('target_mispredictions', 19), ('taken_control_flow', 21)]:
            bad = list(stop)
            bad[COUNTERS.index(key)] = start[COUNTERS.index(key)] + value
            with self.subTest(key=key), self.assertRaises(ValueError): statistics(start, bad, params, 100)
        for bad in (None, [], [True]*len(COUNTERS), [-1]*len(COUNTERS), start):
            with self.subTest(snapshot=bad), self.assertRaises(ValueError): statistics(start, bad, params, 100)
        for bad in ({}, dict(params, MUA_BRANCH_PREDICTOR='unknown'), dict(params, MUA_BTB=[])):
            with self.subTest(parameters=bad), self.assertRaises(ValueError): statistics(start, stop, bad, 100)

    def test_derived_results_and_scope_cannot_be_tampered(self):
        args = self.fixture()
        stats = statistics(*args, 100)
        for field, value in [('scope', 'fetch-attempts'), ('rates_percent', {}),
                             ('counts', {}), ('redirects_per_1000_instructions', 999)]:
            bad = copy.deepcopy(stats)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate(bad, args[2], 100)
        with self.assertRaises(ValueError): validate({}, args[2], 100)
