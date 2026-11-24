from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import linregress
from ..acquisition.protocol import parse


def ajustar_calibracao(caminho, tipo, referencia):
    if not referencia.strip():
        raise ValueError('Identifique o instrumento/procedimento de referência.')
    source = Path(caminho).read_bytes()
    df = pd.read_csv(caminho)
    columns = ['counts', 'displacement_mm'] if tipo == 'deslocamento' else ['resistance_ohms', 'temperature_C']
    values = df[columns].to_numpy(dtype=float)
    if len(df) < 3 or not np.isfinite(values).all():
        raise ValueError('Calibração exige ao menos três pares finitos.')
    x, y = values.T
    if tipo == 'ntc':
        if (x <= 0).any() or (y <= -273.15).any():
            raise ValueError('Resistência ou temperatura inválida.')
        x, y = np.log(x), 1 / (y + 273.15)
    if np.ptp(x) == 0:
        raise ValueError('Referências sem variação.')
    fit = linregress(x, y)
    if tipo == 'ntc':
        if fit.slope <= 0:
            raise ValueError('Ajuste incompatível com NTC beta positivo.')
        parameters = {'beta_K': 1 / fit.slope, 'r0_ohms': float(np.exp((1 / 298.15 - fit.intercept) / fit.slope)), 't0_C': 25.0}
    else:
        # Intercepto é preservado: tara futura deve ser consistente com a referência.
        parameters = {'mm_per_count': fit.slope, 'intercept_mm': fit.intercept}
    return {'tipo': tipo, 'parametros': parameters, 'referencia': referencia,
            'fonte_sha256': hashlib.sha256(source).hexdigest(),
            'criado_em': datetime.now(timezone.utc).isoformat(), 'validada_experimentalmente': False,
            'amostras': len(df), 'faixa_entrada': [float(values[:, 0].min()), float(values[:, 0].max())],
            'R2': float(fit.rvalue ** 2), 'unidade_RMSE_ajuste': '1/K' if tipo == 'ntc' else 'mm', 'RMSE_ajuste': float(np.sqrt(np.mean((y - (fit.slope * x + fit.intercept)) ** 2)))}


def analisar_serie(df, comprimento_mm, material):
    if not material.strip() or not math.isfinite(comprimento_mm) or comprimento_mm <= 0:
        raise ValueError('Informe material e comprimento positivo.')
    columns = ['tempo_s', 'temperatura_C', 'deslocamento_mm']
    a = df[columns].to_numpy(dtype=float)
    if len(df) < 3 or not np.isfinite(a).all() or (np.diff(a[:, 0]) <= 0).any():
        raise ValueError('Série exige três pares finitos com tempo crescente.')
    peak = int(np.argmax(a[:, 1])) # Independente do deslocamento.
    fits = []
    for phase, part in (('aquecimento', a[:peak + 1]), ('resfriamento', a[peak + 1:])):
        if len(part) < 3 or np.ptp(part[:, 1]) == 0:
            continue
        fit = linregress(part[:, 1] - a[0, 1], part[:, 2])
        residual = part[:, 2] - (fit.slope * (part[:, 1] - a[0, 1]) + fit.intercept)
        fits.append({'fase': phase, 'n': len(part), 'inclinacao_mm_C': float(fit.slope),
                     'intercepto_mm': float(fit.intercept), 'alpha_aparente_C_inv': float(fit.slope / comprimento_mm),
                     'R2': float(fit.rvalue ** 2) if np.ptp(part[:, 2]) else None,
                     'RMSE_mm': float(np.sqrt(np.mean(residual ** 2))), 'residuos_mm': residual.tolist()})
    if not fits:
        raise ValueError('Nenhuma fase com pontos e variação suficientes.')
    return {'material_informado': material, 'comprimento_mm': comprimento_mm, 'temperatura_origem': 'medida',
            'classificacao': 'coeficientes_aparentes', 'criterio_fases': 'primeiro máximo da temperatura medida; pico só no aquecimento',
            'ajustes': fits, 'nota': 'Calibração e relação mecânica precisam de validação independente.'}


def processar_captura(caminho, parametros):
    """Parâmetros explícitos; ignora conversões antigas e mantém motivos de exclusão."""
    digest, sessions = parse(Path(caminho).read_bytes())
    if not isinstance(parametros, dict) or type(parametros.get('ntc_to_ground')) is not bool:
        raise ValueError('ntc_to_ground deve ser booleano JSON.')
    result = []
    for index, session in enumerate(sessions):
        accepted, excluded = [], []
        for line, row in session['rows']:
            flags = row['flags']
            if flags & (1 | 2 | 4 | 8 | 16 | 32 | 256 | 2048 | 4096):
                excluded.append({'linha': line, 'cycle': row['cycle'], 'motivo': 'qualidade', 'flags': flags})
                continue
            adc, counts = row['ntc_adc_mean'], row['hx_corrected_counts']
            if adc is None or counts is None:
                raise ValueError(f'Linha {line}: faltam leituras para conversão.')
            resistor = float(parametros['series_ohms'])
            beta, r0, t0 = (float(parametros[k]) for k in ('beta_K', 'r0_ohms', 't0_C'))
            factor = float(parametros['mm_per_count'])
            if not all(math.isfinite(v) for v in (resistor, beta, r0, t0, factor)) or min(resistor, beta, r0) <= 0 or t0 <= -273.15 or factor == 0:
                raise ValueError('Parâmetros físicos inválidos.')
            resistance = resistor * adc / (1023 - adc) if parametros['ntc_to_ground'] else resistor * (1023 - adc) / adc
            inverse = 1 / (t0 + 273.15) + math.log(resistance / r0) / beta
            if inverse <= 0:
                raise ValueError('Temperatura calculada inválida.')
            end = row['millis_wraps'] * 2**32 + row['window_end_ms']
            if not math.isfinite(counts * factor):
                raise ValueError('Conversão de deslocamento não finita.')
            accepted.append({'cycle': row['cycle'], 'tempo_s': end / 1000,
                             'temperatura_C': 1 / inverse - 273.15, 'deslocamento_mm': counts * factor})
        result.append({'sessao': index, 'pares': accepted, 'excluidos': excluded})
    return {'fonte_sha256': digest, 'parametros': parametros, 'sessoes': result,
            'classificacao': 'estimativas_dependentes_de_validacao'}
