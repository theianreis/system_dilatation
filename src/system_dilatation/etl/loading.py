import argparse
from pathlib import Path

import pandas as pd

from .extract import extract_csv
from .transform import transform_celula, transform_termistor
from ..database.sqlite import (
    criar_banco,
    criar_ensaio,
    salvar_dados,
    validar_ensaio_para_importacao,
)


def salvar_csv(dados: pd.DataFrame, caminho: str | Path) -> None:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    dados.to_csv(caminho, index=False, encoding="utf-8")


def executar_etl(
    sensor: str, entrada: str | Path, saida: str | Path, ensaio_id: str
) -> pd.DataFrame:
    criar_banco()
    validar_ensaio_para_importacao(ensaio_id)
    dados_brutos = extract_csv(entrada)
    if "ensaio_id" in dados_brutos.columns and not dados_brutos["ensaio_id"].eq(ensaio_id).all():
        raise ValueError("O arquivo pertence a outro ensaio.")

    if sensor == "celula":
        dados_tratados = transform_celula(dados_brutos)
    elif sensor == "termistor":
        dados_tratados = transform_termistor(dados_brutos)
    else:
        raise ValueError(f"Sensor não suportado: {sensor}")

    dados_tratados.insert(0, "ensaio_id", ensaio_id)
    salvar_dados(dados_tratados, sensor, ensaio_id)
    salvar_csv(dados_tratados, saida)
    print(f"[ETL] {sensor}: {len(dados_tratados)} registros processados. Ensaio: {ensaio_id}")
    return dados_tratados


def main():
    parser = argparse.ArgumentParser(description="Pipeline ETL dos sensores por ensaio")
    parser.add_argument("--celula", type=Path, help="Arquivo de entrada da célula")
    parser.add_argument("--termistor", type=Path, help="Arquivo de entrada do termistor")
    parser.add_argument(
        "--out", type=Path, default=Path("data/processed"),
        help="Diretório base de saída; os arquivos serão separados pelo UUID do ensaio",
    )
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--ensaio-id", help="UUID de um ensaio já cadastrado")
    grupo.add_argument("--novo-ensaio", metavar="NOME", help="Cadastra um novo ensaio em rascunho")
    args = parser.parse_args()
    if args.celula is None and args.termistor is None:
        parser.error("Informe --celula e/ou --termistor.")

    try:
        criar_banco()
        ensaio_id = args.ensaio_id
        if args.novo_ensaio is not None:
            ensaio_id = criar_ensaio(args.novo_ensaio)
            print(f"[ENSAIO] Cadastrado: {ensaio_id}")
        validar_ensaio_para_importacao(ensaio_id)
        saida = args.out / ensaio_id
        for sensor in ("celula", "termistor"):
            entrada = getattr(args, sensor)
            if entrada is not None:
                executar_etl(sensor, entrada, saida / f"{sensor}_limpo.csv", ensaio_id)
    except (ValueError, RuntimeError) as erro:
        parser.error(str(erro))


if __name__ == "__main__":
    main()
