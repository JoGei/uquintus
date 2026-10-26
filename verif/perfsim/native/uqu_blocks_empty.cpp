#include "uqu_blocks.h"
const std::vector<BlockDefinition>& block_definitions() {
    static const std::vector<BlockDefinition> empty;
    return empty;
}
BlockFunction block_function(unsigned,unsigned) { throw std::runtime_error("no generated block schedules"); }
