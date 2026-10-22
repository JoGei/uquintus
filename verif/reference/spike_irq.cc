// Verification-only external IRQ pin driver for the qualified Spike SDK.
// Host debugger loads encode three line levels in address bits [5:3]. Target
// software never accesses this device; architectural memory remains native RAM.
#include <riscv/sim.h>
#include <cstring>
#include <fstream>
#include <array>
#include <sstream>

// CSR-visible pin sample can precede delivery while native older work drains.
// Keep Spike's actual interrupt selection on state->mip; only the software CSR
// view is sampled. Native MIP source bits are all hardware-owned, writes ignored.
class uqu_mip_view_t : public csr_t {
  csr_t_p original;
public:
  reg_t pins = 0;
  uqu_mip_view_t(processor_t* core, csr_t_p original)
    : csr_t(core, CSR_MIP), original(original) {}
  void verify_permissions(insn_t insn, bool write) const override {
    original->verify_permissions(insn, write);
  }
  reg_t read() const noexcept override { return pins; }
protected:
  bool unlogged_write(reg_t) noexcept override { return true; }
};

class uqu_irq_t : public abstract_device_t {
  processor_t* core;
  std::vector<std::array<reg_t, 5>> samples;
  std::shared_ptr<uqu_mip_view_t> mip_view;
  size_t cursor = 0;
public:
  explicit uqu_irq_t(const sim_t* sim, const std::vector<std::string>& arguments)
    : core(const_cast<sim_t*>(sim)->get_core(0)) {
    if (arguments.size() > 1) throw std::runtime_error("uqu_irq accepts one replay file");
    if (!arguments.empty()) {
      std::ifstream input(arguments[0]);
      if (!input) throw std::runtime_error("cannot open uqu replay input");
      std::string line;
      while (std::getline(input, line)) {
        std::array<reg_t, 5> row;
        std::istringstream fields(line);
        std::string extra;
        if (!(fields >> std::hex >> row[0] >> row[1] >> row[2] >> row[3] >> row[4]) || fields >> extra)
          throw std::runtime_error("invalid uqu replay row");
        if (row[0] > 1 || (row[3] | row[4]) & ~reg_t(0x888) || samples.size() >= 2000000)
          throw std::runtime_error("invalid uqu replay input");
        samples.push_back(row);
      }
      if (!input.eof() || samples.empty()) throw std::runtime_error("invalid uqu replay file");
      auto state = core->get_state();
      mip_view = std::make_shared<uqu_mip_view_t>(core, state->csrmap.at(CSR_MIP));
      state->add_csr(CSR_MIP, mip_view);
    }
  }
  bool load(reg_t address, size_t length, uint8_t* bytes) override {
    if (address == 0x100 && length == 8 && mip_view && cursor < samples.size()) {
      const auto& row = samples[cursor++];
      auto state = core->get_state();
      if (row[0]) {
        // Seed pre-instruction inputs, never GPRs, PC, privilege or CSR results.
        // bump(0) clears the counter API's explicit-write bookkeeping before
        // the target instruction. Its normal CSR implementation stays intact.
        state->mcycle->write(row[1]); state->mcycle->bump(0);
        state->minstret->write(row[2]); state->minstret->bump(0);
      }
      mip_view->pins = row[3];
      state->mip->backdoor_write_with_mask(0x888, row[4]);
      std::memset(bytes, 0, length);
      for (size_t n=0; n<length; ++n) bytes[n] = (reg_t(cursor) >> (8*n)) & 255;
      return true;
    }
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
  *base = 0x50000000;
  return new uqu_irq_t(sim, arguments);
}
static std::string generate(const sim_t*, const std::vector<std::string>&) {
  return "uqu_irq@50000000 { compatible = \"uqu,irq\"; "
         "reg = <0x0 0x50000000 0x0 0x1000>; };\n";
}
REGISTER_DEVICE(uqu_irq, parse, generate)
