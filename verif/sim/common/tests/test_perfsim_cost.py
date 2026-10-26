"""Native cost boundaries, trace suppression and per-child resource accounting."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT/'verif/perfsim'))
from benchmark_cost import measure, native_signature, summarize, trace_free_command


class PerfsimCostTests(unittest.TestCase):
    def test_median_range_cpu_and_peak_memory(self):
        samples=[dict(wall_seconds=v,user_seconds=v/2,system_seconds=v/4,max_rss_kib=1024*v)
                 for v in (1,2,100)]
        result=summarize(samples)
        self.assertEqual(result['median_seconds'],2)
        self.assertEqual(result['min_seconds'],1)
        self.assertEqual(result['max_seconds'],100)
        self.assertEqual(result['median_cpu_seconds'],1.5)
        self.assertEqual(result['peak_rss_mib'],100)
        with self.assertRaisesRegex(ValueError,'empty'):
            summarize([])

    def test_trace_free_arguments_preserve_workload_and_bus_parameters(self):
        image=Path('/tmp/program-image.bin')
        rtl=['/tmp/rtl','program-image.bin','1000','0x80000000','1','2','0x1000','4','8','retire.bin']
        self.assertEqual(trace_free_command(rtl,'rtl',image),[rtl[0],str(image),*rtl[2:9]])
        self.assertEqual(len(rtl),10)
        iss=['/tmp/iss','old-image','entry','host','start','stop','limit','misa','hart','3','range']
        native=trace_free_command(iss,'iss',image)
        self.assertEqual(native[9],'0')
        self.assertEqual(native[2:9],iss[2:9])
        self.assertEqual(native[10:],iss[10:])
        with self.assertRaisesRegex(ValueError,'unexpected RTL'):
            trace_free_command(rtl+['extra'],'rtl',image)

    def test_native_signatures_check_completion_and_model_identity(self):
        good=dict(status='passed',functional_instructions=100,models=[dict(id='a',cycles=50,instructions=40)])
        signature=native_signature(good,'iss')
        self.assertEqual(signature['models'],dict(a=(50,40)))
        with self.assertRaisesRegex(ValueError,'duplicate'):
            native_signature(dict(good,models=good['models']*2),'iss')
        with self.assertRaisesRegex(ValueError,'did not pass'):
            native_signature(dict(good,status='failed'),'iss')

    @unittest.skipUnless(hasattr(os,'wait4') and hasattr(os,'sched_getaffinity') and shutil.which('taskset'),
                         'Linux process accounting and taskset required')
    def test_peak_rss_is_per_child_and_process_failures_are_retained(self):
        cpu=min(os.sched_getaffinity(0))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            large=measure([sys.executable,'-c',
                'b=bytearray(64*1024*1024)\nfor i in range(0,len(b),4096): b[i]=1'],root/'large',cpu,10)
            small=measure([sys.executable,'-c','pass'],root/'small',cpu,10)
            self.assertGreater(large['max_rss_kib'],small['max_rss_kib']+32*1024)
            self.assertGreater(small['wall_seconds'],0)
            self.assertGreater(small['user_seconds']+small['system_seconds'],0)
            with self.assertRaisesRegex(RuntimeError,'native execution failed'):
                measure([sys.executable,'-c','raise SystemExit(7)'],root/'failed',cpu,10)
            self.assertEqual(json.loads((root/'failed/process.json').read_text())['exit_code'],7)


if __name__=='__main__':
    unittest.main()
