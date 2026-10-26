#ifndef UQU_PERFSIM_MODELS_H
#define UQU_PERFSIM_MODELS_H
#include "PerformanceModel.h"
#include <array>
#include <algorithm>
#include <cstdint>
#include "uqu_frontend.h"
#include "uqu_shared.h"

// Generated schedules determine producer completion times. x0 never acquires
// a dependency, including when a load or multiply names it as destination.
namespace uqu {
class RegisterModel : public ConnectorModel {
public:
    std::array<uint64_t, 32> available{}, admission{};
    bool forwarding = true;
    uint64_t *rs1_ptr = nullptr, *rs2_ptr = nullptr, *rd_ptr = nullptr;
    explicit RegisterModel(PerformanceModel *p) : ConnectorModel("uqu registers", p) {}
    uint64_t getXa() { return rs1_ptr[getInstrIndex()] ? available.at(rs1_ptr[getInstrIndex()]) : 0; }
    uint64_t getXb() { return rs2_ptr[getInstrIndex()] ? available.at(rs2_ptr[getInstrIndex()]) : 0; }
    uint64_t getDa() { return rs1_ptr[getInstrIndex()] ? admission.at(rs1_ptr[getInstrIndex()]) : 0; }
    uint64_t getDb() { return rs2_ptr[getInstrIndex()] ? admission.at(rs2_ptr[getInstrIndex()]) : 0; }
    void setXd(uint64_t t) {
        if (const auto rd=rd_ptr[getInstrIndex()]) {
            available.at(rd)=t; admission.at(rd)=t+!forwarding;
        }
    }
    void setLd(uint64_t t) {
        // The response can retire at edge t. Its value is visible for a DE
        // capture only at t+1: no live OBI-response -> operand bypass exists.
        if (const auto rd=rd_ptr[getInstrIndex()]) {
            available.at(rd)=t; admission.at(rd)=t+1;
        }
    }
};

struct FrontendState {
    bool force_recovery=false;
    bool external_memory=false;
    MemorySettings memory_settings;
    bool initialized = false, hold = false, awaiting_branch = false;
    uint64_t release_edge = 0;
    uint32_t fallthrough = 0, target = 0;
    bool redirect = false;
    static bool control(uint32_t code) {
        const unsigned op=code&127;
        if ((code&3)==3) return op==0x63 || op==0x6f || op==0x67;
        const unsigned q=code&3, f=code>>13&7;
        return (q==1 && (f==1 || f==5 || f==6 || f==7)) ||
               (q==2 && f==4 && (code>>7&31) && !(code>>2&31));
    }
    void tick(bool consume=false,bool prediction=false,uint32_t predicted_pc=0) {
        const bool event=awaiting_branch && release_edge==queues.time+1;
        const bool recover=event && redirect;
        queues.step(!recover && consume,recover,prediction?predicted_pc:target,hold,prediction && !recover);
        if(event) {hold=false;awaiting_branch=false;force_recovery=false;}
    }
    void before(uint64_t edge) {
        if(edge<=queues.time)throw std::runtime_error("frontend timestamp moved backwards");
        while(queues.time+1<edge) {
            auto limit=edge-1;
            if(awaiting_branch)limit=std::min(limit,release_edge-1);
            if(!queues.skip_idle_until(limit,hold))tick();
        }
    }
    bool static_not_taken = false, compressed = false;
    unsigned imem_latency = 1, buffer_words = 2, bypass = 0;
    FrontendQueues queues;
    bool equivalent(const FrontendState& b) const {
        return force_recovery==b.force_recovery && external_memory==b.external_memory && initialized==b.initialized && hold==b.hold && awaiting_branch==b.awaiting_branch &&
            release_edge==b.release_edge && fallthrough==b.fallthrough && target==b.target &&
            redirect==b.redirect && static_not_taken==b.static_not_taken && compressed==b.compressed &&
            imem_latency==b.imem_latency && buffer_words==b.buffer_words && bypass==b.bypass &&
            queues.equivalent(b.queues);
    }
    uint64_t getPc(uint32_t pc, uint32_t code) {
        if(!initialized) {queues.configure(imem_latency,buffer_words,bypass,pc,compressed);
            if(external_memory)memory_settings.apply(queues.memory);initialized=true;}
        queues.instruction_length((code&3)==3 ? 4 : 2);
        if(awaiting_branch) {
            target=pc;redirect=force_recovery || pc!=fallthrough;
            if(redirect) {before(release_edge);tick();}
        }
        while(!queues.signals().valid)tick();
        if(queues.signals().pc!=pc)throw std::runtime_error("functional/frontend PC mismatch");
        return queues.time+1;
    }
    void setIfConsumed(uint64_t t, uint32_t code,bool prediction=false,uint32_t predicted_pc=0,bool replay=false) {
        before(t);tick(!replay,prediction,predicted_pc);
        if(!static_not_taken && control(code))hold=true;
    }
    void setDeAdvanced(uint64_t t, uint32_t pc, uint32_t code,uint32_t predicted_pc=0,bool predicted=false) {
        if(control(code)) {
            if(t<=queues.time)throw std::runtime_error("invalid DE completion timestamp");
            awaiting_branch=true;release_edge=t;fallthrough=predicted?predicted_pc:uint32_t(pc+((code&3)==3 ? 4 : 2));
        }
    }
    void recover_at(uint64_t edge,uint32_t sequential) {
        if(edge<=queues.time)throw std::runtime_error("invalid WB recovery edge");
        hold=true;awaiting_branch=true;force_recovery=true;release_edge=edge;fallthrough=sequential;
    }
};

class FrontendModel : public ConnectorModel {
    FrontendState local;
    SharedState<FrontendState> state;
    FrontendSharing* sharing = nullptr;
    void configure(FrontendState& s) const {
        s.static_not_taken=static_not_taken;s.compressed=compressed;
        s.imem_latency=imem_latency;s.buffer_words=buffer_words;s.bypass=bypass;
    }
public:
    bool static_not_taken = false, compressed = false;
    unsigned imem_latency = 1, buffer_words = 2, bypass = 0;
    uint64_t *pc_ptr = nullptr, *code_ptr = nullptr, *brTarget_ptr = nullptr;
    explicit FrontendModel(PerformanceModel *p) : ConnectorModel("uqu frontend", p) {}
    void share(FrontendSharing& pool);
    void setPc_p(uint64_t) {}
    void setPc_np(uint64_t) {}
    uint64_t transition(unsigned kind, uint64_t t=0);
    uint64_t getPc() {
        if(sharing)return transition(0);
        if(!local.initialized)configure(local);
        return local.getPc(pc_ptr[getInstrIndex()],code_ptr[getInstrIndex()]);
    }
    void setIfConsumed(uint64_t t) {
        if(sharing)transition(1,t);
        else local.setIfConsumed(t,code_ptr[getInstrIndex()]);
    }
    void setDeAdvanced(uint64_t t) {
        if(sharing)transition(2,t);
        else local.setDeAdvanced(t,pc_ptr[getInstrIndex()],code_ptr[getInstrIndex()]);
    }
    virtual std::array<uint64_t,3> branch_times() const { return {}; }
    virtual void set_branch_times(uint64_t,uint64_t,uint64_t) {}
    const FrontendState& snapshot() const { return sharing ? *state.value : local; }
};

using FrontendSharingBase = TransitionCache<FrontendState>;
class FrontendSharing : public FrontendSharingBase {};

inline void FrontendModel::share(FrontendSharing& pool) {
    sharing=&pool;
    // Initial state is canonical only for identical component parameters.
    state=pool.initial({static_not_taken,compressed,imem_latency,buffer_words,bypass});
}
inline uint64_t FrontendModel::transition(unsigned kind, uint64_t t) {
    const uint32_t pc=pc_ptr[getInstrIndex()], code=code_ptr[getInstrIndex()];
    auto apply=[&](FrontendState& s) -> uint64_t {
        if(!s.initialized)configure(s);
        if(kind==0) return s.getPc(pc,code);
        if(kind==1) s.setIfConsumed(t,code);
        else s.setDeAdvanced(t,pc,code);
        return 0;
    };
    return sharing->apply(state,{kind,pc,code,t},apply);
}

class SerialModel : public ConnectorModel {
public:
    uint64_t serial = 0, committed = 0;
    uint64_t *if_stage_ptr=nullptr,*ex_stage_ptr=nullptr,*wb_stage_ptr=nullptr;
    uint64_t getAdmissionBase() {return std::max({*if_stage_ptr+1,*ex_stage_ptr,serial+1})-1;}
    uint64_t getRequestBase() {return std::max(*ex_stage_ptr+1,*wb_stage_ptr)-1;}
    explicit SerialModel(PerformanceModel *p) : ConnectorModel("uqu serialization", p) {}
    uint64_t getSerial() { return serial; }
    uint64_t getCommitted() { return committed; }
    void setSerial(uint64_t t) { serial = t; }
    void setCommitted(uint64_t t) { committed = std::max(committed, t); }
};
} // namespace uqu
#endif
