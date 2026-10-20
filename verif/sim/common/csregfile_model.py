"""Architectural CSR words/events shared by CSR and WB component scoreboards."""

MASK = (1 << 32) - 1
MASK64 = (1 << 64) - 1
INPUTS = dict(rst_n=1, flush=0, csr_valid=0, csr_commit=0, csr_addr=0,
              csr_op=2, csr_src=0, csr_src_zero=1, csr_rd_zero=0,
              csr_instr=0xC0002573, priv_m=1, hart_id=0xCAFEBABE,
              irq_software=0, irq_timer=0, irq_external=0, retire=0,
              trap=0, trap_pc=0, trap_interrupt=0, trap_cause=0, trap_tval=0,
              mret=0, fp_flags_valid=0, fp_flags=0)


class CSRModel:
    def __init__(self, params):
        self.p = params
        self.addresses = [None] * 16
        self.reset()

    def reset(self):
        self.words = {0x300: 0x1800, 0x304: 0, 0x305: 0, 0x306: 0,
                      0x320: 0, 0x340: 0, 0x341: 0, 0x342: 0, 0x343: 0,
                      0x001: 0, 0x002: 0}
        self.cycle = self.instret = 0
        self.configs = [0] * 16

    def read(self, addr, i):
        if addr in (1, 2, 3):
            if not self.p['ISA_ZFINX']:
                raise KeyError(addr)
            return (self.words[1] | self.words[2] << 5) if addr == 3 else self.words[addr]
        if addr == 0x301:
            return 0x40000000 | (0x10 if self.p['ISA_E'] else 0x100) | (
                self.p['ISA_M'] << 12) | (self.p['ISA_C'] << 2) | (self.p['ISA_UMODE'] << 20)
        if addr in (0x306, 0x30A, 0x31A) and not self.p['ISA_UMODE']:
            raise KeyError(addr)
        if addr in (0x30A, 0x31A, 0x310, 0xF11, 0xF12, 0xF13, 0xF15):
            return 0
        if addr == 0xF14:
            return i['hart_id']
        if addr == 0x344:
            return (i['irq_software'] << 3) | (i['irq_timer'] << 7) | (i['irq_external'] << 11)
        if addr in (0xB00, 0xB80, 0xC00, 0xC80):
            return (self.cycle >> (32 if addr & 0x80 else 0)) & MASK
        if addr in (0xB02, 0xB82, 0xC02, 0xC82):
            return (self.instret >> (32 if addr & 0x80 else 0)) & MASK
        if any(lo <= addr <= hi for lo, hi in ((0xB03, 0xB1F), (0xB83, 0xB9F),
                (0x323, 0x33F), (0xC03, 0xC1F), (0xC83, 0xC9F))):
            return 0
        if 0x3A0 <= addr <= 0x3A3:
            return sum(c << (8 * j) for j, c in enumerate(self.configs[(addr-0x3A0)*4:(addr-0x3A0+1)*4]))
        if 0x3B0 <= addr <= 0x3BF:
            return self.addresses[addr-0x3B0] if self.p['ISA_PMP'] else 0
        return self.words[addr]

    def query(self, i):
        addr, op = i['csr_addr'], i['csr_op']
        read = op & 3 != 1 or not i['csr_rd_zero']
        source = i['csr_src'] & (31 if op & 4 else MASK)
        zero = source == 0 if op & 4 else bool(i['csr_src_zero'])
        write = op & 3 == 1 or not zero
        try:
            value = self.read(addr, i)
            mapped = True
        except KeyError:
            value, mapped = 0, False
        allowed = bool(i['priv_m']) or (self.p['ISA_UMODE'] and (addr >> 8) & 3 == 0)
        if not i['priv_m'] and (0xC00 <= addr <= 0xC1F or 0xC80 <= addr <= 0xC9F):
            bit = 0 if addr & 0x7F == 0 else 2 if addr & 0x7F == 2 else None
            allowed = allowed and bit is not None and bool(self.words[0x306] & (1 << bit))
        illegal = not mapped or not allowed or op & 3 == 0 or (write and addr >> 10 == 3)
        active = bool(i['rst_n'] and i['csr_valid'] and not i['flush'])
        error = active and illegal
        rdata = value if active and not illegal and read else 0
        if op & 3 == 1:
            updated = source
        elif value is None:
            updated = None
        elif op & 3 == 2:
            updated = value | source
        else:
            updated = value & ~source
        return dict(read=int(active and not illegal and read),
                    write=int(active and not illegal and write), rdata=rdata,
                    exception_valid=int(error), exception_cause=2 if error else 0,
                    exception_tval=i['csr_instr'] if error else 0), updated

    def step(self, i):
        if not i['rst_n']:
            self.reset()
            return
        response, updated = self.query(i)
        old_status = self.words[0x300]
        if not self.words[0x320] & 1:
            self.cycle = (self.cycle + 1) & MASK64
        if i['retire'] and not self.words[0x320] & 4:
            self.instret = (self.instret + 1) & MASK64
        write = response['write'] and i['csr_commit'] and not i['trap'] and not i['mret']
        # An explicit counter write suppresses that cycle's entire increment.
        if write and i['csr_addr'] in (0xB00, 0xB80, 0xB02, 0xB82):
            is_cycle = i['csr_addr'] in (0xB00, 0xB80)
            value = self.cycle if is_cycle else self.instret
            incremented = not self.words[0x320] & (1 if is_cycle else 4) and (is_cycle or i['retire'])
            if incremented:
                value = (value - 1) & MASK64
            high = bool(i['csr_addr'] & 0x80)
            value = ((updated << 32) | (value & MASK)) if high else ((value & (MASK << 32)) | updated)
            if is_cycle:
                self.cycle = value
            else:
                self.instret = value
        if self.p['ISA_ZFINX'] and i['fp_flags_valid']:
            self.words[1] |= i['fp_flags']
        if i['trap']:
            status = old_status & ~((3 << 11) | (1 << 7) | (1 << 3))
            status |= ((3 if i['priv_m'] or not self.p['ISA_UMODE'] else 0) << 11)
            status |= ((old_status >> 3) & 1) << 7
            self.words[0x300] = status
            self.words[0x341] = i['trap_pc'] & (~1 if self.p['ISA_C'] else ~3)
            self.words[0x342] = (i['trap_interrupt'] << 31) | (i['trap_cause'] & 15)
            self.words[0x343] = i['trap_tval']
        elif i['mret'] and i['priv_m']:
            status = old_status & ~((3 << 11) | (1 << 7) | (1 << 3))
            status |= ((old_status >> 7) & 1) << 3 | (1 << 7)
            if self.p['ISA_UMODE']:
                if not old_status & (3 << 11):
                    status &= ~(1 << 17)
            else:
                status |= 3 << 11
            self.words[0x300] = status
        if write:
            a = i['csr_addr']
            if a == 0x300:
                status = updated & ((1 << 3) | (1 << 7))
                if self.p['ISA_UMODE']:
                    status |= updated & ((1 << 17) | (1 << 21))
                    status |= (3 << 11) if updated & (3 << 11) else 0
                else:
                    status |= 3 << 11
                self.words[a] = status
            elif a == 0x304:
                self.words[a] = updated & 0x888
            elif a == 0x305:
                self.words[a] = (updated & ~3) | int(updated & 3 == 1)
            elif a in (0x306, 0x320):
                self.words[a] = updated & 5
            elif a in (0x340, 0x343):
                self.words[a] = updated
            elif a == 0x341:
                self.words[a] = updated & (~1 if self.p['ISA_C'] else ~3)
            elif a == 0x342:
                self.words[a] = updated & 0x8000000F
            elif a == 1:
                self.words[1] = updated & 31
            elif a == 2:
                self.words[2] = updated & 7
            elif a == 3:
                self.words[1], self.words[2] = updated & 31, (updated >> 5) & 7
            elif 0x3A0 <= a <= 0x3A3 and self.p['ISA_PMP']:
                for j in range(4):
                    entry = (a-0x3A0)*4+j
                    if not self.configs[entry] & 0x80:
                        cfg = (updated >> (8*j)) & 0x9F
                        if cfg & 3 == 2:
                            cfg &= ~2
                        self.configs[entry] = cfg
            elif 0x3B0 <= a <= 0x3BF and self.p['ISA_PMP']:
                entry = a-0x3B0
                locked = self.configs[entry] & 0x80
                if entry < 15:
                    locked |= self.configs[entry+1] & 0x98 == 0x88
                if not locked:
                    self.addresses[entry] = updated
