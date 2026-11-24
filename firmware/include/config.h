#pragma once

#include <stdint.h>

namespace config {
constexpr uint8_t HX_DOUT = 2;
constexpr uint8_t HX_SCK = 3;
constexpr uint8_t NTC_PIN = 14;  // A0 no Uno.
constexpr uint8_t LED_PIN = 13;
constexpr uint32_t SERIAL_BAUD = 115200;

// Valores iniciais de engenharia, ainda não requisitos experimentais validados.
constexpr uint32_t INTERVAL_MS = 10000;
constexpr uint32_t WINDOW_TIMEOUT_MS = 2500;
constexpr uint8_t SAMPLES = 10;
constexpr uint32_t NTC_SAMPLE_MS = 100;
constexpr uint32_t MAX_MIDPOINT_SKEW_MS = 250;
constexpr uint32_t TARE_TIMEOUT_MS = 5000;
constexpr uint8_t TARE_SAMPLES = 20;

// Habilitar somente após montar o circuito. Não ligar A0 em paralelo ao display.
constexpr bool NTC_ENABLED = false;
// Divisor: VCC -- resistor fixo -- A0 -- NTC -- GND, alimentado pelo AVCC do Uno.
// false inverte as posições do NTC e do resistor no divisor.
constexpr bool NTC_TO_GROUND = true;
constexpr bool NTC_MODEL_ENABLED = false;
constexpr float SERIES_OHMS = 0.0f;
constexpr float NTC_R0_OHMS = 0.0f;
constexpr float NTC_BETA_K = 0.0f;
constexpr float NTC_T0_C = 25.0f;
constexpr char NTC_CALIBRATION_ID[] = "pendente";

// Conversão direta da deflexão no ponto calibrado; NÃO é dilatação livre da barra.
// delta_mm = (media_bruta - tara) * MM_PER_COUNT. Aceita sinal positivo ou negativo.
constexpr bool DISPLACEMENT_ENABLED = false;
constexpr float MM_PER_COUNT = 0.0f;
constexpr char DISPLACEMENT_CALIBRATION_ID[] = "pendente";

static_assert(SAMPLES > 0 && TARE_SAMPLES > 0, "Numero de amostras invalido");
static_assert(INTERVAL_MS > WINDOW_TIMEOUT_MS, "Janela deve caber no intervalo");
static_assert(NTC_SAMPLE_MS > 0 && (SAMPLES - 1UL) * NTC_SAMPLE_MS < WINDOW_TIMEOUT_MS,
              "Amostragem NTC nao cabe na janela");
static_assert(INTERVAL_MS < 0x80000000UL && TARE_TIMEOUT_MS < 0x80000000UL,
              "Intervalo excede limite do relogio");
}
