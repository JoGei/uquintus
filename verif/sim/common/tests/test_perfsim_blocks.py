"""Block algebra, profile guards and state-dependent component sharing."""
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'verif/perfsim'))
from block_schedule import Compiler, STAGES, delay, load_profile, maximum


class BlockTests(unittest.TestCase):
    def test_max_plus_composition_matches_numeric_schedule(self):
        rng=random.Random(42)
        for _ in range(500):
            a={s:rng.randrange(30) for s in rng.sample(list('abcd'),rng.randrange(1,5))}
            b={s:rng.randrange(30) for s in rng.sample(list('abcd'),rng.randrange(1,5))}
            values={s:rng.randrange(1000) for s in 'abcd'}
            n=rng.randrange(30)
            evaluate=lambda e:max(values[s]+d for s,d in e.items())
            self.assertEqual(evaluate(delay(maximum(a,b),n)),max(evaluate(a),evaluate(b))+n)

    def test_unknown_connector_and_layout_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'layout'):
            Compiler(dict(states=['other']),True)
        compiler=Compiler(dict(states=STAGES),True)
        with self.assertRaisesRegex(ValueError,'contract'):
            compiler.read(['connector','unknown','Pc'],{},dict(rs1=1))
        with self.assertRaises(ValueError):delay({'s':0},-1)

    def test_emitted_factoring_matches_unoptimized_expressions(self):
        cxx=shutil.which('c++')
        if not cxx:self.skipTest('requires a C++ compiler')
        compiler=Compiler(dict(states=STAGES),True)
        rng=random.Random(713)
        for index in range(200):
            expression={f'x{s}':rng.randrange(30) for s in rng.sample(range(6),rng.randrange(1,7))}
            if index%3 and compiler.locals:
                prior=dict(rng.choice(list(compiler.locals)))
                expression=maximum(expression,delay(prior,rng.randrange(4)))
            result=compiler.emit(expression)
            literal='std::max<uint64_t>({'+','.join(f'{s}+{d}ULL' for s,d in expression.items())+'})'
            compiler.lines.append(f'if({result}!={literal})return {index+1};')
        text=('#include <algorithm>\n#include <cstdint>\nint main(){ uint32_t seed=17; '
              'for(unsigned trial=0;trial<300;++trial){\n'+
              '\n'.join(f'const uint64_t x{s}=(seed=seed*1664525+1013904223)%100000;' for s in range(6))+
              '\n'+'\n'.join(compiler.lines)+'\n}return 0;}\n')
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'expressions.cpp';source.write_text(text);exe=Path(tmp)/'expressions'
            built=subprocess.run([cxx,'-std=c++17',str(source),'-o',str(exe)],text=True,
                                 stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            self.assertEqual(built.returncode,0,built.stdout)
            self.assertEqual(subprocess.run([str(exe)]).returncode,0)

    def test_x0_and_load_admission_contract(self):
        compiler=Compiler(dict(states=STAGES),True)
        compiler.write(['connector','regModel','Xd'],{'time':0},dict(rd=0))
        self.assertFalse(compiler.registers)
        compiler.write(['connector','regModel','Ld'],{'time':0},dict(rd=3))
        self.assertEqual(compiler.registers['available',3],{'time':0})
        self.assertEqual(compiler.registers['admission',3],{'time':1})
        self.assertEqual(compiler.read(['connector','regModel','Da'],{},dict(rs1=3)),{'time':1})
        compiler.write(['connector','regModel','Xd'],{'new':0},dict(rd=3))
        self.assertEqual(compiler.registers['admission',3],{'new':0})
        compiler.forwarding=False
        compiler.write(['connector','regModel','Xd'],{'new':0},dict(rd=3))
        self.assertEqual(compiler.registers['admission',3],{'new':1})

    def test_profile_rejects_invalid_registers_and_unbounded_blocks(self):
        insn=dict(pc=0x80000000,code=0x13,type=1,rs1=0,rs2=0,rd=1)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'profile.json'
            for blocks in ([],[[dict(insn,rd=32)]],[[insn]*17],[[dict(insn,code=-1)]]):
                path.write_text(json.dumps(dict(schema_version=1,blocks=blocks)))
                with self.assertRaises(ValueError):load_profile(path)
            path.write_text(json.dumps(dict(schema_version=1,blocks=[[insn]])))
            self.assertEqual(load_profile(path)['blocks'],[[insn]])

    def test_native_state_sharing_handles_timestamp_divergence(self):
        backend=ROOT/'build/deps/perfsim-upstream/etiss-perf-sim/etiss_plugins/SoftwareEvalLib/libs/backends'
        source=backend/'src/internal/PerformanceModel.cpp'
        compiler=shutil.which('c++')
        if not compiler or not source.is_file():self.skipTest('requires pinned upstream API and C++')
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'sharing'
            args=[compiler,'-std=c++17','-include','cstdint','-I'+str(ROOT/'verif/perfsim/models'),
                  '-I'+str(backend/'include/internal'),'-I'+str(backend/'include/api/softwareEval-backends'),
                  str(ROOT/'verif/perfsim/tests/shared_models.cpp'),str(source),'-o',str(exe)]
            built=subprocess.run(args,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            self.assertEqual(built.returncode,0,built.stdout)
            run=subprocess.run([str(exe)],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            self.assertEqual(run.returncode,0,run.stdout)


if __name__=='__main__':unittest.main()
