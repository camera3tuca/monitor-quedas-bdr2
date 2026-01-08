# 📈 Monitor BDR - Swing Trade

Um aplicativo profissional em **Streamlit** para análise técnica e detecção de oportunidades de **swing trade** em BDRs (Brazilian Depositary Receipts) listados na B3.

## 🎯 Funcionalidades

- ✅ **Busca Automática de BDRs** via BRAPI API
- ✅ **Indicadores Técnicos Avançados**:
  - RSI (Relative Strength Index)
  - MACD (Moving Average Convergence Divergence)
  - Bandas de Bollinger
  - Fibonacci Golden Zone
  - Médias Móveis (EMA)
  - Divergência Bullish
  
- ✅ **Sinais de Reversão**:
  - RSI Oversold/Sobrecompra
  - Suporte e Resistência
  - MACD Positivo/Negativo
  - Fibo Golden Zone
  - Volatilidade Extrema
  - Divergência Bullish

- ✅ **Visualizações Profissionais**:
  - Gráficos interativos dos Top 5
  - Tabelas com dados completos
  - Resumo detalhado expansível

- ✅ **Filtros Automáticos**:
  - Apenas BDRs em queda no dia
  - Score de confiança (0-10)
  - Análise de volume e liquidez

## 🚀 Como Usar

### Instalação Local

```bash
# Clone o repositório
git clone https://github.com/seu-usuario/monitor-quedas-bdr.git
cd monitor-quedas-bdr

# Crie um ambiente virtual
python -m venv venv
source venv/bin/activate  # No Windows: venv\Scripts\activate

# Instale as dependências
pip install -r requirements.txt

# Execute o app
streamlit run app.py
```

### Deploy no Streamlit Cloud

1. **Faça push para o GitHub**:
```bash
git add .
git commit -m "Deploy Monitor BDR"
git push origin main
```

2. **Acesse Streamlit Cloud**:
   - Vá para https://share.streamlit.io/
   - Clique em "New app"
   - Selecione seu repositório
   - Branch: `main`
   - Main file: `app.py`
   - Clique em "Deploy"

3. **Configure Secrets (se necessário)**:
   - Vá em Settings → Secrets
   - Adicione variáveis conforme necessário

## 📊 Como Interpretar os Sinais

### Score de Confiança
- 🟢 **Score ≥ 5**: Forte oportunidade de reversão
- 🟡 **Score 2-4**: Oportunidade moderada
- 🔴 **Score < 2**: Fraco, avalie com cuidado

### Sinais Principais

| Sinal | O que significa | Ação |
|-------|-----------------|------|
| 🔴 RSI Oversold | Ativo muito vendido | Potencial compra |
| 🟡 Fibo Golden Zone | Preço em nível Fibonacci | Suporte/Resistência |
| 💪 Suporte BB (Forte) | Preço no suporte | Provável reversão |
| 🔄 Divergência Bullish | Preço cai, RSI sobe | Reversão muito provável |
| ✅ MACD Positivo | Momentum positivo | Confirma reversão |

## 📈 Estratégia Recomendada

1. **Identifique** as BDRs com maior Score
2. **Analise** os gráficos (preço, RSI, MACD)
3. **Espere** confirmação de reversão
4. **Entre** com stop loss 2% abaixo do suporte
5. **Saída** quando atingir resistência ou MACD virar negativo

## ⚙️ Estrutura do Projeto

```
monitor-quedas-bdr/
├── app.py                 # Aplicativo Streamlit
├── requirements.txt       # Dependências Python
├── .streamlit/
│   └── secrets.toml      # Variáveis sensíveis (não commitado)
├── .gitignore            # Arquivos a ignorar
└── README.md             # Este arquivo
```

## 🔧 Dependências

- **streamlit**: Framework web
- **pandas**: Manipulação de dados
- **numpy**: Computações numéricas
- **yfinance**: Download de dados históricos
- **matplotlib & seaborn**: Visualizações
- **requests**: Requisições HTTP
- **pytz**: Timezone Brasil

## 📡 APIs Utilizadas

### BRAPI
- **URL**: `https://brapi.dev/api/quote/list`
- **Uso**: Lista todas as BDRs negociadas
- **Rate Limit**: 120 requests/minuto (free)

### Yahoo Finance
- **Via yfinance**: Dados históricos de preço/volume
- **Período**: 6 meses de histórico
- **Atualização**: Diária

## ⚠️ Disclaimers

- Este app é apenas para **análise técnica educacional**
- **NÃO é recomendação de investimento**
- Sempre faça sua própria análise antes de operar
- Swing trade envolve risco, use stop loss sempre
- Histórico passado ≠ Garantia de resultado futuro

## 🤝 Contribuições

Sugestões e melhorias são bem-vindas! Abra uma issue ou faça um pull request.

## 📝 Licença

MIT License - veja LICENSE.md para detalhes

## 📞 Contato

Para dúvidas ou sugestões, abra uma issue no GitHub.

---

**Desenvolvido com ❤️ para traders de swing trade em BDRs**
