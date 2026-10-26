#include "Vuqu_hazard.h"
#include "verilated.h"
#include "uqu_hazard_windows.h"
#include <cstdio>
#include <random>
#include <stdexcept>

using Windows=uqu::HazardWindows;
struct Producer {unsigned rd;Windows::Writer w;};
static bool usable(const Windows::Writer& w,unsigned stage,uint64_t t) {
    return stage==0?w.kind==Windows::arithmetic && t>=w.ready:
           stage==1?(w.kind==Windows::arithmetic || w.kind==Windows::split):
                    (w.kind==Windows::arithmetic || w.kind==Windows::split);
}
int main(int argc,char** argv) {
    Verilated::commandArgs(argc,argv);Vuqu_hazard rtl;
    std::mt19937 random(20261026);
    unsigned checked=0;
    for(unsigned trial=0;trial<1000;++trial) {
        Windows model;model.forwarding=UQU_MASTER;model.ex_to_de=UQU_MASK&1;model.mem_to_de=UQU_MASK&2;
        model.mem_to_ex=UQU_MASK&4;model.wb_to_ex=UQU_MASK&8;model.retention=UQU_RETAIN;
        Producer p[2];uint64_t ex=0,mem=0,wb=0;
        for(unsigned i=0;i<2;++i) {
            p[i].rd=(trial%7==0)?3:3+i;
            auto& w=p[i].w;w.valid=true;w.kind=Windows::Kind(random()%4);
            w.de=std::max(ex,1+uint64_t(i));w.ready=w.de+1+random()%8;
            w.ex=std::max(w.ready,mem);w.mem=std::max(w.ex+1,wb);w.wb=w.mem+1+random()%5;
            ex=w.ex;mem=w.mem;wb=w.wb;
            model.write(p[i].rd,w.kind,w.de,w.ready,w.ex,w.mem,w.wb);
        }
        // A held DE consumer starts while the second producer occupies EX.
        const auto start=p[1].w.de+1+random()%2;
        const auto base=std::max(start,p[1].w.ex)+random()%4;
        const unsigned a=trial%11==0?0:3,b=trial%13==0?3:4;
        const bool need_now=trial&1;
        const auto predicted=model.admit(a,b,start,base,need_now);
        rtl.clk_i=0;rtl.rst_ni=0;rtl.de_valid_i=0;rtl.eval();rtl.clk_i=1;rtl.eval();
        rtl.rst_ni=1;rtl.de_valid_i=1;rtl.de_clear_i=0;
        rtl.de_rs0_addr_i=a;rtl.de_rs1_addr_i=b;rtl.de_rs_used_i=3;
        rtl.de_rs_need_now_i=need_now?3:0;
        bool retained[2]={};uint64_t observed=0;
        for(uint64_t t=start;t<=wb+5;++t) {
            rtl.clk_i=0;rtl.ex_valid_i=rtl.mem_valid_i=rtl.wb_valid_i=0;
            rtl.ex_pending_i=rtl.mem_pending_i=rtl.wb_pending_i=0;
            rtl.ex_result_available_i=rtl.ex_result_forwardable_i=0;
            rtl.mem_result_available_i=rtl.mem_result_forwardable_i=0;
            rtl.wb_result_available_i=rtl.wb_result_forwardable_i=0;
            rtl.ex_advance_i=rtl.mem_advance_i=rtl.wb_advance_i=0;
            for(const auto& v:p) {
                const auto& w=v.w;
                if(t<=w.de || t>w.wb)continue;
                if(t<=w.ex) {
                    rtl.ex_valid_i=1;rtl.ex_pending_i=1;rtl.ex_rd0_i=v.rd;
                    rtl.ex_result_available_i=rtl.ex_result_forwardable_i=usable(w,0,t);rtl.ex_advance_i=t==w.ex;
                } else if(t<=w.mem) {
                    rtl.mem_valid_i=1;rtl.mem_pending_i=1;rtl.mem_rd0_i=v.rd;
                    rtl.mem_result_available_i=rtl.mem_result_forwardable_i=usable(w,1,t);rtl.mem_advance_i=t==w.mem;
                } else {
                    rtl.wb_valid_i=1;rtl.wb_pending_i=1;rtl.wb_rd0_i=v.rd;
                    rtl.wb_result_available_i=rtl.wb_result_forwardable_i=usable(w,2,t);rtl.wb_advance_i=t==w.wb;
                }
            }
            rtl.eval();bool all=true;
            for(unsigned n=0;n<2;++n) {
                const auto v=model.source(n?b:a,t,need_now);
                const bool ready=v.ready || retained[n],guaranteed=!retained[n] && v.guaranteed;
                if(bool(rtl.de_rs_ready_o&(1<<n))!=ready || bool(rtl.de_rs_ex_guaranteed_o&(1<<n))!=guaranteed) {
                    std::printf("mask %u retain %u master %u trial %u edge %llu source %u: RTL %u/%u vs %u/%u\n",
                        UQU_MASK,UQU_RETAIN,UQU_MASTER,trial,(unsigned long long)t,n,
                        bool(rtl.de_rs_ready_o&(1<<n)),bool(rtl.de_rs_ex_guaranteed_o&(1<<n)),ready,guaranteed);return 1;
                }
                all&=ready || guaranteed;
                if(UQU_RETAIN && v.ready)retained[n]=true;
            }
            ++checked;
            if(t>=base && all){observed=t;break;}
            rtl.clk_i=1;rtl.eval();
        }
        if(predicted!=observed) {
            std::printf("admission mismatch trial %u: %llu vs %llu\n",trial,
                (unsigned long long)predicted,(unsigned long long)observed);return 1;
        }
    }
    // Directed disappearing bypass: x4 is available in EX while x3 waits in
    // MEM; retaining x4 allows the branch to leave a cycle earlier.
    Windows gap;gap.mem_to_de=false;gap.write(3,Windows::arithmetic,1,2,2,3,4);
    gap.write(4,Windows::arithmetic,2,3,3,4,5);
    if(gap.admit(3,4,3,3,true)!=5)return 2;
    gap.retention=true;if(gap.admit(3,4,3,3,true)!=4)return 3;
    std::printf("PASS: %u producer-window/RTL edges, 1000 admission scenarios\n",checked);
}
