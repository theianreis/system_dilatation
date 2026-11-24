"""Criação e migração explícitas, sem substituir o banco original."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import sqlite3
from uuid import UUID, uuid4

from ..validation import validar_serie
from .models import ESTADOS
from .schema import COLUNAS, VERSAO, criar_esquema, reconhecer, verificar_integridade


def abrir_leitura(caminho):
    return sqlite3.connect(Path(caminho).resolve().as_uri() + "?mode=ro", uri=True)


def reservar(caminho):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("xb"):
        pass


def contagens(conexao, atual=False):
    resultado = {}
    for tabela in COLUNAS:
        resultado[tabela] = {"total": conexao.execute(f'SELECT count(*) FROM "{tabela}"').fetchone()[0]}
        if atual:
            resultado[tabela]["por_ensaio"] = dict(conexao.execute(
                f'SELECT ensaio_id, count(*) FROM "{tabela}" GROUP BY ensaio_id'
            ))
    return resultado


def preparar_mapeamento(conexao, mapeamento):
    if mapeamento is None:
        mapeamento = {"ensaios": [], "medicoes": []}
    if (not isinstance(mapeamento, dict) or set(mapeamento) != {"ensaios", "medicoes"}
            or not isinstance(mapeamento["ensaios"], list)
            or not isinstance(mapeamento["medicoes"], list)):
        raise ValueError("Mapeamento deve conter ensaios e medicoes.")
    cadastros, destinos = {}, {}
    agora = datetime.now(timezone.utc).isoformat()
    for ensaio in mapeamento["ensaios"]:
        if (not isinstance(ensaio, dict) or not {"id", "nome", "estado"} <= set(ensaio)
                or set(ensaio) - {"id", "nome", "estado", "descricao"}):
            raise ValueError("Cadastro deve conter id, nome, estado e descrição opcional.")
        identificador = ensaio["id"]
        if (not isinstance(identificador, str) or str(UUID(identificador)) != identificador
                or identificador in cadastros or not isinstance(ensaio["nome"], str)
                or not ensaio["nome"].strip() or ensaio["estado"] not in ESTADOS[:-1]
                or not isinstance(ensaio.get("descricao", ""), (str, type(None)))):
            raise ValueError("Cadastro inválido ou duplicado no mapeamento.")
        cadastros[identificador] = {**ensaio, "criado_em": agora}
    for item in mapeamento["medicoes"]:
        if not isinstance(item, dict) or set(item) != {"sensor", "leitura", "ensaio_id"}:
            raise ValueError("Associação deve conter sensor, leitura e ensaio_id.")
        sensor = {"celula": "célula", "termistor": "termistor"}.get(item["sensor"])
        chave = (sensor, item["leitura"])
        if (sensor is None or type(item["leitura"]) is not int or item["leitura"] <= 0
                or chave in destinos or item["ensaio_id"] not in cadastros):
            raise ValueError("Associação inválida, duplicada ou com ensaio desconhecido.")
        destinos[chave] = item["ensaio_id"]
    esperados = {}
    for tabela in COLUNAS:
        linhas = conexao.execute(f'SELECT * FROM "{tabela}" ORDER BY leitura').fetchall()
        esperado = []
        for linha in linhas:
            leitura, tempo, *_ = linha
            if (type(leitura) is not int or leitura <= 0 or tempo is None
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in linha[1:])
                    or tempo < 0):
                raise ValueError(f"Medição inválida em {tabela}, leitura {leitura}.")
            chave = (tabela, leitura)
            if chave not in destinos:
                raise ValueError(f"Mapeamento ausente para {tabela}, leitura {leitura}.")
            esperado.append((destinos.pop(chave), *linha))
        tempos = {}
        for ensaio_id, _, tempo, *_ in esperado:
            serie = tempos.setdefault(ensaio_id, set())
            if tempo in serie:
                raise ValueError(f"Tempos duplicados em {tabela}, ensaio {ensaio_id}.")
            serie.add(tempo)
        esperados[tabela] = sorted(esperado)
    if destinos:
        raise ValueError("Mapeamento contém leituras inexistentes na origem.")
    return list(cadastros.values()), esperados


def copiar_legado(destino, cadastros, esperados):
    criar_esquema(destino)
    for ensaio in cadastros:
        destino.execute(
            "INSERT INTO ensaios (id,nome,descricao,estado,criado_em) VALUES (?,?,?,?,?)",
            tuple(ensaio.get(c) for c in ("id", "nome", "descricao", "estado", "criado_em")),
        )
    for tabela, linhas in esperados.items():
        destino.executemany(f'INSERT INTO "{tabela}" VALUES (?,?,?,?,?)', linhas)


def validar_conteudo(conexao):
    for tabela in COLUNAS:
        ids = conexao.execute(f'SELECT DISTINCT ensaio_id FROM "{tabela}"').fetchall()
        for (identificador,) in ids:
            validar_serie(conexao.execute(
                f'SELECT {",".join(COLUNAS[tabela])} FROM "{tabela}" WHERE ensaio_id=?',
                (identificador,),
            ).fetchall())


def comparar(destino, esperados):
    for tabela, linhas in esperados.items():
        obtidos = destino.execute(f'SELECT * FROM "{tabela}" ORDER BY ensaio_id, leitura').fetchall()
        if obtidos != linhas:
            raise ValueError(f"Valores divergentes após cópia: {tabela}.")


def executar(destino, *, origem=None, criar=False, mapeamento=None, pasta_backup=None):
    """Retorna relatório; preserva origem e deixa ativação sob controle do operador."""
    destino = Path(destino).resolve()
    origem = Path(origem).resolve() if origem is not None else None
    if criar == (origem is not None):
        raise ValueError("Selecione criação explícita ou informe uma origem existente.")
    if origem == destino or destino.exists():
        raise ValueError("O candidato deve usar um caminho novo, diferente da origem.")
    operacao = str(uuid4())
    relatorio_path = destino.with_name(destino.name + f".{operacao}.json")
    relatorio = {
        "operacao": operacao, "horario_utc": datetime.now(timezone.utc).isoformat(),
        "origem": str(origem) if origem else None, "candidato": str(destino),
        "backup": None, "versao_destino": VERSAO, "mapeamento": mapeamento,
        "validacoes": [], "relatorio": str(relatorio_path),
    }
    candidato_reservado = False
    # Reserva exclusiva também impede sobrescrita de relatórios existentes.
    reservar(relatorio_path)
    try:
        if criar:
            if mapeamento is not None:
                raise ValueError("Mapeamento só se aplica à migração legada.")
            reservar(destino)
            candidato_reservado = True
            with closing(sqlite3.connect(destino)) as candidato:
                candidato.execute("PRAGMA foreign_keys=ON")
                with candidato:
                    candidato.execute("BEGIN")
                    criar_esquema(candidato)
                    verificar_integridade(candidato)
                    candidato.execute(f"PRAGMA user_version={VERSAO}")
        else:
            with closing(abrir_leitura(origem)) as fonte:
                verificar_integridade(fonte)
                esquema = reconhecer(fonte)
                relatorio["esquema_origem"] = esquema
                relatorio["versao_origem"] = fonte.execute("PRAGMA user_version").fetchone()[0]
                relatorio["validacoes"].append("integridade e esquema da origem")
                if esquema == "atual":
                    if mapeamento is not None:
                        raise ValueError("Banco atualizado não recebe mapeamento.")
                    validar_conteudo(fonte)
                    relatorio["contagens_antes"] = contagens(fonte, True)
                    relatorio["resultado"] = "ja_atualizado"
                    return relatorio
                pasta = Path(pasta_backup).resolve() if pasta_backup else origem.parent.parent / "backups"
                # Inclui páginas confirmadas que ainda podem estar no WAL.
                tamanho_banco = (fonte.execute("PRAGMA page_count").fetchone()[0]
                                 * fonte.execute("PRAGMA page_size").fetchone()[0])
                # Espaço para backup e candidato, com margem para estruturas e relatório.
                if shutil.disk_usage(relatorio_path.parent).free < tamanho_banco * 2 + 1048576:
                    raise ValueError("Espaço insuficiente para backup e candidato.")
                pasta.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(pasta).free < tamanho_banco + 1048576:
                    raise ValueError("Espaço insuficiente para backup.")
                backup = pasta / f"{origem.name}.{operacao}.backup.db"
                reservar(backup)
                relatorio["backup"] = str(backup)
                with closing(sqlite3.connect(backup)) as copia:
                    fonte.backup(copia)
            with backup.open("rb") as arquivo_backup:
                relatorio["backup_sha256"] = hashlib.file_digest(arquivo_backup, "sha256").hexdigest()
            with closing(abrir_leitura(backup)) as copia:
                verificar_integridade(copia)
                if reconhecer(copia) != esquema:
                    raise ValueError("Esquema mudou durante a preparação do backup.")
                relatorio["validacoes"].append("backup reaberto e íntegro")
                relatorio["contagens_antes"] = contagens(copia, esquema != "legado")
                if esquema == "legado":
                    cadastros, esperados = preparar_mapeamento(copia, mapeamento)
                elif mapeamento is not None:
                    raise ValueError("Banco com ensaios não recebe mapeamento legado.")
                reservar(destino)
                candidato_reservado = True
                with closing(sqlite3.connect(destino)) as candidato:
                    candidato.execute("PRAGMA foreign_keys=ON")
                    if esquema in ("sem_versao", "versao_1"):
                        copia.backup(candidato)
                        esperados = {t: copia.execute(
                            f'SELECT * FROM "{t}" ORDER BY ensaio_id, leitura'
                        ).fetchall() for t in COLUNAS}
                    with candidato:
                        candidato.execute("BEGIN")
                        if esquema == "versao_1":
                            from .schema import ddl_atual
                            existentes = {r[0] for r in candidato.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                            for sql in ddl_atual():
                                import re
                                nome = re.search(r'CREATE TABLE\s+"?([^"\s(]+)', sql).group(1)
                                if nome not in existentes:
                                    candidato.execute(sql)
                        if esquema == "legado":
                            copiar_legado(candidato, cadastros, esperados)
                        validar_conteudo(candidato)
                        comparar(candidato, esperados)
                        if esquema in ("sem_versao", "versao_1") and candidato.execute(
                            "SELECT * FROM ensaios ORDER BY id"
                        ).fetchall() != copia.execute("SELECT * FROM ensaios ORDER BY id").fetchall():
                            raise ValueError("Cadastros divergentes após cópia.")
                        verificar_integridade(candidato)
                        candidato.execute(f"PRAGMA user_version={VERSAO}")
                    relatorio["validacoes"].append("comparação integral das medições e referências")
        with closing(abrir_leitura(destino)) as candidato:
            verificar_integridade(candidato)
            if reconhecer(candidato) != "atual":
                raise ValueError("Candidato com esquema ou versão inválidos.")
            if origem:
                comparar(candidato, esperados)
            relatorio["contagens_depois"] = contagens(candidato, True)
        relatorio["validacoes"].append("candidato reaberto: integridade, referências e versão")
        relatorio["resultado"] = "candidato_validado"
        return relatorio
    except Exception as erro:
        relatorio["resultado"] = "falha"
        relatorio["erro"] = str(erro)
        if candidato_reservado:
            destino.unlink(missing_ok=True)
        raise
    finally:
        relatorio_path.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--origem", type=Path)
    grupo.add_argument("--criar", action="store_true")
    parser.add_argument("--destino", type=Path, required=True, help="Caminho novo para o candidato")
    parser.add_argument("--mapeamento", type=Path, help="JSON com ensaios e associações de leituras")
    parser.add_argument("--backups", type=Path)
    args = parser.parse_args(argv)
    try:
        mapeamento = json.loads(args.mapeamento.read_text(encoding="utf-8")) if args.mapeamento else None
        resultado = executar(args.destino, origem=args.origem, criar=args.criar,
                             mapeamento=mapeamento, pasta_backup=args.backups)
    except (ValueError, OSError, sqlite3.Error, TypeError, KeyError) as erro:
        parser.exit(2, f"Migração recusada: {erro}\n")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
