#ifndef UQU_MAP_MODELS_H
#define UQU_MAP_MODELS_H
#include "map_models/Models.h"
#include "uqu_trace_models.h"
#include <sstream>
namespace uqu_map {
class FetchModel final : public map_models::ResourceModel, public uqu::TraceFetchState {
public:
    uint64_t *pc_ptr=nullptr,*code_ptr=nullptr,*rs1_ptr=nullptr,*rs2_ptr=nullptr,*rd_ptr=nullptr,*brTarget_ptr=nullptr,*memAddr_ptr=nullptr,*event_ptr=nullptr;
    uint64_t evaluations=0;
protected:
    void updateDelay() override {
        const auto i=getInstrIdx();
        const auto delay=access(pc_ptr[i],code_ptr[i],rs1_ptr[i],rs2_ptr[i],rd_ptr[i],brTarget_ptr[i],memAddr_ptr[i],event_ptr[i]);
        if(delay>255)throw std::runtime_error("MAP-DSE delay exceeds upstream byte vector");
        delayBuffer=delay;++evaluations;
    }
};
class HazardModel final : public map_models::ResourceModel {
public:
    uqu::TraceFetchState* source=nullptr;
    uint64_t evaluations=0;
protected:
    void updateDelay() override {
        if(!source || source->admission_delay>=255)throw std::runtime_error("invalid MAP-DSE hazard delay");
        delayBuffer=source->admission_delay+1;++evaluations;
    }
};
template<bool Request> class DataModel final : public map_models::ResourceModel {
public:
    uqu::TraceFetchState* source=nullptr;
    uint64_t evaluations=0;
protected:
    void updateDelay() override {
        const auto delay=Request?source->request_delay:source->response_delay;
        if(!delay || delay>255)throw std::runtime_error("invalid data-memory delay");
        delayBuffer=delay;++evaluations;
    }
};
using RequestModel=DataModel<true>;
using ResponseModel=DataModel<false>;
class BranchModel final : public map_models::BranchModel {
    uint32_t fallthrough=0;
    bool redirect=false,predicted_taken=false,replay=false,wb_event=false;
public:
    unsigned recovery_cycles=0;
    uqu::TraceFetchState* fetch_ptr=nullptr;
    uint64_t *pc_ptr=nullptr,*code_ptr=nullptr;
    uint64_t catches=0,evaluations=0;
    void catchBranch() override {
        const auto i=getInstrIdx();
        wb_event=fetch_ptr && fetch_ptr->last_event>=1 && fetch_ptr->last_event<=4;
        const auto p=fetch_ptr?fetch_ptr->prediction:uqu::BpuState::Prediction{};
        const uint32_t sequential=uint32_t(pc_ptr[i]+((code_ptr[i]&3)==3?4:2));
        predicted_taken=p.taken && p.target!=sequential;replay=predicted_taken && p.hwords;
        fallthrough=p.taken?p.target:sequential;++catches;
    }
    void evaluate() override {redirect=wb_event || uint32_t(pc_ptr[getInstrIdx()])!=fallthrough;++evaluations;}
    void shiftVector(uint64_t* vec) const override {
        // Input PC, predicted PC and resolved PC slots in the uqu matrix layout.
        vec[72]=redirect?vec[74]+recovery_cycles:vec[73]+(predicted_taken && !replay?recovery_cycles:0);
    }
};
}
#endif
