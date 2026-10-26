#ifndef UQU_PERFSIM_MEMORY_H
#define UQU_PERFSIM_MEMORY_H
#include <algorithm>
#include <array>
#include <cstdint>
#include <stdexcept>
#include <vector>
namespace uqu {
// External timing stub: independent ports; periodic grant availability;
// address-indexed response delays; optional blocking direct-mapped tag cache.
// Stores are write-through/no-write-allocate. Tags never hold architectural data.
class MemoryPort {
    std::vector<unsigned> grants_{1},responses_{1};
    std::array<uint64_t,256> tags_{};
    std::array<bool,256> valid_{};
    unsigned lines_=0,line_bytes_=16,hit_=1,miss_=1;
    uint64_t busy_until_=0,last_due_=0;
public:
    uint64_t requests=0,hits=0,misses=0,grant_wait=0;
    void configure(std::vector<unsigned> grants,std::vector<unsigned> responses,unsigned lines=0,
                   unsigned line_bytes=16,unsigned hit=1,unsigned miss=1) {
        if(grants.empty() || grants.size()>64 || std::none_of(grants.begin(),grants.end(),[](unsigned x){return x==1;}) ||
           std::any_of(grants.begin(),grants.end(),[](unsigned x){return x>1;}) || responses.empty() || responses.size()>64 ||
           std::any_of(responses.begin(),responses.end(),[](unsigned x){return x<1;}) ||
           lines>256 || (lines && (lines&(lines-1))) || line_bytes<4 || line_bytes>64 || (line_bytes&(line_bytes-1)) ||
           !hit || miss<hit || miss>254)throw std::runtime_error("invalid external memory configuration");
        grants_=std::move(grants);responses_=std::move(responses);lines_=lines;line_bytes_=line_bytes;hit_=hit;miss_=miss;
        tags_.fill(0);valid_.fill(false);busy_until_=last_due_=requests=hits=misses=grant_wait=0;
    }
    bool can_grant(uint64_t edge) const {return edge && edge>=busy_until_ && grants_[(edge-1)%grants_.size()];}
    uint64_t next_grant(uint64_t edge) const {
        edge=std::max({edge,busy_until_,uint64_t(1)});
        for(unsigned n=0;n<grants_.size();++n)if(can_grant(edge+n))return edge+n;
        throw std::runtime_error("memory has no future grant");
    }
    uint64_t accept(uint32_t address,bool write,uint64_t edge) {
        if(!can_grant(edge))throw std::runtime_error("memory request accepted without grant");
        ++requests;unsigned delay=responses_[(address>>2)%responses_.size()];
        if(lines_) {
            const uint64_t tag=address/line_bytes_;const unsigned index=tag%lines_;
            const bool hit=valid_[index] && tags_[index]==tag;
            hit?++hits:++misses;delay=hit?hit_:miss_;
            // The port blocks through a miss, so an installed tag cannot be
            // observed before that fill completes. No MSHRs/bursts/coherence.
            if(!hit){busy_until_=edge+delay;if(!write){tags_[index]=tag;valid_[index]=true;}}
        }
        const auto due=std::max(edge+delay,last_due_+1);last_due_=due;return due;
    }
    bool equivalent(const MemoryPort& b) const {
        return grants_==b.grants_ && responses_==b.responses_ && tags_==b.tags_ && valid_==b.valid_ &&
               lines_==b.lines_ && line_bytes_==b.line_bytes_ && hit_==b.hit_ && miss_==b.miss_ &&
               busy_until_==b.busy_until_ && last_due_==b.last_due_ && requests==b.requests && hits==b.hits && misses==b.misses;
    }
};
struct MemorySettings {
    unsigned grant_length=1,response_length=1,grants[64]={1},responses[64]={1};
    unsigned lines=0,line_bytes=16,hit_cycles=1,miss_cycles=1;
    void apply(MemoryPort& port) const {
        if(!grant_length || grant_length>64 || !response_length || response_length>64)
            throw std::runtime_error("invalid memory parameter length");
        port.configure({grants,grants+grant_length},{responses,responses+response_length},lines,line_bytes,hit_cycles,miss_cycles);
    }
};
}
#endif
