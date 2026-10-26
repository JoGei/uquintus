// Compare the timing-only queue component against the actual IF
// RTL, not another implementation of the instruction scheduler.
#include "Vuqu_stage_if.h"
#include "verilated.h"
#include "uqu_frontend.h"
#include <iostream>
#include <deque>
#include <stdexcept>

static uint16_t halfword(uint32_t addr) {
    // 2,4,2,4-byte instructions: includes long instructions crossing a word.
    static constexpr uint16_t h[]={0x0001,0x0013,0x0000,0x0001,0x0013,0x0000};
    return h[((addr-0x80000000)/2)%6];
}
static uint32_t word(uint32_t addr) {
    return UQU_TEST_C ? uint32_t(halfword(addr)) | uint32_t(halfword(addr+2))<<16 : 0x13;
}
static void check(bool b, const char *what, uint64_t edge) {
    if(!b)throw std::runtime_error(std::string(what)+" at edge "+std::to_string(edge));
}
int main(int argc,char **argv) {
    try {
        if(argc!=4 && argc!=5)throw std::runtime_error("expected bypass, depth, latency");
        unsigned bypass=std::stoul(argv[1]),depth=std::stoul(argv[2]),latency=std::stoul(argv[3]);
        unsigned profile=argc==5?std::stoul(argv[4]):0;
        Vuqu_stage_if d;uqu::FrontendQueues model;uqu::MemoryPort memory;
        memory.configure({1},{latency});
        if(profile==1)memory.configure({1,0,1,1},{1,3,2,1});
        if(profile==2)memory.configure({1},{8},16,16,1,8);
        d.boot_addr_i=0x80000000;d.pmp_allow_i=1;d.replay_pmp_allow_i=3;d.priv_m_i=1;
        d.fetch_enable_i=1;d.request_permit_i=1;d.permit_i=1;d.ready_i=1;
        d.imem_gnt_i=1;d.imem_rdata_i=0x13;
        model.configure(latency,depth,bypass,0x80000000,UQU_TEST_C);
        model.memory=memory;
        for(unsigned i=0;i<2;++i) {d.clk_i=0;d.rst_ni=0;d.eval();d.clk_i=1;d.eval();}
        d.rst_ni=1;
        std::deque<std::pair<uint64_t,uint32_t>> due;
        uint32_t random=0x97531;
        for(unsigned edge=1;edge<=3000;++edge) {
            random=random*1664525+1013904223;
            bool ready=(random&7)!=0 && edge%71>8;
            bool hold=edge%43<7;
            bool redirect=edge%67==20 || edge%67==21;
            static constexpr unsigned starts[]={0,2,6,8};
            uint32_t target=0x80000000+(UQU_TEST_C ? 12*(edge%103)+starts[edge%4] : 4*(edge%313));
            bool response=!due.empty() && due.front().first<=edge;
            d.clk_i=0;d.ready_i=ready;d.branch_pending_i=hold;
            d.redirect_valid_i=redirect;d.redirect_request_permit_i=redirect;
            d.redirect_addr_i=target;d.flush_i=redirect;
            d.imem_gnt_i=memory.can_grant(edge);
            d.imem_rvalid_i=response;d.imem_rdata_i=response ? word(due.front().second) : 0;d.eval();
            model.instruction_length(UQU_TEST_C && (halfword(d.pc_o)&3)!=3 ? 2 : 4);
            const bool consume=d.valid_o && ready;
            auto expected=model.signals(consume,redirect,target,hold);
            check(bool(d.valid_o)==expected.valid,"IF valid",edge);
            check(!d.valid_o || d.pc_o==expected.pc,"IF PC",edge);
            check(bool(d.imem_req_o)==expected.req,"OBI request",edge);
            check(!d.imem_req_o || d.imem_addr_o==expected.addr,"OBI address",edge);
            if(response)due.pop_front();
            if(d.imem_req_o && d.imem_gnt_i)due.push_back({memory.accept(d.imem_addr_o,false,edge),d.imem_addr_o});
            model.step(consume,redirect,target,hold);
            d.clk_i=1;d.eval();
        }
        std::cout<<"PASS: c="<<UQU_TEST_C<<" bypass="<<bypass<<" words="<<depth<<" latency="<<latency<<" 3000 RTL edges\n";
    }catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
