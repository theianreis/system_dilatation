from pathlib import Path
import pandas as pd

def extract_csv(caminho:str | Path) -> pd.DataFrame:
    caminho = Path(caminho)
    if not caminho.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado:{caminho}")
    if caminho.suffix.lower() not in {".csv", ".txt"}:
        raise ValueError("Formato não suportado. Utilize CSV ou TXT.")
    dados = pd.read_csv(caminho)
    if dados.empty:
        raise ValueError(f"O arquivo está vazio: {caminho}")

    return dados
    