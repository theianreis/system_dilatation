"""Verifica importação, isolamento entre ensaios e integridade SQLite."""

import contextlib
from datetime import datetime, timezone
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

import pandas as pd
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from system_dilatation.database import models, sqlite
from system_dilatation.etl import loading


ENTRADAS = {
    "celula": "leitura,tempo_s,bits_media,deltaL_mm\n2,1,110,0.2\n1,0,100,0.1\n",
    "termistor": "Leitura,Tempo,Bits,Temperatura\n2,1,510,26\n1,0,500,25\n",
}


class EtlIntegrationTest(unittest.TestCase):
    def setUp(self):
        temporario = TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        self.pasta = Path(temporario.name)
        self.engine = sqlite.criar_engine(self.pasta / "teste.db")
        self.addCleanup(self.engine.dispose)
        troca = patch.object(sqlite, "engine", self.engine)
        troca.start()
        self.addCleanup(troca.stop)
        sqlite.criar_banco()
        for sensor, texto in ENTRADAS.items():
            (self.pasta / f"{sensor}.csv").write_text(texto, encoding="utf-8")

    def cli(self, *argumentos):
        with patch("sys.argv", ["etl", "--out", str(self.pasta / "saida"), *argumentos]):
            with contextlib.redirect_stdout(io.StringIO()):
                loading.main()

    def registros(self, sensor, ensaio_id):
        tabela = models.TABELAS[sensor]
        with self.engine.connect() as conexao:
            return [dict(linha) for linha in conexao.execute(
                select(tabela).where(tabela.c.ensaio_id == ensaio_id).order_by(tabela.c.leitura)
            ).mappings()]

    def importar_ambos(self, ensaio_id):
        self.cli(
            "--ensaio-id", ensaio_id,
            "--celula", str(self.pasta / "celula.csv"),
            "--termistor", str(self.pasta / "termistor.csv"),
        )

    def test_cli_processa_sensores_individuais_e_em_conjunto(self):
        esperados = {
            "celula": pd.DataFrame({
                "leitura": [1, 2], "tempo_s": [0.0, 1.0],
                "bits_medido": [100.0, 110.0], "deltaL_mm": [0.1, 0.2],
            }),
            "termistor": pd.DataFrame({
                "leitura": [1, 2], "tempo_s": [0.0, 1.0],
                "bits_medido": [500.0, 510.0], "temperatura_C": [25.0, 26.0],
            }),
        }
        for sensores in [("celula",), ("termistor",), ("celula", "termistor")]:
            with self.subTest(sensores=sensores):
                ensaio_id = sqlite.criar_ensaio("Teste de importação")
                argumentos = ["--ensaio-id", ensaio_id]
                for sensor in sensores:
                    argumentos.extend([f"--{sensor}", str(self.pasta / f"{sensor}.csv")])
                self.cli(*argumentos)
                self.cli(*argumentos)
                self.assertEqual(
                    set(inspect(self.engine).get_table_names()), {"ensaios", "célula", "termistor"}
                )
                for sensor in models.TABELAS:
                    registros = self.registros(sensor, ensaio_id)
                    if sensor not in sensores:
                        self.assertEqual(registros, [])
                        continue
                    esperado = esperados[sensor].copy()
                    esperado.insert(0, "ensaio_id", ensaio_id)
                    csv = pd.read_csv(self.pasta / "saida" / ensaio_id / f"{sensor}_limpo.csv")
                    banco = pd.DataFrame(registros, columns=list(esperado))
                    for resultado in (csv, banco):
                        pd.testing.assert_frame_equal(resultado, esperado, check_dtype=False)

    def test_cadastro_e_consulta(self):
        ensaio_id = sqlite.criar_ensaio("  Ensaio A  ", "Observação")
        self.assertEqual(str(UUID(ensaio_id)), ensaio_id)
        ensaio = sqlite.consultar_ensaio(ensaio_id)
        self.assertEqual(ensaio["nome"], "Ensaio A")
        self.assertEqual(ensaio["descricao"], "Observação")
        self.assertEqual(ensaio["estado"], "RASCUNHO")
        self.assertEqual(datetime.fromisoformat(ensaio["criado_em"]).tzinfo, timezone.utc)
        self.assertIsNone(ensaio["iniciado_em"])
        self.assertIsNone(ensaio["finalizado_em"])
        self.assertIsNone(sqlite.consultar_ensaio("inexistente"))
        for nome, estado in [(" ", "RASCUNHO"), ("Teste", "INVALIDO"), ("Teste", "LIXEIRA")]:
            with self.subTest(nome=nome, estado=estado), self.assertRaises(ValueError):
                sqlite.criar_ensaio(nome, estado=estado)

    def test_cli_cadastra_ensaio_e_reutiliza_id(self):
        self.cli("--novo-ensaio", "Criado pela CLI", "--celula", str(self.pasta / "celula.csv"))
        with self.engine.connect() as conexao:
            ensaio_id = conexao.execute(select(models.ensaios.c.id)).scalar_one()
        self.importar_ambos(ensaio_id)
        self.assertEqual(len(self.registros("celula", ensaio_id)), 2)
        self.assertEqual(len(self.registros("termistor", ensaio_id)), 2)
        with self.engine.connect() as conexao:
            self.assertEqual(len(conexao.execute(select(models.ensaios.c.id)).all()), 1)

    def test_reimportacao_atualiza_somente_ensaio_e_sensor_selecionados(self):
        a = sqlite.criar_ensaio("A")
        b = sqlite.criar_ensaio("B")
        self.importar_ambos(a)
        self.importar_ambos(b)
        originais_b = {sensor: self.registros(sensor, b) for sensor in models.TABELAS}
        termistor_a = self.registros("termistor", a)
        csv_b = (self.pasta / "saida" / b / "celula_limpo.csv").read_bytes()
        (self.pasta / "celula.csv").write_text(
            "leitura,tempo_s,bits_media,deltaL_mm\n1,0,900,9.9\n2,1,910,10.0\n",
            encoding="utf-8",
        )
        self.cli("--ensaio-id", a, "--celula", str(self.pasta / "celula.csv"))
        registros_a = self.registros("celula", a)
        self.assertEqual(len(registros_a), 2)
        self.assertEqual(registros_a[0]["deltaL_mm"], 9.9)
        self.assertEqual(registros_a[0]["bits_medido"], 900)
        self.assertEqual(self.registros("termistor", a), termistor_a)
        for sensor in models.TABELAS:
            self.assertEqual(self.registros(sensor, b), originais_b[sensor])
        self.assertEqual((self.pasta / "saida" / b / "celula_limpo.csv").read_bytes(), csv_b)

    def test_rejeita_ensaio_inexistente_ou_na_lixeira_sem_csv(self):
        ensaio_id = sqlite.criar_ensaio("Descartado")
        with self.engine.begin() as conexao:
            conexao.execute(models.ensaios.update().where(models.ensaios.c.id == ensaio_id).values(
                estado="LIXEIRA", estado_anterior="RASCUNHO",
            ))
        for identificador in ["inexistente", ensaio_id]:
            with self.subTest(ensaio=identificador), self.assertRaises(ValueError):
                loading.executar_etl(
                    "celula", self.pasta / "celula.csv", self.pasta / "nao_criado.csv", identificador
                )
            self.assertFalse((self.pasta / "nao_criado.csv").exists())

    def test_rejeita_identificador_divergente_no_arquivo_e_na_persistencia(self):
        a, b = sqlite.criar_ensaio("A"), sqlite.criar_ensaio("B")
        dados = pd.DataFrame({
            "ensaio_id": [b], "leitura": [1], "tempo_s": [0],
            "bits_medido": [100], "deltaL_mm": [0.1],
        })
        with self.assertRaises(ValueError):
            sqlite.salvar_dados(dados, "celula", a)
        dados.rename(columns={"bits_medido": "bits_media"}).to_csv(self.pasta / "divergente.csv", index=False)
        with self.assertRaises(ValueError):
            loading.executar_etl("celula", self.pasta / "divergente.csv", self.pasta / "saida.csv", a)
        self.assertEqual(self.registros("celula", a), [])
        self.assertFalse((self.pasta / "saida.csv").exists())

    def test_integridade_referencial_em_todas_as_conexoes(self):
        ensaio_id = sqlite.criar_ensaio("A")
        self.importar_ambos(ensaio_id)
        # Descarta o pool para testar também uma nova conexão física.
        self.engine.dispose()
        with self.engine.connect() as conexao:
            self.assertEqual(conexao.exec_driver_sql("PRAGMA foreign_keys").scalar_one(), 1)
            self.assertEqual(conexao.exec_driver_sql("PRAGMA foreign_key_check").all(), [])
        for tabela in models.TABELAS.values():
            with self.subTest(tabela=tabela.name), self.assertRaises(IntegrityError):
                with self.engine.begin() as conexao:
                    valores = dict(self.registros("celula" if tabela is models.hx711 else "termistor", ensaio_id)[0])
                    valores["ensaio_id"] = "inexistente"
                    conexao.execute(tabela.insert().values(**valores))
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conexao:
                conexao.execute(models.ensaios.delete().where(models.ensaios.c.id == ensaio_id))
        self.assertIsNotNone(sqlite.consultar_ensaio(ensaio_id))

    def test_cli_exige_ensaio(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as erro:
            self.cli("--celula", str(self.pasta / "celula.csv"))
        self.assertEqual(erro.exception.code, 2)

    def test_esquema_antigo_e_rejeitado_sem_alterar_dados(self):
        legado = sqlite.criar_engine(self.pasta / "legado.db")
        try:
            with legado.begin() as conexao:
                conexao.exec_driver_sql(
                    'CREATE TABLE "célula" (leitura INTEGER PRIMARY KEY, tempo_s FLOAT NOT NULL, '
                    'bits_medido FLOAT NOT NULL, deltaL_mm FLOAT NOT NULL)'
                )
                conexao.exec_driver_sql('INSERT INTO "célula" VALUES (1, 0, 100, 0.1)')
            antes = (self.pasta / "legado.db").read_bytes()
            with patch.object(sqlite, "engine", legado), self.assertRaisesRegex(RuntimeError, "migração"):
                sqlite.criar_banco()
            self.assertEqual((self.pasta / "legado.db").read_bytes(), antes)
            self.assertEqual(inspect(legado).get_table_names(), ["célula"])
        finally:
            legado.dispose()


if __name__ == "__main__":
    unittest.main()
