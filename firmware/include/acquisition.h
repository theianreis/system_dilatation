#pragma once

#include <math.h>
#include <stdint.h>

namespace acquisition {
// Subtração modular: funciona na passagem de millis() por zero.
inline uint32_t elapsed(uint32_t now, uint32_t then) { return now - then; }

struct Series {
    int64_t sum = 0;
    uint16_t count = 0;
    uint16_t attempts = 0;
    uint32_t first = 0;
    uint32_t last = 0;
    bool rail = false;

    void add(int32_t value, uint32_t at, bool valid) {
        ++attempts;
        if (!valid) { rail = true; return; }
        if (count == 0) first = at;
        last = at;
        sum += value;
        ++count;
    }
    float mean() const { return count ? static_cast<float>(sum) / count : NAN; }
    uint32_t midpoint() const { return first + elapsed(last, first) / 2; }
};

inline uint32_t skew(const Series &a, const Series &b) {
    uint32_t difference = a.midpoint() - b.midpoint();
    return difference <= 0x7FFFFFFFUL ? difference : 0UL - difference;
}

inline int32_t signed24(uint32_t value) {
    return (value & 0x800000UL) ? static_cast<int32_t>(value) - 16777216L
                                 : static_cast<int32_t>(value);
}

inline float resistance(float adc, float series, bool ntcToGround) {
    if (!isfinite(adc) || adc <= 0 || adc >= 1023 || !isfinite(series) || series <= 0)
        return NAN;
    return ntcToGround ? series * adc / (1023.0f - adc)
                       : series * (1023.0f - adc) / adc;
}

inline float temperature(float resistanceOhms, float r0, float beta, float t0C) {
    if (!isfinite(resistanceOhms) || resistanceOhms <= 0 || !isfinite(r0) || r0 <= 0
            || !isfinite(beta) || beta <= 0 || !isfinite(t0C) || t0C <= -273.15f)
        return NAN;
    float inverseK = 1.0f / (t0C + 273.15f) + logf(resistanceOhms / r0) / beta;
    return inverseK > 0 ? 1.0f / inverseK - 273.15f : NAN;
}

enum Flag : uint16_t {
    HX_INCOMPLETE = 1, HX_RAIL = 2, NO_TARE = 4,
    NTC_DISABLED = 8, NTC_INCOMPLETE = 16, NTC_RAIL = 32,
    NTC_UNCONFIGURED = 64, DISPLACEMENT_UNCONFIGURED = 128,
    TEMPORAL_SKEW = 256, LATE = 512, CONVERSION_INVALID = 1024,
    CANCELLED = 2048, WINDOW_TIMEOUT = 4096
};
}
