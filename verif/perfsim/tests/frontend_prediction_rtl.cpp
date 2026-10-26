// Clocked IF/BPU comparison. A one-entry DE stimulus resolves synthetic
// control flow with independent stalls; memory remains ordered/fixed latency.
#include "Vuqu_stage_if.h"
#include "verilated.h"
#include "uqu_frontend.h"
#include "uqu_bpu_model.h"
#include <iostream>
#include <deque>
#include <stdexcept>
#include <vector>

static constexpr uint32_t boot=0x80000000;
static uint16_t halfword(uint32_t addr) {
    static constexpr uint16_t h[]={0x0001,0x0013,0x0000,0x0001};
    return h[((addr-boot)/2)%4];
}
static uint32_t word(uint32_t addr) {
    return UQU_TEST_C?uint32_t(halfword(addr)) | uint32_t(halfword(addr+2))<<16:0x13;
}
static void check(bool b,const char* what,uint64_t edge) {
    if(!b)throw std::runtime_error(std::string(what)+" at edge "+std::to_string(edge));
}
struct Decode {
    bool valid=false,control=false,conditional=false,taken=false;
    uint64_t due=0;
    uint32_t pc=0,target=0,next=0,predicted=0;
};
int main(int argc,char**argv) {
    try {
        if(argc!=4)throw std::runtime_error("expected bypass, depth, latency");
        const unsigned bypass=std::stoul(argv[1]),depth=std::stoul(argv[2]),latency=std::stoul(argv[3]);
        Vuqu_stage_if d;uqu::FrontendQueues q;uqu::BpuState bpu;
        q.configure(latency,depth,bypass,boot,UQU_TEST_C);
        bpu.enabled=true;bpu.bimodal=true;bpu.compressed=UQU_TEST_C;bpu.hwords=UQU_TEST_H;bpu.initialize();
        d.boot_addr_i=boot;d.pmp_allow_i=1;d.replay_pmp_allow_i=3;d.priv_m_i=1;
        d.fetch_enable_i=1;d.request_permit_i=1;d.permit_i=1;d.imem_gnt_i=1;
        for(unsigned i=0;i<2;++i){d.clk_i=0;d.rst_ni=0;d.eval();d.clk_i=1;d.eval();}d.rst_ni=1;
        std::deque<std::pair<uint64_t,uint32_t>> due;
        std::vector<uint16_t> replay;
        uint32_t pc=boot,held_pc=0;bool held=false;Decode de;
        uint64_t transfers=0,predictions=0,replays=0,visits=0,corrections=0;
        for(unsigned edge=1;edge<=6000;++edge) {
            const bool de_fire=de.valid && de.due==edge;
            const bool recover=de_fire && de.predicted!=de.next;
            const bool ready=(!de.valid || de_fire) && !recover && edge%41>3;
            const bool response=!due.empty() && due.front().first==edge;
            const auto before=q.signals();
            q.instruction_length(UQU_TEST_C && (word(before.pc)&3)!=3?2:4);
            const bool replaying=!replay.empty();
            const uint32_t code=replaying?uint32_t(replay[0]) | (replay.size()>1?uint32_t(replay[1])<<16:0):word(pc);
            const unsigned size=UQU_TEST_C && (code&3)!=3?2:4;
            const bool valid=!recover && (replaying || q.signals().valid);
            const bool transfer=valid && ready;
            const auto p=bpu.lookup(pc);
            const uint32_t predicted=held?held_pc:p.taken?p.target:pc+size;
            const bool steering=transfer && predicted!=pc+size;
            const bool start=steering && p.taken && p.target==predicted && p.hwords;
            const uint32_t target=recover?de.next:start?predicted+p.hwords*2:predicted;
            d.clk_i=0;d.ready_i=ready;d.redirect_valid_i=recover;d.flush_i=recover;
            d.redirect_request_permit_i=recover;d.redirect_addr_i=de.next;
            d.predictor_update_valid_i=de_fire;d.predictor_update_pc_i=de.pc;
            d.predictor_update_control_flow_i=de.control;d.predictor_update_conditional_i=de.conditional;
            d.predictor_update_taken_i=de.taken;d.predictor_update_target_i=de.target;
            d.imem_rvalid_i=response;d.imem_rdata_i=response?word(due.front().second):0;d.eval();
            auto expected=q.signals(transfer && !replaying,recover,target,false,steering);
            check(bool(d.valid_o)==valid,"IF valid",edge);
            check(!valid || d.pc_o==pc,"IF PC",edge);
            const uint32_t mask=size==2?0xffff:0xffffffff;
            check(!valid || (d.original_instr_o&mask)==(code&mask),"IF payload",edge);
            check(!valid || d.predicted_next_pc_o==predicted,"held prediction",edge);
            check(bool(d.imem_req_o)==expected.req,"OBI request",edge);
            check(!expected.req || d.imem_addr_o==expected.addr,"OBI address",edge);
            if(response)due.pop_front();
            if(d.imem_req_o)due.push_back({edge+latency,d.imem_addr_o});
            std::vector<uint16_t> prefix;
            if(start)for(unsigned h=0;h<p.hwords;++h)prefix.push_back(bpu.data(pc,h));
            bpu.clock({de_fire,de.control,de.conditional,de.taken,de.pc,de.target},{transfer,pc,code},recover);
            q.step(transfer && !replaying,recover,target,false,steering);
            if(recover){replay.clear();held=false;++corrections;}
            else {
                if(valid && !ready && !held){held=true;held_pc=predicted;}
                if(transfer)held=false;
                if(steering){replay=prefix;++predictions;}
                else if(transfer && replaying)replay.erase(replay.begin(),replay.begin()+size/2);
            }
            if(de_fire)de.valid=false;
            if(transfer) {
                ++transfers;replays+=replaying;
                de.valid=true;de.pc=pc;de.predicted=predicted;
                de.control=pc==boot || pc==boot+0x50;de.conditional=pc==boot;
                de.target=pc==boot?boot+(UQU_TEST_C?0x42:0x40):boot;
                de.taken=de.control && (!de.conditional || ++visits%5!=0);
                de.next=de.taken?de.target:pc+size;
                de.due=edge+1+(transfers%13==0?31:transfers%7==0?5:0);
                pc=predicted;
            } else if(recover)pc=de.next;
            d.clk_i=1;d.eval();
        }
        check(transfers>100 && predictions>10 && corrections>10,"stimulus coverage",6000);
        check(!UQU_TEST_H || replays>10,"replay exercised",6000);
        std::cout<<"PASS: c="<<UQU_TEST_C<<" hwords="<<UQU_TEST_H<<" bypass="<<bypass<<" latency="<<latency
                 <<" 6000 RTL edges, "<<transfers<<" captures, "<<replays<<" replayed\n";
    }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}
