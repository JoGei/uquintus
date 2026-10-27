"""Verify the experiment isolates forwarding and joins timing with RTL cycles."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    'forwarding_sweep', ROOT / 'impl/asic/orfs/explore/forwarding_sweep.py')
sweep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sweep)


class ForwardingSweepTests(unittest.TestCase):
    def test_ladder_adds_one_real_path_and_freezes_every_other_parameter(self):
        base = yaml.safe_load((ROOT / 'config/rv32imc_bimodal_idata.yml').read_text())
        cases, configs = sweep.make_cases(base)
        self.assertEqual(len(cases), 6)
        self.assertEqual(len(configs), 6)
        previous = None
        for step, case in enumerate(cases):
            config = configs[case['name']]
            self.assertEqual(case['step'], step)
            self.assertEqual(len(case['paths']), step)
            self.assertEqual(set(config), set(base))
            self.assertEqual({k: v for k, v in config.items() if k not in sweep.FORWARD_PARAMS},
                             {k: v for k, v in base.items() if k not in sweep.FORWARD_PARAMS})
            self.assertNotIn('wb2mem', case['paths'])
            if previous is not None:
                self.assertEqual(sum(config[k] != previous[k] for k in config), 1)
            previous = config
        self.assertEqual(cases[0]['paths'], [])
        self.assertEqual(cases[1]['paths'], ['wb2de'])
        self.assertEqual(cases[-1]['paths'], ['wb2de', 'wb2ex', 'mem2ex', 'mem2de', 'ex2de'])
        self.assertEqual(configs[cases[-1]['name']], base)
        self.assertEqual(base['MUA_MUL'], 'dadda_mac')
        self.assertEqual(base['MUA_MULDIV_ITERUNROLL'], 8)
        self.assertEqual((base['ISA_M'], base['ISA_C']), (1, 1))

    def test_report_uses_platform_baselines_and_never_qualifies_missing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sweep, 'ROOT', Path(tmp)):
            root = Path(tmp)
            directory = root / 'summary'
            directory.mkdir()
            cases = []
            for step, cycles in enumerate((2000, 1000)):
                bench = f'benchmark{step}.json'
                (root / bench).write_text(json.dumps(dict(status='passed', metrics=[
                    dict(name='benchmark_cycles', value=cycles),
                    dict(name='benchmark_cpi', value=cycles / 1000)])))
                for platform, period in (('sky130hd', 25), ('ihp-sg13g2', 20)):
                    (root / f'{platform}{step}.json').write_text(json.dumps(dict(status='passed', metrics=[
                        dict(name='minimum_clock_period', value=period + 5 * step),
                        dict(name='cell_area', value=100 + step * 10)])))
                cases.append(dict(name=f'f{step}', step=step, added='wb2de' if step else 'none',
                                  paths=['wb2de'] if step else [], bp=16, btb=16, hwords=6,
                                  benchmark=bench, sky130hd=f'sky130hd{step}.json',
                                  **({'ihp-sg13g2': f'ihp-sg13g2{step}.json'} if not step else {})))
            (directory / 'config').mkdir()
            (directory / 'config/f0.yml').write_text(yaml.safe_dump(dict(
                MUA_MUL='dadda_mac', MUA_DIV='parallel', MUA_MULDIV_ITERUNROLL=8)))
            rows = sweep.render(directory, dict(context=dict(clock_period_ns=40),
                                platforms=['sky130hd', 'ihp-sg13g2'], cases=cases))
            self.assertEqual(len(rows), 4)
            self.assertAlmostEqual(rows[1]['runtime_speedup'], 50 / 30)
            self.assertEqual(rows[0]['execution_time_ms'], .05)
            self.assertFalse(rows[3]['qualified'])
            self.assertNotIn('runtime_speedup', rows[3])
            self.assertIn('WB→DE is implicit', (directory / 'index.html').read_text())
            self.assertIn('DIV=parallel', (directory / 'index.html').read_text())
            self.assertNotIn('DIV remains iterative', (directory / 'index.html').read_text())
            self.assertIn('../benchmark0.json', (directory / 'index.html').read_text())
            self.assertEqual(json.loads((directory / 'summary.json').read_text())['rows'], rows)
            cases[1]['pending']={'ihp-sg13g2':'queued'}
            rows=sweep.render(directory,dict(context=dict(clock_period_ns=40),
                platforms=['sky130hd','ihp-sg13g2'],cases=cases))
            self.assertEqual(rows[3]['placement_status'],'queued')
            self.assertFalse(rows[3]['qualified'])


if __name__ == '__main__':
    unittest.main()
