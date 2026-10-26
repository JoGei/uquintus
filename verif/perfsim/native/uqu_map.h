#ifndef UQU_PERFSIM_MAP_H
#define UQU_PERFSIM_MAP_H
#include "registry.h"
class UQU_Channel;
class MapBackend {
public:
    virtual ~MapBackend() = default;
    virtual void execute(unsigned end,uint64_t ordinal,void* context,
                         void (*observe)(void*,unsigned,unsigned,uint64_t,uint32_t)) = 0;
    virtual uint64_t calls() const = 0;
    virtual std::string statistics() const = 0;
};
class MapExtractor {
public:
    virtual ~MapExtractor() = default;
    virtual void consume(unsigned count,bool finished) = 0;
    virtual void save() = 0;
};
std::unique_ptr<MapBackend> make_map_backend(UQU_Channel&,std::vector<ModelInstance>&);
std::unique_ptr<MapExtractor> make_map_extractor(UQU_Channel&,unsigned,unsigned);
#endif
