// Verification-only compressed gate activity. Time is in ps, independent of
// the native driver's delta-evaluation counter. Capture post-edge state at the
// start marker through post-edge state at the stop marker: exactly N periods.
#ifndef UQU_ACTIVITY_VCD_H
#define UQU_ACTIVITY_VCD_H
#include "verilated_vcd_c.h"
#include <zlib.h>
#include <cstdlib>
#include <stdexcept>

class GzipVcdFile final : public VerilatedVcdFile {
    gzFile file = nullptr;
public:
    bool open(const std::string &name) override {
        file = gzopen(name.c_str(), "wb1");
        return file != nullptr;
    }
    void close() override {
        if (file) {
            int result = gzclose(file);
            file = nullptr;
            if (result != Z_OK) throw std::runtime_error("cannot finish activity VCD");
        }
    }
    ssize_t write(const char *data, ssize_t size) override {
        int written = gzwrite(file, data, unsigned(size));
        return written == size ? size : -1;
    }
};

struct ActivityVcd {
    GzipVcdFile file;
    VerilatedVcdC trace{&file};
    uint64_t time = 0, period = 0;
    bool active = false;
    ActivityVcd() {
        const char *value = std::getenv("UQU_POWER_PERIOD_PS");
        if (!value) throw std::runtime_error("missing UQU_POWER_PERIOD_PS");
        period = std::stoull(value);
        if (!period || period % 2) throw std::runtime_error("power period must be positive even ps");
        // This helper is constructed before the DUT sets the context units.
        // dump() timestamps below are explicitly picoseconds.
        trace.set_time_unit("1ps");
        trace.set_time_resolution("1ps");
    }
    void rising(bool start, bool stop) {
        if (start) { trace.open("activity.vcd.gz"); active = true; }
        if (active) {
            trace.dump(time);
            if (stop) { trace.close(); active = false; }
            else time += period / 2;
        }
    }
    void low() {
        if (active) { trace.dump(time); time += period / 2; }
    }
};
#endif
