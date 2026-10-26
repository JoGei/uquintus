#ifndef UQU_PERFSIM_ARCH_H
#define UQU_PERFSIM_ARCH_H
#include <array>
#include <cstdint>
#include <stdexcept>
namespace uqu {
// Architectural policy for the native ETISS adapter. Arithmetic semantics stay
// in CoreDSL. CSR WARL, privilege and PMP match uqu_csregfile/uqu_pmp.
struct Architecture {
    bool embedded=false,multiply=false,compressed=false,user=true,pmp=false;
    uint32_t hart=0,privilege=3;
    std::array<uint32_t,4096> csr{};
    std::array<uint8_t,16> cfg{};
    std::array<uint32_t,16> addr{};
    std::array<bool,16> addr_written{};
    uint64_t cycle=0,retired=0,last_cycle=0,last_retired=0;
    Architecture(){csr[0x300]=0x1800;}
    uint32_t misa() const {return 0x40000000u | (embedded?0x10:0x100) | (multiply?1<<12:0) | (compressed?4:0) | (user?1<<20:0);}
    void advance(uint64_t c,uint64_t r) {
        if(c<last_cycle || r<last_retired)throw std::runtime_error("architectural counter moved backwards");
        if(!(csr[0x320]&1))cycle+=c-last_cycle;
        if(!(csr[0x320]&4))retired+=r-last_retired;
        last_cycle=c;last_retired=r;
    }
    bool mapped(unsigned a) const {
        switch(a) {
          case 0x300:case 0x301:case 0x304:case 0x305:case 0x310:case 0x320:
          case 0x340:case 0x341:case 0x342:case 0x343:case 0x344:
          case 0xb00:case 0xb80:case 0xb02:case 0xb82:case 0xc00:case 0xc80:case 0xc02:case 0xc82:
          case 0xf11:case 0xf12:case 0xf13:case 0xf14:case 0xf15:return true;
          case 0x306:case 0x30a:case 0x31a:return user;
          default:return (a>=0x3a0 && a<=0x3a3) || (a>=0x3b0 && a<=0x3bf) ||
            (a>=0xb03 && a<=0xb1f) || (a>=0xb83 && a<=0xb9f) || (a>=0x323 && a<=0x33f) ||
            (a>=0xc03 && a<=0xc1f) || (a>=0xc83 && a<=0xc9f);
        }
    }
    uint32_t read(unsigned a) const {
        if(!mapped(a))throw std::runtime_error("unmapped CSR read");
        if(a==0x301)return misa();if(a==0xf14)return hart;
        if(a>=0x3a0 && a<=0x3a3){uint32_t value=0;if(pmp)for(unsigned i=0;i<4;++i)value|=uint32_t(cfg[(a-0x3a0)*4+i])<<(i*8);return value;}
        if(a>=0x3b0 && a<=0x3bf){if(pmp && !addr_written[a-0x3b0])throw std::runtime_error("PMP address payload read before initialization");return pmp?addr[a-0x3b0]:0;}
        if(a==0xb00 || a==0xc00)return uint32_t(cycle);if(a==0xb80 || a==0xc80)return cycle>>32;
        if(a==0xb02 || a==0xc02)return uint32_t(retired);if(a==0xb82 || a==0xc82)return retired>>32;
        return csr[a];
    }
    void write(unsigned a,uint32_t value) {
        switch(a) {
          case 0x300:csr[a]=(value&0x88) | (user?(value&0x220000) | ((value&0x1800)?0x1800:0):0x1800);break;
          case 0x304:csr[a]=value&0x888;break;
          case 0x305:csr[a]=(value&~3u) | ((value&3)==1);break;
          case 0x306:case 0x320:csr[a]=value&5;break;
          case 0x340:case 0x343:csr[a]=value;break;
          case 0x341:csr[a]=value & (compressed?~1u:~3u);break;
          case 0x342:csr[a]=value&0x8000000f;break;
          case 0xb00:cycle=(cycle&0xffffffff00000000ULL)|value;break;
          case 0xb80:cycle=(uint64_t(value)<<32)|uint32_t(cycle);break;
          case 0xb02:retired=(retired&0xffffffff00000000ULL)|value;break;
          case 0xb82:retired=(uint64_t(value)<<32)|uint32_t(retired);break;
          default:
            if(pmp && a>=0x3a0 && a<=0x3a3)for(unsigned i=0;i<4;++i) {
                const unsigned index=(a-0x3a0)*4+i;uint8_t v=(value>>(i*8))&0x9f;
                if(!(v&1))v&=~2u;if(!(cfg[index]&0x80))cfg[index]=v;
            }
            if(pmp && a>=0x3b0 && a<=0x3bf) {
                const unsigned index=a-0x3b0;
                const bool locked=(cfg[index]&0x80) || (index<15 && (cfg[index+1]&0x98)==0x88);
                if(!locked){addr[index]=value;addr_written[index]=true;}
            }
        }
    }
    struct CsrResult {bool illegal=false,read=false,write=false;uint32_t value=0;};
    CsrResult access(uint32_t instruction,uint32_t source) {
        const unsigned a=instruction>>20,op=instruction>>12&7,rs=instruction>>15&31,rd=instruction>>7&31;
        const bool immediate=op&4;source=immediate?rs:source;
        const bool reading=(op&3)!=1 || rd!=0,writing=(op&3)==1 || rs!=0;
        bool allowed=privilege==3 || (user && ((a>>8)&3)==0);
        if(privilege!=3 && ((a>=0xc00 && a<=0xc1f) || (a>=0xc80 && a<=0xc9f))) {
            const unsigned low=a&0x7f;
            allowed &= (low==0 || low==2) && bool(csr[0x306]&(1u<<low));
        }
        if(!mapped(a) || !allowed || !(op&3) || (writing && (a>>10)==3))return {true};
        // CSRRW rd=x0 need not read an uninitialized PMP payload.
        uint32_t previous=reading || (op&3)!=1?read(a):0;
        if(writing)write(a,(op&3)==1?source:(op&3)==2?previous|source:previous&~source);
        return {false,reading,writing,reading?previous:0};
    }
    bool permitted(uint32_t address,unsigned bytes,unsigned access,bool data=false) const {
        if(!pmp)return true;
        const bool machine=data && (csr[0x300]&(1<<17))?(csr[0x300]&0x1800)!=0:privilege==3;
        if(!bytes || uint64_t(address)+bytes>(1ULL<<32))return false;
        for(unsigned i=0;i<16;++i) {
            const unsigned mode=(cfg[i]>>3)&3;if(!mode)continue;
            uint64_t lo=0,hi=0;
            if(mode==1){lo=i?uint64_t(addr[i-1])*4:0;hi=uint64_t(addr[i])*4;}
            else if(mode==2){lo=uint64_t(addr[i])*4;hi=lo+4;}
            else {unsigned trailing=0;while(trailing<32 && (addr[i]&(1u<<trailing)))++trailing;
                const uint64_t size=1ULL<<(trailing+3);lo=(uint64_t(addr[i])*4/size)*size;hi=lo+size;}
            if(uint64_t(address)<hi && uint64_t(address)+bytes>lo)
                return address>=lo && uint64_t(address)+bytes<=hi && ((machine && !(cfg[i]&0x80)) || (cfg[i]&access)==access);
        }
        return machine;
    }
    uint32_t trap(uint32_t pc,uint32_t cause,uint32_t value) {
        const uint32_t old=csr[0x300];csr[0x300]=(old&~0x1888u) | (privilege==3?0x1800:0) | ((old&8)<<4);
        csr[0x341]=pc & (compressed?~1u:~3u);csr[0x342]=cause;csr[0x343]=value;privilege=3;
        return csr[0x305]&~3u;
    }
    uint32_t mret() {
        const auto old=csr[0x300];privilege=(old&0x1800)?3:0;
        csr[0x300]=(old&~0x1888u) | ((old&0x80)>>4) | 0x80 | (user?0:0x1800);
        if(privilege!=3)csr[0x300]&=~(1u<<17);
        return csr[0x341] & (compressed?~1u:~3u);
    }
};
}
#endif
