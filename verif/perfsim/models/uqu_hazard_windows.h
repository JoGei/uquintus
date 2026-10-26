#ifndef UQU_PERFSIM_HAZARD_WINDOWS_H
#define UQU_PERFSIM_HAZARD_WINDOWS_H
#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <stdexcept>

namespace uqu {
// Youngest-writer lifetimes on an independent reference clock. Intervals
// describe pre-edge occupancy: EX ends at ex, MEM at mem, WB at wb. GPR
// storage is readable after WB's architectural write edge, never before it.
struct HazardWindows {
    enum Kind { arithmetic, load, csr, split };
    struct Writer {
        bool valid=false;
        Kind kind=arithmetic;
        uint64_t de=0,ready=0,ex=0,mem=0,wb=0;
    };
    struct Operand {bool ready=false,guaranteed=false;};
    bool forwarding=true,ex_to_de=true,mem_to_de=true,mem_to_ex=true,wb_to_ex=true,retention=false;
    std::array<Writer,32> writers{};
    Operand source(unsigned reg,uint64_t edge,bool need_now) const {
        if(reg>=32)throw std::runtime_error("invalid hazard source");
        const auto& w=writers[reg];
        if(!reg || !w.valid || edge>w.wb)return {true,false};
        if(!forwarding)return {};
        if(edge<=w.ex) {
            const bool usable=w.kind==arithmetic && edge>=w.ready;
            return {usable && ex_to_de,usable && !ex_to_de && !need_now && edge==w.ex && mem_to_ex};
        }
        if(edge<=w.mem) {
            const bool usable=w.kind==arithmetic || w.kind==split;
            return {usable && mem_to_de,usable && !mem_to_de && !need_now && (edge==w.mem?wb_to_ex:mem_to_ex)};
        }
        return {w.kind==arithmetic || w.kind==split,false}; // WB-to-DE follows the master.
    }
    uint64_t first_ready(unsigned reg,uint64_t start) const {
        if(!reg || !writers[reg].valid)return start;
        const auto& w=writers[reg];
        uint64_t first=std::max(start,w.wb+1);
        if(!forwarding)return first;
        if(w.kind==arithmetic && ex_to_de) {
            const auto t=std::max(start,w.ready);if(t<=w.ex)first=std::min(first,t);
        }
        if(w.kind==arithmetic || w.kind==split) {
            if(mem_to_de) {const auto t=std::max(start,w.ex+1);if(t<=w.mem)first=std::min(first,t);}
            const auto t=std::max(start,w.mem+1);if(t<=w.wb)first=std::min(first,t);
        }
        return first;
    }
    uint64_t admit(unsigned rs1,unsigned rs2,uint64_t start,uint64_t base,bool need_now) const {
        uint64_t t=base;
        for(unsigned iteration=0;iteration<32;++iteration) {
            bool ready=true;uint64_t next=std::numeric_limits<uint64_t>::max();
            for(unsigned reg:{rs1,rs2}) {
                const auto value=source(reg,t,need_now);
                if(value.ready || value.guaranteed || (retention && first_ready(reg,start)<=t))continue;
                ready=false;
                const auto& w=writers.at(reg);
                for(auto event:{w.ready,w.ex,w.ex+1,w.mem,w.mem+1,w.wb+1})
                    if(event>t)next=std::min(next,event);
            }
            if(ready)return t;
            if(next==std::numeric_limits<uint64_t>::max())throw std::runtime_error("hazard admission has no future event");
            t=next;
        }
        throw std::runtime_error("hazard admission did not converge");
    }
    void write(unsigned rd,Kind kind,uint64_t de,uint64_t ready,uint64_t ex,uint64_t mem,uint64_t wb) {
        if(rd>=32 || de>ex || ex>=mem || mem>=wb || ready<de || ready>ex)
            throw std::runtime_error("invalid producer lifetime");
        if(rd)writers[rd]={true,kind,de,ready,ex,mem,wb};
    }
};
}
#endif
