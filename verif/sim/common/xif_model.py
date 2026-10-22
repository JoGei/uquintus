"""Small custom ISA oracle and a standard-channel coprocessor test agent.

Opcodes are verification fixtures, not an architectural uquintus extension.
The retirement oracle evaluates these operations from its own GPR state; this
agent computes responses from the actual delivered register packets instead.
"""
import json
from pathlib import Path

MASK=0xffffffff


def custom(insn, params):
    if insn & 127 != 0x0b: return None
    op=insn >> 12 & 7
    if op>5 or (op in (1,5) and params['XIF_NUM_RS']<3): return None
    pair=op==3
    if pair and not params['XIF_DUALWRITE']: return None
    used={0:3,1:7,2:0,3:3,4:1,5:4}[op]
    rd=insn >> 7 & 31
    addresses=(insn >> 15 & 31,insn >> 20 & 31,rd)
    writes=0 if op==2 else 3 if pair else 1
    if pair and rd & 1: return None
    if params['ISA_E'] and (any(used >> i & 1 and a>=16 for i,a in enumerate(addresses)) or
                           writes and rd>=16): return None
    return dict(op=op,used=used,writes=writes,rd=rd,addresses=addresses)


def result(desc, operands):
    a,b,c=operands
    value={0:a+b,1:a+b+c,2:0,3:a+b,4:a,5:c}[desc['op']] & MASK
    return value, (a ^ b) & MASK if desc['writes']==3 else 0


class Coprocessor:
    def __init__(self, env):
        self.env=env
        self.live=[]
        self.presented=None
        self.last_id=None
        self.generation=0
        self.hold_issue=False
        self.hold_result=False
        self.delay=3
        self.same_cycle=False
        self.force_bad_accept=False
        self.bad_packets=0
        self.history=[]
        self.max_live=0
        self.pre_busy=False
        self.retiring=None
        self.trace=[]
        self.epoch=-1
        self.reset_seen=False
        path=Path('xif-agent.json')
        self.previous=json.loads(path.read_text()) if path.is_file() else dict(max_live=0,events=[])

    def read(self,name): return self.env.signal('xif_'+name+'_o')
    def write(self,name,value): getattr(self.env.dut,'xif_'+name+'_i').value=value

    def drive(self,rst):
        self.pre_busy=bool(self.live or self.presented)
        self.retiring=None
        for name in ('issue_ready','issue_accept','issue_writeback','issue_register_read','register_ready',
                     'result_valid','result_hartid','result_id','result_data','result_rd','result_we'):
            self.write(name,0)
        if not rst:
            if not self.reset_seen:
                self.epoch+=1
                self.history.append(dict(type='reset',cycle=self.env.cycles,
                    canceled=[row['id'] for row in self.live]))
                self.save()
            self.reset_seen=True
            self.live=[]; self.presented=None; self.last_id=None; self.generation=0
            return
        self.reset_seen=False
        if self.read('issue_valid'):
            insn=self.read('issue_instr')
            desc=custom(insn,self.env.params)
            if self.force_bad_accept and desc is None and insn & 127==0x0b:
                desc=dict(op=0,used=1,writes=1,rd=insn >> 7 & 31,
                          addresses=(insn >> 15 & 31,insn >> 20 & 31,insn >> 7 & 31))
            used=desc['used'] if desc else 0
            ready=(not self.hold_issue and (self.read('register_rs_valid') & used)==used and
                   self.env.rng.randrange(4)!=0)
            self.write('issue_ready',int(ready)); self.write('register_ready',int(ready))
            self.write('issue_accept',int(desc is not None))
            self.write('issue_writeback',desc['writes'] if desc else 0)
            self.write('issue_register_read',used)
        oldest=next((row for row in self.live if row['accepted']),None)
        if oldest:
            allowed=oldest['committed'] or (self.same_cycle and self.read('commit_valid') and
                not self.read('commit_kill') and self.read('commit_id')==oldest['id'])
            if allowed and oldest['delay']==0 and not self.hold_result:
                self.write('result_valid',1)
                kind=self.bad_packets % 3 if self.bad_packets else None
                self.write('result_hartid',self.env.hart_id ^ (1 if kind==1 else 0))
                self.write('result_id',(oldest['id']+1)&7 if kind==0 else oldest['id'])
                self.write('result_data',oldest['data'][0] | oldest['data'][1] << 32)
                self.write('result_rd',(oldest['desc']['rd']+2)&31 if kind==2 and not self.env.params['XIF_DUALWRITE'] else oldest['desc']['rd'])
                self.write('result_we',3 if kind==2 and self.env.params['XIF_DUALWRITE'] else oldest['desc']['writes'])

    def sample(self,rst):
        if not rst: return
        e=self.env
        previous_events=len(self.history)
        valid=self.read('issue_valid')
        assert self.read('register_valid')==valid
        if valid:
            ident,insn,hart=self.read('issue_id'),self.read('issue_instr'),self.read('issue_hartid')
            assert (self.read('register_id'),self.read('register_hartid'))==(ident,hart)
            assert hart==e.hart_id
            values=self.read('register_rs'); flags=self.read('register_rs_valid')
            operands=[values >> (32*i) & MASK for i in range(e.params['XIF_NUM_RS'])]
            operands += [0]*(3-len(operands))
            if self.presented:
                old=self.presented
                assert (ident,insn,hart)==(old['id'],old['instr'],old['hart'])
                assert flags & old['flags']==old['flags'], 'operand validity retracted'
                for i in range(3):
                    if old['flags'] >> i & 1: assert operands[i]==old['operands'][i], 'operand changed while valid'
            else:
                assert all(row['id']!=ident for row in self.live),'live ID reused'
                if self.last_id is not None: assert ident==(self.last_id+1)&7, 'non-sequential allocation'
                if self.live: assert self.generation-self.live[0]['generation']<8,'ID allocation lapped oldest transaction'
                self.last_id=ident
                self.generation+=1
            self.presented=dict(id=ident,instr=insn,hart=hart,flags=flags,operands=operands)
            if int(e.dut.xif_issue_ready_i.value):
                desc=custom(insn,e.params)
                accepted=bool(int(e.dut.xif_issue_accept_i.value))
                assert bool(int(e.dut.xif_register_ready_i.value))
                if accepted and desc is None:
                    assert self.force_bad_accept
                    desc=dict(op=0,used=1,writes=1,rd=insn >> 7 & 31,addresses=(insn >> 15 & 31,0,0))
                if accepted: assert flags & desc['used']==desc['used']
                row=dict(id=ident,instr=insn,pc=e.signal('de_pc_q'),accepted=accepted,
                    committed=False,desc=desc,operands=operands,data=result(desc,operands) if accepted else (0,0),
                    delay=self.delay,generation=self.generation-1)
                self.live.append(row)
                self.history.append(dict(type='issue',cycle=e.cycles,id=ident,pc=row['pc'],accepted=accepted))
                self.max_live=max(self.max_live,sum(row['accepted'] for row in self.live))
                self.presented=None
        elif self.presented:
            self.history.append(dict(type='retract',cycle=e.cycles,id=self.presented['id']))
            self.presented=None
        if self.read('commit_valid'):
            ident=self.read('commit_id')
            row=next((r for r in self.live if r['id']==ident),None)
            assert row is not None and not row['committed'],('duplicate/unknown commit',ident,self.live)
            kill=self.read('commit_kill')
            self.history.append(dict(type='kill' if kill else 'commit',cycle=e.cycles,id=ident,pc=row['pc']))
            if kill: self.live.remove(row)
            else:
                assert row['accepted']
                assert row==next(r for r in self.live if r['accepted']), 'out-of-order commit'
                row['committed']=True
        oldest=next((r for r in self.live if r['accepted']),None)
        if oldest and oldest['committed'] and e.signal('wb_valid_q') and e.signal('wb_xif_id_q')==oldest['id']:
            assert self.read('result_ready'), 'result ready depends on result availability'
        if int(e.dut.xif_result_valid_i.value) and self.read('result_ready'):
            if self.bad_packets:
                assert not e.signal('wb_retire') and not e.signal('wb_we0') and not e.signal('wb_we1')
                self.bad_packets-=1
                self.history.append(dict(type='invalid_result',cycle=e.cycles))
            else:
                row=next(r for r in self.live if r['accepted'])
                assert row['committed'] and e.signal('wb_retire')
                self.history.append(dict(type='result',cycle=e.cycles,id=row['id'],pc=row['pc']))
                self.retiring=row
                self.live.remove(row)
        for row in self.live: row['delay']=max(0,row['delay']-1)
        if len(self.history)!=previous_events: self.save()

    def save(self):
        events=self.previous['events']+[dict(row,test=type(self.env).__name__) for row in self.history]
        Path('xif-agent.json').write_text(json.dumps(dict(max_live=max(self.max_live,self.previous['max_live']),events=events),indent=2)+'\n')

    def finish(self, instructions):
        observed=[json.loads(line) for line in Path('xif.jsonl').read_text().splitlines()]
        custom_events=[r for r in instructions if r['rvfi_insn'] & 127==0x0b and not r['rvfi_trap']]
        assert len(custom_events)==len(self.trace)
        expected=[]
        for row,event in zip(self.trace,custom_events):
            assert (row['pc'],row['instr'],row['order'])==(event['rvfi_pc_rdata'],event['rvfi_insn'],event['rvfi_order'])
            expected.append(dict(row,epoch=event['epoch']))
        if expected:
            assert observed[-len(expected):]==expected,('custom retirement trace',observed,expected)
        self.save()
