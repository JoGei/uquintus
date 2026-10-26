// Native ETISS execution with generated CorePerfDSL schedules. No Python is
// called during execution; multiple timing states consume one functional trace.
#include "etiss/ETISS.h"
#include "etiss/CPUCore.h"
#include "etiss/Plugin.h"
#include "etiss/jit/ReturnCode.h"
#include "jit/Arch/RV32IMACFD/RV32IMACFD.h"
#include "TracerPlugin.h"
#include "UQU_Channel.h"
#include "UQU_Monitor.h"
#include "registry.h"
#include "uqu_map.h"
#include <array>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <unordered_map>
#include <vector>
#include <cstdlib>
#include <map>
#include <algorithm>

static void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}
static uint32_t read32(std::istream &in) {
    uint32_t v = 0;
    for (unsigned i=0; i<4; ++i) { int c=in.get(); require(c!=EOF,"truncated image"); v|=uint32_t(uint8_t(c))<<(8*i); }
    return v;
}
static void write32(std::ostream &out, uint32_t v) {
    for (unsigned i=0; i<4; ++i) out.put(char(v>>(8*i)));
}
struct Memory {
    std::unordered_map<uint32_t, std::array<uint8_t,4096>> pages;
    std::vector<std::pair<uint64_t,uint64_t>> executable;
    UQU_Channel *channel = nullptr;
    uqu::Architecture architecture;
    uint64_t* processed=nullptr;
    uint64_t faults=0;
    uint32_t start=0,stop=0;
    std::string error;
    std::vector<std::array<uint32_t,3>> expected,observed;
    uint32_t tohost = 0;
    bool done = false, bad = false;
    uint64_t stop_index = 0, exit_code = 0;
    uint8_t byte(uint32_t a) const { auto p=pages.find(a>>12); return p==pages.end()?0:p->second[a&4095]; }
    void load(const char *path) {
        std::ifstream f(path,std::ios::binary); char magic[8]{}; f.read(magic,8);
        require(std::string(magic,8)=="UQUMEM01","bad image magic");
        uint32_t n=read32(f); require(n<=4096,"too many segments"); uint64_t total=0;
        while(n--) {
            uint32_t a=read32(f), size=read32(f), mem=read32(f); total+=mem;
            require(size<=mem && uint64_t(a)+mem<=(1ull<<32) && total<=16*1024*1024,"bad image bounds");
            for(uint32_t i=0;i<size;++i) { int c=f.get(); require(c!=EOF,"truncated image data");pages[(a+i)>>12][(a+i)&4095]=uint8_t(c); }
        }
        require(f.peek()==EOF,"trailing image data");
    }
    void save() const {
        std::ofstream f("final-memory.bin",std::ios::binary);f.write("UQUMEM01",8);write32(f,pages.size());
        for(const auto &p:pages) {write32(f,p.first<<12);write32(f,4096);write32(f,4096);f.write(reinterpret_cast<const char*>(p.second.data()),4096);}
        require(bool(f),"cannot save memory");
    }
    static int32_t read(void *handle, ETISS_CPU *cpu, uint64_t a, uint8_t *b, uint32_t n) {
        auto &m=*static_cast<Memory*>(handle);
        if(cpu && m.channel && m.channel->instrCnt)m.channel->memAddr[m.channel->instrCnt-1]=uint32_t(a);
        if(cpu && ((n!=1 && n!=2 && n!=4) || a&(n-1))) {
            m.bad=true;return etiss::RETURNCODE::CPUFINISHED;
        }
        if(a+n>(1ull<<32)) return etiss::RETURNCODE::DBUS_READ_ERROR;
        for(uint32_t i=0;i<n;++i)b[i]=m.byte(uint32_t(a+i));
        return etiss::RETURNCODE::NOERROR;
    }
    static int32_t write(void *handle, ETISS_CPU* cpu, uint64_t a, uint8_t *b, uint32_t n) {
        auto &m=*static_cast<Memory*>(handle);
        if(cpu && m.channel && m.channel->instrCnt)m.channel->memAddr[m.channel->instrCnt-1]=uint32_t(a);
        if(m.done) return etiss::RETURNCODE::CPUFINISHED;
        if((n!=1 && n!=2 && n!=4) || a&(n-1)) {
            m.bad=true;return etiss::RETURNCODE::CPUFINISHED;
        }
        if(a+n>(1ull<<32)) return etiss::RETURNCODE::DBUS_WRITE_ERROR;
        for(const auto &r:m.executable) if(a<r.second && a+n>r.first) {
            m.bad=true;return etiss::RETURNCODE::CPUFINISHED;
        }
        for(uint32_t i=0;i<n;++i)m.pages[uint32_t(a+i)>>12][uint32_t(a+i)&4095]=b[i];
        bool nonzero=false;for(uint32_t i=0;i<n;++i)nonzero|=b[i]!=0;
        if(a<uint64_t(m.tohost)+8 && a+n>m.tohost && nonzero) {
            if(a!=m.tohost || n!=4 || !(b[0]&1)) {m.bad=true;return etiss::RETURNCODE::CPUFINISHED;}
            uint32_t v=0;for(unsigned i=0;i<4;++i)v|=uint32_t(b[i])<<(8*i);
            m.exit_code=v>>1;m.done=true;
            require(m.channel->instrCnt>0 && m.channel->instrCnt<=100,"invalid completion trace slot");
            m.stop_index=m.channel->instrCnt-1;
        }
        return etiss::RETURNCODE::NOERROR;
    }
    static int32_t debug_read(void *h,uint64_t a,uint8_t *b,uint32_t n) {return read(h,nullptr,a,b,n);}
    static int32_t debug_write(void*,uint64_t,uint8_t*,uint32_t) {return etiss::RETURNCODE::DBUS_WRITE_ERROR;}
    static int32_t iread(void*,ETISS_CPU*,uint64_t,uint32_t) {return etiss::RETURNCODE::NOERROR;}
    static void sync(void*,ETISS_CPU*) {}
};

static Memory* active_memory=nullptr;
extern "C" {int uqu_arch_guard=0;}
static int32_t sext(uint32_t v,unsigned bits){return int32_t(v<<(32-bits))>>(32-bits);}
extern "C" int uqu_before_instruction(void* raw) {
    auto& m=*active_memory;auto& c=*m.channel;auto& a=m.architecture;
    auto& state=*static_cast<RV32IMACFD*>(raw);const unsigned i=c.instrCnt-1;
    if(!supported_type(c.typeId[i])) {
        // ETISS's default decoder supplies no static address/encoding. Read
        // the architectural fault site before any fallback semantics execute.
        const uint32_t address=uint32_t(state.cpu.instructionPointer);
        uint32_t encoding=0;for(unsigned n=0;n<4;++n)encoding|=uint32_t(m.byte(address+n))<<(n*8);
        c.pc[i]=address;c.code[i]=(encoding&3)==3?encoding:encoding&0xffff;
    }
    const uint32_t pc=c.pc[i],code=c.code[i],op=code&127,funct=code>>12&7;
    const bool word=(code&3)==3;
    if(std::getenv("UQU_PERFSIM_ARCH_DEBUG"))std::cerr<<"ARCH pc="<<std::hex<<pc<<" code="<<code<<" privilege="<<a.privilege<<" mepc="<<a.csr[0x341]<<" x5="<<*state.X[5]<<std::dec<<" count="<<c.instrCnt<<"\n";
    auto fault=[&](unsigned stage,uint32_t cause,uint32_t value)->int {
        const std::array<uint32_t,3> row{pc,cause,value};
        if(m.observed.size()>=m.expected.size() || m.expected[m.observed.size()]!=row) {
            m.bad=true;m.error="unexpected trap pc="+std::to_string(pc)+" cause="+std::to_string(cause)+" tval="+std::to_string(value);
        }
        m.observed.push_back(row);++m.faults;c.event[i]=stage;c.typeId[i]=event_type(stage);c.rd[i]=0;
        if(cause!=0 && stage!=2)c.rs1[i]=c.rs2[i]=0;
        if(stage==3)c.code[i]=0; // instruction bits were not supplied by the bus
        state.cpu.instructionPointer=a.trap(pc,cause,value);state.PRIV=a.privilege;state.MSTATUS=a.csr[0x300];
        return 1;
    };
    try {
        if(!a.permitted(pc&~3u,4,4))return fault(3,1,pc);
        if(!word && !a.compressed)return fault(1,2,code);
        if(word && (pc&2) && !a.permitted((pc&~3u)+4,4,4))return fault(3,1,pc+2);
        const auto used=operand_mask(c.typeId[i]);
        if(a.embedded && (((used&1) && c.rs1[i]>=16) || ((used&2) && c.rs2[i]>=16) || ((used&4) && c.rd[i]>=16)))return fault(1,2,code);
        if(!supported_type(c.typeId[i]) || (!a.multiply && word && (code&0xfe00007f)==0x02000033))return fault(1,2,code);
        // Decode the original memory encoding only to check its architectural
        // access. Arithmetic/data semantics still execute in the CoreDSL JIT.
        bool load=false,store=false;unsigned bytes=0;uint32_t address=0;
        if(word && (op==3 || op==0x23)) {
            load=op==3;store=!load;bytes=1u<<(funct&3);
            const uint32_t imm=load?code>>20:((code>>25)<<5)|((code>>7)&31);
            address=*state.X[code>>15&31]+sext(imm,12);
        } else if(!word) {
            const unsigned q=code&3,f=code>>13;
            if(q==0 && (f==2 || f==6)) {
                load=f==2;store=!load;bytes=4;
                address=*state.X[8+(code>>7&7)]+((code>>10&7)<<3)+((code>>6&1)<<2)+((code>>5&1)<<6);
            } else if(q==2 && (f==2 || f==6)) {
                load=f==2;store=!load;bytes=4;
                const uint32_t imm=load?((code>>12&1)<<5)|((code>>4&7)<<2)|((code>>2&3)<<6):((code>>9&15)<<2)|((code>>7&3)<<6);
                address=*state.X[2]+imm;
            }
        }
        if(load || store) {
            c.memAddr[i]=address;
            if(bytes>4)return fault(1,2,code);
            if(address&(bytes-1))return fault(2,load?4:6,address);
            if(!a.permitted(address,bytes,load?1:2,true))return fault(2,load?5:7,address);
        }
        if(word && (op==0x6f || op==0x67 || op==0x63)) {
            bool taken=true;uint32_t target=0;
            if(op==0x6f)target=pc+sext(((code>>31)<<20)|((code>>12&255)<<12)|((code>>20&1)<<11)|((code>>21&1023)<<1),21);
            else if(op==0x67)target=(*state.X[code>>15&31]+sext(code>>20,12))&~1u;
            else {
                const uint32_t x=*state.X[code>>15&31],y=*state.X[code>>20&31];
                taken=funct==0?x==y:funct==1?x!=y:funct==4?int32_t(x)<int32_t(y):funct==5?int32_t(x)>=int32_t(y):funct==6?x<y:funct==7?x>=y:false;
                target=pc+sext(((code>>31)<<12)|((code>>7&1)<<11)|((code>>25&63)<<5)|((code>>8&15)<<1),13);
            }
            if(taken && (target&(a.compressed?1:3)))return fault(1,0,target);
        }
        if(word && op==0x73) {
            if(funct) {
                const unsigned csr=code>>20;
                if((csr==0xb00 || csr==0xb80 || csr==0xc00 || csr==0xc80) &&
                   ((funct&3)!=1 || (code>>7&31)) && !(a.csr[0x320]&1) && pc!=m.start && pc!=m.stop)
                    throw std::runtime_error("timing-dependent cycle read outside measurement markers");
                const uint64_t previous=*m.processed+i;
                a.advance(previous,previous-m.faults);
                const auto old_inhibit=a.csr[0x320];
                auto result=a.access(code,*state.X[code>>15&31]);
                if(result.illegal)return fault(1,2,code);
                // A CSR write itself retires under the old inhibit state;
                // explicit counter writes suppress that counter's increment.
                if(result.write && csr==0x320) {
                    a.cycle+=!(old_inhibit&1);a.retired+=!(old_inhibit&4);
                    ++a.last_cycle;++a.last_retired;
                }
                if(result.write && (csr==0xb00 || csr==0xb80))++a.last_cycle;
                if(result.write && (csr==0xb02 || csr==0xb82))++a.last_retired;
                if(result.read && c.rd[i])*state.X[c.rd[i]]=result.value;
                state.MSTATUS=a.csr[0x300];state.MIE=a.csr[0x304];state.MIP=0;
                for(unsigned address:{0x305u,0x340u,0x341u,0x342u,0x343u})*state.CSR[address]=a.csr[address];
                state.cpu.instructionPointer=pc+4;return 1;
            }
            if(code==0x00000073)return fault(1,a.privilege==3?11:8,0);
            if(code==0x00100073)return fault(1,3,0);
            if(code==0x30200073) {
                if(a.privilege!=3)return fault(1,2,code);
                c.event[i]=4;c.typeId[i]=event_type(4);c.rs1[i]=c.rs2[i]=c.rd[i]=0;
                state.cpu.instructionPointer=a.mret();state.PRIV=a.privilege;state.MSTATUS=a.csr[0x300];return 1;
            }
            if(code==0x10500073) {
                if(a.privilege!=3 && (a.csr[0x300]&(1<<21)))return fault(1,2,code);
                // WFI is a nop when no interrupt arrives; no asynchronous event
                // source is enabled in this deterministic execution profile.
                c.typeId[i]=event_type(6);c.event[i]=6;state.cpu.instructionPointer=pc+4;return 1;
            }
            return fault(1,2,code);
        }
        if(!word && code==0x9002)return fault(1,3,0);
        return 0;
    } catch(const std::exception& e){m.bad=true;m.error=e.what();return 1;}
}

static bool option(const char* name) {
    const char* value=std::getenv(name);
    if(!value)return false;
    require(std::string(value)=="0" || std::string(value)=="1",std::string("expected 0/1 for ")+name);
    return std::string(value)=="1";
}

class UquPlugin : public etiss::plugin::TracerPlugin::TracerPlugin {
    using Code=std::array<uint64_t,6>;
    std::map<std::vector<Code>,unsigned> profile_blocks;
    std::unordered_map<uint32_t,std::vector<const BlockDefinition*>> dictionary;
    Code code(unsigned i) const {
        // The generated channel leaves unused operand fields untouched. They
        // are not part of instruction identity or a block's static operands.
        const auto mask=operand_mask(channel.typeId[i]);
        return {channel.pc[i],channel.code[i],channel.typeId[i],
                mask&1 ? channel.rs1[i]:0,mask&2 ? channel.rs2[i]:0,mask&4 ? channel.rd[i]:0};
    }
    void observe(ModelInstance& m,unsigned i,uint64_t ordinal,uint32_t pc,bool reference_advanced=false) {
        if(m.reference) {
            if(!reference_advanced) {m.reference->instrIndex=i;
                m.reference->callSchedulingFunction(channel.typeId[i]);m.reference->update();}
            auto a=m.view(*m.model),b=m.view(*m.reference);
            bool same=a.entrance==b.entrance && a.registers.available==b.registers.available &&
                a.registers.admission==b.registers.admission && a.serial.serial==b.serial.serial &&
                a.serial.committed==b.serial.committed;
            for(unsigned stage=0;stage<5;++stage)same=same && *a.stages[stage]==*b.stages[stage];
            const auto& fa=a.frontend.snapshot();const auto& fb=b.frontend.snapshot();
            same=same && fa.equivalent(fb) && a.frontend.branch_times()==b.frontend.branch_times();
            require(same,"instruction/block equivalence failed at instruction "+std::to_string(ordinal)+
                " PC "+std::to_string(pc)+" model "+m.id);
        }
        if(m.trace)*m.trace<<ordinal<<','<<pc<<','<<m.model->getPipelineStream();
        const uint64_t cycle=m.model->getCycleCount();
        if(pc==start_pc && start_pc) {require(!m.started&&!m.stopped,"repeated start marker");m.started=true;m.start_cycle=cycle;m.start_count=ordinal-fault_prefix[i];}
        if(pc==stop_pc && stop_pc) {require(m.started&&!m.stopped,"invalid stop marker");m.stopped=true;m.stop_cycle=cycle;m.stop_count=ordinal-fault_prefix[i];}
    }
    static void map_observer(void* context,unsigned combination,unsigned i,uint64_t ordinal,uint32_t pc) {
        auto& p=*static_cast<UquPlugin*>(context);
        p.observe(p.models[combination],i,ordinal,pc,true);
    }
    struct Observation { UquPlugin* plugin; ModelInstance* model; };
    static void observer(void* context,unsigned i,uint64_t ordinal,uint32_t pc) {
        auto& o=*static_cast<Observation*>(context);o.plugin->observe(*o.model,i,ordinal,pc);
    }
    unsigned profile_length(unsigned first,unsigned end) const {
        unsigned size=0;
        do {
            unsigned i=first+size++;
            if(uqu::FrontendState::control(channel.code[i]) || channel.pc[i]==start_pc || channel.pc[i]==stop_pc)break;
        }while(size<16 && first+size<end);
        return size;
    }
    void processTrace() override {
        require(channel.instrCnt<=100,"ETISS exceeded generated channel capacity");
        const unsigned end=memory.done ? memory.stop_index+1 : channel.instrCnt;
        for(unsigned i=0;i<end;++i) {
            traced_faults+=channel.event[i]>=1 && channel.event[i]<=3;fault_prefix[i]=traced_faults;
            uint32_t pc=channel.pc[i], code=channel.code[i];
            require(supported_type(channel.typeId[i]),"instruction outside modeled ISA profile at "+std::to_string(pc));
            require(channel.event[i] || isa_c || (code&3)==3,"compressed instruction on a non-C configuration");
            require(channel.event[i] || isa_m || (code&0xfe00007f)!=0x02000033,"M instruction on an RV32I configuration");

        }
        require(instructions+end<=limit,"instruction watchdog expired");
        for(auto &m:models)m.model->newTraceBlock();
        if(map_extractor && profiling)map_extractor->consume(end,memory.done);
        if(map_mode) {
            map_backend->execute(end,instructions,this,map_observer);
            for(unsigned i=0;i<end;++i)if(trace)trace<<instructions+i+1<<','<<channel.pc[i]<<','<<channel.code[i]<<'\n';
            instructions+=end;
            if(memory.done)finished=true;
            return;
        }
        unsigned profile_next=0;
        for(unsigned i=0;i<end;) {
            const BlockDefinition* block=nullptr;
            if(block_mode) {
                auto found=dictionary.find(channel.pc[i]);
                if(found!=dictionary.end()) for(auto candidate:found->second) {
                    if(candidate->size>end-i)continue;
                    bool match=true;
                    for(unsigned j=0;j<candidate->size;++j) {
                        const auto& c=candidate->instructions[j];
                        if(code(i+j)!=Code{c.pc,c.code,c.type,c.rs1,c.rs2,c.rd}) {match=false;break;}
                    }
                    if(match) {block=candidate;break;}
                }
            }
            const unsigned size=block ? block->size : 1;
            if(profiling && !map_extractor && i==profile_next) {
                const unsigned length=profile_length(i,end);profile_next+=length;
                std::vector<Code> seq;for(unsigned j=0;j<length;++j)seq.push_back(code(i+j));
                profile_blocks.emplace(std::move(seq),0);
                require(profile_blocks.size()<=20000,"block extraction exceeds 20000 distinct blocks");
            }
            sharing.beginInstruction();
            for(auto& m:models) {
                if(block) {
                    auto view=m.view(*m.model);Observation observation{this,&m};
                    if(m.reference || m.trace) {view.observe=observer;view.context=&observation;}
                    block_function(m.block_group,block->id)(view,i,instructions);
                    if(!view.observe)observe(m,i+size-1,instructions+size,channel.pc[i+size-1]);
                    ++block_calls;
                } else {
                    m.model->instrIndex=i;
                    m.model->callSchedulingFunction(channel.typeId[i]);m.model->update();
                    observe(m,i,instructions+1,channel.pc[i]);
                    ++instruction_calls;
                }
            }
            for(unsigned j=0;j<size;++j)if(trace)trace<<instructions+j+1<<','<<channel.pc[i+j]<<','<<channel.code[i+j]<<'\n';
            instructions+=size;i+=size;
        }
        if(memory.done)finished=true;
    }
    void finalizeTrace() override {if(!finished)processTrace();}
public:
    UQU_Channel channel;
    std::vector<ModelInstance> models;
    uqu::FrontendSharing sharing;
    bool share_models=option("UQU_PERFSIM_SHARING"),verify=option("UQU_PERFSIM_VERIFY"),
         profiling=option("UQU_PERFSIM_PROFILE"),block_mode=false,map_mode=false;
    std::unique_ptr<MapBackend> map_backend;
    std::unique_ptr<MapExtractor> map_extractor;
    uint64_t block_calls=0,instruction_calls=0,traced_faults=0;
    std::array<uint64_t,100> fault_prefix{};
    Memory &memory;
    uint64_t instructions=0,limit;
    uint32_t start_pc,stop_pc;
    bool isa_m,isa_c,finished=false;
    std::ofstream trace;
    UQU_Monitor* instruction_monitor=nullptr;
    UquPlugin(Memory &mem,uint64_t max_instr,uint32_t start,uint32_t stop,bool m,bool c,unsigned trace_flags)
      : memory(mem),limit(max_instr),start_pc(start),stop_pc(stop),isa_m(m),isa_c(c) {
        const char* mode=std::getenv("UQU_PERFSIM_SCHEDULER");
        const std::string scheduler=mode ? mode : "instruction";
        require(scheduler=="instruction" || scheduler=="block" || scheduler=="map_explorer","unknown scheduling backend");
        block_mode=scheduler=="block";map_mode=scheduler=="map_explorer";
        if(map_mode)share_models=true;
        require(!block_mode || !block_definitions().empty(),"block scheduler requires generated block kernels");
        require(!profiling || (!block_mode && !map_mode),"extract blocks with the instruction scheduler");
        models=make_models(verify);
        for(const auto& block:block_definitions())dictionary[block.instructions[0].pc].push_back(&block);
        for(auto& row:dictionary)std::sort(row.second.begin(),row.second.end(),[](auto a,auto b){return a->size>b->size;});
        auto monitor=new UQU_Monitor();instruction_monitor=monitor;monitor->connectChannel(&channel);addMonitor(monitor);
        for(auto &entry:models) {
            entry.model->connectChannel(&channel);
            if(entry.reference)entry.reference->connectChannel(&channel);
            if(share_models && !map_mode)entry.view(*entry.model).frontend.share(sharing);
        }
        if(map_mode) {map_backend=make_map_backend(channel,models);require(bool(map_backend),"MAPExplorer requires generated matrices");}
        if(profiling)map_extractor=make_map_extractor(channel,start,stop);
        memory.channel=&channel;memory.processed=&instructions;memory.start=start;memory.stop=stop;
        if(trace_flags&1) trace.open("trace.csv");
        if(trace_flags&2) {
            for(auto &m:models) {
                m.trace=std::make_unique<std::ofstream>("timing-"+m.id+".csv");
                *m.trace<<"instruction,pc,"<<m.model->getPrintHeader();
            }
        }
    }
    void finalizeInstrSet(etiss::instr::ModedInstructionSet& sets) const override {
        etiss::plugin::TracerPlugin::TracerPlugin::finalizeInstrSet(sets);
        // The stock tracer visits registered instructions but omits decoder
        // fallbacks. Record those before ETISS's default exception callback.
        sets.foreach([this](etiss::instr::VariableInstructionSet& modes) {
            modes.foreach([this](etiss::instr::InstructionSet& set) {
                auto& invalid=set.getInvalid();
                invalid.addCallback([this,&invalid](etiss::instr::BitArray& bits,etiss::CodeSet& code,etiss::instr::InstructionContext& context) {
                    code.prepend(etiss::CodePart::PREINITIALDEBUGRETURNING).code()=instruction_monitor->getPreInstrCallback(invalid,bits,context);
                    return true;
                },0);
            });
        });
    }
    void initCodeBlock(etiss::CodeBlock& block) const override {
        etiss::plugin::TracerPlugin::TracerPlugin::initCodeBlock(block);
        block.fileglobalCode().insert("extern int uqu_arch_guard; extern int uqu_before_instruction(void*);");
    }
    void saveProfile() {
        if(!profiling)return;
        if(map_extractor) {map_extractor->save();return;}
        std::ofstream out("blocks.json");out<<"{\"schema_version\":1,\"blocks\":[";
        bool first_block=true;
        for(const auto& row:profile_blocks) {
            if(!first_block)out<<',';first_block=false;out<<'[';
            bool first=true;
            for(const auto& c:row.first) {
                if(!first)out<<',';first=false;
                out<<"{\"pc\":"<<c[0]<<",\"code\":"<<c[1]<<",\"type\":"<<c[2]
                   <<",\"rs1\":"<<c[3]<<",\"rs2\":"<<c[4]<<",\"rd\":"<<c[5]<<'}';
            }
            out<<']';
        }
        out<<"]}\n";require(bool(out),"cannot write block profile");
    }
    etiss::int32 execute() override {
        etiss::plugin::TracerPlugin::TracerPlugin::execute();
        return memory.bad || memory.done ? etiss::RETURNCODE::CPUFINISHED : etiss::RETURNCODE::NOERROR;
    }
    std::string _getPluginName() const override {return "uqu CorePerfDSL";}
};

int main(int argc,const char **argv) {
    try {
        require(argc>=10,"expected image, entry, tohost, start, stop, watchdog, misa, hartid, trace, executable ranges");
        Memory memory;memory.load(argv[1]);memory.architecture=architectural_configuration();
        active_memory=&memory;
        if(const auto path=std::getenv("UQU_PERFSIM_TRAPS")) {
            std::ifstream input(path,std::ios::binary);char magic[8]{};input.read(magic,8);
            require(std::string(magic,8)=="UQUTRP01","invalid expected trap manifest");
            const auto count=read32(input);require(count<=341,"trap manifest too large");
            for(unsigned i=0;i<count;++i){std::array<uint32_t,3> row;for(auto& v:row)v=read32(input);memory.expected.push_back(row);}
            require(input.peek()==EOF,"trailing trap manifest data");
        }
        uqu_arch_guard=memory.architecture.embedded || memory.architecture.pmp || !memory.expected.empty();
        uint64_t entry=std::stoull(argv[2],nullptr,0);memory.tohost=std::stoul(argv[3],nullptr,0);
        uint32_t start=std::stoul(argv[4],nullptr,0),stop=std::stoul(argv[5],nullptr,0);
        uint64_t limit=std::stoull(argv[6],nullptr,0);uint32_t misa=std::stoul(argv[7],nullptr,0);
        for(int i=10;i<argc;++i) {std::string s=argv[i];auto p=s.find(':');require(p!=s.npos,"bad executable range");memory.executable.emplace_back(std::stoull(s.substr(0,p),nullptr,0),std::stoull(s.substr(p+1),nullptr,0));}
        const char *init_args[]={argv[0]};etiss::Initializer initializer(1,init_args);
        etiss::cfg().set<int>("etiss.loglevel",2);
        etiss::cfg().set<int>("etiss.max_block_size",64);
        etiss::cfg().set<bool>("etiss.exit_on_loop",false);
        etiss::cfg().set<bool>("etiss.enable_dmi",false);
        auto cpu=etiss::CPUCore::create("RV32IMACFD","uqu");require(bool(cpu),"cannot load pinned RV32 ISA model");
        cpu->setTimer(false);cpu->setBlockChainCount(1);cpu->reset(&entry);
        // A functional instruction tick, independent of every timing model.
        cpu->getState()->cpuCycleTime_ps=1;
        auto state=reinterpret_cast<RV32IMACFD*>(cpu->getState());
        *state->CSR[0x301]=misa;*state->CSR[0xf14]=std::stoul(argv[8],nullptr,0);state->PRIV=3;state->MSTATUS=0x1800;state->MIE=state->MIP=0;
        auto jit=etiss::getJIT("TCCJIT",{});require(bool(jit),"TCCJIT is required");cpu->set(jit);
        auto plugin=std::make_shared<UquPlugin>(memory,limit,start,stop,bool(misa&(1<<12)),bool(misa&(1<<2)),std::stoul(argv[9]));
        cpu->addPlugin(plugin);
        ETISS_System system{};system.handle=&memory;system.iread=Memory::iread;system.iwrite=Memory::write;
        system.dread=Memory::read;system.dwrite=Memory::write;system.dbg_read=Memory::debug_read;
        system.dbg_write=Memory::debug_write;system.syncTime=Memory::sync;
        int32_t result=cpu->execute(system);
        require(memory.done&&!memory.bad&&plugin->finished,"ETISS stopped before checked completion: "+std::to_string(result)+" "+memory.error);
        require(memory.observed==memory.expected,"missing expected synchronous traps");
        require(memory.exit_code==0,"software reported failure: "+std::to_string(memory.exit_code));
        memory.save();plugin->saveProfile();
        std::ofstream events("traps.csv");for(const auto& t:memory.observed)events<<t[0]<<','<<t[1]<<','<<t[2]<<'\n';
        std::ofstream out("native.json");out<<"{\"status\":\"passed\",\"functional_instructions\":"<<plugin->instructions<<",\"models\":[";
        bool first=true;
        for(auto &m:plugin->models) {
            require(!start || (m.started&&m.stopped),"incomplete benchmark window");
            uint64_t cycles=start?m.stop_cycle-m.start_cycle:m.model->getCycleCount();
            uint64_t count=start?m.stop_count-m.start_count:plugin->instructions-memory.faults;
            require(cycles>0&&count>0,"empty timing window");
            if(!first)out<<',';first=false;
            out<<"{\"id\":\""<<m.id<<"\",\"cycles\":"<<cycles<<",\"instructions\":"<<count<<'}';
        }
        out<<"],\"execution\":{\"scheduler\":\""<<(plugin->map_mode?"map_explorer":plugin->block_mode?"block":"instruction")
           <<"\",\"shared_components\":"<<(plugin->share_models?"true":"false")
           <<",\"verified_instructions\":"<<(plugin->verify?plugin->instructions:0)
           <<",\"map_calls\":"<<(plugin->map_backend?plugin->map_backend->calls():0)
           <<",\"block_calls\":"<<plugin->block_calls<<",\"instruction_calls\":"<<plugin->instruction_calls
           <<(plugin->map_backend?plugin->map_backend->statistics():"")
           <<",\"frontend_calls\":"<<plugin->sharing.calls<<",\"frontend_evaluations\":"<<plugin->sharing.evaluations
           <<",\"frontend_cache_hits\":"<<plugin->sharing.hits<<",\"peak_cache_entries\":"<<plugin->sharing.peak_entries<<"}}\n";
        require(bool(out),"cannot write native result");
        return 0;
    } catch(const std::exception &e) {std::cerr<<"uqu perfsim: "<<e.what()<<'\n';return 1;}
}
