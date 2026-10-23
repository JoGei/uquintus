"""Exercise Tcl region classification and empty-collection guards without STA."""
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[2]/'impl/asic/orfs/common/stage_paths.tcl'


class StagePathTests(unittest.TestCase):
    def execute(self,folder,body):
        script=folder/'test.tcl'
        script.write_text('set uqu_timing_dir [lindex $argv 0]\n'+body)
        return subprocess.run(['tclsh',str(script),str(folder),str(SOURCE)],text=True,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout

    def test_names_are_classified_without_guessing_shared_or_mixed_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            output=self.execute(root,'''proc current_design {} {return uqu_fpu}
source [lindex $argv 1]
foreach nets {{u_if.u_buffer.data_q[0]} {u_de.state_q} {u_ex.state_q} {u_mem/state_q}
              {u_wb.state_q} {de_pc_q[2]} {ex_data_q[1]} {mem_data_q[1]} {wb_data_q[1]}
              {if_pc[2]} {u_gpr.registers[1]} {_auto_123_} {u_if.pc_q de_pc_q}} {
  puts [uqu_register_region $nets]
}
''')
            self.assertEqual(output.splitlines(),['IF','DE','EX','MEM','WB','DE','EX','MEM','WB',
                                                  'IF','CORE','CORE','CORE'])
            self.assertEqual((root/'regions.tsv').read_text(),'status\tnot_applicable\n')
            self.assertFalse((root/'paths.tsv').exists())

    def test_empty_regions_never_issue_unrestricted_sta_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            output=self.execute(root,'''proc current_design {} {return uqu_core}
proc all_registers {args} {return reg0}
proc get_pins {args} {return pin0}
proc get_nets {args} {return net0}
proc get_full_name {obj} {if {$obj eq "net0"} {return {u_if.pc_q[2]}}; return $obj}
set queries 0
proc find_timing_paths {args} {
  foreach flag {-from -to} {
    set index [lsearch -exact $args $flag]
    if {$index < 0 || ![llength [lindex $args [expr {$index+1}]]]} {error "unrestricted query"}
  }
  incr ::queries
  return {}
}
set regs reg0
source [lindex $argv 1]
puts $queries
''')
            self.assertEqual(output.strip(),'4')
            lines=(root/'paths.tsv').read_text().splitlines()
            self.assertEqual(len(lines),84)
            self.assertTrue(all(line.endswith('\tno_paths') for line in lines))
            self.assertIn('IF\t1\n',(root/'regions.tsv').read_text())


if __name__=='__main__': unittest.main()
