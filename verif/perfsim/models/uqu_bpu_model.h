#ifndef UQU_PERFSIM_BPU_MODEL_H
#define UQU_PERFSIM_BPU_MODEL_H
#include <cstdint>
#include <vector>
#include <stdexcept>
#include <map>

namespace uqu {
// Native counterpart of uqu_bpu. lookup() observes pre-edge state; clock()
// applies the preceding edge's accepted DE/IF event bundle.
class BpuState {
    struct Target {bool valid=false,conditional=false;uint32_t pc=0,target=0;std::vector<uint16_t> data;};
    struct Direction {bool valid=false;uint32_t pc=0;unsigned counter=0;};
    std::vector<Target> targets;
    std::vector<Direction> directions;
    bool filling=false;
    uint32_t owner_pc=0,owner_target=0,fill_pc=0;
    unsigned offset=0;
    unsigned index(uint32_t pc,unsigned size) const {return (pc>>(compressed?1:2))&(size-1);}
    bool aligned(uint32_t pc) const {return !(pc&(compressed?1:3));}
public:
    bool compressed=false,enabled=false,bimodal=false;
    unsigned entries=16,direction_entries=16,hwords=0;
    struct Prediction {bool hit=false,taken=false;uint32_t target=0;unsigned hwords=0;};
    struct Update {bool valid=false,control=false,conditional=false,taken=false;uint32_t pc=0,target=0;};
    struct Capture {bool valid=false;uint32_t pc=0,code=0;};
private:
    Update pending_update;
    Capture pending_capture;
    bool pending_flush=false;
public:
    void initialize() {
        if(entries<2 || (entries&(entries-1)) || direction_entries<2 ||
           (direction_entries&(direction_entries-1)) || (!compressed && (hwords&1)))
            throw std::runtime_error("invalid trace BPU configuration");
        targets.resize(entries);directions.resize(direction_entries);
    }
    void invalidate() {
        for(auto& t:targets){t.valid=false;t.data.clear();}
        for(auto& d:directions)d.valid=false;
        filling=false;pending_update={};pending_capture={};pending_flush=false;
    }
    Prediction lookup(uint32_t pc) const {
        Prediction p;
        if(!enabled || !aligned(pc))return p;
        const auto& t=targets.at(index(pc,entries));
        p.hit=t.valid && t.pc==pc;
        if(!p.hit)return p;
        const auto& d=directions.at(index(pc,direction_entries));
        p.taken=!t.conditional || (bimodal && d.valid && d.pc==pc && d.counter>=2);
        p.target=t.target;p.hwords=t.data.size();return p;
    }
    uint16_t data(uint32_t pc,unsigned hword) const {
        const auto p=lookup(pc);return p.hit && hword<p.hwords?targets.at(index(pc,entries)).data.at(hword):0;
    }
    void clock(const Update& u,const Capture& c,bool flush=false) {
        apply(pending_update,pending_capture,pending_flush);
        pending_update=u;pending_capture=c;pending_flush=flush;
    }
protected:
    // Sparse timestamped models apply already-delayed, ordered events here.
    void apply(const Update& u,const Capture& c,bool flush=false) {
        if(!enabled)return;
        const bool update=u.valid && aligned(u.pc),control=update && u.control && aligned(u.target);
        auto& t=targets.at(index(u.pc,entries));
        const bool hit=t.valid && t.pc==u.pc;
        const bool changed=update && (control?(!hit || t.target!=u.target):hit);
        const bool start=control && u.taken;
        auto& old=targets.at(index(owner_pc,entries));
        const bool live=old.valid && old.pc==owner_pc && old.target==owner_target &&
            !(changed && index(u.pc,entries)==index(owner_pc,entries));
        auto& slot=start?t:old;
        const unsigned pos=start?0:offset;
        const uint32_t expected=start?u.target:fill_pc;
        const bool short_insn=compressed && (c.code&3)!=3;
        const unsigned size=short_insn?1:2;
        const unsigned count=start && changed?0:slot.data.size();
        bool same=true;
        if(pos<count) {
            same=slot.data.at(pos)==uint16_t(c.code);
            if(!short_insn)same=same && pos+1<count && slot.data.at(pos+1)==uint16_t(c.code>>16);
        }
        const bool collect=hwords && c.valid && c.pc==expected && same && pos+size<=hwords &&
            (start || (filling && !flush && live));
        if(flush || !live)filling=false;
        if(changed)t.data.clear();
        if(start) {filling=count<hwords;owner_pc=u.pc;owner_target=u.target;fill_pc=u.target;offset=0;}
        if(filling && c.valid && (!same || c.pc!=expected || pos+size>hwords))filling=false;
        if(collect) {
            if(pos==count){slot.data.push_back(uint16_t(c.code));if(!short_insn)slot.data.push_back(uint16_t(c.code>>16));}
            fill_pc=c.pc+size*2;offset=pos+size;if(offset==hwords)filling=false;
        }
        if(update) {
            if(control){t.valid=true;t.pc=u.pc;t.target=u.target;t.conditional=u.conditional;}
            else if(hit)t.valid=false;
            if(bimodal) {
                auto& d=directions.at(index(u.pc,direction_entries));
                const bool dhit=d.valid && d.pc==u.pc;
                if(control && u.conditional) {
                    d.counter=!dhit?(u.taken?2:1):u.taken?(d.counter==3?3:d.counter+1):(d.counter?d.counter-1:0);
                    d.valid=true;d.pc=u.pc;
                } else if(control || dhit)d.valid=false;
            }
        }
    }
};
// BPU events commit one edge after acceptance on the shared reference clock.
// A sparse calendar preserves same-edge update/capture/flush bundles without
// adding cycle-by-cycle callbacks during long backend or memory waits.
struct TimedBpuState : BpuState {
    Prediction prediction;
    uint64_t evaluations=0,hits=0,taken=0;
private:
    bool initialized=false,valid=false,previous_control=false,previous_conditional=false;
    uint32_t previous_pc=0,previous_target=0,next_pc=0,expected_pc=0;
    struct Event {Update update;Capture capture;bool flush=false;};
    std::map<uint64_t,Event> events;
    void apply_before(uint64_t edge) {
        while(!events.empty() && events.begin()->first<edge) {
            const auto e=events.begin()->second;
            apply(e.update,e.capture,e.flush);events.erase(events.begin());
        }
    }
public:
    void invalidate() {
        BpuState::invalidate();events.clear();valid=false;prediction={};
    }
    void prepare(uint32_t pc,uint64_t ready,uint64_t previous_de) {
        if(!initialized){initialize();initialized=true;}
        if(!enabled){prediction={};return;}
        if(valid) {
            auto& e=events[previous_de+1];
            e.update={true,previous_control,previous_conditional,pc!=next_pc,previous_pc,previous_target};
            e.flush=pc!=expected_pc;
        }
        apply_before(ready);
        prediction=lookup(pc);++evaluations;hits+=prediction.hit;taken+=prediction.taken;
    }
    void accept(uint32_t pc,uint32_t code,uint32_t target,uint64_t edge,bool control,bool conditional) {
        if(!enabled)return;
        apply_before(edge+1);
        events[edge+1].capture={true,pc,code};
        previous_pc=pc;previous_control=control;previous_conditional=conditional;previous_target=target;next_pc=pc+((code&3)==3?4:2);
        expected_pc=prediction.taken?prediction.target:next_pc;valid=true;
    }
};

}
#endif
