#!/usr/bin/env python3
"""Check upstream emitted block code against numeric instruction-matrix products."""
import json
from pathlib import Path
import random
import subprocess
import sys

root=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root/'verif/perfsim'))
from map_explorer import UquMapping

def main():
    generator,description,output=map(Path,sys.argv[1:])
    sys.path.insert(0,str(generator/'m2isar_perf'))
    from frontends.corePerfDsl import api
    from meta_models.scheduling_model.SchedulingTransformer import SchedulingTransformer
    from meta_models.matrix_model.MatrixTransformer import MatrixTransformer
    from backends.block_schedule_generator.BlockScheduleGenerator import BlockScheduleGenerator
    scheduling=SchedulingTransformer().transform(api.execute(str(description),None))
    s,=scheduling.getAllVariants()
    v,=MatrixTransformer(mapping=UquMapping(True)).transform(scheduling).getAllVariants()
    rng=random.Random(4173)
    funcs=[f for f in s.getAllSchedulingFunctions() if not f.isBranch]
    branch=[f for f in s.getAllSchedulingFunctions() if f.isBranch]
    profiles=[]
    for n in range(30):
        insns=[]
        for j in range(rng.randrange(2,15)):
            f=rng.choice(branch if j==0 and n%4==0 else funcs)
            # Keep branches last, as required by MAP-DSE.
            if f.isBranch and insns:break
            used={e.name for node in f.nodes for e in node.getAllInEdges() if e.isDynamic()}
            writes=any(e.isDynamic() and e.getConnectorModel().name=='regModel' for node in f.nodes for e in node.getAllOutEdges())
            insns.append(dict(pc=0x80000000+n*128+j*4,code=0x13,typeId=f.identifier,
                rs1=rng.randrange(7) if used&{'Xa','Da'} else 0,
                rs2=rng.randrange(7) if used&{'Xb','Db'} else 0,rd=rng.randrange(7) if writes else 0))
            if f.isBranch:break
        profiles.append(dict(id=n,startPc=insns[0]['pc'],endPc=insns[-1]['pc'],callCnt=1,instrs=insns,endOnBranch=False))
    emitter=BlockScheduleGenerator()
    blocks=sorted(emitter.compose_blocks(v,dict(blocks=profiles)),key=lambda b:b.id)
    code=['#include "BlockSchedulingFunctions.h"','#include <array>','#include <algorithm>','#include <cstdio>']
    for block in blocks:code.append(f'void block_{block.id}(uint64_t* vec_,uint8_t* d_){{\n{block.code}\n}}')
    code+=['int main(){']
    for block,profile in zip(blocks,profiles):
        # No matrix multiplication, optimizer or generated code in this oracle.
        # Evaluate each original instruction matrix numerically, in trace order.
        matrices=[v.getInstruction(i['typeId']).getMatrix(i) for i in profile['instrs']]
        for sample in range(20):
            before=[rng.randrange(10000) for _ in range(75)];before[8]=before[40]=0
            delays=[tuple(rng.randrange(1,20) for _ in range(v.getInstruction(i['typeId']).getNumDynDelays()))
                    for i in profile['instrs']]
            expected=before[:]
            for m,d in zip(matrices,delays):
                previous=expected[:]
                for row in range(75):
                    if m.isZeroRow(row) or m.isUnitRow(row):continue
                    terms=[]
                    for col,e in enumerate(m.matrix[row]):
                        if e==-1:continue
                        if type(e) is tuple:
                            offset,mask,temp,_=e
                            assert temp==0 and 0<=mask<(1<<len(d))
                            e=offset+sum(value for bit,value in enumerate(d) if mask&(1<<bit))
                        terms.append(previous[col]+e)
                    if terms:expected[row]=max(terms)
            code += ['{', 'uint64_t vec_[]={'+','.join(map(str,before))+'};',
                     'uint8_t d_[]={'+','.join(str(value) for pair in delays for value in pair)+'};',f'block_{block.id}(vec_,d_);',
                     'const uint64_t expected[]={'+','.join(map(str,expected))+'};',
                     f'for(unsigned i=0;i<75;++i)if(vec_[i]!=expected[i]){{std::printf("block {block.id} sample {sample} slot %u: %llu vs %llu\\n",i,(unsigned long long)vec_[i],(unsigned long long)expected[i]);return 1;}}','}']
    code+=['}']
    source=output/'numeric.cpp';source.write_text('\n'.join(code)+'\n')
    backend=root/'build/deps/perfsim-upstream/etiss-perf-sim/etiss_plugins/SoftwareEvalLib/libs/backends'
    subprocess.run(['c++','-std=c++17','-O0','-I'+str(backend/'include/internal'),str(source),'-o',str(output/'numeric')],check=True)
    subprocess.run([str(output/'numeric')],check=True)
    print('30 composed blocks x 20 randomized state/delay assignments passed')

if __name__=='__main__':main()
