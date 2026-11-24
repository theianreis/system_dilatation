#pragma once
#include <stdint.h>
#include <iomanip>
#include <sstream>
#include <string>
#define F(text) text
#define LOW 0
#define HIGH 1
#define OUTPUT 1
#define INPUT_PULLUP 2
#define DEFAULT 1

extern uint32_t fakeNow;
extern uint32_t fakeHxNext;
extern uint32_t fakeHxPeriod;
extern bool fakeConnected;
extern bool fakeClockHigh;
extern uint8_t fakePulse;
extern int32_t fakeHxValue;
extern int fakeNtcValue;

inline unsigned long millis() { return fakeNow; }
inline void pinMode(uint8_t, uint8_t) {}
inline void analogReference(uint8_t) {}
inline void delayMicroseconds(unsigned int) {}
inline int analogRead(uint8_t) { return fakeNtcValue; }
inline int digitalRead(uint8_t pin) {
    if (pin != 2) return LOW;
    if (!fakeClockHigh) return !fakeConnected || int32_t(fakeNow - fakeHxNext) < 0 ? HIGH : LOW;
    return (uint32_t(fakeHxValue) >> (23 - fakePulse)) & 1;
}
inline void digitalWrite(uint8_t pin, uint8_t value) {
    if (pin != 3) return;
    if (value == HIGH) fakeClockHigh = true;
    else if (fakeClockHigh) {
        fakeClockHigh = false;
        if (++fakePulse == 25) { fakePulse = 0; fakeHxNext = fakeNow + fakeHxPeriod; }
    }
}
struct FakeSerial {
    std::string input;
    std::ostringstream output;
    void begin(uint32_t) {}
    int available() { return input.size(); }
    char read() { char c = input[0]; input.erase(0, 1); return c; }
    void print(const char *s) { output << s; }
    void print(char c) { output << c; }
    void print(float f, uint8_t digits) { output << std::fixed << std::setprecision(digits) << f; }
    template <typename T> void print(T v) { output << +v; }
    void println() { output << '\n'; }
    template <typename T> void println(T v) { print(v); println(); }
};
extern FakeSerial Serial;
