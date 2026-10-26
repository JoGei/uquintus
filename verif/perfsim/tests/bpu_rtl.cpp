#include "Vuqu_bpu.h"
#include "verilated.h"
#include "uqu_bpu_model.h"
#include <iostream>
#include <stdexcept>

static void check(bool b,const char* name,unsigned edge) {
    if(!b)throw std::runtime_error(std::string(name)+" at edge "+std::to_string(edge));
}
int main() {
    try {
        Vuqu_bpu d;uqu::BpuState m;
        m.enabled=true;m.bimodal=UQU_BPU_P==2;m.compressed=UQU_BPU_C;
        m.entries=UQU_BPU_E;m.direction_entries=4;m.hwords=UQU_BPU_H;m.initialize();
        d.clk_i=0;d.rst_ni=0;d.eval();d.clk_i=1;d.eval();d.rst_ni=1;
        uint32_t random=73,fill=0;
        for(unsigned edge=1;edge<=4000;++edge) {
            random=random*1664525+1013904223;
            const unsigned phase=edge%32;
            const uint32_t pc=0x80000000+((edge/32)%19)*(UQU_BPU_C?2:4);
            uqu::BpuState::Update u{phase==0 || phase>20,phase<24,phase%3!=0,
                (random&3)!=0,pc,0x80001000+4*(edge/32%23)};
            if(phase==0){u.taken=true;fill=u.target;}
            const uint32_t code=UQU_BPU_C && phase%3==1?0x0085:0x00108093;
            uqu::BpuState::Capture c{phase<12,fill,code};
            const bool flush=phase==14,invalidate=edge%197==0;
            const uint32_t lookup=phase<16?pc:pc+((random>>12&3)*m.entries*(UQU_BPU_C?2:4));
            d.clk_i=0;d.invalidate_i=invalidate;d.lookup_valid_i=1;d.lookup_pc_i=lookup;
            d.update_valid_i=u.valid;d.update_pc_i=u.pc;d.update_control_flow_i=u.control;
            d.update_conditional_i=u.conditional;d.update_taken_i=u.taken;d.update_target_i=u.target;
            d.capture_valid_i=c.valid;d.capture_pc_i=c.pc;d.capture_instr_i=c.code;d.stream_flush_i=flush;d.eval();
            const auto p=invalidate?uqu::BpuState::Prediction{}:m.lookup(lookup);
            check(bool(d.hit_o)==p.hit,"target hit",edge);
            check(bool(d.taken_o)==p.taken,"direction",edge);
            check(d.target_o==(p.taken?p.target:0),"target",edge);
            check(d.idata_hwords_o==p.hwords,"prefix length",edge);
            check(d.idata_next_pc_o==(UQU_BPU_H && p.hit?p.target+p.hwords*2:0),"prefix successor",edge);
            for(unsigned h=0;h<UQU_BPU_H;++h) {
#if UQU_BPU_H > 2
                const uint32_t data=d.idata_o[h/2];
#else
                const uint32_t data=d.idata_o;
#endif
                check(uint16_t(data>>((h&1)*16))==(invalidate?0:m.data(lookup,h)),"prefix payload",edge);
            }
            if(invalidate)m.invalidate();else m.clock(u,c,flush);
            d.clk_i=1;d.eval();if(c.valid)fill+=(code&3)==3?4:2;
        }
        std::cout<<"PASS: 4000 BPU RTL edges\n";
    } catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
