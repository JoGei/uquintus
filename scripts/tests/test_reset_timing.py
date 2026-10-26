"""A timing trial must not turn missing or inconsistent data into an Fmax claim."""
import importlib.util
import math
from pathlib import Path
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[2]/'impl/asic/orfs/explore/reset_timing.py'
SPEC=importlib.util.spec_from_file_location('uqu_reset_timing',SOURCE)
trial=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)


class ResetTimingTests(unittest.TestCase):
    def test_metrics_validate_frequency_period_units_and_preserve_failures(self):
        values={k:0 for k in trial.UNITS}
        values.update(minimum_clock_period=12.5,estimated_fmax=80,
                      setup_worst_slack=7.5,hold_worst_slack=-0.1,slew_violations=2)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'metrics.tsv'
            def write(data):
                path.write_text(''.join(f'{k}\t{v}\n' for k,v in data.items()))
            write(values)
            actual=trial.metrics(path)
            self.assertEqual(actual['minimum_clock_period'],12.5)
            self.assertEqual(actual['estimated_fmax'],80)
            self.assertEqual(actual['hold_worst_slack'],-0.1)
            self.assertEqual(actual['slew_violations'],2)
            for changes in ({'estimated_fmax':1},{'estimated_fmax':0},
                            {'minimum_clock_period':0},{'setup_worst_slack':math.nan}):
                write(dict(values,**changes))
                with self.subTest(changes=changes),self.assertRaises(ValueError):
                    trial.metrics(path)
            write({k:v for k,v in values.items() if k!='hold_worst_slack'})
            with self.assertRaises(ValueError):trial.metrics(path)


if __name__=='__main__':unittest.main()
