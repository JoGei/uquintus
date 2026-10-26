#!/usr/bin/env python3
"""Generate uqu bindings for MAP-DSE's trace-driven, composed-block backend."""
import argparse
import json
from pathlib import Path
import sys

STAGES = ('IF_stage', 'DE_stage', 'EX_stage', 'MEM_stage', 'WB_stage')


class UquMapping:
    def __init__(self, forwarding):
        self.forwarding = forwarding

    def configure(self, matrix, schedule):
        if tuple(v.name for v in schedule.getAllTimingVariables()) != STAGES:
            raise ValueError('unsupported MAPExplorer stage layout')
        if {m.name for m in schedule.getAllResourceModels()} != {'fetchModel','hazardModel','requestModel','responseModel'}:
            raise ValueError('MAP-DSE requires the trace-driven fetch/hazard resource contract')
        group = matrix.createResourceGroup('FETCHMODEL')
        group.createResourceModel('fetch', 'uqu_map/FetchModel.h', ['pc', 'code', 'rs1', 'rs2', 'rd', 'brTarget','memAddr','event'])
        hazard = matrix.createResourceGroup('HAZARDMODEL')
        hazard.createResourceModel('hazard', 'uqu_map/HazardModel.h', [])
        matrix.createResourceGroup('REQUESTMODEL').createResourceModel('request','uqu_map/RequestModel.h',[])
        matrix.createResourceGroup('RESPONSEMODEL').createResourceModel('response','uqu_map/ResponseModel.h',[])
        matrix.createBranchGroup().createBranchModel('branch', 'uqu_map/BranchModel.h', ['pc', 'code'])
        matrix.createAllResourceCombinations();matrix.createAllCombinations()
        matrix.createTimingVariableSet([(s, 1) for s in (*STAGES, 'Serial', 'Committed', 'Entrance')])
        matrix.addStaticConnectorSet('Available', [('Xa', 'rs1'), ('Xb', 'rs2')], [('Xd', 'rd')], 32, [0])
        matrix.addStaticConnectorSet('Admission', [('Da', 'rs1'), ('Db', 'rs2')], [('Admit', 'rd')], 32, [0])
        matrix.createBranchSet(['Pc'], ['Pc_p', 'Pc_np'])

    def edge_name(self, edge):
        name = edge.name if edge.isDynamic() else edge.getTimingVariable().name
        allowed = set(STAGES) | {'Serial', 'Committed', 'AdmissionBase','RequestBase', 'Xa', 'Xb', 'Xd', 'Ld', 'Da', 'Db', 'Pc', 'Pc_p', 'Pc_np'}
        if name not in allowed:
            raise ValueError('unsupported MAPExplorer connector: '+name)
        return {'Ld':'Xd','AdmissionBase':'EX_stage','RequestBase':'WB_stage'}.get(name,name)

    def graph(self, graph, function):
        graph.add_edge('Enter', 'Entrance_o', weight=0)
        graph.add_edge('Committed_i', 'Committed_o', weight=0)
        if 'Admission' in graph:
            # Biased base = max(IF, previous EX-1, Serial). The positive
            # resource delay is hazard_wait+1, preserving zero-wait admission.
            graph.add_edge('EX_stage_i', 'Admission', weight=-1)
            graph.add_edge('IF_stage', 'Admission', weight=0)
            graph.add_edge('Serial_i', 'Admission', weight=0)
        if 'Request' in graph:
            graph.add_edge('WB_stage_i','Request',weight=-1)
            graph.add_edge('EX_stage','Request',weight=0)
        if 'Pc_p_o' in graph:
            graph.remove_edges_from(list(graph.in_edges('Pc_p_o')))
            graph.add_edge('IF_stage', 'Pc_p_o', weight=0)
        if 'Pc_np_o' in graph:
            # Publish branch resolution on DE advance, not one extra cycle
            # after operand readiness. This is a linear scheduling-state edge.
            graph.remove_edges_from(list(graph.in_edges('Pc_np_o')))
            graph.add_edge('WB_stage_o' if function.name in ('ecall','ebreak','wfi','mret') else 'DE_stage', 'Pc_np_o', weight=0)
        pending, visited, load_write = [function.getRootNode()], set(), False
        while pending:
            node = pending.pop()
            if node in visited: continue
            visited.add(node)
            load_write |= any(e.isDynamic() and e.name == 'Ld' for e in node.getAllOutEdges())
            pending.extend(node.getAllOutNodes())
        if 'Xd_o' in graph:
            for source, _, edge in list(graph.in_edges('Xd_o', data=True)):
                graph.add_edge(source, 'UquAdmissionResult', weight=edge['weight'])
            graph.add_edge('UquAdmissionResult','Admit_o',weight=int(load_write or not self.forwarding))


def load_profile(path):
    profile = json.loads(Path(path).read_text())
    if profile.get('schema_version') != 2 or not profile.get('blocks'):
        raise ValueError('MAP-DSE requires a nonempty upstream-format block profile')
    identities, starts = {}, set()
    for block in profile['blocks']:
        if not block.get('instrs') or block['startPc'] != block['instrs'][0]['pc'] or block['endPc'] != block['instrs'][-1]['pc']:
            raise ValueError('invalid/unfinished MAP-DSE block')
        if block['startPc'] in starts: raise ValueError('duplicate MAP-DSE block start')
        starts.add(block['startPc'])
        for i in block['instrs']:
            if set(i) != {'pc','code','typeId','rs1','rs2','rd'}:
                raise ValueError('invalid MAP-DSE instruction fields')
            for k,v in i.items():
                limit = 32 if k in ('rs1','rs2','rd') else 2**32
                if type(v) is not int or not 0 <= v < limit: raise ValueError('invalid MAP-DSE instruction value')
            key = tuple(i[k] for k in ('pc','code','typeId','rs1','rs2','rd'))
            if i['pc'] in identities and identities[i['pc']] != key:
                raise ValueError('MAP-DSE requires immutable instruction/operand identity per PC')
            identities[i['pc']] = key
    return profile


def extractor(target):
    out = target/'map';out.mkdir(exist_ok=True)
    ids=[i['id'] for i in json.loads((target/'trace.json').read_text())['trace']['instructions']]
    text=(Path(__file__).parent/'native/uqu_map_extract.cpp.in').read_text()
    (out/'extractor.cpp').write_text(text.replace('@TYPE_IDS@','{'+','.join(map(str,ids))+'}'))


def generate(target, generator, descriptions, profile):
    sys.path.insert(0, str(generator/'m2isar_perf'))
    from frontends.corePerfDsl import api
    from meta_models.scheduling_model.SchedulingTransformer import SchedulingTransformer
    from meta_models.matrix_model.MatrixTransformer import MatrixTransformer
    from backends.block_schedule_generator.BlockScheduleGenerator import BlockScheduleGenerator

    data = load_profile(profile)
    out = target/'map';out.mkdir(exist_ok=True)
    (out/'profile.json').write_text(Path(profile).read_text())
    rows, sources, tables, canonical, metadata = [], [], [], {}, None
    pending = []

    def flush():
        if not pending: return
        source = out/f'blocks-{len(sources)}.cpp'
        source.write_text('#include "BlockSchedulingFunctions.h"\n'+'\n'.join(pending)+'\n')
        sources.append(source);pending.clear()

    for d in descriptions:
        if d['schedule'].get('contract') != 'map_dse':
            raise ValueError('MAPExplorer needs the map_dse timing contract; queue feedback cannot be composed')
        schedule = SchedulingTransformer().transform(api.execute(str(target/d['id']/'uqu.corePerfDsl'), None))
        variant, = MatrixTransformer(mapping=UquMapping(d['schedule']['forwarding'])).transform(schedule).getAllVariants()
        if variant.getDimension()!=75: raise ValueError('unexpected MAP-DSE vector layout')
        emitter = BlockScheduleGenerator()
        # Use the stock 100-entry delay-vector bound for deterministic splits
        # across structural variants; do not split on model-dependent temp count.
        emitter.MAX_TEMP_COUNT_PER_BLOCK = 2**31
        sched_variant,=schedule.getAllVariants()
        branch_types={f.identifier for f in sched_variant.getAllSchedulingFunctions() if f.isBranch}
        bounded=dict(data,blocks=[dict(b,endOnBranch=b['instrs'][-1]['typeId'] in branch_types) for b in data['blocks']])
        blocks = sorted(emitter.compose_blocks(variant, bounded), key=lambda b:b.id)
        current = [(b.id,b.startPc,b.endPc,b.endsOnBranch) for b in blocks]
        if metadata is None: metadata=current
        elif current!=metadata: raise ValueError('MAP-DSE structural variants have different block boundaries')
        functions = []
        for block in blocks:
            if block.code not in canonical:
                name = f'uqu_map_block_{len(canonical)}'
                pending.append(f'void {name}(uint64_t* vec_,uint8_t* d_) {{\n{block.code}\n}}')
                rows.append(f'extern void {name}(uint64_t*,uint8_t*);')
                canonical[block.code] = name
                if len(pending)==24: flush()
            functions.append(canonical[block.code])
        tables.append(functions)
    flush()
    instruction_by_pc = {i['pc']:i for b in data['blocks'] for i in b['instrs']}
    # Preserve counts for split blocks without assuming a fixed instruction size.
    lengths=[]
    for _,start,end,_ in metadata:
        pc=start;length=0
        while True:
            insn=instruction_by_pc[pc];length+=1
            if pc==end: break
            pc+=(4 if insn['code']&3==3 else 2)
            if length>100: raise ValueError('upstream block exceeds delay-vector capacity')
        lengths.append(length)
    entries = ['{'+f'{i},{start}ULL,{end}ULL,{str(branch).lower()},{tables[0][i]}'+'}'
               for i,start,end,branch in metadata]
    rows += ['static MAP_Explorer::Block blocks[]={'+','.join(entries)+'};',
             'static const MAP_Explorer::Block* block_ptrs[]={'+','.join('&blocks['+str(i)+']' for i in range(len(metadata)))+'};',
             'static unsigned block_lengths[]={'+','.join(map(str,lengths))+'};']
    rows += [f'static MAP_Explorer::Block::SchedFuncPtr functions_{i}[]={{'+','.join(t)+'};' for i,t in enumerate(tables)]
    rows += ['static MAP_Explorer::Block::SchedFuncPtr* functions[]={'+','.join('functions_'+str(i) for i in range(len(tables)))+'};']
    ordered = sorted(instruction_by_pc.values(),key=lambda i:i['pc'])
    memory_names={'lb','lh','lw','lbu','lhu','sb','sh','sw','clw','clwsp','csw','cswsp'}
    memory_types={i['id'] for i in json.loads((target/'trace.json').read_text())['trace']['instructions'] if i['name'].lower() in memory_names}
    rows += ['static const ProfileInstruction expected[]={'+','.join('{'+','.join(str(i[k])+'ULL' for k in ('pc','code','typeId','rs1','rs2','rd'))+'}' for i in ordered)+'};']
    fetches,branches,fetch_ids,branch_ids,branch_fetch_ids,bpus,fetch_bpu_ids=[],[],[],[],[],[],[]
    for d in descriptions:
        f=d['external_models']['fetchModel']['parameters']
        b=dict(d['external_models']['frontendModel']['parameters'],
               envelope=f if f['btb'] and f['predictor'] else None)
        if f not in fetches:
            fetches.append(f)
            # Training/lookup order depends on the full envelope clock. Only
            # identical envelopes may share a BPU history.
            fetch_bpu_ids.append(len(bpus))
            bpus.append(f)
        if b not in branches: branches.append(b);branch_fetch_ids.append(fetches.index(f))
        fetch_ids.append(fetches.index(f));branch_ids.append(branches.index(b))
    rows += ['static unsigned fetch_ids[]={'+','.join(map(str,fetch_ids))+'};',
             'static unsigned branch_ids[]={'+','.join(map(str,branch_ids))+'};',
             'static unsigned branch_fetch_ids[]={'+','.join(map(str,branch_fetch_ids))+'};',
             'static unsigned fetch_bpu_ids[]={'+','.join(map(str,fetch_bpu_ids))+'};']
    replacements = dict(ACTIVE_BPUS=sum(b["btb"] and b["predictor"]!=0 for b in bpus),BPUS=len(bpus),CONFIGURE_BPU='\n'.join(
        f'bpus[{i}].enabled={str(b["btb"] and b["predictor"]!=0).lower()};bpus[{i}].bimodal={str(b["predictor"]==2).lower()};'
        f'bpus[{i}].compressed={str(b["compressed"]).lower()};bpus[{i}].entries={b["btb_entries"]};'
        f'bpus[{i}].direction_entries={b["bp_entries"]};bpus[{i}].hwords={b["idata_hwords"]};' for i,b in enumerate(bpus)),COUNT=len(descriptions), BLOCKS=len(metadata), FETCHES=len(fetches), BRANCHES=len(branches),
        TYPES=max(int(i['typeId']) for i in ordered)+1, TABLES='\n'.join(rows),
        MEMORY_TYPE_FLAGS=','.join('true' if i in memory_types else 'false' for i in range(max(int(i['typeId']) for i in ordered)+1)),
        FETCH_TYPES=','.join(['uqu_map::FetchModel']*len(fetches)),
        HAZARD_TYPES=','.join(['uqu_map::HazardModel']*len(fetches)),
        REQUEST_TYPES=','.join(['uqu_map::RequestModel']*len(fetches)),
        RESPONSE_TYPES=','.join(['uqu_map::ResponseModel']*len(fetches)),
        BRANCH_TYPES=','.join(['uqu_map::BranchModel']*len(branches)),
        FETCH_REFS=','.join(f'pool[{i}]' for i in range(len(fetches))),
        HAZARD_REFS=','.join(f'pool[{i}]' for i in range(len(fetches))),
        BRANCH_REFS=','.join(f'pool[{i}]' for i in range(len(branches))),
        CONFIGURE_FETCH='\n'.join(f'fetches[{i}].{k}={str(v).lower() if type(v) is bool else v};' for i,f in enumerate(fetches) for k,v in f.items()),
        CONFIGURE_BRANCH='\n'.join(f'branches[{i}].recovery_cycles={b["recovery_cycles"]};' for i,b in enumerate(branches)))
    template = (Path(__file__).parent/'native/uqu_map.cpp.in').read_text()
    for key,value in replacements.items(): template=template.replace('@'+key+'@',str(value))
    source=out/'explorer.cpp';source.write_text(template);sources.append(source)
    record=dict(backend='upstream MAPExplorer composed blocks', timing_contract='map_dse',
        matrix_generator='upstream MatrixTransformer / Instruction.mulMatrix',
        matrix_codegen='upstream BlockScheduleGenerator.compose_blocks', feedback_granularity='branch boundary PC mapping',
        blocks=len(metadata), multi_instruction_blocks=sum(n>1 for n in lengths), max_block_instructions=max(lengths),
        compiled_matrices=len(canonical), timing_models=len(descriptions), shared_fetch_models=len(fetches),
        shared_hazard_models=len(fetches),
        shared_branch_models=len(branches), shared_bpu_models=len(bpus), sources=list(map(str,sources)),
        approximations=descriptions[0]['approximations'])
    (out/'generation.json').write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target',type=Path);parser.add_argument('--generator',type=Path)
    parser.add_argument('--descriptions',type=Path);parser.add_argument('--profile',type=Path)
    args=parser.parse_args();extractor(args.target)
    if args.profile: generate(args.target,args.generator,json.loads(args.descriptions.read_text()),args.profile)
