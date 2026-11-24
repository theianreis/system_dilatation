"""Parser estrito do protocolo CSV v1; não converte ausência em zero."""
import csv
import hashlib
import io
import math

FIELDS = ('schema,cycle,millis_wraps,window_start_ms,window_end_ms,late_ms,hx_first_ms,'
          'hx_last_ms,hx_valid,hx_attempts,hx_mean_counts,tare_counts,tare_revision,'
          'hx_corrected_counts,ntc_first_ms,ntc_last_ms,ntc_valid,ntc_attempts,'
          'ntc_adc_mean,ntc_resistance_ohms,temperature_C,cell_deflection_mm,'
          'midpoint_skew_ms,flags').split(',')
INTS = set(('schema cycle millis_wraps window_start_ms window_end_ms late_ms hx_valid '
            'hx_attempts tare_revision ntc_valid ntc_attempts flags').split())
STAMPS = {'hx_first_ms', 'hx_last_ms', 'ntc_first_ms', 'ntc_last_ms'}


def parse(data: bytes):
    """Valida tudo antes da persistência. Retorna sessões e hash da captura."""
    sessions = []
    current = None
    header = False
    for line_no, text in enumerate(data.decode('utf-8-sig').splitlines(), 1):
        if not text.strip():
            continue
        if text.startswith('# boot,'):
            current = {'events': [], 'rows': [], 'metadata': {}}
            sessions.append(current)
            header = False
        if current is None:
            raise ValueError(f'Linha {line_no}: captura precisa começar com # boot.')
        if text.startswith('#'):
            current['events'].append((line_no, text))
            key, _, value = text[1:].strip().partition(',')
            current['metadata'][key] = value
            continue
        values = next(csv.reader([text]))
        if values == FIELDS:
            if header:
                raise ValueError(f'Linha {line_no}: cabeçalho repetido sem boot.')
            header = True
            continue
        if not header or len(values) != len(FIELDS):
            raise ValueError(f'Linha {line_no}: cabeçalho ausente ou registro truncado.')
        row = {}
        try:
            for field, value in zip(FIELDS, values):
                if field in INTS:
                    row[field] = int(value)
                    if row[field] < 0:
                        raise ValueError('inteiro negativo')
                elif value.lower() == 'nan':
                    row[field] = None
                else:
                    row[field] = float(value)
                    if not math.isfinite(row[field]):
                        raise ValueError('valor não finito')
                if field in STAMPS and row[field] is not None:
                    if not row[field].is_integer() or not 0 <= row[field] <= 0xFFFFFFFF:
                        raise ValueError('timestamp inválido')
                    row[field] = int(row[field])
            if row['schema'] != 1 or row['cycle'] < 1 or row['flags'] & ~8191:
                raise ValueError('versão, ciclo ou flags inválidos')
            for field in ('window_start_ms', 'window_end_ms', 'late_ms'):
                if row[field] > 0xFFFFFFFF:
                    raise ValueError('timestamp excede 32 bits')
            for sensor, mean in (('hx', 'hx_mean_counts'), ('ntc', 'ntc_adc_mean')):
                valid, attempts = row[sensor + '_valid'], row[sensor + '_attempts']
                if not 0 <= valid <= attempts <= 255:
                    raise ValueError('contagem de amostras inválida')
                if bool(valid) != (row[mean] is not None):
                    raise ValueError('média incompatível com contagem')
                for suffix in ('_first_ms', '_last_ms'):
                    if bool(valid) != (row[sensor + suffix] is not None):
                        raise ValueError('janela incompatível com contagem')
            if row['ntc_adc_mean'] is not None and not 0 < row['ntc_adc_mean'] < 1023:
                raise ValueError('ADC NTC inválido')
            target = int(current['metadata'].get('target_samples', '10'))
            if not 1 <= target <= 255:
                raise ValueError('alvo de amostras inválido')
            if row['hx_valid'] < target and not row['flags'] & 1:
                raise ValueError('HX711 incompleto sem flag correspondente')
            if not row['flags'] & 8 and row['ntc_valid'] < target and not row['flags'] & 16:
                raise ValueError('NTC incompleto sem flag correspondente')
            if row['hx_mean_counts'] is not None and not -8388608 < row['hx_mean_counts'] < 8388607:
                raise ValueError('média HX711 fora da faixa')
            end = row['millis_wraps'] * 2**32 + row['window_end_ms']
            duration = (row['window_end_ms'] - row['window_start_ms']) % 2**32
            if duration >= 2**31:
                raise ValueError('janela temporal inválida')
            if current['rows']:
                previous = current['rows'][-1][1]
                previous_end = previous['millis_wraps'] * 2**32 + previous['window_end_ms']
                if end <= previous_end:
                    raise ValueError('tempo não crescente na sessão')
            if current['rows'] and row['cycle'] <= current['rows'][-1][1]['cycle']:
                raise ValueError('ciclo repetido ou fora de ordem')
        except ValueError as error:
            raise ValueError(f'Linha {line_no}: {error}') from error
        current['rows'].append((line_no, row))
    if not sessions or any(not session['rows'] for session in sessions):
        raise ValueError('Captura sem ciclos em uma das sessões.')
    return hashlib.sha256(data).hexdigest(), sessions
