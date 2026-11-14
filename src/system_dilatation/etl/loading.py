
from pathlib import Path
import argparse
import pandas as pd
from .extract import extract_csv
from .transform import (transform_celula,transform_termistor)
from ..database.sqlite import (criar_banco,salvar_dados)


def salvar_csv(dados: pd.DataFrame,caminho: str | Path) -> None:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True,exist_ok=True)
    dados.to_csv(caminho,index=False, encoding="utf-8")

def executar_etl(sensor: str,entrada: str | Path, saida: str | Path) -> pd.DataFrame:
    # EXTRACT
    dados_brutos = extract_csv(entrada)
    # TRANSFORM
    if sensor == "celula":
        dados_tratados = transform_celula(dados_brutos)
    elif sensor == "termistor":
        dados_tratados = transform_termistor(dados_brutos)
    else:
        raise ValueError(
            f"Sensor não suportado: {sensor}")
    # LOAD
    salvar_csv(dados_tratados,saida)
    # 4. LOAD — SQLite
    criar_banco()
    salvar_dados(dados_tratados,sensor)
    print(f"[ETL] {sensor}: "f"{len(dados_tratados)} registros processados.")
    return dados_tratados

def main():
    parser = argparse.ArgumentParser(description="Pipeline ETL dos sensores")
    parser.add_argument("--celula",type=Path, help="Arquivo de entrada da célula")
    parser.add_argument("--termistor",type=Path,help="Arquivo de entrada do termistor")
    parser.add_argument("--out",type=Path,default=Path("data/processed"),help="Diretório dos dados processados"
    )

    args = parser.parse_args()
    if args.celula is None and args.termistor is None:
        parser.error("Informe --celula e/ou --termistor.")
    if args.celula is not None:
        executar_etl(sensor="celula",entrada=args.hx711,saida=args.out / "celula_limpo.csv")
    if args.termistor is not None:executar_etl(sensor="termistor",entrada=args.termistor,saida=args.out / "termistor_limpo.csv" )

if __name__ == "__main__":
    main()
