"""Abstract independent target/direction tables, using arithmetic PC indexing."""


class BpuModel:
    def __init__(self, params):
        self.enabled = params['MUA_BRANCH_PREDICTOR'] != 0 and params['MUA_BTB'] == 1
        self.bimodal = params['MUA_BRANCH_PREDICTOR'] == 2
        self.alignment = 2 if params['ISA_C'] else 4
        self.capacity = params['MUA_BTB_ENTRIES']
        self.direction_capacity = params['MUA_BP_ENTRIES']
        self.hwords = params.get('MUA_BTB_IDATA_HWORDS', 0) if self.enabled else 0
        self.payloads = {}
        self.fill = None
        self.entries = {}
        self.directions = {}
        self.pending = {}

    def lookup(self, pc, valid=True, invalidate=False):
        entry = self.entries.get((pc // self.alignment) % self.capacity)
        direction = self.directions.get((pc // self.alignment) % self.direction_capacity)
        hit = bool(self.enabled and valid and not invalidate and pc % self.alignment == 0
                   and entry is not None and entry['pc'] == pc)
        direction_taken = bool(self.bimodal and direction is not None and direction['pc'] == pc
                               and direction['confidence'] >= 0)
        taken = hit and (not entry['conditional'] or direction_taken)
        return dict(hit=int(hit), taken=int(taken), target=entry['target'] if taken else 0)

    def payload(self, pc):
        prediction = self.lookup(pc)
        if not prediction['hit']:
            return []
        return list(self.payloads.get(pc, []))

    def length(self, instr):
        return 2 if self.alignment == 2 and instr & 3 != 3 else 4

    def fit_prefix(self, instructions):
        prefix = []
        used = 0
        for instr in instructions:
            length = self.length(instr)
            if used + length > 2*self.hwords:
                break
            prefix.append(instr & ((1 << (8*length))-1))
            used += length
        return prefix

    def packed(self, instructions):
        bits, offset = 0, 0
        for instr in instructions:
            bits |= instr << offset
            offset += 8*self.length(instr)
        return bits

    def step(self, *, reset=False, invalidate=False, valid=False, pc=0,
             control_flow=False, conditional=False, taken=False, target=0,
             stream_flush=False, capture_valid=False, capture_pc=0, capture_instr=0):
        # One accepted bundle per edge. Invalidation discards both the pending
        # bundle and the current inputs; ordinary flush stays ordered in-band.
        if reset or invalidate:
            self.pending = {}
            self._apply(reset=True)
            return
        self._apply(**self.pending)
        self.pending = dict(valid=valid, pc=pc, control_flow=control_flow,
            conditional=conditional, taken=taken, target=target,
            stream_flush=stream_flush, capture_valid=capture_valid,
            capture_pc=capture_pc, capture_instr=capture_instr)

    def _apply(self, *, reset=False, invalidate=False, valid=False, pc=0,
               control_flow=False, conditional=False, taken=False, target=0,
               stream_flush=False, capture_valid=False, capture_pc=0, capture_instr=0):
        if reset or invalidate:
            self.payloads.clear()
            self.fill = None
            self.entries.clear()
            self.directions.clear()
            return
        update = valid and pc % self.alignment == 0
        start = update and control_flow and taken and target % self.alignment == 0
        if self.hwords:
            capture_instr &= (1 << (8*self.length(capture_instr)))-1
            if update:
                old = self.entries.get((pc // self.alignment) % self.capacity)
                if old and (old['pc'] != pc or old['target'] != target or not control_flow or target % self.alignment):
                    # A non-control tag miss leaves the aliased entry intact.
                    if control_flow and target % self.alignment == 0 or old['pc'] == pc:
                        self.payloads.pop(old['pc'], None)
                        if self.fill and self.fill[0] == old['pc']:
                            self.fill = None
            if stream_flush:
                self.fill = None
            if start:
                self.fill = (pc, target, 0)
            if self.fill and capture_valid and not (start and capture_pc != target):
                owner, expected, offset = self.fill
                prefix = self.payloads.setdefault(owner, [])
                if capture_pc != expected or (offset < len(prefix) and prefix[offset] != capture_instr):
                    self.fill = None
                elif offset < len(prefix) or sum(map(self.length,prefix))+self.length(capture_instr) <= 2*self.hwords:
                    if offset == len(prefix):
                        prefix.append(capture_instr)
                    self.fill = ((owner, (expected + self.length(capture_instr)) & 0xffffffff, offset+1)
                                 if sum(map(self.length,prefix)) < 2*self.hwords else None)
                else:
                    self.fill = None
        if not update:
            return
        admissible = control_flow and target % self.alignment == 0
        if self.enabled:
            index = (pc // self.alignment) % self.capacity
            previous = self.entries.get(index)
            match = previous is not None and previous['pc'] == pc
            if admissible:
                self.entries[index] = dict(pc=pc, conditional=conditional, target=target)
            elif match:
                del self.entries[index]
        if self.bimodal:
            index = (pc // self.alignment) % self.direction_capacity
            previous = self.directions.get(index)
            match = previous is not None and previous['pc'] == pc
            if admissible and conditional:
                confidence = 0 if taken else -1
                if match:
                    confidence = max(-2, min(1, previous['confidence'] + (1 if taken else -1)))
                self.directions[index] = dict(pc=pc, confidence=confidence)
            elif admissible or match:
                self.directions.pop(index, None)
