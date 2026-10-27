#include "uqu_bpu_model.h"
#include <cassert>

static void configure(uqu::BpuState& b) {
    b.enabled=true;b.compressed=true;b.bimodal=true;b.hwords=6;b.initialize();
}
int main() {
    constexpr uint32_t branch=0x1000,target=0x2000;
    const uqu::BpuState::Update update{true,true,false,true,branch,target};
    const uqu::BpuState::Capture first{true,target,1},second{true,target+2,0x85};
    uqu::BpuState clocked;configure(clocked);
    clocked.clock(update,first);
    assert(!clocked.lookup(branch).hit);
    clocked.clock({},{});
    assert(clocked.lookup(branch).hit && clocked.lookup(branch).hwords==1);
    clocked.clock({},second);
    clocked.clock({},{},true); // Older capture commits before the ordinary flush.
    assert(clocked.lookup(branch).hwords==2);
    clocked.clock({}, {true,target+4,1});
    clocked.clock({},{});
    assert(clocked.lookup(branch).hwords==2);
    clocked.clock(update,first);clocked.invalidate();clocked.clock({},{});
    assert(!clocked.lookup(branch).hit); // Pending work cannot survive FENCE.I.

    for(unsigned ready:{2,3,4,5}) {
        uqu::TimedBpuState b;configure(b);
        b.prepare(branch,1,0);b.accept(branch,0x6f,branch,1,true,false);
        b.prepare(branch,ready,2);
        assert(b.prediction.hit==(ready>3)); // Edge-2 training commits at edge 3.
        b.accept(branch,0x6f,branch,ready,true,false);
        assert(b.lookup(branch).hwords==0);
        b.prepare(branch,8,6);
        assert(b.prediction.hit && b.prediction.taken && b.prediction.hwords==2);
    }
    // DE training and IF capture accepted on the same edge must merge even
    // when the model discovers them in separate instruction callbacks.
    uqu::TimedBpuState sparse;configure(sparse);
    sparse.prepare(branch,1,0);sparse.accept(branch,0x6f,target,1,true,false);
    sparse.prepare(target,2,2);sparse.accept(target,1,0,2,false,false);
    sparse.prepare(target+2,1ULL<<40,4); // Sparse waits must not tick every cycle.
    assert(sparse.lookup(branch).hit && sparse.lookup(branch).hwords==1);
    assert(sparse.data(branch,0)==1);
    // Discard both future training and the delayed capture on invalidation.
    uqu::TimedBpuState canceled;configure(canceled);
    canceled.prepare(branch,1,0);canceled.accept(branch,0x6f,target,1,true,false);
    canceled.prepare(target,2,100);canceled.invalidate();
    canceled.prepare(target,1000,100);
    assert(!canceled.lookup(branch).hit && !canceled.lookup(branch).hwords);
}
