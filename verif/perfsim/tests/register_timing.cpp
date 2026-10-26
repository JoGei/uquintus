// Exercise the real connector against the pinned upstream API.
#include "uqu_models.h"
#include <stdexcept>

class TestModel : public PerformanceModel {
public:
    explicit TestModel(SchedulingFunctionSet *s) : PerformanceModel("test", s) { instrIndex=0; }
    void connectChannel(Channel*) override {}
    uint64_t getCycleCount() override { return 0; }
    std::string getPipelineStream() override { return ""; }
    std::string getPrintHeader() override { return ""; }
};
static void check(bool ok) { if(!ok) throw std::runtime_error("register availability boundary"); }
int main() {
    SchedulingFunctionSet schedules("test"); TestModel model(&schedules);
    uqu::RegisterModel registers(&model);
    uint64_t a=3,b=3,d=3;
    registers.rs1_ptr=&a;registers.rs2_ptr=&b;registers.rd_ptr=&d;
    registers.setXd(7); // same-cycle EX/MEM candidate -> DE forwarding
    check(registers.getXa()==7 && registers.getDa()==7 && registers.getDb()==7);
    registers.setLd(8); // live load response cannot bypass into DE
    check(registers.getXa()==8 && registers.getDa()==9 && registers.getDb()==9);
    registers.forwarding=false;
    registers.setXd(10); // architectural write becomes an RF read next cycle
    check(registers.getXa()==10 && registers.getDa()==11);
    registers.forwarding=true;
    registers.setXd(12); // youngest producer supersedes the earlier dependency
    check(registers.getDa()==12);
    a=b=d=0;registers.setXd(100);registers.setLd(200);
    check(registers.getXa()==0 && registers.getXb()==0 && registers.getDa()==0 && registers.getDb()==0);
}
