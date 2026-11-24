# Aquisição conjunta — Arduino Uno, HX711 e NTC

Firmware para registrar célula de carga de **5 kg** e um futuro NTC no mesmo
Arduino. Preserva dados brutos e identifica leituras incompletas. Não utiliza os
fatores teóricos para célula de 10 kg do firmware anterior.

## Configuração e ligação

Edite `include/config.h` antes da compilação.

| Sinal | Pino do Uno | Observação |
|---|---|---|
| HX711 DOUT/DT | D2 | Entrada com pull-up; ausência de conversão não bloqueia o loop |
| HX711 SCK/CLK | D3 | Canal A, ganho 128 |
| Divisor NTC | A0 | Desabilitado inicialmente; exige circuito confirmado |
| LED | D13 | Aceso durante aquisição de uma janela ou tara |

Alimente o módulo HX711 conforme sua documentação e use GND comum com o Uno.
Ligue a célula em E+/E− e A+/A− conforme a identificação do fabricante. As cores
informadas no anúncio foram vermelho/E+, preto/E−, verde/A+ e branco aparentemente
A−; confirme essa última identificação antes de ligar.

Para um NTC independente, o circuito previsto é:

```text
VCC/AVCC do Uno ─ resistor fixo ─┬─ NTC ─ GND
                              └─ A0
```

Defina `NTC_ENABLED=true` somente depois de montar esse divisor. Para inverter as
posições do resistor e do NTC, configure `NTC_TO_GROUND=false`. O divisor usa a
mesma alimentação da referência ADC padrão; outras referências exigem adaptar a
conversão. Uma entrada analógica flutuante pode produzir valores intermediários:
a identificação de extremos ADC não garante detectar toda desconexão.

**O NTC com display ainda não tem interface identificada.** Este firmware não lê
o display nem pressupõe acesso digital a ele. Não conecte a sonda em paralelo a
A0 mantendo o circuito do display: isso pode alterar a medição. Use um divisor
independente ou defina primeiro a interface documentada do instrumento.

## Valores iniciais e calibração

Os seguintes valores são provisórios para coleta piloto:

- Um ciclo a cada **10.000 ms**, com até **10 tentativas** por sensor.
- Janela máxima de **2.500 ms**; NTC a cada **100 ms** dentro da janela.
- Limite de **250 ms** entre centros das janelas observadas, apenas para diagnóstico.
- Tara manual com **20 tentativas**, prazo de **5.000 ms**.

Os dez segundos correspondem ao procedimento histórico informado pelo usuário;
a janela, quantidade de amostras e tolerância continuam sujeitos à validação do
experimento. A taxa física de 10/80 SPS do HX711 depende do pino RATE do módulo:
o firmware não altera esse pino. Em 80 SPS, dez leituras ocupam uma janela menor
que em 10 SPS, podendo gerar o indicador de desalinhamento temporal.

As conversões começam desabilitadas. Para configurar o modelo beta do NTC,
preencha `SERIES_OHMS`, `NTC_R0_OHMS`, `NTC_BETA_K`, `NTC_T0_C`, a orientação do
divisor e `NTC_CALIBRATION_ID`; depois habilite `NTC_MODEL_ENABLED`.
A temperatura é calculada a partir da média ADC. Parâmetros do fabricante
permitem uma estimativa; a validação experimental contra referência continua necessária.

Para obter deflexão da célula, calibre o conjunto no mesmo ponto de contato e
preencha `MM_PER_COUNT`, com sinal, e `DISPLACEMENT_CALIBRATION_ID`; depois habilite
`DISPLACEMENT_ENABLED`. O cálculo é:

```text
contagens_corrigidas = média_bruta − tara
cell_deflection_mm = contagens_corrigidas × MM_PER_COUNT
```

Esse campo é **deflexão da célula no ponto calibrado**. A equivalência com a
dilatação da amostra ainda precisa ser validada mecanicamente. O firmware não
calcula força, coeficiente de dilatação ou correção para o comprimento de 545 mm.
Calibração não configurada, falta de tara e amostras incompletas deixam os campos
físicos correspondentes em `nan`; nenhum zero é usado para representar ausência.

## Compilação e operação

Com PlatformIO instalado:

```bash
pio run -d firmware
pio run -d firmware --target upload --upload-port /dev/ttyACM0
pio device monitor -d firmware --port /dev/ttyACM0
```

A porta acima é um exemplo. O monitor agora usa **115200 baud**; firmware e
receptor devem concordar. Upload e teste físico devem ser executados na placa.

O equipamento inicia **pausado**, sem tara automática. Envie letras minúsculas:

| Comando | Ação |
|---|---|
| `h` | Mostra ajuda |
| `t` | Solicita tara quando pausado; mantenha a condição mecânica de referência estável |
| `s` | Inicia aquisição; primeiro ciclo após dez segundos |
| `p` | Pausa; uma janela ativa é emitida como cancelada |

A tara exige todas as vinte tentativas válidas e sem saturação. Falhas preservam
a referência anterior; ao reiniciar a placa ela é perdida. Cada tara bem-sucedida
incrementa `tare_revision`. `p` pausa aquisição de ciclos; uma tara já solicitada
termina ou expira pelo seu prazo. Não altere a referência durante um ensaio sem
registrar essa mudança. É possível coletar valores brutos sem executar tara.

## Protocolo CSV, versão 1

A serial transmite metadados/eventos iniciados por `#`, um cabeçalho CSV e uma linha
por ciclo. Preserve os metadados junto das linhas para rastrear parâmetros e taras.
Um novo `# boot` indica nova sessão. O contador de ciclos reinicia em cada boot;
o UUID do ensaio é responsabilidade da aplicação no computador.

| Campos | Significado |
|---|---|
| `schema`, `cycle` | Versão do protocolo e ciclo sequencial, inclusive falhas |
| `millis_wraps` | Número de voltas de `millis()` observado desde o boot |
| `window_start_ms`, `window_end_ms` | Início/fim da janela do ciclo, relógio do Arduino |
| `late_ms` | Atraso do início em relação ao intervalo configurado |
| `hx_first_ms`, `hx_last_ms` | Instantes de leitura da primeira/última amostra válida do HX711 |
| `hx_valid`, `hx_attempts` | Amostras aceitas e tentativas recebidas; os extremos de 24 bits são sinalizados |
| `hx_mean_counts` | Média bruta das amostras válidas; pode existir em lote parcial |
| `tare_counts`, `tare_revision`, `hx_corrected_counts` | Referência e média corrigida; campos dependentes da tara ficam `nan` antes dela |
| `ntc_first_ms`, `ntc_last_ms` | Instantes da primeira/última leitura ADC válida |
| `ntc_valid`, `ntc_attempts`, `ntc_adc_mean` | Contagens de amostras/tentativas e média ADC; códigos 0/1023 são rejeitados |
| `ntc_resistance_ohms`, `temperature_C` | Estimativas apenas com NTC configurado e lote completo sem extremos |
| `cell_deflection_mm` | Deflexão estimada apenas com fator configurado, tara e lote completo sem extremos |
| `midpoint_skew_ms` | Diferença entre centros das janelas válidas; `nan` se faltar uma série |
| `flags` | Soma dos indicadores abaixo; não interpretar como um único estado |

Os tempos estão em milissegundos desde o boot e voltam a zero após cerca de 49,7
dias. Use subtração modular de 32 bits nos intervalos; `millis_wraps` corresponde ao
fim da janela e permite reconstruir a cronologia junto das marcas temporais.
Os timestamps do HX711 são de **leitura do resultado**, não de início/fim da sua
conversão interna. Uma conversão pode ter começado antes da janela. O conversor é
lido continuamente fora das janelas para evitar reter uma conversão antiga.
As janelas compartilham relógio; não são conversões simultâneas nem comprovação
de sincronismo físico. A diferença entre centros é um diagnóstico aproximado.

| Bit/valor | Indicador |
|---|---|
| 1 | HX711 com menos amostras válidas que o alvo |
| 2 | HX711 atingiu um extremo do ADC |
| 4 | Tara ainda não realizada |
| 8 | NTC desabilitado |
| 16 | NTC com menos amostras válidas que o alvo |
| 32 | NTC atingiu 0 ou 1023 no ADC |
| 64 | Modelo de conversão do NTC desabilitado |
| 128 | Conversão de deflexão desabilitada |
| 256 | Centros das janelas separados além da tolerância provisória |
| 512 | Início do ciclo atrasado |
| 1024 | Conversão habilitada gerou resultado inválido ou recebeu parâmetros inválidos |
| 2048 | Janela cancelada pelo comando de pausa |
| 4096 | Prazo máximo da janela atingido |

Campos físicos de um sensor podem ser finitos quando o outro falhou; para analisar
a relação entre temperatura e deflexão, a aplicação precisa validar o par e os
indicadores. O limite de tempo encerra a janela e mantém o firmware responsivo.
A emissão serial é síncrona; não ocorre dentro do trecho crítico dos pulsos SCK.

**Este CSV não é entrada direta do ETL atual.** O ETL recebe séries separadas e
exige grandezas físicas preenchidas. O receptor/importador Python está disponível nos comandos `capturar` e
`importar-captura`; ele preserva eventos, identifica a sessão/ensaio e trata `nan`,
falhas e janelas parciais. Veja [operação integrada](../docs/operacao.md). Não renomeie automaticamente `cell_deflection_mm` para dilatação da barra.

## Verificação

Testes nativos com `g++` e Python 3, sem Arduino conectado:

```bash
python firmware/test/native/run.py
```

O script verifica extensão de sinal de 24 bits, média com acumulador inteiro,
tratamento de ausência de dados, conversão do divisor nas duas orientações,
modelo beta e passagem do relógio por zero. Executa ainda 30 cenários do firmware
real com I/O simulado: padrão, NTC bruto e parâmetros de teste habilitados.
Os valores fictícios de calibração usados pelos testes não são gravados na configuração.

Compilação para Uno e simulação não validam circuito, precisão, calibração,
temporização elétrica dos pulsos ou comportamento térmico. Na bancada, verificar
os pulsos SCK, leituras em repouso, desconexões, saturação, tara, janelas e comparação
com referências antes de usar os valores físicos no experimento.

## Referências

- [Datasheet AVIA HX711](https://cdn.sparkfun.com/datasheets/Sensors/ForceFlex/hx711_english.pdf): interface, ganho, taxa e saturação.
- [Equações e circuito de termistor — Portland State University](https://web.cecs.pdx.edu/~gerry/class/EAS199B/howto/thermistorArduino/thermistorArduino.pdf): divisor e conversão de resistência.

- [Constante beta — TDK](https://product.tdk.com/en/contact/faq/protection-0009.html): relação entre resistência e temperatura absoluta.
