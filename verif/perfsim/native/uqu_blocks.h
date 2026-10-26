#ifndef UQU_PERFSIM_BLOCKS_H
#define UQU_PERFSIM_BLOCKS_H
#include "uqu_models.h"
#include <vector>
#include <array>

struct TimingView {
    PerformanceModel& model;
    std::array<uint64_t*,5> stages;
    uint64_t& entrance;
    uqu::RegisterModel& registers;
    uqu::SerialModel& serial;
    uqu::FrontendModel& frontend;
    void* context=nullptr;
    void (*observe)(void*,unsigned,uint64_t,uint32_t)=nullptr;
};
struct ProfileInstruction { uint64_t pc,code,type,rs1,rs2,rd; };
struct BlockDefinition { unsigned id,size; const ProfileInstruction* instructions; };
using BlockFunction = void (*)(TimingView&,unsigned,uint64_t);
const std::vector<BlockDefinition>& block_definitions();
BlockFunction block_function(unsigned group,unsigned block);
// Defined in one translation unit so queue/cache code is not expanded into
// every specialized block. The ordered feedback contract remains unchanged.
uint64_t uqu_block_get_pc(uqu::FrontendModel&);
void uqu_block_if_consumed(uqu::FrontendModel&,uint64_t);
void uqu_block_de_advanced(uqu::FrontendModel&,uint64_t);
#endif
