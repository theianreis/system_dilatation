#include <assert.h>
#include <math.h>
#include "acquisition.h"

int main() {
    using namespace acquisition;
    assert(signed24(0) == 0);
    assert(signed24(0x7FFFFF) == 8388607);
    assert(signed24(0x800000) == -8388608);
    assert(signed24(0xFFFFFF) == -1);
    assert(elapsed(20, 0xFFFFFFF0UL) == 36);
    Series a, b;
    assert(isnan(a.mean()));
    a.add(-100, 0xFFFFFFF0UL, true);
    a.add(300, 20, true);
    a.add(8388607, 25, false);
    assert(a.count == 2 && a.attempts == 3 && a.rail);
    assert(a.mean() == 100);
    assert(a.first == 0xFFFFFFF0UL && a.last == 20 && a.midpoint() == 2);
    b.add(100, 12, true);
    assert(skew(a, b) == 10 && skew(b, a) == 10);
    Series large;
    for (int i = 0; i < 255; ++i) large.add(8388606, i, true);
    assert(large.sum == 2139094530LL);
    // Divisores em ambas as orientações e pontos independentes conhecidos.
    assert(fabs(resistance(511.5f, 10000, true) - 10000) < 0.1);
    assert(fabs(resistance(341, 10000, true) - 5000) < 0.1);
    assert(fabs(resistance(341, 10000, false) - 20000) < 0.1);
    assert(isnan(resistance(0, 10000, true)));
    assert(isnan(resistance(1023, 10000, false)));
    assert(isnan(resistance(500, 0, false)));
    assert(fabs(temperature(10000, 10000, 3950, 25) - 25) < 0.001);
    assert(fabs(temperature(3588.18f, 10000, 3950, 25) - 50) < 0.01);
    assert(isnan(temperature(10000, 10000, 0, 25)));
    assert(isnan(temperature(-1, 10000, 3950, 25)));
    assert(isnan(temperature(10000, 10000, 3950, -273.15f)));
}
