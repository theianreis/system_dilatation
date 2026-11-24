#include <assert.h>
#include <iostream>
#include <cstdlib>
#include <vector>
#include "Arduino.h"
uint32_t fakeNow = 0, fakeHxNext = 0, fakeHxPeriod = 100;
bool fakeConnected = true, fakeClockHigh = false;
uint8_t fakePulse = 0, SREG = 0;
int32_t fakeHxValue = 1000;
int fakeNtcValue = 512;
FakeSerial Serial;
#include "../../src/main.cpp"

void step(uint32_t duration) {
    for (uint32_t i = 0; i < duration; ++i) { ++fakeNow; loop(); }
}
void command(char c) { Serial.input += c; loop(); }
std::vector<std::vector<std::string>> rows() {
    std::vector<std::vector<std::string>> result;
    std::istringstream stream(Serial.output.str());
    std::string line;
    while (std::getline(stream, line)) {
        if (line.rfind("1,", 0) != 0) continue;
        std::vector<std::string> fields;
        std::istringstream csv(line);
        std::string field;
        while (std::getline(csv, field, ',')) fields.push_back(field);
        assert(fields.size() == 24);
        result.push_back(fields);
    }
    return result;
}
int main(int argc, char **argv) {
    assert(argc == 2);
    std::string scenario = argv[1];
    if (scenario == "wrap") fakeNow = fakeHxNext = 0xFFFFF000UL;
    if (scenario == "skew") fakeHxPeriod = 20;
    setup();
    step(1000);
    assert(rows().empty()); // Inicia pausado.
    if (scenario == "timeout") fakeConnected = false;
    if (scenario == "rail") fakeHxValue = 8388607;
    if (scenario == "ntc_rail") fakeNtcValue = 0;
    if (scenario == "tare" || scenario == "tare_failure") {
        command('t'); step(2500);
        assert(Serial.output.str().find("# tare,ok") != std::string::npos);
        fakeHxValue = 1100;
        if (scenario == "tare_failure") {
            fakeConnected = false;
            command('t'); step(5100);
            assert(Serial.output.str().find("# tare,failed") != std::string::npos);
            fakeConnected = true;
        }
    }
    command('s');
    if (scenario == "tare_busy") {
        command('t');
        assert(Serial.output.str().find("pause_first") != std::string::npos);
    }
    if (scenario == "pause") {
        step(10200); command('p');
        auto data = rows();
        assert(data.size() == 1);
        assert(std::stoi(data[0][23]) & acquisition::HX_INCOMPLETE);
        assert(std::stoi(data[0][23]) & acquisition::CANCELLED);
        step(15000); assert(rows().size() == 1);
        return 0;
    }
    step(13000);
    auto data = rows();
    assert(data.size() == 1);
    auto row = data[0];
    uint16_t flags = std::stoi(row[23]);
    if (scenario == "timeout" || scenario == "rail") {
        assert(flags & acquisition::HX_INCOMPLETE);
        assert(row[10] == "nan" && row[21] == "nan");
        if (scenario == "rail") assert(flags & acquisition::HX_RAIL);
        else assert(flags & acquisition::WINDOW_TIMEOUT);
    } else {
        assert(std::stoi(row[8]) == 10);
        assert(!(flags & acquisition::HX_INCOMPLETE));
    }
    if (scenario == "tare" || scenario == "tare_failure") {
        assert(!(flags & acquisition::NO_TARE));
        assert(std::stoi(row[12]) == 1);
        assert(std::stof(row[13]) == 100);
        if (config::DISPLACEMENT_ENABLED) assert(std::stof(row[21]) == 0.1f);
    } else {
        assert(flags & acquisition::NO_TARE);
        assert(row[13] == "nan" && row[21] == "nan");
    }
    if (!config::NTC_ENABLED) {
        assert(flags & acquisition::NTC_DISABLED);
        assert(row[18] == "nan" && row[20] == "nan");
    } else if (scenario == "ntc_rail") {
        assert(flags & acquisition::NTC_RAIL);
        assert(flags & acquisition::NTC_INCOMPLETE);
        assert(row[20] == "nan");
    } else {
        assert(std::stoi(row[16]) == 10);
        assert(!(flags & acquisition::NTC_INCOMPLETE));
        if (config::NTC_MODEL_ENABLED) {
            assert(std::stof(row[20]) > 24 && std::stof(row[20]) < 26);
        } else assert(row[20] == "nan");
    }
    if (scenario == "skew" && config::NTC_ENABLED) assert(flags & acquisition::TEMPORAL_SKEW);
    if (scenario == "wrap") assert(std::stoul(row[2]) == 1);
    command('p'); step(15000); assert(rows().size() == 1);
    if (scenario == "dump") std::cout << Serial.output.str();
}
