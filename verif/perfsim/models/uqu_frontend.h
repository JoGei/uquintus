#ifndef UQU_PERFSIM_FRONTEND_H
#define UQU_PERFSIM_FRONTEND_H
#include <cstdint>
#include <algorithm>
#include <deque>
#include <optional>
#include <stdexcept>
#include "uqu_memory.h"

namespace uqu {
// Timing only: ordered, immediately granted OBI reads. Edges count from the
// end of reset. A grant at edge G returns at edge G+latency. Payloads are PCs,
// not instruction data; functional execution and branch outcomes come from ISA.
class FrontendQueues {
    struct Pending { uint32_t addr; uint64_t due; bool killed; };
    struct Request { uint32_t addr; bool presented, killed; };
    std::deque<Pending> pending;
    std::deque<uint32_t> results, words;
    std::optional<Request> request;
    uint32_t fetch_addr = 0, pc = 0;
    unsigned latency = 1, depth = 2, bypass = 0, instruction_bytes = 4;
    bool compressed = false;
    struct Cycle {
        bool response, live, result_pop, result_ready, consume_live;
        bool word_valid, word_pop, word_push, request_fire, queued_grant, direct_grant, queued_request, direct_request;
        uint32_t word_addr, native_addr;
    };
    Cycle evaluate(bool consume, bool redirect, uint32_t target, bool hold,bool local_clear=false) const {
        // A local prediction clears storage at the edge, but its source
        // instruction may still consume a registered result and release a
        // request credit in that cycle. Global recovery masks those outputs.
        const bool invalidate=redirect || local_clear;
        Cycle c{};
        c.response = !pending.empty() && pending.front().due <= time+1;
        c.live = (bypass&4) && !redirect && results.empty() &&
                 c.response && !pending.front().killed;
        const bool result_valid = !redirect && (!results.empty() || c.live);
        const bool head_valid = !words.empty() || ((bypass&1) && result_valid);
        const bool successor_valid = words.size()>1 ||
                                     ((bypass&1) && !words.empty() && result_valid);
        const bool crossing = compressed && (pc&2) && instruction_bytes==4;
        c.word_valid = !redirect && head_valid && (!crossing || successor_valid);
        const bool drop_word = instruction_bytes==4 || (pc&2);
        c.word_pop = consume && c.word_valid && drop_word && !words.empty();
        c.result_ready = !redirect && (words.size()<depth || c.word_pop);
        c.result_pop = !redirect && !results.empty() && c.result_ready;
        c.consume_live = c.live && c.result_ready;
        c.word_addr = !words.empty() ? words.front() : !results.empty() ? results.front() :
                      c.live ? pending.front().addr : 0;
        const bool consume_word_live = (bypass&1) && words.empty() && consume && c.word_valid && drop_word;
        c.word_push = result_valid && c.result_ready && !consume_word_live;
        const unsigned reserved = pending.size()+results.size();
        const bool room = reserved<2 || c.result_pop;
        const bool replace = invalidate && (bypass&2);
        const bool queued = request && (!invalidate || request->presented);
        c.queued_grant = request && (request->presented || (!invalidate && room));
        const bool native_valid = replace || (!invalidate && !hold && c.result_ready);
        c.native_addr = replace ? target&~3U : fetch_addr;
        c.direct_grant = (!invalidate || replace) && !queued && native_valid && room;
        c.queued_request=c.queued_grant;c.direct_request=c.direct_grant;
        if(!memory.can_grant(time+1)){c.queued_grant=false;c.direct_grant=false;}
        c.request_fire = native_valid && (!invalidate || replace) && (!queued || c.queued_grant);
        return c;
    }
public:
    MemoryPort memory;
    uint64_t time = 0, grants = 0, redirects = 0, discarded = 0;
    bool skip_idle_until(uint64_t edge,bool hold=false) {
        if(edge<=time)return false;
        const auto c=evaluate(false,false,0,hold);
        if(c.response || c.result_pop || c.word_push || c.request_fire ||
           c.queued_grant || c.direct_grant)return false;
        if(c.queued_request || c.direct_request)edge=std::min(edge,memory.next_grant(time+1)-1);
        if(!pending.empty())edge=std::min(edge,pending.front().due-1);
        if(edge<=time)return false;
        time=edge;return true;
    }
    bool equivalent(const FrontendQueues& b) const {
        if(time!=b.time || grants!=b.grants || redirects!=b.redirects || discarded!=b.discarded ||
           fetch_addr!=b.fetch_addr || pc!=b.pc || latency!=b.latency || depth!=b.depth ||
           bypass!=b.bypass || instruction_bytes!=b.instruction_bytes || compressed!=b.compressed ||
           results!=b.results || words!=b.words || pending.size()!=b.pending.size() ||
           bool(request)!=bool(b.request) || !memory.equivalent(b.memory))return false;
        for(unsigned i=0;i<pending.size();++i)
            if(pending[i].addr!=b.pending[i].addr || pending[i].due!=b.pending[i].due ||
               pending[i].killed!=b.pending[i].killed)return false;
        return !request || (request->addr==b.request->addr && request->presented==b.request->presented &&
                            request->killed==b.request->killed);
    }
    struct Signals { bool valid, req; uint32_t pc, addr; };
    void configure(unsigned l, unsigned d, unsigned b, uint32_t boot, bool c=false) {
        if (!l || d<2 || b>7 || boot&3) throw std::runtime_error("invalid frontend configuration");
        latency=l; depth=d; bypass=b; compressed=c; instruction_bytes=4; pc=fetch_addr=boot;
        memory.configure({1},{l});
        time=grants=redirects=discarded=0;pending.clear();results.clear();words.clear();request.reset();
    }
    void instruction_length(unsigned bytes) {
        if ((bytes!=2 && bytes!=4) || (!compressed && bytes!=4))
            throw std::runtime_error("invalid instruction length");
        instruction_bytes=bytes;
    }
    Signals signals(bool consume=false, bool redirect=false, uint32_t target=0, bool hold=false,bool local_clear=false) const {
        const auto c=evaluate(consume,redirect,target,hold,local_clear);
        return {c.word_valid,c.queued_request||c.direct_request,pc,
                c.queued_request ? request->addr : c.native_addr};
    }
    void step(bool consume=false, bool redirect=false, uint32_t target=0, bool hold=false,bool local_clear=false) {
        const bool invalidate=redirect || local_clear;
        const auto c=evaluate(consume,redirect,target,hold,local_clear);
        if (consume && (!c.word_valid || c.word_addr!=(pc&~3U)))
            throw std::runtime_error("frontend consumed a missing/wrong word");
        const auto old_request=request;
        const bool grant=c.queued_grant||c.direct_grant;
        const uint32_t grant_addr=c.queued_grant ? request->addr : c.native_addr;
        const bool grant_killed=c.queued_grant && (request->killed||invalidate);
        const bool push_result=c.response && !pending.front().killed && !invalidate && !c.consume_live;
        const uint32_t response_addr=c.response ? pending.front().addr : 0;
        const uint32_t push_word_addr=!results.empty() ? results.front() : response_addr;
        if (c.response && (pending.front().killed||invalidate)) ++discarded;
        if (c.response) pending.pop_front();
        if (grant) {pending.push_back({grant_addr,memory.accept(grant_addr,false,time+1),grant_killed});++grants;}
        if (invalidate) {results.clear();words.clear();for(auto &p:pending)p.killed=true;
            // A same-cycle direct replacement belongs to the new stream.
            if(c.direct_grant)pending.back().killed=false;
            pc=target;fetch_addr=(target&~3U)+(c.request_fire?4:0);++redirects;
        } else {
            if(c.result_pop)results.pop_front();
            if(push_result)results.push_back(response_addr);
            if(c.word_pop)words.pop_front();
            if(c.word_push)words.push_back(push_word_addr);
            if(c.request_fire)fetch_addr+=4;
            if(consume)pc+=instruction_bytes;
        }
        if(c.queued_grant)request.reset();
        if(invalidate) {
            request=(old_request && old_request->presented && !grant) ? old_request : std::nullopt;
            if(request)request->killed=true;
        }
        const unsigned reserved=pending.size()+results.size();
        if(request && reserved<2)request->presented=true;
        if(c.request_fire) {
            if(c.direct_grant)request.reset();
            else request=Request{c.native_addr,reserved<2,false};
        }
        ++time;
        if(pending.size()>2 || reserved>2 || words.size()>depth)
            throw std::runtime_error("frontend capacity invariant violated");
    }
};
} // namespace uqu
#endif
