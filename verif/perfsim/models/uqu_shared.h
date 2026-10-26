#ifndef UQU_PERFSIM_SHARED_H
#define UQU_PERFSIM_SHARED_H
#include <array>
#include <algorithm>
#include <map>
#include <memory>
#include <cstdint>

namespace uqu {
class FrontendSharing;

template<class State> struct SharedState {
    uint64_t id=0;
    std::shared_ptr<State> value;
    bool detached=false;
};

// A state ID denotes an exact callback history, not merely equal parameters.
// Cache entries live for one instruction, across all timing models. They never
// cross functional runs. Copy-on-write preserves peers that have not advanced.
template<class State> class TransitionCache {
    struct Result { SharedState<State> state; uint64_t result; };
    std::map<std::array<uint64_t,5>,SharedState<State>> roots;
    std::map<std::array<uint64_t,5>,Result> transitions;
    uint64_t next_id=1;
public:
    uint64_t calls=0, evaluations=0, hits=0, private_evaluations=0, peak_entries=0;
    SharedState<State> initial(std::array<uint64_t,5> config) {
        auto [it,inserted]=roots.try_emplace(config);
        if(inserted) {it->second.id=next_id++;it->second.value=std::make_shared<State>();}
        return it->second;
    }
    void beginInstruction() { transitions.clear(); roots.clear(); }
    template<class Apply>
    uint64_t apply(SharedState<State>& state, std::array<uint64_t,4> args, Apply fn) {
        ++calls;
        if(state.detached) {
            ++evaluations;++private_evaluations;
            return fn(*state.value);
        }
        const std::array<uint64_t,5> key={state.id,args[0],args[1],args[2],args[3]};
        if(auto it=transitions.find(key);it!=transitions.end()) {
            ++hits;state=it->second.state;return it->second.result;
        }
        // Check cached outgoing transitions before detaching: the last peer
        // still owns a unique old state after another peer has already moved.
        // Only a unique state with no matching outgoing transition is private.
        if(state.value.unique()) {
            state.detached=true;++evaluations;++private_evaluations;
            return fn(*state.value);
        }
        ++evaluations;
        // The old identity may still be referenced by another timing variant.
        if(!state.value.unique()) state.value=std::make_shared<State>(*state.value);
        const auto result=fn(*state.value);
        state.id=next_id++;
        transitions.emplace(key,Result{state,result});
        peak_entries=std::max<uint64_t>(peak_entries,transitions.size());
        return result;
    }
};
} // namespace uqu
#endif
