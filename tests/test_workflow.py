"""Regressões da revisão e fluxo bruto, recuperação e ciência com fontes conhecidas."""
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import pandas as pd
from sqlalchemy import select

from system_dilatation.database import sqlite, models, schema, migration, lifecycle
from system_dilatation.etl import loading
from system_dilatation.acquisition.protocol import FIELDS, parse
from system_dilatation.acquisition.importer import importar
from system_dilatation.acquisition.serial_capture import capturar
from system_dilatation.science.analysis import analisar_serie, ajustar_calibracao, processar_captura
from system_dilatation.cli import main


def capture(cycles=3):
    lines = ['# boot,system_dilatation,firmware=1', '# target_samples,10', ','.join(FIELDS)]
    for cycle in range(1, cycles + 1):
        row = dict.fromkeys(FIELDS, 0)
        row.update(schema=1, cycle=cycle, window_start_ms=cycle*10000,
                   window_end_ms=cycle*10000+1000, hx_first_ms=cycle*10000,
                   hx_last_ms=cycle*10000+900, ntc_first_ms=cycle*10000,
                   ntc_last_ms=cycle*10000+900, hx_valid=10, hx_attempts=10,
                   ntc_valid=10, ntc_attempts=10, hx_mean_counts=1100,
                   tare_counts=1000, tare_revision=1, hx_corrected_counts=100,
                   ntc_adc_mean=512, ntc_resistance_ohms='nan', temperature_C='nan',
                   cell_deflection_mm='nan', flags=192)
        lines.append(','.join(str(row[k]) for k in FIELDS))
    return ('\n'.join(lines)+'\n').encode()


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.engine = sqlite.criar_engine(self.folder/'test.db'); self.addCleanup(self.engine.dispose)
        swap=patch.object(sqlite,'engine',self.engine); swap.start(); self.addCleanup(swap.stop)
        sqlite.criar_banco(); self.id=sqlite.criar_ensaio('Teste')
        self.source=self.folder/'capture.csv'; self.source.write_bytes(capture())

    def test_inf_and_duplicate_times_rollback(self):
        data=pd.DataFrame({'leitura':[1],'tempo_s':[0.0],'bits_medido':[1.0],'deltaL_mm':[float('inf')]})
        with self.assertRaises(ValueError): sqlite.salvar_dados(data,'celula',self.id)
        data['deltaL_mm']=0.1; sqlite.salvar_dados(data,'celula',self.id)
        data['leitura']=2
        with self.assertRaises(ValueError): sqlite.salvar_dados(data,'celula',self.id)
        with self.engine.connect() as c:
            self.assertEqual(len(c.execute(select(models.hx711)).all()),1)
        data['leitura']=1; data['deltaL_mm']=0.2
        sqlite.salvar_dados(data,'celula',self.id)

    def test_migration_unversioned_rejects_inf(self):
        source=self.folder/'old.db'
        with closing(sqlite3.connect(source)) as c:
            schema.criar_esquema(c)
            c.execute("INSERT INTO ensaios (id,nome,criado_em,estado) VALUES (?,'A','2026-11-24T00:00:00+00:00','RASCUNHO')",(self.id,))
            c.execute('INSERT INTO "célula" VALUES (?,1,0,100,?)',(self.id,float('inf'))); c.commit()
        before=source.read_bytes()
        with self.assertRaises(ValueError): migration.executar(self.folder/'candidate.db',origem=source)
        self.assertEqual(source.read_bytes(),before)

    def test_migrates_version_1_and_preserves_measurements(self):
        source=self.folder/'v1.db'
        with closing(sqlite3.connect(source)) as c:
            for statement in schema.ddl_atual():
                if any(schema.normalizar(statement).startswith('createtable'+name+'(') for name in ('ensaios','célula','termistor')):
                    c.execute(statement)
            c.execute('PRAGMA user_version=1')
            c.execute("INSERT INTO ensaios (id,nome,criado_em,estado) VALUES (?,'A','2026-11-24T00:00:00+00:00','RASCUNHO')",(self.id,))
            c.execute('INSERT INTO "célula" VALUES (?,1,0,100,0.1)',(self.id,)); c.commit()
        destination=self.folder/'v2.db'
        migration.executar(destination,origem=source)
        with closing(sqlite3.connect(destination)) as c:
            self.assertEqual(schema.reconhecer(c),'atual')
            self.assertEqual(c.execute('SELECT deltaL_mm FROM "célula"').fetchone()[0],0.1)
            self.assertEqual(c.execute('SELECT count(*) FROM ciclos').fetchone()[0],0)

    def test_export_failure_is_recoverable(self):
        file=self.folder/'physical.csv'; file.write_text('leitura,tempo_s,bits_media,deltaL_mm\n1,0,100,0.1\n')
        with patch.object(loading,'salvar_csv',side_effect=OSError('cheio')), self.assertRaisesRegex(RuntimeError,'Banco confirmado'):
            loading.executar_etl('celula',file,self.folder/'out.csv',self.id)
        destination=self.folder/'recovered.csv'
        main(['exportar',self.id,'--sensor','celula','--destino',str(destination)])
        self.assertEqual(pd.read_csv(destination)['deltaL_mm'].iloc[0],0.1)

    def test_import_sessions_and_idempotency(self):
        self.source.write_bytes(capture()+capture())
        first=importar(self.source,self.id)
        self.assertEqual(first,importar(self.source,self.id))
        self.assertEqual(len(set(first['sessoes'])),2)
        with self.engine.connect() as c:
            self.assertEqual(len(c.execute(select(models.ciclos)).all()),6)
            self.assertEqual(len(c.execute(select(models.eventos)).all()),4)
        other=sqlite.criar_ensaio('Outro')
        result=importar(self.source,other)
        self.assertNotEqual(first['sessoes'],result['sessoes'])

    def test_invalid_capture_never_partially_imported(self):
        for suffix in (b'1,2\n',capture().splitlines()[-1]+b'\n'):
            self.source.write_bytes(capture()+suffix)
            with self.assertRaises(ValueError): importar(self.source,self.id)
        with self.engine.connect() as c: self.assertEqual(c.execute(select(models.sessoes)).all(),[])

    def test_nan_and_flags_are_preserved(self):
        content=capture().decode().splitlines(); row=content[-1].split(',')
        for field in ('hx_mean_counts','hx_corrected_counts','hx_first_ms','hx_last_ms','midpoint_skew_ms'): row[FIELDS.index(field)]='nan'
        row[FIELDS.index('hx_valid')]='0'; row[FIELDS.index('hx_attempts')]='0'; row[FIELDS.index('flags')]='4097'
        content[-1]=','.join(row); self.source.write_text('\n'.join(content)+'\n')
        importar(self.source,self.id)
        with self.engine.connect() as c:
            rows=[json.loads(r) for r in c.execute(select(models.ciclos.c.dados_json)).scalars()]
        self.assertIsNone(rows[-1]['hx_mean_counts']); self.assertEqual(rows[-1]['flags'],4097)

    def test_lifecycle_and_retention_with_raw_children(self):
        importar(self.source,self.id)
        lifecycle.alterar(self.id,'EM_ANDAMENTO')
        with self.assertRaises(ValueError): lifecycle.alterar(self.id,'descartar')
        lifecycle.alterar(self.id,'CONCLUIDO'); lifecycle.alterar(self.id,'descartar')
        with self.assertRaises(ValueError): importar(self.source,self.id)
        with self.assertRaises(ValueError): lifecycle.alterar(self.id,'excluir')
        lifecycle.alterar(self.id,'restaurar')
        self.assertEqual(sqlite.consultar_ensaio(self.id)['estado'],'CONCLUIDO')
        lifecycle.alterar(self.id,'descartar')
        with self.engine.begin() as c:
            c.execute(models.ensaios.update().where(models.ensaios.c.id==self.id).values(excluir_apos=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()))
        lifecycle.alterar(self.id,'excluir')
        self.assertIsNone(sqlite.consultar_ensaio(self.id))
        with self.engine.connect() as c: self.assertEqual(c.execute(select(models.ciclos)).all(),[])

    def test_serial_preserves_fragments_on_disconnect(self):
        class Fake:
            def __init__(self,*a,**k): self.lines=iter([b'# boot,x\n', b'schema,cycle,\n', b'1,partial'])
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def readline(self):
                try: return next(self.lines)
                except StopIteration: raise OSError('desconectado')
            def write(self,data): pass
        path=self.folder/'serial.csv'
        with self.assertRaises(OSError): capturar('fake',path,5,serial_factory=Fake)
        self.assertEqual(path.read_bytes(),b'# boot,x\nschema,cycle,\n1,partial')
        self.assertEqual(len(path.with_name(path.name+'.recepcao.jsonl').read_text().splitlines()),3)
        with self.assertRaises(FileExistsError): capturar('fake',path,5,serial_factory=Fake)

    def test_science_uses_measured_temperature_and_correct_material(self):
        temperatures=[28,30,35,40,38,34,30]
        frame=pd.DataFrame({'tempo_s':range(7),'temperatura_C':temperatures,'deslocamento_mm':[0.01*t+0.2 for t in temperatures]})
        report=analisar_serie(frame,545,'Alumínio')
        self.assertEqual(report['material_informado'],'Alumínio')
        for fit in report['ajustes']:
            self.assertAlmostEqual(fit['alpha_aparente_C_inv'],0.01/545)
        parameters={'series_ohms':10000,'beta_K':3950,'r0_ohms':10000,'t0_C':25,'mm_per_count':0.001,'ntc_to_ground':True}
        output=processar_captura(self.source,parameters)
        self.assertEqual(len(output['sessoes'][0]['pares']),3)
        self.assertAlmostEqual(output['sessoes'][0]['pares'][0]['deslocamento_mm'],0.1)

    def test_calibration_keeps_evidence_and_is_not_self_validated(self):
        path=self.folder/'cal.csv'; path.write_text('counts,displacement_mm\n0,0\n100,0.1\n200,0.2\n')
        report=ajustar_calibracao(path,'deslocamento','Referência de teste')
        self.assertAlmostEqual(report['parametros']['mm_per_count'],0.001)
        self.assertFalse(report['validada_experimentalmente'])
        self.assertEqual(len(report['fonte_sha256']),64)

    def test_serial_start_handles_fragmented_header_and_stops(self):
        writes=[]
        class Fake:
            def __init__(self,*a,**k): self.lines=iter([b'schema,cy',b'cle,other\n'])
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def readline(self): return next(self.lines)
            def write(self,data): writes.append(data)
        with patch('system_dilatation.acquisition.serial_capture.time.monotonic',side_effect=[0,.1,.2,.3]):
            result=capturar('fake',self.folder/'success.csv',.25,serial_factory=Fake,iniciar=True)
        self.assertEqual(writes,[b's\n',b'p\n'])
        self.assertEqual(result['fragmentos'],2)

    def test_bad_second_input_is_rejected_before_first_commit(self):
        cell=self.folder/'cell.csv'; cell.write_text('leitura,tempo_s,bits_media,deltaL_mm\n1,0,1,0.1\n')
        ntc=self.folder/'ntc.csv'; ntc.write_text('leitura,tempo_s,bits_medido,temperatura_C\n1,0,512,inf\n')
        with patch('sys.argv',['etl','--ensaio-id',self.id,'--celula',str(cell),'--termistor',str(ntc)]):
            from contextlib import redirect_stderr
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit): loading.main()
        with self.engine.connect() as c: self.assertEqual(c.execute(select(models.hx711)).all(),[])

    def test_corrected_historical_analysis_with_independent_peaks(self):
        import subprocess, sys
        rows=[]
        temperatures=[28,30,40,38,35,30]
        for i,temperature in enumerate(temperatures,1):
            rows.append([i,i*10,100,10,10,0.1,1.0,0.5 if i==2 else i*0.01])
        path=self.folder/'historical.txt'
        path.write_text('\n'.join(','.join(map(str,r)) for r in rows)+'\n')
        temps=self.folder/'temps.csv'
        pd.DataFrame({'ensaio':['A']*6,'leitura':range(1,7),'temperatura_C':temperatures}).to_csv(temps,index=False)
        metadata=self.folder/'metadata.json'
        metadata.write_text(json.dumps({'A':{'arquivo':'historical.txt','material':'Alumínio','comprimento_mm':545}}))
        script=Path(__file__).resolve().parents[1]/'analysis/ensaios_historicos.py'
        result=subprocess.run([sys.executable,str(script),'--metadados',str(metadata),'--temperaturas',str(temps),'--out',str(self.folder/'reports')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(next((self.folder/'reports').glob('*.json')).read_text())
        self.assertEqual(report['classificacao'],'coeficientes_aparentes')
        self.assertEqual(report['material_informado'],'Alumínio')

    def test_operational_backup_and_calibration_registration(self):
        importar(self.source,self.id)
        backup=self.folder/'backup.db'
        with redirect_stdout(io.StringIO()): main(['backup','--destino',str(backup)])
        with closing(sqlite3.connect(backup)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM ciclos').fetchone()[0],3)
        calibration=self.folder/'calibration.csv'
        calibration.write_text('counts,displacement_mm\n0,0\n100,0.1\n200,0.2\n')
        output=self.folder/'calibration.json'
        with redirect_stdout(io.StringIO()): main(['calibrar',str(calibration),'--tipo','deslocamento','--referencia','Teste','--destino',str(output)])
        record=json.loads(output.read_text())
        with self.engine.connect() as c:
            self.assertEqual(c.execute(select(models.calibracoes.c.id)).scalar_one(),record['id'])

    def test_parser_accepts_actual_firmware_output(self):
        import shutil, subprocess
        if not shutil.which('g++'):
            self.skipTest('g++ indisponível')
        firmware=Path(__file__).resolve().parents[1]/'firmware'
        exe=self.folder/'firmware'
        subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror',
            '-I'+str(firmware/'test/native/fakes'),'-I'+str(firmware/'include'),
            str(firmware/'test/native/test_firmware.cpp'),'-o',str(exe)], check=True)
        output=subprocess.run([str(exe),'dump'],capture_output=True,check=True).stdout
        self.source.write_bytes(output)
        result=importar(self.source,self.id)
        self.assertEqual(result['ciclos'],1)
        self.assertEqual(Path(result['arquivo_preservado']).read_bytes(),output)

    def test_engine_creation_is_lazy_and_schema_creates_data_directory(self):
        path=self.folder/'new-directory'/'nested'/'db.sqlite'
        engine=sqlite.criar_engine(path)
        try:
            self.assertFalse(path.parent.exists())
            with patch.object(sqlite,'engine',engine): sqlite.criar_banco()
            self.assertTrue(path.exists())
        finally: engine.dispose()

    def test_cli_selects_db_without_mutating_default_engine(self):
        target=self.folder/'cli.db'
        with redirect_stdout(io.StringIO()): main(['--db',str(target),'criar-ensaio','CLI'])
        with closing(sqlite3.connect(target)) as c: self.assertEqual(c.execute('SELECT nome FROM ensaios').fetchone()[0],'CLI')
        self.assertIs(sqlite.engine,self.engine)


if __name__=='__main__': unittest.main()
