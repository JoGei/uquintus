#include <deque>
#include "uqu_memory.h"
#include "memory_environment.h"
// Native cycle driver. Python is used only before and after this executable.
#include "Vuqu_perfsim_tb.h"
#include "verilated.h"

#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

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

struct Pending { bool valid = false; uint64_t due = 0; uint32_t data = 0; };
struct Request { bool valid = false, we = false; uint32_t addr = 0, data = 0, be = 0, pc = 0; };

struct BpuSnapshot {
    std::vector<uint64_t> values;
    void sample(const Vuqu_perfsim_tb &dut) {
        require(dut.bpu_counter_count_o > 0 && dut.bpu_counter_count_o <= 32, "invalid BPU counter count");
        for (unsigned i = 0; i < dut.bpu_counter_count_o; ++i)
            values.push_back(uint64_t(dut.bpu_counters_o[2*i]) | uint64_t(dut.bpu_counters_o[2*i+1]) << 32);
    }
    std::string json() const {
        if (values.empty()) return "null";
        std::string result = "[";
        for (unsigned i = 0; i < values.size(); ++i)
            result += (i ? "," : "") + std::to_string(values[i]);
        return result + "]";
    }
};

int main(int argc, char **argv) {
    Memory memory;
    std::ofstream retirement_trace;
    std::ofstream trap_trace("traps.csv");
    std::vector<std::array<uint32_t,3>> expected, observed;
    uqu::MemoryPort ports[2]; configure_memory(ports);
    uint64_t cycles = 0, retired = 0;
    Point start, stop;
    BpuSnapshot bpu_start, bpu_stop;
    std::string detail;
    int64_t exit_code = -1;
    auto context = std::make_unique<VerilatedContext>();
    context->commandArgs(argc, argv);
    auto dut = std::make_unique<Vuqu_perfsim_tb>(context.get());
    try {
        require(argc == 9 || argc == 10, "expected image, watchdog, boot, imem/dmem latency, tohost, start/stop PC, optional retirement trace");
        if (argc == 10) {
            retirement_trace.open(argv[9], std::ios::binary);
            require(bool(retirement_trace), "cannot open diagnostic retirement trace");
            retirement_trace.write("UQUTRC01", 8);
        }
        memory.load(argv[1]);
        if (const char* path=std::getenv("UQU_PERFSIM_TRAPS")) {
            std::ifstream input(path,std::ios::binary); char magic[8]{}; input.read(magic,8);
            require(std::string(magic,8)=="UQUTRP01","invalid trap manifest");
            auto count=read32(input); require(count<=341,"trap manifest too large");
            while(count--) {std::array<uint32_t,3> row;for(auto& value:row)value=read32(input);expected.push_back(row);}
            require(input.peek()==EOF,"trailing trap manifest bytes");
        }
        uint64_t limit = std::stoull(argv[2], nullptr, 0);
        uint32_t boot = uint32_t(std::stoull(argv[3], nullptr, 0));
        uint32_t latency[2] = {uint32_t(std::stoull(argv[4])), uint32_t(std::stoull(argv[5]))};
        uint32_t tohost = uint32_t(std::stoull(argv[6], nullptr, 0));
        uint32_t start_pc = uint32_t(std::stoull(argv[7], nullptr, 0));
        uint32_t stop_pc = uint32_t(std::stoull(argv[8], nullptr, 0));
        require(limit > 0 && latency[0] > 0 && latency[1] > 0, "invalid watchdog/memory latency");
        std::deque<Pending> pending[2];
        bool completion_pending = false;
        uint32_t completion_pc = 0, completion_value = 0;
        auto eval = [&]() { dut->eval(); context->timeInc(1); };
        dut->boot_addr_i = boot;
        for (; cycles < limit+2 && exit_code < 0; ++cycles) {
            bool reset = cycles < 2;
            bool start_edge = false, stop_edge = false;
            dut->clk_i = 0; dut->rst_ni = !reset;
            dut->imem_gnt_i = dut->dmem_gnt_i = 0;
            dut->imem_rvalid_i = dut->dmem_rvalid_i = 0;
            dut->imem_rdata_i = dut->dmem_rdata_i = 0;
            dut->imem_err_i = dut->dmem_err_i = 1;
            eval();
            bool returning[2] = {!reset && !pending[0].empty() && pending[0].front().due <= cycles-1,
                                 !reset && !pending[1].empty() && pending[1].front().due <= cycles-1};
            dut->imem_rvalid_i = returning[0]; dut->dmem_rvalid_i = returning[1];
            if (returning[0]) { dut->imem_rdata_i = pending[0].front().data; dut->imem_err_i = 0; }
            if (returning[1]) { dut->dmem_rdata_i = pending[1].front().data; dut->dmem_err_i = 0; }
            eval();
            // Availability is an independent input. Grant both buses before
            // sampling requests: a data grant can release DE and redirect IF
            // combinationally. Capturing the earlier address reads wrong code.
            dut->imem_gnt_i = !reset && ports[0].can_grant(cycles-1);
            dut->dmem_gnt_i = !reset && ports[1].can_grant(cycles-1);
            eval();
            Request request[2] = {
                {bool(!reset && dut->imem_req_o && dut->imem_gnt_i), false, dut->imem_addr_o, 0, 0, 0},
                {bool(!reset && dut->dmem_req_o && dut->dmem_gnt_i), bool(dut->dmem_we_o), dut->dmem_addr_o,
                 dut->dmem_wdata_o, dut->dmem_be_o, dut->dmem_pc_o}};
            if (!reset) {
                if (dut->trap_o) {
                    std::array<uint32_t,3> row{dut->trap_pc_o,dut->trap_cause_o,dut->trap_tval_o};
                    require(observed.size()<expected.size() && row==expected[observed.size()],
                            "unexpected trap at " + std::to_string(row[0]) + " cause " + std::to_string(row[1]) + " tval " + std::to_string(row[2]));
                    observed.push_back(row);trap_trace<<row[0]<<','<<row[1]<<','<<row[2]<<'\n';
                    if(retirement_trace.is_open()) {
                        write32(retirement_trace,uint32_t(cycles));write32(retirement_trace,row[0]);
                        write32(retirement_trace,row[1]==1?0:memory.word(row[0]));
                    }
                }
                if (start.valid && !stop.valid)
                    require(!(dut->mcountinhibit_o & 5), "benchmark counters inhibited");
                // Match the checked agents' ordering: IF reads before a
                // simultaneous data store; response data is captured at grant.
                for (unsigned bus = 0; bus < 2; ++bus) {
                    auto &p = pending[bus]; const auto &r = request[bus];
                    if (returning[bus]) p.pop_front();
                    if (r.valid) {
                        require(p.size() < (bus == 0 ? 2u : 1u), "too many outstanding bus requests");
                        require(!(r.addr & 3), "unaligned bus request");
                        p.push_back({true, ports[bus].accept(r.addr,r.we,cycles-1), memory.word(r.addr)});
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
                    if (retirement_trace.is_open()) {
                        // Observation only: include startup/warmup so offline
                        // models can distinguish first visits from steady state.
                        write32(retirement_trace, uint32_t(cycles));
                        write32(retirement_trace, pc);
                        write32(retirement_trace, memory.word(pc));
                    }
                    if (pc == start_pc || pc == stop_pc) {
                        require(!(dut->mcountinhibit_o & 5), "benchmark counters inhibited");
                        Point point = {true, cycles, retired, dut->retire_data_o};
                        if (pc == start_pc) {
                            require(!start.valid && !stop.valid, "repeated benchmark start"); start = point;
                            start_edge = true;
                        } else {
                            require(start.valid && !stop.valid, "out-of-order/repeated benchmark stop"); stop = point;
                            stop_edge = true;
                        }
                    }
                    if (completion_pending && pc == completion_pc) {
                        // The accepted write's MEM PC identifies its in-order
                        // retirement, including compressed store encodings.
                        require((completion_value & 1) && completion_value, "invalid tohost completion value");
                        require(memory.word(tohost+4) == 0, "nonzero tohost upper word");
                        require(pending[1].empty(), "completion retired before the data response");
                        exit_code = completion_value == 1 ? 0 : completion_value >> 1;
                    }
                }
            }
            dut->clk_i = 1; eval();
            // Post-edge counters include the retiring marker. Subtracting
            // these snapshots implements the same (start, stop] boundary.
            if (start_edge) bpu_start.sample(*dut);
            if (stop_edge) bpu_stop.sample(*dut);
            dut->clk_i = 0; eval();
            require(!context->gotFinish(), "RTL finished before benchmark completion");
        }
        require(exit_code >= 0, "benchmark watchdog expired");
        require(exit_code == 0, "software reported failure " + std::to_string(exit_code));
        require(observed==expected,"missing expected traps");
        require(!start_pc || (start.valid && stop.valid), "incomplete benchmark window");
        if(start_pc) {
        require(stop.cycle > start.cycle && stop.cycle-start.cycle < (1ull << 32), "invalid benchmark duration");

        require(stop.retired > start.retired, "empty benchmark instruction window");
        }
        if (retirement_trace.is_open()) {
            retirement_trace.flush();
            require(bool(retirement_trace), "cannot write diagnostic retirement trace");
        }
    } catch (const std::exception &e) { detail = e.what(); }
    dut->final();
    memory.save("final-memory.bin");
    std::ofstream out("native.json");
    out << "{\"status\":" << json_string(detail.empty() ? "passed" : "failed")
        << ",\"detail\":" << (detail.empty() ? "null" : json_string(detail))
        << ",\"cycles\":" << cycles << ",\"retired\":" << retired
        << ",\"exit_code\":" << exit_code << ",\"start\":" << start.json()
        << ",\"stop\":" << stop.json() << ",\"bpu_start\":" << bpu_start.json()
        << ",\"bpu_stop\":" << bpu_stop.json() << "}\n";
    if (!detail.empty()) std::cerr << detail << '\n';
    return detail.empty() ? 0 : 1;
}
