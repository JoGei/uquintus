"""Known IEEE/RISC-V edges and optional independent Berkeley SoftFloat checks."""
import ctypes as C
import os
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fpu_model import (DZ, NV, NX, OF, UF, QNAN, SIGN, NAMES, result,
                       decode_instruction, encode_instruction, is_nan)


class FpuModelTests(unittest.TestCase):
    def test_rounding_boundaries_and_flags(self):
        for rm in range(5):
            self.assertEqual(result(0,0x3f800000,0x33800000,rm=rm),
                             (0x3f800001 if rm in (3,4) else 0x3f800000,NX))
        self.assertEqual(result(2,0x00800000,0x3f7fffff),(0x00800000,NX))
        self.assertEqual(result(2,0x00800000,0x3f7fffff,rm=1),(0x007fffff,UF|NX))
        self.assertEqual(result(2,0x7f7fffff,0x40000000),(0x7f800000,OF|NX))
        self.assertEqual(result(3,0x3f800000,0),(0x7f800000,DZ))
        self.assertEqual(result(3,0,0),(QNAN,NV))
        self.assertEqual(result(4,0x80000000),(0x80000000,0))
        # A fused product retains low bits lost by a separate multiply.
        self.assertEqual(result(5,0x3f800001,0x3f7ffffe,0xbf800000),(0xa8800000,0))
        self.assertEqual(result(5,0x7f800000,0,0x7fc00000),(QNAN,NV))

    def test_non_arithmetic_special_values(self):
        self.assertEqual(result(12,0,0x80000000),(0x80000000,0))
        self.assertEqual(result(13,0,0x80000000),(0,0))
        self.assertEqual(result(12,0x7f800001,0x3f800000),(0x3f800000,NV))
        self.assertEqual(result(14,QNAN,0),(0,0))
        self.assertEqual(result(15,QNAN,0),(0,NV))
        self.assertEqual(result(10,0x7f812345,0),(0xff812345,0))
        self.assertEqual(result(18,0xcf000001),(0x80000000,NV))
        self.assertEqual(result(19,0xbe800000),(0,NX))
        classes=(0xff800000,0xbf800000,0x80000001,0x80000000,0,1,0x3f800000,
                 0x7f800000,0x7f800001,0x7fc00000)
        for index,bits in enumerate(classes):
            self.assertEqual(result(17,bits),(1 << index,0))

    def test_opcode_round_trips(self):
        for op in range(len(NAMES)):
            for rm in range(5):
                decoded,used,rounding=decode_instruction(encode_instruction(op,4,1,2,3,rm))
                self.assertEqual(decoded,op)
                self.assertEqual(used,7 if 5<=op<=8 else 1 if op in (4,17,18,19,20,21) else 3)
                self.assertEqual(rounding,rm if op<9 or op>=18 else 0)

    @unittest.skipUnless(os.environ.get('SOFTFLOAT_LIB'), 'optional external SOFTFLOAT_LIB not supplied')
    def test_external_softfloat_arithmetic_and_conversion(self):
        class Float32(C.Structure):
            _fields_=[('v',C.c_uint32)]
        library=C.CDLL(os.environ['SOFTFLOAT_LIB'])
        rounding=C.c_ubyte.in_dll(library,'softfloat_roundingMode')
        flags=C.c_ubyte.in_dll(library,'softfloat_exceptionFlags')
        tininess=C.c_ubyte.in_dll(library,'softfloat_detectTininess')
        tininess.value=1  # Detect after rounding.
        functions=[]
        for name,arity in (('add',2),('sub',2),('mul',2),('div',2),('sqrt',1),('mulAdd',3)):
            fn=getattr(library,'f32_'+name)
            fn.argtypes=[Float32]*arity
            fn.restype=Float32
            functions.append(fn)
        for name,unsigned in (('i32',False),('ui32',True)):
            fn=getattr(library,'f32_to_'+name)
            fn.argtypes=[Float32,C.c_ubyte,C.c_bool]
            fn.restype=C.c_ulong if unsigned else C.c_long  # uint/int_fast32_t on the host.
            fn=getattr(library,name+'_to_f32')
            fn.argtypes=[C.c_uint32 if unsigned else C.c_int32]
            fn.restype=Float32
        rng=random.Random(120)
        for op in list(range(9))+list(range(18,22)):
            for _ in range(2000):
                a,b,c=(rng.getrandbits(32) for _ in range(3))
                rm=rng.randrange(5)
                rounding.value,flags.value=rm,0
                if op<5:
                    args=[Float32(a)] if op==4 else [Float32(a),Float32(b)]
                    answer=functions[op](*args)
                elif op<9:
                    answer=functions[5](Float32(a^(SIGN if op in (7,8) else 0)),Float32(b),
                                        Float32(c^(SIGN if op in (6,8) else 0)))
                elif op<20:
                    answer=getattr(library,'f32_to_'+('ui32' if op==19 else 'i32'))(Float32(a),rm,True)
                else:
                    answer=getattr(library,('ui32' if op==21 else 'i32')+'_to_f32')(a)
                bits=answer.v if isinstance(answer,Float32) else answer & 0xffffffff
                if op<9 and is_nan(bits): bits=QNAN  # RISC-V's canonical NaN policy.
                self.assertEqual(result(op,a,b,c,rm),(bits,flags.value),(NAMES[op],hex(a),hex(b),hex(c),rm))
