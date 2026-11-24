"""Comandos operacionais para ensaios, captura, processamento e recuperação."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from .database import sqlite, models, lifecycle
from .etl.loading import salvar_csv


def gravar_json(path, value):
    # Resultados novos nunca substituem evidência anterior.
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # A migração tem parser próprio e nunca usa o engine cotidiano.
    if argv and argv[0] == 'migrar':
        from .database.migration import main as migration_main
        return migration_main(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, help='Banco explícito; padrão data/database/sensores.db no diretório atual')
    sub = parser.add_subparsers(dest='comando', required=True)
    listing = sub.add_parser('listar')
    listing.add_argument('--lixeira', action='store_true', help='Mostra somente ensaios descartados')
    new = sub.add_parser('criar-ensaio'); new.add_argument('nome')
    show = sub.add_parser('consultar'); show.add_argument('ensaio_id')
    state = sub.add_parser('estado'); state.add_argument('ensaio_id'); state.add_argument('acao', choices=['EM_ANDAMENTO', 'CONCLUIDO', 'INTERROMPIDO', 'descartar', 'restaurar', 'excluir'])
    imp = sub.add_parser('importar-captura'); imp.add_argument('arquivo', type=Path); imp.add_argument('--ensaio-id', required=True)
    cap = sub.add_parser('capturar'); cap.add_argument('--porta', required=True); cap.add_argument('--destino', type=Path, required=True); cap.add_argument('--duracao', type=float, required=True); cap.add_argument('--iniciar', action='store_true'); cap.add_argument('--ensaio-id', required=True)
    exp = sub.add_parser('exportar'); exp.add_argument('ensaio_id'); exp.add_argument('--sensor', choices=['celula', 'termistor'], required=True); exp.add_argument('--destino', type=Path, required=True)
    bak = sub.add_parser('backup'); bak.add_argument('--destino', type=Path, required=True)
    cal = sub.add_parser('calibrar'); cal.add_argument('arquivo', type=Path); cal.add_argument('--tipo', choices=['ntc', 'deslocamento'], required=True); cal.add_argument('--referencia', required=True); cal.add_argument('--destino', type=Path, required=True)
    ana = sub.add_parser('analisar-serie'); ana.add_argument('arquivo', type=Path); ana.add_argument('--comprimento-mm', type=float, required=True); ana.add_argument('--material', required=True); ana.add_argument('--destino', type=Path, required=True)
    raw = sub.add_parser('processar-captura'); raw.add_argument('arquivo', type=Path); raw.add_argument('--parametros', type=Path, required=True); raw.add_argument('--destino', type=Path, required=True)
    mig = sub.add_parser('migrar'); mig.add_argument('argumentos', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    previous = sqlite.engine
    if args.db:
        sqlite.engine = sqlite.criar_engine(args.db.resolve())
    try:
        command = args.comando
        if command == 'migrar':
            from .database.migration import main as migration_main
            return migration_main(args.argumentos)
        if command in ('calibrar', 'analisar-serie', 'processar-captura'):
            import pandas as pd
            from .science.analysis import ajustar_calibracao, analisar_serie, processar_captura
            if command == 'calibrar':
                result = ajustar_calibracao(args.arquivo, args.tipo, args.referencia)
            elif command == 'analisar-serie':
                result = analisar_serie(pd.read_csv(args.arquivo), args.comprimento_mm, args.material)
                import hashlib
                result['fonte_sha256'] = hashlib.sha256(args.arquivo.read_bytes()).hexdigest()
            else:
                result = processar_captura(args.arquivo, json.loads(args.parametros.read_text()))
            if command == 'calibrar':
                result['id'] = str(uuid4())
                sqlite.criar_banco()
                gravar_json(args.destino, result)
                with sqlite.engine.begin() as connection:
                    connection.execute(models.calibracoes.insert().values(
                        id=result['id'], criado_em=result['criado_em'],
                        parametros_json=json.dumps(result, allow_nan=False)))
            else:
                gravar_json(args.destino, result)
            print(args.destino)
            return
        if command == 'backup' and not Path(sqlite.engine.url.database).is_file():
            raise FileNotFoundError('Banco de origem do backup não existe.')
        sqlite.criar_banco()
        if command == 'criar-ensaio':
            print(sqlite.criar_ensaio(args.nome))
        elif command == 'consultar':
            result = sqlite.consultar_ensaio(args.ensaio_id)
            if result is None:
                raise ValueError('Ensaio inexistente.')
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif command == 'listar':
            with sqlite.engine.connect() as c:
                print(json.dumps([dict(r) for r in c.execute(select(models.ensaios).where(
                    models.ensaios.c.estado == 'LIXEIRA' if args.lixeira else models.ensaios.c.estado != 'LIXEIRA'
                )).mappings()], ensure_ascii=False, indent=2))
        elif command == 'estado':
            lifecycle.alterar(args.ensaio_id, args.acao)
        elif command == 'importar-captura':
            from .acquisition.importer import importar
            print(json.dumps(importar(args.arquivo, args.ensaio_id), indent=2))
        elif command == 'capturar':
            from .acquisition.serial_capture import capturar
            sqlite.validar_ensaio_para_importacao(args.ensaio_id)
            lifecycle.alterar(args.ensaio_id, 'EM_ANDAMENTO')
            try:
                result = capturar(args.porta, args.destino, args.duracao, iniciar=args.iniciar)
            except BaseException:
                lifecycle.alterar(args.ensaio_id, 'INTERROMPIDO')
                raise
            # Captura encerrada não declara automaticamente conclusão física.
            lifecycle.alterar(args.ensaio_id, 'INTERROMPIDO')
            result['ensaio_id'] = args.ensaio_id
            print(json.dumps(result, indent=2))
        elif command == 'exportar':
            import pandas as pd
            table = models.TABELAS[args.sensor]
            with sqlite.engine.connect() as c:
                df = pd.DataFrame(c.execute(select(table).where(table.c.ensaio_id == args.ensaio_id).order_by(table.c.tempo_s)).mappings().all(), columns=table.c.keys())
            salvar_csv(df, args.destino)
        elif command == 'backup':
            if not sqlite.engine.url.database or sqlite.engine.url.database == ':memory:':
                raise ValueError('Backup operacional exige banco em arquivo.')
            from .database.migration import abrir_leitura, reservar
            from .database.schema import verificar_integridade
            reservar(args.destino)
            with closing(abrir_leitura(sqlite.engine.url.database)) as source, closing(sqlite3.connect(args.destino)) as dest:
                source.backup(dest)
                verificar_integridade(dest)
            print(args.destino)
    except (ValueError, RuntimeError, OSError, SQLAlchemyError, sqlite3.Error, KeyError) as error:
        parser.exit(2, f'Operação recusada: {error}\n')
    finally:
        if args.db:
            sqlite.engine.dispose()
            sqlite.engine = previous


if __name__ == '__main__':
    main()
