"""Candidate source/next-PC cones must not depend on live DE qualification."""
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

COMMON = Path(__file__).resolve().parents[1]
ROOT = COMMON.parents[2]
sys.path.insert(0, str(COMMON))
from hw_config import write_header

YOSYS = shutil.which(os.environ.get('YOSYS', 'yosys'))
FIELDS = ('rs0_addr_o','rs1_addr_o','rs2_addr_o','rs_used_o','rs_need_now_o',
          'rs_ex_used_o','rs_captured_o','next_pc_o')
FORBIDDEN = ('clk_i','rst_ni','flush_i','valid_i','ready_i','permit_i',
             'xif_issue_ready_i','xif_issue_accept_i','xif_issue_writeback_i',
             'xif_issue_register_read_i','xif_register_ready_i','xif_cleanup_ready_i')
SOURCES = ('uqu_decompressor.v','uqu_decoder.v','uqu_decoder_c.v',
           'uqu_decoder_select.v','uqu_branch.v','uqu_stage_de.v')


@unittest.skipUnless(YOSYS, 'Yosys required for RTL cone checks')
class DECandidateContractTests(unittest.TestCase):
    def test_candidates_exclude_live_control_and_xif_response_cones(self):
        catalog=json.loads((ROOT/'config/selectors.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);write_header(catalog,tmp)
            sources=' '.join(f'"{ROOT}/src/uquintus/{name}"' for name in SOURCES)
            for (compressed,impl,placement),embedded,xif in itertools.product(
                    ((0,0,0),(1,0,0),(1,0,1),(1,1,0)),(0,1),(0,1)):
                with self.subTest(c=compressed,impl=impl,placement=placement,e=embedded,xif=xif):
                    output=tmp/'netlist.json'
                    script=(f'read_verilog -I{tmp} -I{ROOT}/src/uquintus {sources}; '
                        f'chparam -set ISA_M 1 -set ISA_ZFINX 1 -set ISA_E {embedded} '
                        f'-set ISA_C {compressed} -set MUA_C_IMPL {impl} '
                        f'-set MUA_C_DECOMPRESS_STAGE {placement} -set XIF {xif} '
                        '-set XIF_NUM_RS 3 -set XIF_DUALWRITE 1 uqu_stage_de; '
                        'prep -top uqu_stage_de -flatten; opt -full; check -assert; '
                        f'scc -expect 0; write_json {output}')
                    result=subprocess.run([YOSYS,'-Q','-T','-p',script],text=True,
                        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
                    self.assertEqual(result.returncode,0,result.stdout)
                    modules=json.loads(output.read_text())['modules'];self.assertEqual(len(modules),1)
                    module=next(iter(modules.values()));drivers={}
                    for cell in module['cells'].values():
                        if any(kind in cell['type'].lower() for kind in ('dff','latch')):
                            continue  # Stored XIF lifecycle state is allowed.
                        inputs={bit for port,bits in cell['connections'].items()
                                if cell['port_directions'][port]=='input' for bit in bits}
                        for port,bits in cell['connections'].items():
                            if cell['port_directions'][port]=='output':
                                for bit in bits:drivers[bit]=inputs
                    forbidden={bit for name in FORBIDDEN for bit in module['ports'][name]['bits']}
                    for name in FIELDS:
                        visited=set();pending=list(module['ports'][name]['bits'])
                        while pending:
                            bit=pending.pop()
                            if bit in visited:continue
                            visited.add(bit);pending.extend(drivers.get(bit,()))
                        self.assertFalse(visited & forbidden,(name,visited & forbidden))
