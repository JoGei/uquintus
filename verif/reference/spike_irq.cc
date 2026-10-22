// Verification-only external IRQ pin driver for the qualified Spike SDK.
// Host debugger loads encode three line levels in address bits [5:3]. Target
// software never accesses this device; architectural memory remains native RAM.
#include <riscv/sim.h>
#include <cstring>

class uqu_irq_t : public abstract_device_t {
  processor_t* core;
public:
  explicit uqu_irq_t(const sim_t* sim)
    : core(const_cast<sim_t*>(sim)->get_core(0)) {}
  bool load(reg_t address, size_t length, uint8_t* bytes) override {
    if (address >= 64 || address % 8 || length != 8) return false;
    const reg_t index = address / 8;
    const reg_t lines = ((index & 1) ? 8 : 0) |
                        ((index & 2) ? 128 : 0) | ((index & 4) ? 2048 : 0);
    // The same external-input API used by Spike's platform devices. No CSR
    // instruction, privilege/PC mutation or fabricated trap is introduced.
    core->get_state()->mip->backdoor_write_with_mask(0x888, lines);
    std::memset(bytes, 0, length);
    bytes[0] = index;
    return true;
  }
  bool store(reg_t, size_t, const uint8_t*) override { return false; }
  reg_t size() override { return 4096; }
};

static uqu_irq_t* parse(const void*, const sim_t* sim, reg_t* base,
                        const std::vector<std::string>& arguments) {
  if (!arguments.empty()) throw std::runtime_error("uqu_irq takes no arguments");
  *base = 0x50000000;
  return new uqu_irq_t(sim);
}
static std::string generate(const sim_t*, const std::vector<std::string>&) {
  return "uqu_irq@50000000 { compatible = \"uqu,irq\"; "
         "reg = <0x0 0x50000000 0x0 0x1000>; };\n";
}
REGISTER_DEVICE(uqu_irq, parse, generate)
