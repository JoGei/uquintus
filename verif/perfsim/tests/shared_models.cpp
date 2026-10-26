#include "uqu_models.h"
#include <stdexcept>

class TestModel : public PerformanceModel {
public:
    TestModel(SchedulingFunctionSet* s):PerformanceModel("test",s) {instrIndex=0;}
    void connectChannel(Channel*) override {}
    uint64_t getCycleCount() override {return 0;}
    std::string getPipelineStream() override {return "";}
    std::string getPrintHeader() override {return "";}
};
static void check(bool ok) {if(!ok)throw std::runtime_error("shared transition mismatch");}
int main() {
    // Equal histories reuse results; diverging callback inputs retain distinct
    // states, including across cache epochs. Parameter differences never alias.
    struct State {uint64_t total=0;};
    uqu::TransitionCache<State> cache;
    auto a=cache.initial({1,0,0,0,0}),b=cache.initial({1,0,0,0,0}),c=cache.initial({2,0,0,0,0});
    cache.beginInstruction();
    auto add=[](State& s){return ++s.total;};
    check(cache.apply(a,{0,0,0,0},add)==1);
    check(cache.apply(b,{0,0,0,0},add)==1 && cache.hits==1);
    check(cache.apply(c,{0,0,0,0},add)==1 && cache.evaluations==2);
    cache.apply(a,{1,0,0,2},[](State& s){return s.total+=2;});
    cache.apply(b,{1,0,0,4},[](State& s){return s.total+=4;});
    cache.beginInstruction();
    check(cache.apply(a,{0,0,0,0},add)==4);
    check(cache.apply(b,{0,0,0,0},add)==6);

    SchedulingFunctionSet schedules("test");
    TestModel pa(&schedules),pb(&schedules),pr(&schedules),ps(&schedules);
    uqu::FrontendModel fa(&pa),fb(&pb),fr(&pr),fs(&ps);
    uint64_t pc[80],code[80];
    for(unsigned i=0;i<80;++i) {pc[i]=0x80000000+4*i;code[i]=i==5 ? 0x00000263 : 0x13;}
    for(unsigned i=6;i<80;++i)pc[i]+=4; // Taken branch, including wrong-path fetches.
    for(auto f:{&fa,&fb,&fr,&fs}) {f->pc_ptr=pc;f->code_ptr=code;f->bypass=7;}
    uqu::FrontendSharing pool;fa.share(pool);fb.share(pool);
    for(unsigned i=0;i<80;++i) {
        pa.instrIndex=pb.instrIndex=pr.instrIndex=ps.instrIndex=i;
        pool.beginInstruction();
        const auto ra=fa.getPc(),rr=fr.getPc();check(ra==rr);
        fa.setIfConsumed(ra);fr.setIfConsumed(rr);
        fa.setDeAdvanced(ra+1);fr.setDeAdvanced(rr+1);
        const auto rb=fb.getPc(),rs=fs.getPc();check(rb==rs);
        const auto extra=i>=4 ? 2 : 0;
        fb.setIfConsumed(rb+extra);fs.setIfConsumed(rs+extra);
        fb.setDeAdvanced(rb+extra+1);fs.setDeAdvanced(rs+extra+1);
        check(fa.snapshot().equivalent(fr.snapshot()));
        check(fb.snapshot().equivalent(fs.snapshot()));
    }
    check(pool.hits>0 && pool.evaluations<pool.calls && pool.peak_entries<=6);
}
