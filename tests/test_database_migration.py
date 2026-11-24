"""Preservação, diagnóstico, recuperação e uso de bancos candidatos."""

from contextlib import closing, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import os
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine

from system_dilatation.database import migration, models, schema, sqlite


class MigrationTest(unittest.TestCase):
    def setUp(self):
        temporario = TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        self.pasta = Path(temporario.name)
        self.origem = self.pasta / "legado.db"
        self.destino = self.pasta / "candidato.db"
        self.backups = self.pasta / "backups"
        self.a, self.b = str(uuid4()), str(uuid4())
        self.mapa = {
            "ensaios": [
                {"id": self.a, "nome": "A", "estado": "CONCLUIDO"},
                {"id": self.b, "nome": "B", "estado": "INTERROMPIDO", "descricao": "Obs"},
            ],
            "medicoes": [
                {"sensor": sensor, "leitura": leitura, "ensaio_id": ensaio}
                for sensor in ("celula", "termistor")
                for leitura, ensaio in ((1, self.a), (2, self.b))
            ],
        }

    def legado(self, vazio=False):
        with closing(sqlite3.connect(self.origem)) as banco, banco:
            for tabela, colunas in schema.COLUNAS.items():
                banco.execute(f'CREATE TABLE "{tabela}" (leitura INTEGER PRIMARY KEY, '
                              f'tempo_s FLOAT NOT NULL, bits_medido FLOAT NOT NULL, '
                              f'{colunas[-1]} FLOAT NOT NULL)')
                if not vazio:
                    banco.executemany(f'INSERT INTO "{tabela}" VALUES (?,?,?,?)',
                                      [(1, 0, 100.25, 0.125), (2, 10, -99.5, 25.875)])

    def executar(self, mapa=None):
        return migration.executar(self.destino, origem=self.origem,
                                  mapeamento=mapa, pasta_backup=self.backups)

    def test_criacao_explicita_e_cli(self):
        with redirect_stdout(io.StringIO()):
            migration.main(["--criar", "--destino", str(self.destino)])
        self.assertFalse(self.origem.exists())
        with closing(migration.abrir_leitura(self.destino)) as banco:
            self.assertEqual(schema.reconhecer(banco), "atual")
            self.assertEqual(banco.execute("SELECT count(*) FROM ensaios").fetchone()[0], 0)
        relatorio = json.loads(next(self.pasta.glob("*.json")).read_text())
        self.assertEqual(relatorio["resultado"], "candidato_validado")
        self.assertIsNone(relatorio["backup"])
        self.assertEqual(datetime.fromisoformat(relatorio["horario_utc"]).tzinfo, timezone.utc)

    def test_preserva_todos_os_valores_e_backup_restauravel(self):
        self.legado()
        antes = self.origem.read_bytes()
        resultado = self.executar(self.mapa)
        self.assertEqual(self.origem.read_bytes(), antes)
        backup = Path(resultado["backup"])
        self.assertEqual(resultado["backup_sha256"], hashlib.sha256(backup.read_bytes()).hexdigest())
        # Restaura uma cópia descartável pela API SQLite e consulta no esquema antigo.
        restaurado = self.pasta / "restaurado.db"
        with closing(migration.abrir_leitura(backup)) as copia, closing(sqlite3.connect(restaurado)) as banco:
            copia.backup(banco)
            self.assertEqual(schema.reconhecer(banco), "legado")
            for tabela in schema.COLUNAS:
                self.assertEqual(banco.execute(f'SELECT * FROM "{tabela}" ORDER BY leitura').fetchall(),
                                 [(1, 0, 100.25, 0.125), (2, 10, -99.5, 25.875)])
        with closing(migration.abrir_leitura(self.destino)) as banco:
            self.assertEqual(schema.reconhecer(banco), "atual")
            for tabela in schema.COLUNAS:
                self.assertEqual(banco.execute(f'SELECT * FROM "{tabela}" ORDER BY leitura').fetchall(),
                                 [(self.a, 1, 0, 100.25, 0.125), (self.b, 2, 10, -99.5, 25.875)])
                self.assertEqual(resultado["contagens_depois"][tabela]["por_ensaio"], {self.a: 1, self.b: 1})
            self.assertEqual(banco.execute('SELECT iniciado_em, finalizado_em FROM ensaios').fetchall(),
                             [(None, None), (None, None)])

    def test_legado_vazio_nao_exige_mapeamento(self):
        self.legado(vazio=True)
        self.assertEqual(self.executar()["contagens_depois"]["célula"]["total"], 0)

    def test_mapeamentos_invalidos_preservam_origem_e_reportam_falha(self):
        self.legado()
        antes = self.origem.read_bytes()
        incompleto = deepcopy(self.mapa)
        incompleto["medicoes"].pop()
        duplicado = deepcopy(self.mapa)
        duplicado["medicoes"].append(duplicado["medicoes"][0])
        extra = deepcopy(self.mapa)
        extra["medicoes"].append({"sensor": "celula", "leitura": 99, "ensaio_id": self.a})
        desconhecido = deepcopy(self.mapa)
        desconhecido["medicoes"][0]["ensaio_id"] = str(uuid4())
        uuid_invalido = deepcopy(self.mapa)
        uuid_invalido["ensaios"][0]["id"] = "errado"
        for mapa in (None, incompleto, duplicado, extra, desconhecido, uuid_invalido):
            with self.subTest(mapa=mapa), self.assertRaises(ValueError):
                self.executar(mapa)
            self.assertEqual(self.origem.read_bytes(), antes)
            self.assertFalse(self.destino.exists())
        for caminho in self.pasta.glob("*.json"):
            relatorio = json.loads(caminho.read_text())
            self.assertEqual(relatorio["resultado"], "falha")
            self.assertTrue(Path(relatorio["backup"]).exists())

    def test_falha_durante_copia_reverte_candidato(self):
        self.legado()
        antes = self.origem.read_bytes()
        original = migration.copiar_legado

        def falhar(destino, cadastros, esperados):
            original(destino, cadastros, esperados)
            raise RuntimeError("falha simulada após inserção")

        with patch.object(migration, "copiar_legado", falhar), self.assertRaises(RuntimeError):
            self.executar(self.mapa)
        self.assertEqual(self.origem.read_bytes(), antes)
        self.assertFalse(self.destino.exists())
        self.assertEqual(len(list(self.backups.glob("*.db"))), 1)

    def test_comparacao_detecta_alteracao_mesmo_com_contagem_igual(self):
        self.legado()
        original = migration.copiar_legado

        def corromper(destino, cadastros, esperados):
            original(destino, cadastros, esperados)
            destino.execute('UPDATE "célula" SET bits_medido=999 WHERE leitura=1')

        with patch.object(migration, "copiar_legado", corromper), self.assertRaisesRegex(ValueError, "divergentes"):
            self.executar(self.mapa)
        self.assertFalse(self.destino.exists())

    def test_recusa_origem_ausente_e_destinos_ocupados(self):
        with self.assertRaises(sqlite3.Error):
            self.executar()
        self.assertFalse(self.origem.exists())
        self.legado()
        self.destino.write_bytes(b"nao sobrescrever")
        for destino in (self.destino, self.origem):
            with self.subTest(destino=destino), self.assertRaises(ValueError):
                migration.executar(destino, origem=self.origem)
        self.assertEqual(self.destino.read_bytes(), b"nao sobrescrever")

    def test_recusa_esquemas_desconhecidos_versoes_e_dados_invalidos(self):
        alteracoes = [
            'CREATE TABLE extra (id INTEGER)',
            'CREATE VIEW vista AS SELECT * FROM termistor',
            'CREATE INDEX indice ON termistor (tempo_s)',
            'CREATE TRIGGER gatilho AFTER INSERT ON termistor BEGIN SELECT 1; END',
            'PRAGMA user_version=99',
            'UPDATE termistor SET tempo_s=-1',
            'UPDATE termistor SET bits_medido=1e999',
            'UPDATE termistor SET temperatura_C=\'invalido\'',
            'UPDATE termistor SET leitura=0 WHERE leitura=1',
        ]
        for alteracao in alteracoes:
            with self.subTest(alteracao=alteracao):
                self.origem.unlink(missing_ok=True)
                self.legado()
                with closing(sqlite3.connect(self.origem)) as banco, banco:
                    banco.execute(alteracao)
                antes = self.origem.read_bytes()
                with self.assertRaises(ValueError):
                    self.executar(self.mapa)
                self.assertEqual(self.origem.read_bytes(), antes)
                self.assertFalse(self.destino.exists())

    def test_banco_corrompido_preservado(self):
        self.origem.write_bytes(b"isto nao e sqlite")
        with self.assertRaises(sqlite3.DatabaseError):
            self.executar()
        self.assertEqual(self.origem.read_bytes(), b"isto nao e sqlite")
        self.assertFalse(self.destino.exists())

    def test_versiona_esquema_etapa_11_e_repeticao_nao_copia(self):
        engine = create_engine(f"sqlite:///{self.origem}")
        models.metadata.create_all(engine)
        with engine.begin() as conexao:
            conexao.execute(models.ensaios.insert().values(
                id=self.a, nome="Antigo", criado_em="2026-11-24T00:00:00+00:00", estado="RASCUNHO"))
        engine.dispose()
        antes = self.origem.read_bytes()
        self.executar()
        self.assertEqual(self.origem.read_bytes(), antes)
        with closing(migration.abrir_leitura(self.destino)) as banco:
            self.assertEqual(banco.execute("SELECT id FROM ensaios").fetchone()[0], self.a)
        segundo = self.pasta / "segundo.db"
        resultado = migration.executar(segundo, origem=self.destino, pasta_backup=self.backups)
        self.assertEqual(resultado["resultado"], "ja_atualizado")
        self.assertFalse(segundo.exists())
        self.assertEqual(len(list(self.backups.glob("*.db"))), 1)

    def test_aplicacao_rejeita_versao_incompativel_sem_escrever(self):
        for versao in (0, 99):
            self.origem.unlink(missing_ok=True)
            engine = sqlite.criar_engine(self.origem)
            try:
                models.metadata.create_all(engine)
                with engine.begin() as conexao:
                    conexao.exec_driver_sql(f"PRAGMA user_version={versao}")
                antes = self.origem.read_bytes()
                with patch.object(sqlite, "engine", engine), self.assertRaises(RuntimeError):
                    sqlite.criar_banco()
                self.assertEqual(self.origem.read_bytes(), antes)
            finally:
                engine.dispose()

    def test_candidato_aceita_etl_isola_ensaios_e_impoe_referencias(self):
        self.legado()
        self.executar(self.mapa)
        # Aceitação em cópia descartável: não contamina o candidato validado.
        copia = self.pasta / "aceitacao.db"
        with closing(migration.abrir_leitura(self.destino)) as fonte, closing(sqlite3.connect(copia)) as banco:
            fonte.backup(banco)
        entrada = self.pasta / "celula.csv"
        entrada.write_text("leitura,tempo_s,bits_media,deltaL_mm\n1,0,900,9\n")
        ambiente = dict(os.environ, SYSTEM_DILATATION_DB=str(copia))
        processo = subprocess.run(
            [sys.executable, "-m", "system_dilatation.etl.loading", "--ensaio-id", self.b,
             "--celula", str(entrada), "--out", str(self.pasta / "saida")],
            env=ambiente, capture_output=True, text=True,
        )
        self.assertEqual(processo.returncode, 0, processo.stderr)
        with closing(sqlite3.connect(copia)) as banco:
            banco.execute("PRAGMA foreign_keys=ON")
            self.assertEqual(banco.execute('SELECT bits_medido FROM "célula" WHERE ensaio_id=? AND leitura=1',
                                          (self.a,)).fetchone()[0], 100.25)
            self.assertEqual(banco.execute('SELECT bits_medido FROM "célula" WHERE ensaio_id=? AND leitura=1',
                                          (self.b,)).fetchone()[0], 900)
            with self.assertRaises(sqlite3.IntegrityError):
                banco.execute('INSERT INTO termistor VALUES (?,99,0,1,25)', (str(uuid4()),))
            with self.assertRaises(sqlite3.IntegrityError):
                banco.execute('DELETE FROM ensaios WHERE id=?', (self.a,))
        with closing(migration.abrir_leitura(self.destino)) as banco:
            self.assertEqual(banco.execute('SELECT count(*) FROM "célula"').fetchone()[0], 2)

    def test_backup_inclui_transacoes_confirmadas_no_wal(self):
        self.legado()
        with closing(sqlite3.connect(self.origem)) as escritor:
            escritor.execute("PRAGMA journal_mode=WAL")
            escritor.execute("PRAGMA wal_autocheckpoint=0")
            escritor.execute('UPDATE termistor SET temperatura_C=42.5 WHERE leitura=1')
            escritor.commit()
            self.assertTrue(Path(str(self.origem) + "-wal").exists())
            resultado = self.executar(self.mapa)
            with closing(migration.abrir_leitura(self.destino)) as candidato:
                self.assertEqual(candidato.execute(
                    'SELECT temperatura_C FROM termistor WHERE leitura=1'
                ).fetchone()[0], 42.5)
            with closing(migration.abrir_leitura(resultado["backup"])) as backup:
                self.assertEqual(backup.execute(
                    'SELECT temperatura_C FROM termistor WHERE leitura=1'
                ).fetchone()[0], 42.5)

    def test_sem_espaco_preserva_origem(self):
        self.legado()
        antes = self.origem.read_bytes()
        with patch.object(migration.shutil, "disk_usage") as espaco:
            espaco.return_value.free = 0
            with self.assertRaisesRegex(ValueError, "Espaço"):
                self.executar(self.mapa)
        self.assertEqual(self.origem.read_bytes(), antes)
        self.assertFalse(self.destino.exists())

    def test_mapeamento_json_na_cli(self):
        self.legado()
        caminho = self.pasta / "mapa.json"
        caminho.write_text(json.dumps(self.mapa))
        with redirect_stdout(io.StringIO()):
            migration.main(["--origem", str(self.origem), "--destino", str(self.destino),
                            "--mapeamento", str(caminho), "--backups", str(self.backups)])
        self.assertTrue(self.destino.exists())

    def test_cli_diagnostico_sem_criar_origem(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as erro:
            migration.main(["--origem", str(self.origem), "--destino", str(self.destino)])
        self.assertEqual(erro.exception.code, 2)
        self.assertFalse(self.origem.exists())


if __name__ == "__main__":
    unittest.main()
