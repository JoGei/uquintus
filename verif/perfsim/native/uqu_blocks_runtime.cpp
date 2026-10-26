#include "uqu_blocks.h"
uint64_t uqu_block_get_pc(uqu::FrontendModel& frontend) {return frontend.getPc();}
void uqu_block_if_consumed(uqu::FrontendModel& frontend,uint64_t t) {frontend.setIfConsumed(t);}
void uqu_block_de_advanced(uqu::FrontendModel& frontend,uint64_t t) {frontend.setDeAdvanced(t);}
