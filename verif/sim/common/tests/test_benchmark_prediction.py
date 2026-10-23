"""Trace integrity, RV32I/C control flow and finite-history model boundaries."""
from collections import Counter
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark
from benchmark_prediction import (MAGIC, RECORD, Event, Predictor, control_flow,
    kernel_repetitions, simulate, trace_records, validate_trace, write_diagnostic_report)


def event(cycle, pc=0x100, taken=True, target=0x200, kind='conditional'):
    return Event(cycle, pc, kind, taken, target, True)


class PredictionDiagnosticTests(unittest.TestCase):
    def test_trace_integrity_and_native_window_ordinals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'retire.bin'
            rows = [(10, 0x100, 0x13), (12, 0x104, 0x13), (17, 0x108, 0x13)]
            valid = MAGIC + b''.join(RECORD.pack(*row) for row in rows)
            path.write_bytes(valid)
            native = dict(retired=3, start=dict(cycle=10, retired=1), stop=dict(cycle=17, retired=3))
            self.assertEqual(list(trace_records(path)), rows)
            self.assertEqual(validate_trace(path, native)['records'], 3)
            native['stop']['retired'] = 2
            with self.assertRaisesRegex(ValueError, 'disagrees'):
                validate_trace(path, native)
            for bad in (b'wronghdr', valid[:-1], valid + RECORD.pack(*rows[-1]),
                        MAGIC + RECORD.pack(1, 0x101, 0x13)):
                path.write_bytes(bad)
                with self.subTest(data=bad), self.assertRaises(ValueError):
                    list(trace_records(path))

    def test_original_instruction_decoding_and_ambiguity(self):
        branch = control_flow(1, 0x800000de, 0x01d8de63, 0x800000fa)
        self.assertEqual((branch.kind, branch.taken, branch.target), ('conditional', True, 0x800000fa))
        self.assertFalse(control_flow(1, 0x800000de, 0x01d8de63, 0x800000e2).taken)
        self.assertEqual(control_flow(1, 0x800000f6, 0x1af0206f, 0x80002aa4).kind, 'jal')
        self.assertEqual(control_flow(1, 0x100, 0xdead_a001, 0x100).target, 0x100)
        self.assertEqual(control_flow(1, 0x100, 0x8082, 0x200).kind, 'jalr')
        self.assertTrue(control_flow(1, 0x100, 0xc001, 0x100).taken)
        self.assertIsNone(control_flow(1, 0x100, 0x13, 0x104))
        for word in (0x00000263, 0xc009):
            with self.subTest(word=word), self.assertRaisesRegex(ValueError, 'fallthrough'):
                control_flow(1, 0x100, word, 0x104)
        with self.assertRaisesRegex(ValueError, 'encoded'):
            control_flow(1, 0x100, 0xa001, 0x200)

    def test_unlimited_history_still_misses_first_visit_and_changed_outcomes(self):
        model, counts = Predictor(None, None), Counter()
        for e in (event(1), event(2), event(3, taken=False)):
            model.step(e, counts)
        self.assertEqual(counts['btb_hits'], 2)
        self.assertEqual(counts['correct_taken_predictions'], 1)
        self.assertEqual(counts['next_pc_errors'], 2)
        self.assertEqual(counts['prior_target_opportunities'], 1)
        for e in (event(4, pc=0x120, target=0x200, kind='jalr'),
                  event(5, pc=0x120, target=0x300, kind='jalr')):
            model.step(e, counts)
        self.assertEqual(counts['next_pc_errors'], 4)

    def test_capacity_conflicts_and_unconditional_direction_invalidation(self):
        finite, unlimited = Predictor(16, 16), Predictor(None, None)
        fc, uc = Counter(), Counter()
        for cycle, pc in enumerate((0x100, 0x120, 0x100, 0x120), 1):
            finite.step(event(cycle, pc=pc), fc)
            unlimited.step(event(cycle, pc=pc), uc)
        self.assertEqual(fc['btb_hits'], 0)
        self.assertEqual(uc['btb_hits'], 2)
        model, counts = Predictor(16, None), Counter()
        model.step(event(1))
        model.step(event(2, pc=0x140, kind='jal'))
        model.step(event(3), counts)
        self.assertEqual(counts['btb_hits'], 1)
        self.assertEqual(counts['direction_errors'], 1)
        self.assertEqual(counts['next_pc_errors'], 1)

    def test_warmup_history_is_separate_from_empty_at_timer_entry(self):
        results = simulate([event(1), event(2), event(3)], 1, 3, capacities=(16,))
        warm, cold = results
        self.assertEqual(warm['state'], 'warm')
        self.assertEqual(warm['next_pc_errors'], 0)
        self.assertEqual(cold['state'], 'window_cold')
        self.assertEqual(cold['next_pc_errors'], 1)

    def test_kernel_boundaries_exclude_untaken_layout_back_edges(self):
        # One warmup plus three identical kernel passes. Both conditionals are
        # visited every pass; only the true outer-loop tail is taken N-1 times.
        rows = [(1, 0x80, 0x13)]
        for base in (10, 20, 30, 40):
            rows += [(base, 0x100, 0x13), (base+1, 0x104, 0x13), (base+2, 0x108, 0x13)]
        es = [event(base+1, pc=0x104, taken=False, target=0x100)
              for base in (10,20,30,40)]
        es += [event(base+2, pc=0x108, taken=base in (20,30), target=0x100)
               for base in (10,20,30,40)]
        es.sort()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'retire.bin'
            path.write_bytes(MAGIC + b''.join(RECORD.pack(*r) for r in rows))
            phases = kernel_repetitions(path, es, dict(start=dict(cycle=15), stop=dict(cycle=45)), 3)
            self.assertEqual(phases['loop_tail'], '0x108')
            self.assertEqual(phases['measured']['steady_middle']['repetitions'], 1)
            self.assertEqual(len(phases['repetitions']), 4)
            self.assertEqual(phases['measured']['boot_first_kernel']['retired'], 3)

    def test_checked_mode_does_not_silently_ignore_trace_request(self):
        with self.assertRaisesRegex(ValueError, 'BENCHMARK_TRACE requires'):
            benchmark.run('coremark', 'rv32i', mode='checked', retire_trace=True)

    def test_report_labels_model_metrics_and_keeps_json_links(self):
        models = simulate([event(1), event(2)], 0, 3, capacities=(16, None))
        result = dict(profile='example', models=models)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_diagnostic_report(root, Path('suite.json'), [result], [16, None])
            page = (root/'index.html').read_text()
            self.assertIn('modeled next-PC accuracy', page)
            self.assertIn('counterfactual cycles', page)
            self.assertIn('example.json', page)
            self.assertEqual(json.loads((root/'summary.json').read_text())['status'], 'passed')

    def test_failed_analysis_replaces_previously_successful_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            suite = root/'suite.json'
            suite.write_text(json.dumps(dict(status='passed', diagnostic_retirement_trace=True,
                requested=['missing'], results=[dict(profile='missing', status='passed',
                                                     directory=str(root/'missing'))])))
            (root/'index.html').write_text('STALE SUCCESS')
            command = [sys.executable, str(Path(__file__).resolve().parents[1]/'benchmark_prediction.py'),
                       '--suite', str(suite), '--output', str(root), '--capacities', '16', '--jobs', '1']
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads((root/'summary.json').read_text())['status'], 'failed')
            self.assertNotIn('STALE SUCCESS', (root/'index.html').read_text())


if __name__ == '__main__':
    unittest.main()
