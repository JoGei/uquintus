#include "uqu_trace_models.h"
#include <cassert>
class Dummy final : public PerformanceModel {
    static SchedulingFunctionSet functions;
public:
    Dummy():PerformanceModel("trace contract",&functions) {instrIndex=0;}
    void connectChannel(Channel*) override {}
    uint64_t getCycleCount() override {return 0;}
    std::string getPipelineStream() override {return {};}
    std::string getPrintHeader() override {return {};}
};
SchedulingFunctionSet Dummy::functions{"empty"};
int main() {
    // Idle fast-forward must preserve every queue/counter/state bit, including
    // response deadlines and a request armed before a long backend stall.
    for(unsigned mask=0;mask<8;++mask)for(unsigned latency:{1U,5U})for(bool c:{false,true}) {
        uqu::FrontendQueues a;a.configure(latency,2,mask,0x1000,c);
        for(unsigned i=0;i<80;++i) {
            auto b=a;const auto stop=a.time+1+i%19;
            const bool hold=i%3==0;
            while(b.time<stop)b.step(false,false,0,hold);
            while(a.time<stop)if(!a.skip_idle_until(stop,hold))a.step(false,false,0,hold);
            assert(a.equivalent(b));
            if(i%17==0)a.step(false,true,0x2000+4*i,false);
            else a.step(a.signals().valid,false,0,false);
        }
    }
    // Real control flow with mixed instruction lengths and a straddling target.
    uqu::TraceFetchState fetch;fetch.latency=5;fetch.compressed=true;fetch.predictor=1;
    assert(fetch.access(0x1000,0x13)==5);
    for(auto pc:{0x1004U,0x1008U,0x100aU,0x100eU}) {
        const auto delay=fetch.access(pc,pc==0x1008?1:pc==0x100e?0x6f:0x13);
        assert(delay>=1 && delay<=255);
    }
    assert(fetch.access(0x2002,0x13)>=5);
    assert(fetch.access(0x2006,1)>=1);
    // No prediction stops new requests, not consumption of prefetched words.
    // An unresolved load in DE hides a later fetch bubble. Charging that
    // bubble after the interlock would count the same waiting cycle twice.
    for(bool dependent:{false,true}) {
        uqu::TraceFetchState held;held.static_not_taken=false;
        const unsigned codes[]{0x18463,0x2183,0x18463,0x2183,0x2183};
        for(unsigned i=0;i<5;++i) {
            const bool load=codes[i]==0x2183;
            const auto delay=held.access(0x1000+4*i,codes[i],!load && dependent?3:0,0,load?3:0);
            assert(delay==(i==4 && !dependent?2U:1U));
        }
        // Loading x0 cannot create that interlock.
        uqu::TraceFetchState zero;zero.static_not_taken=false;
        for(unsigned i=0;i<5;++i) {
            const auto delay=zero.access(0x1000+4*i,codes[i],codes[i]==0x2183?0:3,0,0);
            assert(delay==(i==4?2U:1U));
        }
    }
    // Training before lookup is visible; training on the IF capture edge is
    // read-before-write. Capture continues collecting after an earlier DE
    // redirect, rather than being delayed until another functional lookup.
    for(bool early:{false,true}) {
        uqu::TimedBpuState b;b.enabled=true;b.compressed=true;b.hwords=6;
        b.prepare(0x1000,1,0);b.accept(0x1000,0x6f,0x1000);
        b.prepare(0x1000,early?5:2,2);
        assert(b.prediction.hit==early);
        b.accept(0x1000,0x6f,0x1000);
        assert(b.lookup(0x1000).hwords==2);
        b.prepare(0x1000,8,6);b.accept(0x1000,0x6f,0x1000);
        assert(b.prediction.hit && b.prediction.taken);
        assert(b.prediction.hwords==2);
    }
    // A source instruction can release a registered credit on local clear.
    // A global recovery masks that same old-stream result.
    bool found_credit=false;
    uqu::FrontendQueues credit;credit.configure(5,2,7,0x1000,true);
    for(unsigned edge=0;edge<100;++edge) {
        if(credit.signals(true,false,0x2000,false,true).req &&
           !credit.signals(false,true,0x2000,false).req)found_credit=true;
        credit.step();
    }
    assert(found_credit);
    Dummy parent;uint64_t pcs[]{0x1000,0x2000},codes[]{0x63,0x13},de=7;
    uqu::TraceBranchModel branch{&parent};branch.pc_ptr=pcs;branch.code_ptr=codes;
    branch.de_stage_ptr=&de;branch.recovery_cycles=3;
    assert(branch.getPc()==0);branch.setPc_p(5);branch.setPc_np(4);
    assert(branch.branch_times()[2]==7);
    de=9;assert(branch.branch_times()[2]==9); // DE waits for EX availability.
    parent.instrIndex=1;assert(branch.getPc()==12);
    assert(branch.branch_times()[2]==9);
    parent.instrIndex=0;de=7;pcs[1]=0x1004;
    uqu::TraceBranchModel predicted{&parent};predicted.pc_ptr=pcs;predicted.code_ptr=codes;
    predicted.de_stage_ptr=&de;predicted.static_not_taken=true;predicted.recovery_cycles=3;
    predicted.setPc_p(5);predicted.setPc_np(4);parent.instrIndex=1;
    assert(predicted.getPc()==5);
    // Fallthrough is already in the prefetch stream for either branch policy.
    // Its hold/queue delay comes from the shared fetch envelope, not a second
    // unconditional dependency on branch resolution.
    parent.instrIndex=0;
    uqu::TraceBranchModel held{&parent};held.pc_ptr=pcs;held.code_ptr=codes;
    held.de_stage_ptr=&de;held.recovery_cycles=3;
    held.setPc_p(5);held.setPc_np(4);parent.instrIndex=1;
    assert(held.getPc()==5);
    // A predicted target equal to fallthrough does not steer IF or pay transport.
    parent.instrIndex=0;de=9;uint64_t if_stage=5;
    uqu::TraceFetchState descriptor;descriptor.prediction={true,true,0x1004,0};
    uqu::TraceBranchModel fallthrough_target{&parent};
    fallthrough_target.pc_ptr=pcs;fallthrough_target.code_ptr=codes;
    fallthrough_target.de_stage_ptr=&de;fallthrough_target.if_stage_ptr=&if_stage;
    fallthrough_target.fetch_ptr=&descriptor;fallthrough_target.recovery_cycles=3;
    fallthrough_target.setPc_p(5);fallthrough_target.setPc_np(4);parent.instrIndex=1;
    assert(fallthrough_target.getPc()==5);

}
