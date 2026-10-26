#ifndef UQU_PERFSIM_TRACE_MODELS_H
#define UQU_PERFSIM_TRACE_MODELS_H
#include "uqu_models.h"
#include "uqu_bpu_model.h"
#include "uqu_hazard_windows.h"
namespace uqu {
// BPU events run on the shared envelope's reference clock. Training before
// IF becomes valid is visible to lookup; training at the capture edge is not.
struct TimedBpuState : BpuState {
    Prediction prediction;
    uint64_t evaluations=0,hits=0,taken=0;
private:
    bool initialized=false,valid=false,pending_flush=false;
    uint32_t previous_pc=0,previous_code=0,previous_target=0,next_pc=0,expected_pc=0;
    Update pending;
public:
    void prepare(uint32_t pc,uint64_t ready,uint64_t previous_de) {
        if(!initialized){initialize();initialized=true;}
        if(!enabled){prediction={};return;}
        pending={};pending_flush=valid && pc!=expected_pc;
        if(valid)pending={true,FrontendState::control(previous_code),
            (previous_code&3)==3?(previous_code&127)==0x63:((previous_code&3)==1 && (previous_code>>13&7)>=6),
            pc!=next_pc,previous_pc,previous_target};
        if(valid && previous_de<ready){clock(pending,{},pending_flush);pending={};pending_flush=false;}
        prediction=lookup(pc);++evaluations;hits+=prediction.hit;taken+=prediction.taken;
    }
    void accept(uint32_t pc,uint32_t code,uint32_t target) {
        if(!enabled)return;
        clock(pending,{true,pc,code},pending_flush);
        previous_pc=pc;previous_code=code;previous_target=target;next_pc=pc+((code&3)==3?4:2);
        expected_pc=prediction.taken?prediction.target:next_pc;valid=true;
    }
};
// Shared trace-derived service calendar: frontend queues and a reference
// backend-occupancy envelope. No scheduled combination supplies timestamps.
struct TraceFetchState {
    MemorySettings imem,dmem;
    bool memory_profile=false;
    MemoryPort data_memory;
    unsigned request_delay=1,response_delay=1,last_event=0;
    unsigned latency=1, buffer_words=2, bypass=0, dmem_latency=1;
    unsigned mul_cycles=1,div_cycles=1;
    bool static_not_taken=true, compressed=false,forwarding=true,split_mul=false;
    unsigned predictor=0,bp_entries=16,btb_entries=16,idata_hwords=0;
    bool btb=false;
    bool fine_forwarding=false,forward_ex_to_de=true,forward_mem_to_de=true,forward_mem_to_ex=true,forward_wb_to_ex=true,operand_retention=false;
    unsigned admission_delay=0;
    uint64_t hazard_wait_cycles=0;
    BpuState::Prediction prediction;
    uint64_t replayed=0,ex_pressure=0,wb_pressure=0;
    TimedBpuState* shared_bpu=nullptr;
private:
    FrontendState frontend;
    uint64_t consumed=0,decoded=0,ex=0,mem=0,wb=0,serial=0,committed=0,resolution=0;
    std::array<uint64_t,32> operands{};
    bool valid=false,previous_barrier=false;
    uint32_t next_pc=0,expected_pc=0;
    unsigned replay_left=0;
    uint32_t replay_pc=0;
    TimedBpuState bpu;
    HazardWindows hazards;
public:
    unsigned access(uint32_t pc,uint32_t code,unsigned rs1=0,unsigned rs2=0,unsigned rd=0,uint32_t target=0,uint32_t address=0,unsigned event=0) {
        if(!frontend.initialized) {
            if(!memory_profile){imem.responses[0]=latency;dmem.responses[0]=dmem_latency;}
            frontend.static_not_taken=static_not_taken;frontend.compressed=compressed;
            frontend.imem_latency=latency;frontend.buffer_words=buffer_words;frontend.bypass=bypass;
            frontend.external_memory=true;frontend.memory_settings=imem;dmem.apply(data_memory);
            bpu.compressed=compressed;bpu.enabled=btb && predictor!=0;bpu.bimodal=predictor==2;
            bpu.entries=btb_entries;bpu.direction_entries=bp_entries;bpu.hwords=idata_hwords;
        }
        const bool sequential=valid && pc==next_pc;
        const bool correction=valid && (previous_barrier || pc!=expected_pc);
        const bool barrier=event>=1 && event<=4;last_event=event;
        if(correction)replay_left=0;
        // Replay bypasses getPc(), but must still publish the observed branch
        // outcome before a queued DE-resolution event reaches its edge.
        if(frontend.awaiting_branch){frontend.target=pc;frontend.redirect=frontend.force_recovery || pc!=frontend.fallthrough;}
        const bool word=(code&3)==3;
        const unsigned op=code&127,f=code>>13&7;
        const bool load=!event && (word?op==3:((code&3)==0 || (code&3)==2) && f==2);
        const bool store=!event && (word?op==0x23:((code&3)==0 || (code&3)==2) && f==6);
        const bool csr=!event && word && (op==0x73 || op==0xf);
        const bool control=!barrier && FrontendState::control(code);
        const bool muldiv=!event && word && op==0x33 && (code>>25)==1;
        const bool divide=muldiv && (code>>14&1);
        const bool replay=replay_left && pc==replay_pc;
        uint64_t ready;
        const uint32_t transport_code=(event==3 || (!compressed && !word))?0x13:code;
        try {ready=replay?frontend.queues.time+1:frontend.getPc(pc,transport_code);}
        catch(const std::exception& e){throw std::runtime_error(std::string(e.what())+" pc="+std::to_string(pc)+
            " queue="+std::to_string(frontend.queues.signals().pc)+" expected="+std::to_string(expected_pc)+
            " predictor="+std::to_string(predictor)+" hwords="+std::to_string(idata_hwords));}
        auto& predictor_state=shared_bpu?*shared_bpu:bpu;
        predictor_state.prepare(pc,ready,decoded);
        prediction=predictor_state.prediction;
        const auto arrival=std::max(ready,decoded);
        const unsigned recovery=3-unsigned(__builtin_popcount(bypass));
        uint64_t delay;
        if(!valid)delay=latency;
        else if(correction)delay=ready>resolution+recovery?ready-resolution-recovery:1;
        else if(!sequential) {
            const unsigned transport=replay?0:recovery;
            delay=ready>consumed+transport?ready-consumed-transport:1;
        }
        else delay=ready>consumed?ready-consumed:1;
        uint64_t admission;
        admission_delay=0;
        if(fine_forwarding) {
            hazards.forwarding=forwarding;hazards.ex_to_de=forward_ex_to_de;hazards.mem_to_de=forward_mem_to_de;
            hazards.mem_to_ex=forward_mem_to_ex;hazards.wb_to_ex=forward_wb_to_ex;hazards.retention=operand_retention;
            const auto base=std::max({arrival+1,ex,serial+1});
            admission=hazards.admit(rs1,rs2,arrival+1,base,control || csr || event==1);
            if(admission-base>=255)throw std::runtime_error("hazard delay exceeds upstream byte vector");
            admission_delay=unsigned(admission-base);hazard_wait_cycles+=admission_delay;
        } else admission=std::max({arrival+1,operands.at(rs1),operands.at(rs2),serial+1});
        ex_pressure+=ex>admission?ex-admission:0;
        decoded=std::max(admission,ex);
        const auto result=decoded+(event?1:muldiv?(divide?div_cycles:mul_cycles):1);
        ex=std::max(result,mem);
        const auto finish=ex+1;
        wb_pressure+=wb>finish?wb-finish:0;
        mem=std::max(finish,wb);request_delay=response_delay=1;
        if(load || store) {
            const auto grant=data_memory.next_grant(mem);
            if(grant-mem>=254)throw std::runtime_error("data grant wait exceeds upstream byte vector");
            request_delay=unsigned(grant-mem+1);mem=grant;
            const auto due=data_memory.accept(address,store,grant);
            if(due-grant>254)throw std::runtime_error("data response exceeds upstream byte vector");
            response_delay=unsigned(due-grant);
        }
        wb=mem+response_delay;
        committed=std::max(committed,wb);
        if(csr || barrier)serial=wb;resolution=barrier?wb:decoded;
        const uint32_t predicted=prediction.taken?prediction.target:pc+(word?4:2);
        const bool steering=prediction.taken && predicted!=pc+(word?4:2);
        if(replay){replay_left-=word?2:1;replay_pc=pc+(word?4:2);++replayed;}
        if(steering){replay_left=prediction.hwords;replay_pc=predicted;}
        predictor_state.accept(pc,code,target);
        frontend.setIfConsumed(arrival,transport_code,steering,predicted+replay_left*2,replay);
        if(barrier) {frontend.recover_at(wb,pc+(word?4:2));replay_left=0;}
        else frontend.setDeAdvanced(decoded,pc,code,predicted,true);
        if(fine_forwarding && rd)hazards.write(rd,load?HazardWindows::load:csr?HazardWindows::csr:
            muldiv && !divide && split_mul?HazardWindows::split:HazardWindows::arithmetic,
            decoded,result,ex,mem,wb);
        if(rd)operands.at(rd)=load?wb+1:!forwarding?wb+1:csr?wb:
            muldiv && !divide && split_mul?finish:result;
        consumed=arrival;next_pc=pc+(word?4:2);expected_pc=predicted;
        valid=true;previous_barrier=barrier;
        if(delay>255)throw std::runtime_error("trace service exceeds upstream byte delay vector");
        return unsigned(delay);
    }
};
class TraceFetchModel : public ResourceModel, public TraceFetchState {
public:
    uint64_t *pc_ptr=nullptr,*code_ptr=nullptr,*rs1_ptr=nullptr,*rs2_ptr=nullptr,*rd_ptr=nullptr,*brTarget_ptr=nullptr,*memAddr_ptr=nullptr,*event_ptr=nullptr;
    explicit TraceFetchModel(PerformanceModel* model):ResourceModel("trace fetch",model) {}
    int getDelay() override {
        const auto i=getInstrIndex();
        return access(pc_ptr[i],code_ptr[i],rs1_ptr[i],rs2_ptr[i],rd_ptr[i],brTarget_ptr[i],memAddr_ptr[i],event_ptr[i]);
    }
};
class TraceHazardModel : public ResourceModel {
public:
    TraceFetchState* source=nullptr;uint64_t* pc_ptr=nullptr;
    explicit TraceHazardModel(PerformanceModel* model):ResourceModel("trace hazards",model) {}
    // Upstream symbolic delays are positive. AdmissionBase is biased by -1.
    int getDelay() override {return source->admission_delay+1;}
};
class TraceRequestModel : public ResourceModel {
public:
    TraceFetchState* source=nullptr;uint64_t* pc_ptr=nullptr;
    explicit TraceRequestModel(PerformanceModel* m):ResourceModel("data grant",m) {}
    int getDelay() override {return source->request_delay;}
};
class TraceResponseModel : public ResourceModel {
public:
    TraceFetchState* source=nullptr;uint64_t* pc_ptr=nullptr;
    explicit TraceResponseModel(PerformanceModel* m):ResourceModel("data response",m) {}
    int getDelay() override {return source->response_delay;}
};
// Candidate PC timestamps are part of scheduling state. The branch decision is
// derived from the functional successor, following MAP-DSE's PC-mapping step.
class TraceBranchModel : public FrontendModel {
    uint64_t pc_time=0,predicted_time=0,resolved_time=0;
    uint32_t fallthrough=0;
    bool pending=false,wb_event=false;
public:
    unsigned recovery_cycles=0;
    uint64_t* de_stage_ptr=nullptr,*if_stage_ptr=nullptr,*wb_stage_ptr=nullptr;
    TraceFetchState* fetch_ptr=nullptr;
    bool predicted_taken=false,replay=false;
    explicit TraceBranchModel(PerformanceModel* model):FrontendModel(model) {}
    uint64_t getPc() {
        if(pending) {
            resolved_time=std::max(resolved_time,wb_event?*wb_stage_ptr:*de_stage_ptr);
            const bool redirect=wb_event || uint32_t(pc_ptr[getInstrIndex()])!=fallthrough;
            predicted_time=if_stage_ptr?std::max(predicted_time,*if_stage_ptr):predicted_time;
            pc_time=redirect?resolved_time+recovery_cycles:predicted_time+(predicted_taken && !replay?recovery_cycles:0);
            pending=false;
        }
        return pc_time;
    }
    void setPc_p(uint64_t t) {predicted_time=t;}
    void setPc_np(uint64_t t) {
        resolved_time=t;pending=true;wb_event=fetch_ptr && fetch_ptr->last_event>=1 && fetch_ptr->last_event<=4;
        const auto p=fetch_ptr?fetch_ptr->prediction:BpuState::Prediction{};
        const uint32_t sequential=uint32_t(pc_ptr[getInstrIndex()]+((code_ptr[getInstrIndex()]&3)==3?4:2));
        predicted_taken=p.taken && p.target!=sequential;replay=predicted_taken && p.hwords;
        fallthrough=p.taken?p.target:sequential;
    }
    std::array<uint64_t,3> branch_times() const override {return {pc_time,if_stage_ptr?std::max(predicted_time,*if_stage_ptr):predicted_time,pending?std::max(resolved_time,wb_event?*wb_stage_ptr:*de_stage_ptr):resolved_time};}
    void set_branch_times(uint64_t pc,uint64_t predicted,uint64_t resolved) override {
        pc_time=pc;predicted_time=predicted;resolved_time=resolved;
    }
};
}
#endif
