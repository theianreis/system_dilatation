# %% [markdown]
# Análise dos ensaios históricos com temperaturas medidas informadas pelo usuário.
# Preserva fontes, não força coincidência entre os máximos de temperatura e ΔL.
# Os valores de ΔL do firmware antigo continuam sendo estimativas não calibradas.
# Uso: PYTHONPATH=src python analysis/ensaios_historicos.py --help

# %%
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import numpy as np
import pandas as pd
from system_dilatation.science.analysis import analisar_serie

COLUMNS = ['leitura','tempo_s','bits','bits_tara','amostras_validas','tensao_mV','forca_N','deltaL_mm']


def ler_txt(path):
    rows=[]
    for n,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        if not re.match(r'^\s*[+-]?\d',line): continue
        fields=next(csv.reader([line]))
        if len(fields)!=8: raise ValueError(f'{path}:{n}: registro incompleto')
        values=[float(v) for v in fields]
        if not all(np.isfinite(values[i]) for i in (0,1,4)) or not values[0].is_integer() or not values[4].is_integer():
            raise ValueError(f'{path}:{n}: contador/tempo inválido')
        rows.append(dict(zip(COLUMNS,values), linha_origem=n))
    df=pd.DataFrame(rows)
    if df.empty or (df['leitura']<=0).any() or (df['tempo_s']<0).any() or (df['leitura'].diff().dropna()<=0).any() or (df['tempo_s'].diff().dropna()<=0).any():
        raise ValueError('Fonte vazia ou leituras/tempos fora de ordem; separe sessões.')
    return df


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadados',type=Path,required=True,help='JSON por ensaio: arquivo, material, comprimento_mm')
    parser.add_argument('--temperaturas',type=Path,required=True,help='CSV ensaio,leitura,temperatura_C')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    metadata=json.loads(args.metadados.read_text())
    temperatures=pd.read_csv(args.temperaturas)
    if set(temperatures['ensaio']) != set(metadata): raise ValueError('Temperaturas e metadados têm ensaios diferentes.')
    args.out.mkdir(parents=True,exist_ok=True)
    for name,info in metadata.items():
        path=(args.metadados.parent/info['arquivo']).resolve()
        raw=ler_txt(path)
        measured=temperatures.loc[temperatures['ensaio']==name,['leitura','temperatura_C']]
        merged=raw.merge(measured,on='leitura',how='outer',validate='one_to_one',indicator=True)
        if not merged['_merge'].eq('both').all() or not np.isfinite(merged['temperatura_C']).all():
            raise ValueError(f'{name}: forneça uma temperatura medida por leitura, sem excedentes.')
        merged=merged.sort_values('tempo_s')
        valid=merged['amostras_validas'].between(1,10)&np.isfinite(merged['deltaL_mm'])
        # Séries físicas aparentes: preserve exclusões no CSV completo.
        merged['incluido_analise']=valid
        report=analisar_serie(merged.loc[valid].rename(columns={'deltaL_mm':'deslocamento_mm'}),
                             float(info['comprimento_mm']),info['material'])
        report.update(fonte_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      temperaturas_sha256=hashlib.sha256(args.temperaturas.read_bytes()).hexdigest(),
                      origem_temperaturas='medidas conforme declaração do usuário; fonte original a conferir',
                      origem_deslocamento='firmware histórico com fatores teóricos de 10 kg; célula utilizada de 5 kg',
                      excluidos=int((~valid).sum()))
        # Nomes de arquivos são independentes dos identificadores fornecidos.
        key=hashlib.sha256(name.encode()).hexdigest()[:16]
        with (args.out/f'{key}.json').open('x',encoding='utf-8') as f:
            json.dump(dict(ensaio=name,**report),f,ensure_ascii=False,indent=2,allow_nan=False)
        with (args.out/f'{key}.csv').open('x',encoding='utf-8',newline='') as f:
            merged.drop(columns='_merge').to_csv(f,index=False)
        print(name, args.out/f'{key}.json')


if __name__=='__main__': main()
