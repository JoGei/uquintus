"""Power evidence must preserve physical inputs, measured activity and units."""
import gzip
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

COMMON = Path(__file__).resolve().parents[2] / 'impl/asic/orfs/common'
sys.path.insert(0, str(COMMON))
SPEC = importlib.util.spec_from_file_location('uqu_power', COMMON / 'power.py')
power = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(power)


class PowerTests(unittest.TestCase):
    def test_dynamic_energy_uses_both_dynamic_terms_and_exact_window(self):
        source = {'Total': dict(internal=.002, switching=.003, leakage=.001, total=.006)}
        result = power.energy(source, 1000, 500, 20)
        self.assertAlmostEqual(result['duration_s'], 20e-6)
        self.assertAlmostEqual(result['dynamic_power_w'], .005)
        self.assertAlmostEqual(result['dynamic_energy_j'], 100e-9)
        self.assertAlmostEqual(result['total_energy_j'], 120e-9)
        self.assertAlmostEqual(result['dynamic_energy_per_instruction_j'], 200e-12)
        for field in source['Total']:
            for value in (-1, math.nan, math.inf, '1'):
                bad = {'Total': dict(source['Total'], **{field: value})}
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    power.energy(bad, 1000, 500, 20)
        for cycles, retired, period in ((0, 1, 20), (1, 0, 20), (1, 1, 0), (1, 1, math.inf)):
            with self.assertRaises(ValueError): power.energy(source, cycles, retired, period)
        with self.assertRaises(ValueError):
            power.energy({'Total': dict(source['Total'], total=.1)}, 1, 1, 20)

    def test_default_activity_does_not_count_as_measured(self):
        result = power.annotation('vcd         999\ninput         0\nunannotated 1\n')
        self.assertEqual(result['measured_pin_fraction'], .999)
        for report in ('', 'input 1000\nunannotated 0\n', 'vcd 98\nunannotated 2\n',
                       'vcd 0\nunannotated 0\n', 'saif 1000\nunannotated 0\n', 'vcd 1000\n',
                       'vcd 1000\nvcd 10\nunannotated 0\n'):
            with self.subTest(report=report), self.assertRaises(ValueError): power.annotation(report)

    def test_sta_clock_warnings_cannot_qualify_power(self):
        power.check_activity_clock('Annotated 1234 pin activities.\n')
        for text in ('[WARNING STA-1450] VCD max time is zero.',
                     '[WARNING STA-1452] clock mismatch',
                     '[WARNING STA-1453] no transitions',
                     'Warning: clock clk pin CLK has no vcd transitions.',
                     'Warning: clock clk vcd period 20 differs from SDC clock period 60'):
            with self.subTest(text=text), self.assertRaises(ValueError): power.check_activity_clock(text)

    def test_gate_shadow_uses_original_inputs_and_qualified_bus_comparisons(self):
        text = 'module uqu_core (clk_i, imem_req_o);\n input clk_i;\n output imem_req_o;\nendmodule\n'
        result = power.gate_include(text)
        self.assertIn('.clk_i(u_core.clk_i)', result)
        self.assertIn('uqu_power_core u_gate', result)
        self.assertIn('if ((imem_req_o) && power_imem_addr_o !== u_core.imem_addr_o)', result)
        with self.assertRaises(ValueError): power.gate_include('module unknown; endmodule')

    def test_functional_cells_reject_missing_input_or_model_but_allow_unused_output(self):
        models = 'module cell(A, X, Y);\n input A;\n output X;\n output Y;\nendmodule\n'
        source = 'module uqu_core (a);\n input a;\n cell \\special[1]  (.A(a), .X(out));\n tap no_pins ();\nendmodule\n'
        result = power.functional_netlist(source, models)
        self.assertIn('module uqu_power_core', result)
        self.assertIn('.Y()', result)
        self.assertNotIn('no_pins', result)
        with self.assertRaisesRegex(ValueError, 'unconnected cell input'):
            power.functional_netlist(source.replace('.A(a), ', ''), models)
        with self.assertRaisesRegex(ValueError, 'missing functional cell model'):
            power.functional_netlist(source.replace('cell \\', 'missing \\'), models)

    def test_vcd_window_requires_picoseconds_and_a_complete_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'activity.vcd.gz'
            def write(text):
                with gzip.open(path, 'wt') as stream: stream.write(text)
            write('$timescale 1ps $end\n#0\n0!\n#20000\n1!\n')
            self.assertEqual(power.vcd_window(path), (0, 20000))
            for bad in ('$timescale 1ns $end\n#0\n#20\n', '$timescale 1ps $end\n#0\n#20'):
                write(bad)
                with self.assertRaises(ValueError): power.vcd_window(path)

    def test_tcl_paths_are_literal(self):
        path = '/tmp/space $value [error injected] "x" \\end\n'
        result = subprocess.run(['tclsh'], input='set item ' + power.tcl(path) + '\nputs -nonewline $item\n',
                                text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout, path)

    def test_native_capture_includes_low_and_high_phase_and_exact_duration(self):
        # Test the actual C++ clock-window helper without building a whole core.
        # The trace stub records dump timestamps; GzipVcdFile still uses zlib.
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'verilated_vcd_c.h').write_text('''
#include <string>
#include <vector>
#include <cstdint>
#include <sys/types.h>
struct VerilatedVcdFile {
    virtual ~VerilatedVcdFile() = default;
    virtual bool open(const std::string&) { return true; }
    virtual void close() {}
    virtual ssize_t write(const char*, ssize_t n) { return n; }
};
struct VerilatedVcdC {
    std::vector<uint64_t> times;
    std::string unit, resolution;
    explicit VerilatedVcdC(VerilatedVcdFile*) {}
    void set_time_unit(const char* s) { unit = s; }
    void set_time_resolution(const char* s) { resolution = s; }
    void open(const std::string&) {}
    void close() {}
    void dump(uint64_t t) { times.push_back(t); }
};
''')
            header = power.ROOT / 'verif/sim/benchmark/activity_vcd.h'
            source = directory / 'window.cpp'
            source.write_text('#include "' + str(header) + '''"
#include <iostream>
int main() {
    ActivityVcd a;
    if (a.trace.unit != "1ps" || a.trace.resolution != "1ps") return 2;
    a.low(); a.rising(true, false);
    a.low(); a.rising(false, false);
    a.low(); a.rising(false, true); a.low();
    for (auto t : a.trace.times) std::cout << t << " ";
    GzipVcdFile file;
    if (!file.open("sample.gz") || file.write("data", 4) != 4) return 1;
    file.close();
}
''')
            executable = directory / 'window'
            subprocess.run(['g++', '-std=c++17', '-I' + str(directory), str(source), '-lz', '-o', str(executable)],
                           check=True, capture_output=True)
            result = subprocess.run([str(executable)], cwd=directory,
                env=dict(os.environ, UQU_POWER_PERIOD_PS='20000'), check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout.split(), ['0', '10000', '20000', '30000', '40000'])
            with gzip.open(directory / 'sample.gz', 'rt') as stream: self.assertEqual(stream.read(), 'data')

    def test_unqualified_or_changed_config_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for record in ({}, dict(kind='synthesis', status='failed'),
                           dict(kind='synthesis', status='passed', component='uqu_fpu')):
                (directory / 'report.json').write_text(json.dumps(record))
                with self.assertRaisesRegex(ValueError, 'successful core implementation'):
                    power.validate_implementation(directory)

    def test_activity_reuse_requires_exact_hardware_elf_period_and_generated_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            program = directory / 'program.elf'; program.write_bytes(b'elf')
            generated = directory / 'cells.v'; generated.write_text('module cell; endmodule\n')
            raw = dict(kind='benchmark', status='passed', configuration=dict(parameters=dict(ISA_M=1)),
                       workload=power.digest(program), context=dict(activity=dict(clock_period_ps=20000)),
                       source_sha256={str(generated): power.digest(generated)})
            (directory / 'report.json').write_text(json.dumps(raw))
            for name in ('benchmark.json', 'native.json'):
                (directory / name).write_text('{"status":"passed"}')
            (directory / 'activity.vcd.gz').write_bytes(b'placeholder')
            self.assertEqual(power.validate_activity(directory, program, dict(ISA_M=1), [generated], 20000), directory)
            with self.assertRaises(ValueError):
                power.validate_activity(directory, program, dict(ISA_M=0), [generated], 20000)
            with self.assertRaises(ValueError):
                power.validate_activity(directory, program, dict(ISA_M=1), [generated], 40000)
            generated.write_text('changed cell function')
            with self.assertRaisesRegex(ValueError, 'cell models differ'):
                power.validate_activity(directory, program, dict(ISA_M=1), [generated], 20000)


if __name__ == '__main__':
    unittest.main()
