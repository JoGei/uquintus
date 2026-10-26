#ifndef UQU_PERFSIM_REGISTRY_H
#define UQU_PERFSIM_REGISTRY_H
#include "PerformanceModel.h"
#include "uqu_blocks.h"
#include "uqu_arch.h"
#include <memory>
#include <vector>
#include <string>
#include <fstream>
struct ModelInstance {
    std::string id;
    std::unique_ptr<PerformanceModel> model;
    TimingView (*view)(PerformanceModel&)=nullptr;
    std::unique_ptr<PerformanceModel> reference;
    unsigned block_group=0;
    bool started=false,stopped=false;
    uint64_t start_cycle=0,start_count=0,stop_cycle=0,stop_count=0;
    std::unique_ptr<std::ofstream> trace;
};
std::vector<ModelInstance> make_models(bool reference=false);
bool supported_type(uint64_t);
unsigned operand_mask(uint64_t);
uqu::Architecture architectural_configuration();
unsigned event_type(unsigned);
#endif
