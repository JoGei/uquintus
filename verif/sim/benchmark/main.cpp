// Native cycle driver. Python is used only before and after this executable.
#include "Vuqu_benchmark_tb.h"
#include "verilated.h"

#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>

static void require(bool condition, const std::string &message) {
    if (!condition) throw std::runtime_error(message);
}

static void require(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

static uint32_t read32(std::istream &in) {
    uint32_t result = 0;
    for (unsigned i = 0; i < 4; ++i) {
        int c = in.get();
        require(c != EOF, "truncated memory image");
        result |= uint32_t(uint8_t(c)) << (8*i);
    }
    return result;
}

static void write32(std::ostream &out, uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) out.put(char(value >> (8*i)));
}

struct Memory {
    std::unordered_map<uint32_t, std::array<uint8_t, 4096>> pages;
    uint8_t byte(uint32_t addr) const {
        auto p = pages.find(addr >> 12);
        return p == pages.end() ? 0 : p->second[addr & 4095];
    }
    uint32_t word(uint32_t addr) const {
        uint32_t result = 0;
        for (unsigned i = 0; i < 4; ++i) result |= uint32_t(byte(addr+i)) << (8*i);
        return result;
    }
    void store(uint32_t addr, uint32_t value, unsigned be) {
        for (unsigned i = 0; i < 4; ++i)
            if (be & (1u << i)) pages[(addr+i) >> 12][(addr+i) & 4095] = uint8_t(value >> (8*i));
    }
    void load(const std::string &name) {
        std::ifstream in(name, std::ios::binary);
        char magic[8] = {};
        in.read(magic, 8);
        require(std::string(magic, 8) == "UQUMEM01", "invalid memory image header");
        uint32_t count = read32(in);
        require(count <= 4096, "too many memory segments");
        uint64_t total = 0;
        for (uint32_t n = 0; n < count; ++n) {
            uint32_t addr = read32(in), filesz = read32(in), memsz = read32(in);
            total += memsz;
            require(filesz <= memsz && uint64_t(addr)+memsz <= (1ull << 32) && total <= 16*1024*1024,
                    "invalid memory image segment");
            for (uint32_t i = 0; i < filesz; ++i) {
                int c = in.get();
                require(c != EOF, "truncated memory image data");
                pages[(addr+i) >> 12][(addr+i) & 4095] = uint8_t(c);
            }
        }
        require(in.peek() == EOF, "trailing memory image data");
    }
    void save(const std::string &name) const {
        std::ofstream out(name, std::ios::binary);
        out.write("UQUMEM01", 8);
        write32(out, uint32_t(pages.size()));
        for (const auto &p : pages) {
            write32(out, p.first << 12); write32(out, 4096); write32(out, 4096);
            out.write(reinterpret_cast<const char *>(p.second.data()), 4096);
        }
        require(bool(out), "cannot write final memory image");
    }
};

static std::string json_string(const std::string &value) {
    std::string result = "\"";
    for (unsigned char c : value) {
        if (c == '\\' || c == '"') { result += '\\'; result += char(c); }
        else if (c == '\n') result += "\\n";
        else if (c == '\r') result += "\\r";
        else if (c == '\t') result += "\\t";
        else if (c >= 32) result += char(c);
        else result += '?';
    }
    return result + '"';
}

struct Point {
    bool valid = false;
    uint64_t cycle = 0, retired = 0;
    uint32_t value = 0;
    std::string json() const {
        if (!valid) return "null";
        return "{\"cycle\":" + std::to_string(cycle) + ",\"retired\":" + std::to_string(retired) +
            ",\"mcycle_low\":" + std::to_string(value) + "}";
    }
};

struct Pending { bool valid = false; uint32_t delay = 0, data = 0; };
struct Request { bool valid = false, we = false; uint32_t addr = 0, data = 0, be = 0, pc = 0; };

int main(int argc, char **argv) {
    Memory memory;
    uint64_t cycles = 0, retired = 0;
    Point start, stop;
    std::string detail;
    int64_t exit_code = -1;
    auto context = std::make_unique<VerilatedContext>();
    context->commandArgs(argc, argv);
    auto dut = std::make_unique<Vuqu_benchmark_tb>(context.get());
    try {
        require(argc == 9, "expected image, watchdog, boot, imem/dmem latency, tohost, start/stop PC");
        memory.load(argv[1]);
        uint64_t limit = std::stoull(argv[2], nullptr, 0);
        uint32_t boot = uint32_t(std::stoull(argv[3], nullptr, 0));
        uint32_t latency[2] = {uint32_t(std::stoull(argv[4])), uint32_t(std::stoull(argv[5]))};
        uint32_t tohost = uint32_t(std::stoull(argv[6], nullptr, 0));
        uint32_t start_pc = uint32_t(std::stoull(argv[7], nullptr, 0));
        uint32_t stop_pc = uint32_t(std::stoull(argv[8], nullptr, 0));
        require(limit > 0 && latency[0] > 0 && latency[1] > 0, "invalid watchdog/memory latency");
        Pending pending[2];
        bool completion_pending = false;
        uint32_t completion_pc = 0, completion_value = 0;
        auto eval = [&]() { dut->eval(); context->timeInc(1); };
        dut->boot_addr_i = boot;
        for (; cycles < limit+2 && exit_code < 0; ++cycles) {
            bool reset = cycles < 2;
            dut->clk_i = 0; dut->rst_ni = !reset;
            dut->imem_gnt_i = dut->dmem_gnt_i = 0;
            dut->imem_rvalid_i = dut->dmem_rvalid_i = 0;
            dut->imem_rdata_i = dut->dmem_rdata_i = 0;
            dut->imem_err_i = dut->dmem_err_i = 1;
            eval();
            Request request[2] = {
                {bool(!reset && dut->imem_req_o), false, dut->imem_addr_o, 0, 0, 0},
                {bool(!reset && dut->dmem_req_o), bool(dut->dmem_we_o), dut->dmem_addr_o,
                 dut->dmem_wdata_o, dut->dmem_be_o, dut->dmem_pc_o}};
            bool returning[2] = {!reset && pending[0].valid && pending[0].delay == 0,
                                 !reset && pending[1].valid && pending[1].delay == 0};
            dut->imem_gnt_i = request[0].valid; dut->dmem_gnt_i = request[1].valid;
            dut->imem_rvalid_i = returning[0]; dut->dmem_rvalid_i = returning[1];
            if (returning[0]) { dut->imem_rdata_i = pending[0].data; dut->imem_err_i = 0; }
            if (returning[1]) { dut->dmem_rdata_i = pending[1].data; dut->dmem_err_i = 0; }
            eval();
            if (!reset) {
                if (dut->trap_o) throw std::runtime_error("unexpected trap at PC " + std::to_string(dut->trap_pc_o) +
                        " cause " + std::to_string(dut->trap_cause_o));
                if (start.valid && !stop.valid)
                    require(!(dut->mcountinhibit_o & 5), "benchmark counters inhibited");
                // Match the checked agents' ordering: IF reads before a
                // simultaneous data store; response data is captured at grant.
                for (unsigned bus = 0; bus < 2; ++bus) {
                    auto &p = pending[bus]; const auto &r = request[bus];
                    if (returning[bus]) p.valid = false;
                    else if (p.valid && p.delay) --p.delay;
                    if (r.valid) {
                        require(!p.valid, "multiple outstanding bus requests");
                        require(!(r.addr & 3), "unaligned bus request");
                        p = {true, latency[bus]-1, memory.word(r.addr)};
                        if (r.we) {
                            memory.store(r.addr, r.data, r.be);
                            if ((r.addr & ~7u) == tohost) {
                                require(r.addr == tohost && r.be == 15 && !completion_pending,
                                        "invalid tohost store");
                                if (r.data) { completion_pending = true; completion_pc = r.pc; completion_value = r.data; }
                            }
                        }
                    }
                }
                if (dut->retire_o) {
                    ++retired;
                    uint32_t pc = dut->retire_pc_o;
                    if (pc == start_pc || pc == stop_pc) {
                        require(!(dut->mcountinhibit_o & 5), "benchmark counters inhibited");
                        Point point = {true, cycles, retired, dut->retire_data_o};
                        if (pc == start_pc) {
                            require(!start.valid && !stop.valid, "repeated benchmark start"); start = point;
                        } else {
                            require(start.valid && !stop.valid, "out-of-order/repeated benchmark stop"); stop = point;
                        }
                    }
                    if (completion_pending && pc == completion_pc) {
                        // The accepted write's MEM PC identifies its in-order
                        // retirement, including compressed store encodings.
                        require((completion_value & 1) && completion_value, "invalid tohost completion value");
                        require(memory.word(tohost+4) == 0, "nonzero tohost upper word");
                        require(!pending[1].valid, "completion retired before the data response");
                        exit_code = completion_value == 1 ? 0 : completion_value >> 1;
                    }
                }
            }
            dut->clk_i = 1; eval(); dut->clk_i = 0; eval();
            require(!context->gotFinish(), "RTL finished before benchmark completion");
        }
        require(exit_code >= 0, "benchmark watchdog expired");
        require(exit_code == 0, "software reported failure " + std::to_string(exit_code));
        require(start.valid && stop.valid, "incomplete benchmark window");
        require(stop.cycle > start.cycle && stop.cycle-start.cycle < (1ull << 32), "invalid benchmark duration");
        require(uint32_t(stop.value-start.value) == stop.cycle-start.cycle, "software/RTL cycle delta mismatch");
        require(stop.retired > start.retired, "empty benchmark instruction window");
    } catch (const std::exception &e) { detail = e.what(); }
    dut->final();
    memory.save("final-memory.bin");
    std::ofstream out("native.json");
    out << "{\"status\":" << json_string(detail.empty() ? "passed" : "failed")
        << ",\"detail\":" << (detail.empty() ? "null" : json_string(detail))
        << ",\"cycles\":" << cycles << ",\"retired\":" << retired
        << ",\"exit_code\":" << exit_code << ",\"start\":" << start.json()
        << ",\"stop\":" << stop.json() << "}\n";
    if (!detail.empty()) std::cerr << detail << '\n';
    return detail.empty() ? 0 : 1;
}
