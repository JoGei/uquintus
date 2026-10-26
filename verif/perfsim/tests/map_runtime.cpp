// The real upstream loop must accumulate resource delays before one block call.
#include <tuple>
#include <cassert>
#include "MAPExplorer.h"
struct Fetch final : map_models::ResourceModel {
    unsigned calls=0;
    void updateDelay() override {delayBuffer=++calls;}
};
struct Group final : MAP_Explorer::ResourceGroupT<Fetch> {
    explicit Group(Fetch& f):ResourceGroupT(0,f) {}
    void connectChannel(Channel*,int*) override {}
};
struct Branch final : map_models::BranchModel {
    unsigned catches=0,evaluations=0;
    mutable unsigned shifts=0;
    void catchBranch() override {++catches;}
    void evaluate() override {++evaluations;}
    void shiftVector(uint64_t* v) const override {v[0]+=10;++shifts;}
};
static void two(uint64_t* v,uint8_t* d) {v[0]+=d[0]+d[1];}
static void other_two(uint64_t* v,uint8_t* d) {v[0]+=2*(d[0]+d[1]);}
static void one(uint64_t* v,uint8_t* d) {v[0]+=d[0];}
static void other_one(uint64_t* v,uint8_t* d) {v[0]+=2*d[0];}
using Engine=MAP_Explorer::MAPExplorer<true,1,2,1,1,1,1,1>;
struct Probe final : Engine {
    MAP_Explorer::Block blocks[2]{{0,4,8,true,two},{1,12,12,false,one}};
    const MAP_Explorer::Block* pointers[2]{&blocks[0],&blocks[1]};
    MAP_Explorer::BlockDictionary dictionary{pointers,2};
    Fetch fetch;Group group{fetch};Branch branch;
    MAP_Explorer::BranchGroupT<Branch> branch_group{branch};
    std::array<const ResGroupEntryType,1> lut{{{1,{{&group}}}}};
    std::array<MAP_Explorer::ResourceGroup*,1> resources{{&group}};
    std::array<DVecType,1> delays{};
    std::array<CombType,2> states{};
    uint64_t count=3,pc[3]{4,8,12},type[3]{};
    unsigned after=0;
    Probe():Engine(&dictionary,nullptr,lut,resources,&branch_group,delays,states) {
        delays[0]=DVecType(std::array<map_models::ResourceModel*,1>{{&fetch}});
        for(auto& c:states)c=CombType(&delays[0],&branch);
        connectChannel(nullptr);
    }
    void connectChannel(Channel*) override {ch_instrCnt_ptr=&count;ch_pc_ptr=pc;ch_typeId_ptr=type;}
    MAP_Explorer::Block::SchedFuncPtr selectBlockSchedule(size_t c,const MAP_Explorer::Block& b) override {
        return c ? (b.id==0?other_two:other_one):Engine::selectBlockSchedule(c,b);
    }
    void afterCombination(size_t,uint64_t*) override {++after;}
};
int main() {
    Probe p;p.executeRange(0,1);
    assert(p.after==0 && p.fetch.calls==1); // An incomplete block is not scheduled.
    p.executeRange(1,3);
    assert(p.after==4 && p.fetch.calls==3); // Shared across both timing states.
    assert(p.states[0].getTimingVector()[0]==16 && p.states[1].getTimingVector()[0]==22);
    assert(p.branch.catches==1 && p.branch.evaluations==1 && p.branch.shifts==2);
    Probe unknown;unknown.pc[0]=16;
    bool rejected=false;try {unknown.execute();}catch(const std::runtime_error&) {rejected=true;}
    assert(rejected);
    rejected=false;try {unknown.executeRange(3,2);}catch(const std::runtime_error&) {rejected=true;}
    assert(rejected);
}
