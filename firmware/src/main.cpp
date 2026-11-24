#include <Arduino.h>
#include <avr/interrupt.h>
#include "acquisition.h"
#include "config.h"

using acquisition::Series;
using acquisition::elapsed;

namespace {
bool running = false;
bool collecting = false;
bool taring = false;
bool tareValid = false;
float tareCounts = NAN;
uint16_t tareRevision = 0;
uint32_t cycle = 0;
uint32_t lastCycleStart = 0;
uint32_t windowStart = 0;
uint32_t lastNtc = 0;
uint32_t tareStart = 0;
uint32_t lateMs = 0;
uint32_t lastClock = 0;
uint32_t wraps = 0;
Series hx, ntc, tareSeries;

// Não espera DOUT: o loop continua disponível para NTC, comandos e timeout.
// Lê sempre, mesmo fora da janela, evitando reter uma conversão antiga no HX711.
bool readHx(int32_t &value) {
    if (digitalRead(config::HX_DOUT) != LOW) return false;
    uint32_t bits = 0;
    uint8_t previous = SREG;
    cli();
    for (uint8_t i = 0; i < 24; ++i) {
        digitalWrite(config::HX_SCK, HIGH);
        delayMicroseconds(1);
        bits = (bits << 1) | (digitalRead(config::HX_DOUT) == HIGH ? 1UL : 0UL);
        digitalWrite(config::HX_SCK, LOW);
        delayMicroseconds(1);
    }
    // Pulso 25 seleciona canal A, ganho 128, para a próxima conversão.
    digitalWrite(config::HX_SCK, HIGH);
    delayMicroseconds(1);
    digitalWrite(config::HX_SCK, LOW);
    delayMicroseconds(1);
    SREG = previous;
    value = acquisition::signed24(bits);
    return true;
}

void number(float value, uint8_t digits = 6) {
    if (isfinite(value)) Serial.print(value, digits);
    else Serial.print(F("nan"));
}
void comma() { Serial.print(','); }
void stamp(const Series &series, bool first) {
    if (series.count) Serial.print(first ? series.first : series.last);
    else Serial.print(F("nan"));
}
void header() {
    Serial.println(F("schema,cycle,millis_wraps,window_start_ms,window_end_ms,late_ms,hx_first_ms,hx_last_ms,hx_valid,hx_attempts,hx_mean_counts,tare_counts,tare_revision,hx_corrected_counts,ntc_first_ms,ntc_last_ms,ntc_valid,ntc_attempts,ntc_adc_mean,ntc_resistance_ohms,temperature_C,cell_deflection_mm,midpoint_skew_ms,flags"));
}

void updateClock(uint32_t now) {
    if (now < lastClock) ++wraps;
    lastClock = now;
}

void emit(uint32_t now, uint16_t reason = 0) {
    updateClock(now);
    uint16_t flags = reason;
    if (hx.count != config::SAMPLES) flags |= acquisition::HX_INCOMPLETE;
    if (hx.rail) flags |= acquisition::HX_RAIL;
    if (!tareValid) flags |= acquisition::NO_TARE;
    if (!config::NTC_ENABLED) flags |= acquisition::NTC_DISABLED;
    else {
        if (ntc.count != config::SAMPLES) flags |= acquisition::NTC_INCOMPLETE;
        if (ntc.rail) flags |= acquisition::NTC_RAIL;
    }
    if (!config::NTC_MODEL_ENABLED) flags |= acquisition::NTC_UNCONFIGURED;
    if (!config::DISPLACEMENT_ENABLED) flags |= acquisition::DISPLACEMENT_UNCONFIGURED;
    if (lateMs) flags |= acquisition::LATE;
    bool paired = hx.count && ntc.count;
    uint32_t skewMs = paired ? acquisition::skew(hx, ntc) : 0;
    if (paired && skewMs > config::MAX_MIDPOINT_SKEW_MS) flags |= acquisition::TEMPORAL_SKEW;
    float corrected = tareValid ? hx.mean() - tareCounts : NAN;
    float resistance = NAN, temp = NAN, deflection = NAN;
    // Falha ou janela parcial não produz uma grandeza física aparentemente válida.
    if (config::NTC_ENABLED && config::NTC_MODEL_ENABLED
            && ntc.count == config::SAMPLES && !ntc.rail) {
        resistance = acquisition::resistance(ntc.mean(), config::SERIES_OHMS, config::NTC_TO_GROUND);
        temp = acquisition::temperature(resistance, config::NTC_R0_OHMS,
                                       config::NTC_BETA_K, config::NTC_T0_C);
        if (!isfinite(temp)) flags |= acquisition::CONVERSION_INVALID;
    }
    if (config::DISPLACEMENT_ENABLED && tareValid && hx.count == config::SAMPLES && !hx.rail) {
        if (isfinite(config::MM_PER_COUNT) && config::MM_PER_COUNT != 0)
            deflection = corrected * config::MM_PER_COUNT;
        if (!isfinite(deflection)) flags |= acquisition::CONVERSION_INVALID;
    }
    Serial.print(1); comma(); Serial.print(cycle); comma(); Serial.print(wraps); comma();
    Serial.print(windowStart); comma(); Serial.print(now); comma(); Serial.print(lateMs); comma();
    stamp(hx, true); comma(); stamp(hx, false); comma();
    Serial.print(hx.count); comma(); Serial.print(hx.attempts); comma(); number(hx.mean(), 2); comma();
    number(tareCounts, 2); comma(); Serial.print(tareRevision); comma(); number(corrected, 2); comma();
    stamp(ntc, true); comma(); stamp(ntc, false); comma();
    Serial.print(ntc.count); comma(); Serial.print(ntc.attempts); comma(); number(ntc.mean(), 3); comma();
    number(resistance, 3); comma(); number(temp, 4); comma(); number(deflection); comma();
    if (paired) Serial.print(skewMs); else Serial.print(F("nan"));
    comma(); Serial.println(flags);
}

void commands(uint32_t now) {
    if (!Serial.available()) return;
    char command = Serial.read();
    if (command == '\r' || command == '\n' || command == ' ') return;
    if (command == 's') {
        if (taring) { Serial.println(F("# busy,tare")); return; }
        if (!running) {
            running = true;
            lastCycleStart = now; // Primeiro ciclo após INTERVAL_MS; permite estabilização.
            Serial.println(F("# acquisition,started"));
        }
    } else if (command == 'p') {
        if (collecting) { emit(now, acquisition::CANCELLED); collecting = false; }
        running = false;
        Serial.println(F("# acquisition,paused"));
    } else if (command == 't') {
        if (running || taring) { Serial.println(F("# tare,rejected,pause_first")); return; }
        taring = true;
        tareSeries = Series{};
        tareStart = now;
        Serial.println(F("# tare,started,reference_must_be_stable"));
    } else if (command == 'h') {
        Serial.println(F("# commands,s=start p=pause t=tare_when_paused h=help"));
    } else Serial.println(F("# command,unknown"));
}
}

void setup() {
    pinMode(config::HX_DOUT, INPUT_PULLUP);
    pinMode(config::HX_SCK, OUTPUT);
    pinMode(config::LED_PIN, OUTPUT);
    digitalWrite(config::HX_SCK, LOW);
    digitalWrite(config::LED_PIN, LOW);
    analogReference(DEFAULT);
    Serial.begin(config::SERIAL_BAUD);
    Serial.println(F("# boot,system_dilatation,firmware=1,board=uno,cell_capacity_kg=5"));
    Serial.println(F("# clock,millis_since_boot,window_times_are_readout_times"));
    Serial.print(F("# interval_ms,")); Serial.println(config::INTERVAL_MS);
    Serial.print(F("# window_timeout_ms,")); Serial.println(config::WINDOW_TIMEOUT_MS);
    Serial.print(F("# target_samples,")); Serial.println(config::SAMPLES);
    Serial.print(F("# ntc_sample_ms,")); Serial.println(config::NTC_SAMPLE_MS);
    Serial.print(F("# max_midpoint_skew_ms,")); Serial.println(config::MAX_MIDPOINT_SKEW_MS);
    Serial.print(F("# ntc_enabled,")); Serial.println(config::NTC_ENABLED);
    Serial.print(F("# ntc_model_enabled,")); Serial.println(config::NTC_MODEL_ENABLED);
    Serial.print(F("# ntc_to_ground,")); Serial.println(config::NTC_TO_GROUND);
    Serial.print(F("# ntc_series_ohms,")); number(config::SERIES_OHMS, 3); Serial.println();
    Serial.print(F("# ntc_r0_ohms,")); number(config::NTC_R0_OHMS, 3); Serial.println();
    Serial.print(F("# ntc_beta_K,")); number(config::NTC_BETA_K, 3); Serial.println();
    Serial.print(F("# ntc_t0_C,")); number(config::NTC_T0_C, 3); Serial.println();
    Serial.print(F("# ntc_calibration,")); Serial.println(config::NTC_CALIBRATION_ID);
    Serial.print(F("# displacement_enabled,")); Serial.println(config::DISPLACEMENT_ENABLED);
    Serial.print(F("# mm_per_count,")); number(config::MM_PER_COUNT, 9); Serial.println();
    Serial.print(F("# displacement_calibration,")); Serial.println(config::DISPLACEMENT_CALIBRATION_ID);
    Serial.println(F("# paused,send_s_to_start,t_to_tare,h_for_help"));
    header();
    lastClock = millis();
}

void loop() {
    uint32_t now = millis();
    updateClock(now);
    commands(now);
    if (running && !collecting && elapsed(now, lastCycleStart) >= config::INTERVAL_MS) {
        lateMs = elapsed(now, lastCycleStart) - config::INTERVAL_MS;
        lastCycleStart = windowStart = now;
        lastNtc = now - config::NTC_SAMPLE_MS;
        hx = Series{};
        ntc = Series{};
        collecting = true;
        ++cycle;
    }
    // Fecha a janela antes de aceitar novas amostras após o prazo.
    if (collecting && elapsed(now, windowStart) >= config::WINDOW_TIMEOUT_MS) {
        collecting = false;
        emit(now, acquisition::WINDOW_TIMEOUT);
    }
    if (taring && elapsed(now, tareStart) >= config::TARE_TIMEOUT_MS) {
        taring = false;
        Serial.println(F("# tare,failed,previous_reference_preserved"));
    }
    int32_t value;
    if (readHx(value)) {
        bool valid = value != -8388608L && value != 8388607L;
        if (taring && tareSeries.attempts < config::TARE_SAMPLES) {
            tareSeries.add(value, now, valid);
            if (tareSeries.attempts == config::TARE_SAMPLES) {
                taring = false;
                if (tareSeries.count == config::TARE_SAMPLES && !tareSeries.rail) {
                    tareCounts = tareSeries.mean();
                    tareValid = true;
                    ++tareRevision;
                    Serial.print(F("# tare,ok,revision=")); Serial.print(tareRevision);
                    Serial.print(F(",counts=")); number(tareCounts, 2); Serial.println();
                } else Serial.println(F("# tare,failed,previous_reference_preserved"));
            }
        } else if (collecting && hx.attempts < config::SAMPLES) hx.add(value, now, valid);
    }
    if (collecting && config::NTC_ENABLED && ntc.attempts < config::SAMPLES
            && elapsed(now, lastNtc) >= config::NTC_SAMPLE_MS) {
        lastNtc = now;
        int valueNtc = analogRead(config::NTC_PIN);
        ntc.add(valueNtc, millis(), valueNtc > 0 && valueNtc < 1023);
    }
    if (collecting && hx.attempts == config::SAMPLES
            && (!config::NTC_ENABLED || ntc.attempts == config::SAMPLES)) {
        collecting = false;
        emit(millis());
    }
    digitalWrite(config::LED_PIN, collecting || taring ? HIGH : LOW);
}
