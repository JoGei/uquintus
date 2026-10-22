"""Abstract independent target/direction tables, using arithmetic PC indexing."""


class BpuModel:
    def __init__(self, params):
        self.enabled = params['MUA_BRANCH_PREDICTOR'] != 0 and params['MUA_BTB'] == 1
        self.bimodal = params['MUA_BRANCH_PREDICTOR'] == 2
        self.alignment = 2 if params['ISA_C'] else 4
        self.capacity = params['MUA_BTB_ENTRIES']
        self.direction_capacity = params['MUA_BP_ENTRIES']
        self.entries = {}
        self.directions = {}

    def lookup(self, pc, valid=True, invalidate=False):
        entry = self.entries.get((pc // self.alignment) % self.capacity)
        direction = self.directions.get((pc // self.alignment) % self.direction_capacity)
        hit = bool(self.enabled and valid and not invalidate and pc % self.alignment == 0
                   and entry is not None and entry['pc'] == pc)
        direction_taken = bool(self.bimodal and direction is not None and direction['pc'] == pc
                               and direction['confidence'] >= 0)
        taken = hit and (not entry['conditional'] or direction_taken)
        return dict(hit=int(hit), taken=int(taken), target=entry['target'] if taken else 0)

    def step(self, *, reset=False, invalidate=False, valid=False, pc=0,
             control_flow=False, conditional=False, taken=False, target=0):
        if reset or invalidate:
            self.entries.clear()
            self.directions.clear()
            return
        if not valid or pc % self.alignment:
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
