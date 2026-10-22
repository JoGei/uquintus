"""Physical comparison summaries preserve timing failures and area definitions."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[2]/'impl/asic/orfs/investigations/place_compare.py'
SPEC=importlib.util.spec_from_file_location('uqu_place_compare',SOURCE)
compare=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare)


class PlaceCompareTests(unittest.TestCase):
    def test_summary_distinguishes_liberty_area_from_physical_master_area(self):
        modules={
            'gate':dict(attributes=dict(area='3.0')),
            'driver':dict(attributes=dict(area='2.0'),ports={
                'A':dict(direction='input',bits=[2]),
                'X':dict(direction='output',bits=[2])})}
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);snapshots=run/'snapshots';snapshots.mkdir()
            for stage in compare.STAGES:
                (snapshots/f'{stage}.cells.tsv').write_text('gate\t4\t3.1\ndriver\t2\t2.2\nphysical\t1\t1.5\n')
            (snapshots/'repair_timing.timing.tsv').write_text(
                'setup_worst_slack\t-0.25\nsetup_total_negative_slack\t-10.5\n'
                'placement_violations\t0\nslew_violations\t7\n')
            result=compare.summarize(run,modules)
            final=result['repair_timing']
            self.assertEqual(final['cell_count'],7)
            self.assertEqual(final['physical_only_count'],1)
            self.assertEqual(final['cell_area'],16.0)
            self.assertAlmostEqual(final['lef_cell_area'],18.3)
            self.assertEqual(final['buffer_count'],2)
            self.assertEqual(final['buffer_area'],4.0)
            self.assertEqual(final['setup_worst_slack'],-0.25)
            self.assertEqual(final['setup_total_negative_slack'],-10.5)
            self.assertEqual(final['slew_violations'],7)
            self.assertNotIn('setup_worst_slack',result['floorplan'])
            (snapshots/'resize.cells.tsv').unlink()
            with self.assertRaises(FileNotFoundError):
                compare.summarize(run,modules)


if __name__=='__main__':unittest.main()
