# Bancada e calibração: execução física pendente

Este procedimento está preparado para execução com instrumentos reais. Nenhum
resultado abaixo é presumido e nenhum parâmetro experimental foi inventado.

## 1. Identificação antes de ligar

Registrar modelo/fabricante da célula de 5 kg, pontos de fixação e aplicação de
carga, material/comprimento da amostra, NTC, display e resistor de referência.
Fotografar/desenhar a montagem e registrar o sentido das contagens.

Decidir entre um divisor NTC independente em A0 ou uma interface documentada do
display. Não ligar a mesma sonda em paralelo aos dois circuitos sem avaliar o efeito
sobre a medição. Ainda precisamos dessas informações do usuário.

## 2. Primeiro teste em bancada

1. Compilar e carregar o firmware; monitor em 115200 baud.
2. Testar HX711 em repouso com conversões desabilitadas e sem aquecimento.
3. Fazer tara na condição mecânica definida e registrar sua revisão.
4. Confirmar variação das contagens, sentido e ausência de saturação.
5. Conectar o divisor NTC confirmado e habilitar apenas leitura ADC.
6. Fazer captura bruta; testar falhas, reinício, pausa e recuperação.
7. Medir a duração real de cada janela e a separação temporal. Confirmar RATE do
   HX711 e ajustar janela, amostras e tolerância a partir da captura.

Os timestamps do HX711 são de leitura; não determinam sozinhos o instante interno
da conversão. A tolerância de 250 ms ainda é provisória.

## 3. Temperatura

Registrar pares de resistência e temperatura de referência em diferentes pontos
da faixa de uso, incluindo aquecimento/resfriamento, repetição e estabilização.
Documentar o instrumento de referência e sua especificação/calibração.

Formato CSV para ajuste beta:

```text
resistance_ohms,temperature_C
```

O comando `calibrar --tipo ntc` ajusta os parâmetros, registra fonte/hash e referência.
O ajuste não certifica o sensor. Analisar resíduos em temperatura, repetibilidade,
autoaquecimento e faixa de validade antes de habilitar as conversões.

## 4. Deflexão da célula

Aplicar deslocamentos conhecidos no mesmo ponto e montagem do uso real. Usar uma
referência independente, registrar carga/descarga e repetições. Calibração só com
massas não determina diretamente milímetros de deflexão.

Formato CSV para ajuste linear:

```text
counts,displacement_mm
```

As contagens precisam usar a mesma referência de tara da conversão futura. O ajuste
retorna inclinação e intercepto; o firmware usa só inclinação após a tara. Se o
intercepto for relevante, investigar a referência e não descartá-lo silenciosamente.

Registrar limites, resolução, repetibilidade, resíduos e incerteza. Identificar e
preservar os dados de validação independentes dos dados usados no ajuste.

## 5. Montagem e resultado científico

Verificar se o deslocamento observado na célula corresponde à variação de comprimento
da amostra nas condições de contato e restrição. Avaliar a contribuição térmica e
mecânica dos apoios, contato, célula e estrutura.

Somente essa validação permite interpretar o resultado como dilatação da amostra.
Os relatórios de software permanecem com coeficientes aparentes. Não usar R² alto
como comprovação de calibração ou identificação do material.

## Registro de aceitação

Preencher data/operador, componentes e esquema, identificadores das referências,
fontes/hash, faixa de uso, parâmetros, resultados das repetições, incerteza,
limites temporais, problemas observados e decisão de aceitação. Enquanto isso não
for executado, etapas 18 e 19 permanecem pendentes de validação física.
