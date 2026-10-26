"""Feedback-preserving max-plus block compiler for the upstream scheduling IR.

Pipeline/register/serialization equations compose across instructions. Frontend
callbacks are ordered barriers: they depend on computed IF/DE timestamps and
cannot be replaced by a configuration-only delay vector. No ISA is decoded here;
register addresses and instruction IDs come from the CoreDSL trace extractor.
"""
import json
from pathlib import Path

STAGES = ('IF_stage', 'DE_stage', 'EX_stage', 'MEM_stage', 'WB_stage')


def maximum(*expressions):
    result = {}
    for expression in expressions:
        for symbol, offset in expression.items():
            result[symbol] = max(result.get(symbol, -1), offset)
    if not result:
        raise ValueError('empty max-plus expression')
    return result


def delay(expression, cycles):
    if type(cycles) is not int or cycles < 0:
        raise ValueError('block scheduling requires nonnegative constant node delays')
    return {symbol: offset+cycles for symbol, offset in expression.items()}


class Compiler:
    def __init__(self, ir, forwarding):
        if tuple(ir['states']) != STAGES:
            raise ValueError('unsupported timing-state layout for block adapter')
        self.ir, self.forwarding = ir, forwarding
        self.state = {s: {f's{i}': 0} for i, s in enumerate(STAGES)}
        self.registers = {}
        self.serial = {'Serial': {'serial': 0}, 'Committed': {'committed': 0}}
        self.lines, self.locals, self.loads = [], {}, {}
        self.serial_inputs = set()
        self.max_terms, self.nodes, self.callbacks = 0, 0, 0

    def emit(self, expression):
        key = tuple(sorted(expression.items()))
        if len(key) == 1 and key[0][1] == 0:
            return key[0][0]
        if key not in self.locals:
            remaining = dict(key)
            factored = []
            # Reuse previously materialized max terms, including a common
            # positive offset. This avoids expanding every pipeline recurrence
            # into a long max over the entire block's original state vector.
            while len(remaining) > 1:
                best = None
                for previous, symbol in list(self.locals.items())[-48:]:
                    if len(previous) < 2 or any(s not in remaining for s, _ in previous):
                        continue
                    shift = min(remaining[s]-d for s, d in previous)
                    if shift < 0:
                        continue
                    covered = [s for s, d in previous if remaining[s] == d+shift]
                    if len(covered) > 1 and (best is None or len(covered) > len(best[2])):
                        best = symbol, shift, covered
                if best is None:
                    break
                symbol, shift, covered = best
                factored.append((symbol, shift))
                for symbol in covered:
                    del remaining[symbol]
            values = [s+(f'+{d}ULL' if d else '') for s, d in [*factored,*remaining.items()]]
            name = f'e{len(self.locals)}'
            rhs = values[0] if len(values) == 1 else 'std::max<uint64_t>({'+','.join(values)+'})'
            self.lines.append(f'const uint64_t {name}={rhs};')
            self.locals[key] = name
        self.max_terms = max(self.max_terms, len(key))
        return self.locals[key]

    def read_register(self, bank, address):
        if address == 0:
            return {'0ULL': 0}
        key = bank, address
        if key not in self.registers:
            symbol = f'r_{bank}_{address}'
            self.registers[key] = {symbol: 0}
            self.loads[symbol] = f'v.registers.{bank}[{address}]'
        return self.registers[key]

    def read(self, edge, nodes, instruction):
        kind, name, *port = edge
        if kind == 'node':
            return nodes[name]
        if kind == 'state':
            return self.state[name]
        if kind != 'connector':
            raise ValueError('unknown schedule input')
        port, = port
        if name == 'regModel' and port in ('Xa', 'Xb', 'Da', 'Db'):
            return self.read_register('admission' if port[0] == 'D' else 'available',
                                      instruction['rs1' if port[-1] == 'a' else 'rs2'])
        if name == 'serialModel' and port in self.serial:
            self.serial_inputs.add(port)
            return self.serial[port]
        if (name, port) == ('frontendModel', 'Pc'):
            symbol = f'f{self.callbacks}'
            self.callbacks += 1
            self.lines.append(f'const uint64_t {symbol}=uqu_block_get_pc(v.frontend);')
            return {symbol: 0}
        raise ValueError(f'no block input contract for {name}.{port}')

    def write(self, edge, value, instruction):
        kind, name, *port = edge
        if kind == 'state':
            self.state[name] = value
            return
        if kind != 'connector':
            raise ValueError('unknown schedule output')
        port, = port
        if name == 'regModel' and port in ('Xd', 'Ld'):
            address = instruction['rd']
            if address:
                self.registers['available', address] = value
                self.registers['admission', address] = delay(value, int(port == 'Ld' or not self.forwarding))
            return
        if name == 'serialModel' and port in self.serial:
            self.serial_inputs.add(port)
            self.serial[port] = maximum(self.serial[port], value) if port == 'Committed' else value
            return
        if name == 'frontendModel':
            if port in ('Pc_p', 'Pc_np'):
                return  # Explicitly empty methods in the uqu connector contract.
            if port in ('IfConsumed', 'DeAdvanced'):
                function = 'if_consumed' if port == 'IfConsumed' else 'de_advanced'
                self.lines.append(f'uqu_block_{function}(v.frontend,{self.emit(value)});')
                self.callbacks += 1
                return
        raise ValueError(f'no block output contract for {name}.{port}')

    def flush(self, entrance):
        lines = [f'*v.stages[{i}]={self.emit(self.state[s])};' for i, s in enumerate(STAGES)]
        lines += [f'v.registers.{bank}[{address}]={self.emit(value)};'
                  for (bank, address), value in sorted(self.registers.items())]
        lines += [f'v.serial.{port.lower()}={self.emit(value)};' for port, value in self.serial.items()]
        lines += [f'v.entrance={self.emit(entrance)};']
        return lines

    def compile(self, instructions):
        for offset, instruction in enumerate(instructions):
            self.lines.append(f'v.model.instrIndex=start+{offset};')
            nodes = {}
            for node in self.ir['instructions'][str(instruction['type'])]['nodes']:
                nodes[node['name']] = delay(maximum(*(self.read(e, nodes, instruction) for e in node['inputs'])), node['delay'])
                for edge in node['outputs']:
                    self.write(edge, nodes[node['name']], instruction)
                self.nodes += 1
            entrance = nodes['Enter']
            # Materializations are outside the conditional; subsequent equations
            # may reuse them even when instruction observation is disabled.
            observe_flush = self.flush(entrance)
            self.lines += ['if(v.observe) {', *observe_flush,
                           f'v.observe(v.context,start+{offset},ordinal+{offset+1},{instruction["pc"]}U);', '}']
            # Bound expression growth without changing max-plus semantics.
            for mapping in (self.state, self.registers, self.serial):
                for key, expression in list(mapping.items()):
                    if len(expression) > 6:
                        mapping[key] = {self.emit(expression): 0}
        self.lines.extend(self.flush(entrance))
        self.lines.append(f'v.model.instrIndex=start+{len(instructions)};')
        header = [f'const uint64_t s{i}=*v.stages[{i}];' for i in range(5)]
        # Always load serial roots: flush writes both, including unused identity.
        header += ['const uint64_t serial=v.serial.serial,committed=v.serial.committed;']
        header += [f'const uint64_t {name}={source};' for name, source in self.loads.items()]
        return '\n'.join(header+self.lines)


def load_profile(path):
    profile = json.loads(Path(path).read_text())
    if profile.get('schema_version') != 1 or not profile.get('blocks'):
        raise ValueError('invalid/empty block profile')
    if len(profile['blocks']) > 20000:
        raise ValueError('block profile exceeds 20000 generated blocks')
    for block in profile['blocks']:
        if not 1 <= len(block) <= 16:
            raise ValueError('block length must be 1..16')
        for insn in block:
            if set(insn) != {'pc', 'code', 'type', 'rs1', 'rs2', 'rd'}:
                raise ValueError('invalid instruction profile fields')
            for key, value in insn.items():
                limit = 32 if key in ('rs1', 'rs2', 'rd') else 2**32
                if type(value) is not int or not 0 <= value < limit:
                    raise ValueError('invalid instruction profile value')
    return profile


def generate_blocks(target, descriptions, model_dirs, profile_path):
    profile = load_profile(profile_path)
    blocks = profile['blocks']
    destination = target/'blocks'
    destination.mkdir(exist_ok=True)
    (destination/'profile.json').write_text(json.dumps(profile, indent=2)+'\n')
    groups, model_groups = {}, {}
    # External frontend settings do not change the generated kernel: they live
    # in independent/shared connector instances, including their callback state.
    for d, folder in zip(descriptions, model_dirs):
        ir = json.loads((folder.parents[4]/'schedule-ir.json').read_text())
        key = json.dumps(dict(ir=dict(ir, name='UQU'), forwarding=d['schedule']['forwarding']), sort_keys=True)
        if key not in groups:
            groups[key] = (len(groups), ir, d['schedule']['forwarding'])
        model_groups[d['id']] = groups[key][0]
    sources, rows, kernels, stats = [], [], [], []
    for index, block in enumerate(blocks):
        entries = ','.join('{'+','.join(str(insn[k])+'ULL' for k in ('pc','code','type','rs1','rs2','rd'))+'}' for insn in block)
        rows.append(f'static const ProfileInstruction code_{index}[]={{{entries}}};')
    canonical = {}
    for group, ir, forwarding in groups.values():
        group_functions, pending = [], []
        chunk = 0
        def write_chunk():
            nonlocal chunk
            if not pending:
                return
            source = destination/f'group-{group}-{chunk}.cpp'
            source.write_text('// Generated from CorePerfDSL scheduling IR; see generation.json.\n'
                              '#include "uqu_blocks.h"\n'+'\n'.join(pending)+'\n')
            sources.append(source)
            pending.clear()
            chunk += 1
        for index, block in enumerate(blocks):
            # Latency choices for instruction kinds absent from a block must
            # not duplicate that block's machine code across the design space.
            signature = (index, forwarding, json.dumps(
                [ir['instructions'][str(i['type'])] for i in block], sort_keys=True))
            if signature not in canonical:
                compiler = Compiler(ir, forwarding)
                body = compiler.compile(block)
                name = f'uqu_block_{group}_{index}'
                canonical[signature] = name
                pending.append(f'void {name}(TimingView& v,unsigned start,uint64_t ordinal) {{\n{body}\n}}')
                rows.append(f'extern void {name}(TimingView&,unsigned,uint64_t);')
                stats.append(dict(group=group, block=index, nodes=compiler.nodes,
                                  callbacks=compiler.callbacks, max_terms=compiler.max_terms))
                if len(pending) == 24:
                    write_chunk()
            group_functions.append(canonical[signature])
        write_chunk()
        rows.append(f'static BlockFunction group_{group}[]={{'+','.join(group_functions)+'};')
        kernels.append(f'group_{group}')
    rows.append('static BlockFunction* groups[]={'+','.join(kernels)+'};')
    rows.append('const std::vector<BlockDefinition>& block_definitions() { static const std::vector<BlockDefinition> blocks={')
    rows += [f'{{{i},{len(b)},code_{i}}},' for i, b in enumerate(blocks)]
    rows += ['}; return blocks; }',
             'BlockFunction block_function(unsigned group,unsigned block) {return groups[group][block];}']
    source = destination/'dictionary.cpp'
    source.write_text('#include "uqu_blocks.h"\n'+'\n'.join(rows)+'\n')
    sources.append(source)
    (destination/'generation.json').write_text(json.dumps(dict(
        backend='uqu feedback-barrier max-plus block adapter', block_count=len(blocks),
        kernel_groups=len(groups), compiled_block_functions=len(canonical),
        unshared_block_functions=len(groups)*len(blocks), model_groups=model_groups, kernels=stats,
        upstream_input='M2-ISA-R-Perf SchedulingTransformer graph',
        limitation='frontend callbacks remain per instruction; not the unmodified upstream MAPExplorer'), indent=2)+'\n')
    return sources, model_groups
