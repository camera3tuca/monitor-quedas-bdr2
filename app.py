import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
import seaborn as sns
import requests
import urllib.parse
from datetime import datetime
import pytz
import warnings

# --- CONFIGURAÇÃO DA PÁGINA ---
VERSAO = "v5.2 (Base Estável + Funcionalidades Completas)"
st.set_page_config(
    page_title=f"Monitor BDR {VERSAO}",
    page_icon="🦅",
    layout="wide"
)

warnings.filterwarnings('ignore')
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

# Aumentado para 1 ano para permitir o cálculo da Média de 200
PERIODO = "1y" 
TERMINACOES_BDR = ('31', '32', '33', '34', '35', '39')

# --- IMPORTAÇÃO DOS SEGREDOS ---
try:
    BRAPI_API_TOKEN = st.secrets["BRAPI_API_TOKEN"]
    # Adicionamos os segredos do WhatsApp para o botão de envio
    WHATSAPP_PHONE = st.secrets["WHATSAPP_PHONE"]
    WHATSAPP_APIKEY = st.secrets["WHATSAPP_APIKEY"]
except:
    st.error("ERRO: Configure as chaves (BRAPI e WHATSAPP) nos 'Secrets' do Streamlit.")
    st.stop()

# --- FUNÇÕES AUXILIARES ---

def obter_hora_brasil():
    fuso = pytz.timezone('America/Sao_Paulo')
    return datetime.now(fuso).strftime('%d/%m %H:%M')

def enviar_whatsapp(msg):
    try:
        texto = urllib.parse.quote(msg)
        phone = WHATSAPP_PHONE.replace("+", "").strip()
        url = f"https://api.textmebot.com/send.php?recipient=+{phone}&apikey={WHATSAPP_APIKEY}&text={texto}"
        requests.get(url, timeout=20)
        return True
    except: return False

@st.cache_data(ttl=3600)
def obter_dados_brapi():
    try:
        url = f"https://brapi.dev/api/quote/list?token={BRAPI_API_TOKEN}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        
        dados = r.json().get('stocks', [])
        bdrs_raw = [d for d in dados if d['stock'].endswith(TERMINACOES_BDR)]
        lista_tickers = [d['stock'] for d in bdrs_raw]
        mapa_nomes = {d['stock']: d.get('name', d['stock']) for d in bdrs_raw}
        return lista_tickers, mapa_nomes
    except Exception as e:
        st.error(f"Erro ao buscar BRAPI: {e}")
        return [], {}

@st.cache_data(ttl=1800)
def buscar_dados(tickers):
    if not tickers: return pd.DataFrame()
    sa_tickers = [f"{t}.SA" for t in tickers]
    try:
        # ignore_tz=True adicionado para evitar erros de fuso horário
        df = yf.download(sa_tickers, period=PERIODO, auto_adjust=True, progress=False, timeout=60, ignore_tz=True)
        if df.empty: return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = pd.MultiIndex.from_tuples([(c[0], c[1].replace(".SA", "")) for c in df.columns])
        return df.dropna(axis=1, how='all')
    except Exception: return pd.DataFrame()

def calcular_indicadores(df):
    df_calc = df.copy()
    tickers = df_calc.columns.get_level_values(1).unique()
    
    progresso = st.progress(0)
    total = len(tickers)
    
    for i, ticker in enumerate(tickers):
        # Atualiza a barra a cada 20 ativos para não travar
        if i % 20 == 0: progresso.progress((i + 1) / total)
        try:
            close = df_calc[('Close', ticker)]
            high = df_calc[('High', ticker)]
            low = df_calc[('Low', ticker)]
            
            # RSI 14
            delta = close.diff()
            ganho = delta.clip(lower=0).rolling(14).mean()
            perda = -delta.clip(upper=0).rolling(14).mean()
            rs = ganho / perda
            df_calc[('RSI14', ticker)] = 100 - (100 / (1 + rs))

            # ESTOCÁSTICO 14 (%K)
            lowest_low = low.rolling(window=14).min()
            highest_high = high.rolling(window=14).max()
            df_calc[('Stoch_K', ticker)] = 100 * ((close - lowest_low) / (highest_high - lowest_low))

            # MÉDIAS (Incluindo a de 200 para o gráfico preferido)
            df_calc[('EMA20', ticker)] = close.ewm(span=20).mean()
            df_calc[('SMA200', ticker)] = close.rolling(window=200).mean()
            
            # Bollinger
            sma = close.rolling(20).mean()
            std = close.rolling(20).std()
            df_calc[('BB_Lower', ticker)] = sma - (std * 2)
            df_calc[('BB_Upper', ticker)] = sma + (std * 2)

            # MACD
            ema_12 = close.ewm(span=12).mean()
            ema_26 = close.ewm(span=26).mean()
            macd = ema_12 - ema_26
            signal = macd.ewm(span=9).mean()
            df_calc[('MACD_Hist', ticker)] = macd - signal
        except: continue
            
    progresso.empty()
    return df_calc

def calcular_fibonacci(df_ticker):
    try:
        if len(df_ticker) < 50: return None
        high = df_ticker['High'].max()
        low = df_ticker['Low'].min()
        diff = high - low
        return {'61.8%': low + (diff * 0.618)} 
    except: return None

def gerar_sinal(row_ticker, df_ticker):
    sinais = []
    score = 0
    
    def classificar(s):
        if s >= 4: return "Muito Alta"
        if s >= 2: return "Alta"
        if s >= 1: return "Média"
        return "Baixa"

    try:
        close = row_ticker.get('Close')
        rsi = row_ticker.get('RSI14')
        stoch = row_ticker.get('Stoch_K')
        macd_hist = row_ticker.get('MACD_Hist')
        bb_lower = row_ticker.get('BB_Lower')
        sma200 = row_ticker.get('SMA200')
        
        # --- LÓGICA DO GRÁFICO PREFERIDO ---
        tendencia_alta = False
        if pd.notna(sma200) and close > sma200:
            tendencia_alta = True
            sinais.append("Trend Alta")
            score += 3
        
        # Sinais de Reversão
        if pd.notna(rsi):
            if rsi < 30:
                sinais.append("RSI Oversold")
                score += 3
            elif rsi < 40:
                score += 1
        
        if pd.notna(stoch):
            if stoch < 20:
                sinais.append("Stoch. Fundo")
                score += 2
            
        if pd.notna(macd_hist) and macd_hist > 0:
            sinais.append("MACD Virando")
            score += 1
            
        if pd.notna(close) and pd.notna(bb_lower):
            if close < bb_lower:
                sinais.append("Abaixo BB")
                score += 2
            elif close < bb_lower * 1.02:
                sinais.append("Suporte BB")
                score += 1

        fibo = calcular_fibonacci(df_ticker)
        if fibo and (fibo['61.8%'] * 0.99 <= close <= fibo['61.8%'] * 1.01):
            sinais.append("Fibo 61.8%")
            score += 2

        return sinais, score, classificar(score), tendencia_alta
    except:
        return [], 0, "Indefinida", False

def analisar_oportunidades(df_calc, mapa_nomes):
    resultados = []
    tickers = df_calc.columns.get_level_values(1).unique()

    for ticker in tickers:
        try:
            df_ticker = df_calc.xs(ticker, axis=1, level=1).dropna()
            if len(df_ticker) < 50: continue

            last = df_ticker.iloc[-1]
            anterior = df_ticker.iloc[-2]
            
            preco = last.get('Close')
            preco_ant = anterior.get('Close')
            preco_open = last.get('Open')
            volume = last.get('Volume')
            
            if pd.isna(preco) or pd.isna(preco_ant): continue

            # Variações
            queda_dia = ((preco - preco_ant) / preco_ant) * 100
            gap = ((preco_open - preco_ant) / preco_ant) * 100
            
            if queda_dia >= 0: continue 

            # --- CÁLCULO VARIAÇÃO 7 DIAS ---
            var_7d = np.nan
            if len(df_ticker) >= 6:
                preco_7d = df_ticker['Close'].iloc[-6]
                var_7d = ((preco - preco_7d) / preco_7d) * 100

            sinais, score, classificacao, tendencia_alta = gerar_sinal(last, df_ticker)
            
            # I.S. (Índice de Sobrevenda)
            rsi = last.get('RSI14', 50)
            stoch = last.get('Stoch_K', 50)
            is_index = ((100 - rsi) + (100 - stoch)) / 2
            
            # Tratamento de Nome
            nome_completo = mapa_nomes.get(ticker, ticker)
            nome_curto = nome_completo.split()[0].replace(',', '').title() if nome_completo else ticker

            # Define o "Setup" (Estratégia)
            setup = "⭐ COMPRA" if tendencia_alta else "⚠️ REPIQUE"

            resultados.append({
                'Ticker': ticker,
                'Empresa': nome_curto,
                'Preco': preco,
                'Volume': volume,
                'Queda_Dia': queda_dia,
                'Var_7d': var_7d, # Novo
                'Gap': gap,
                'IS': is_index, 
                'RSI14': rsi,
                'Stoch': stoch,
                'Setup': setup, # Novo
                'Trend': tendencia_alta,
                'Potencial': classificacao,
                'Score': score,
                'Sinais': ", ".join(sinais) if sinais else "-"
            })
        except: continue
    return resultados

def plotar_grafico(df_ticker, ticker, empresa, setup):
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, gridspec_kw={'height_ratios': [3, 1, 1]})
    
    close = df_ticker['Close']
    sma200 = df_ticker['SMA200']
    
    # Preço
    ax1 = axes[0]
    ax1.plot(close.index, close.values, label='Close', color='#333333')
    
    # Linha Dourada (Média de 200) - O indicador do nosso gráfico preferido
    if not sma200.isnull().all():
        ax1.plot(close.index, sma200, label='SMA 200 (Tendência)', color='gold', linewidth=2)
        
    ax1.plot(close.index, df_ticker['EMA20'], label='EMA 20', alpha=0.7, color='blue')
    ax1.fill_between(close.index, df_ticker['BB_Lower'], df_ticker['BB_Upper'], alpha=0.15, color='gray')
    
    icon = "⭐" if "COMPRA" in setup else "⚠️"
    ax1.set_title(f'{icon} {ticker} - {empresa} | {setup}', fontweight='bold')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)

    # RSI
    ax2 = axes[1]
    ax2.plot(close.index, df_ticker['RSI14'], color='orange', label='RSI')
    ax2.axhline(30, color='red', linestyle='--', linewidth=1)
    ax2.axhline(70, color='green', linestyle='--', linewidth=1)
    ax2.fill_between(close.index, 0, 30, alpha=0.2, color='red')
    ax2.set_ylabel('RSI')
    ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.3)
    
    # Estocástico
    ax3 = axes[2]
    if 'Stoch_K' in df_ticker.columns:
        ax3.plot(close.index, df_ticker['Stoch_K'], color='purple', label='Stoch %K')
        ax3.axhline(20, color='red', linestyle='--', linewidth=1)
        ax3.axhline(80, color='green', linestyle='--', linewidth=1)
        ax3.fill_between(close.index, 0, 20, alpha=0.2, color='red')
    ax3.set_ylabel('Stoch')
    ax3.set_ylim(0, 100)
    ax3.grid(True, alpha=0.3)
    
    plt.tight_layout()
    return fig

# Funções de Estilo
def estilizar_is(val):
    if val >= 75: return 'background-color: #d32f2f; color: white; font-weight: bold'
    elif val >= 60: return 'background-color: #ffa726; color: black'
    else: return 'color: #888888'

def estilizar_setup(val):
    if "COMPRA" in val: return 'background-color: #1b5e20; color: white; font-weight: bold'
    return 'color: #555'

# --- LAYOUT DO APP ---

# Cabeçalho com Versão e Horário
c1, c2 = st.columns([3, 1])
c1.title(f"🦅 Monitor BDR - {VERSAO}")
c2.markdown(f"**🕒 {obter_hora_brasil()} (Brasília)**")

# --- LEGENDA DOS SINAIS (NOVO) ---
with st.expander("ℹ️ LEGENDA E INDICADORES (Clique para abrir)"):
    col_l1, col_l2 = st.columns(2)
    with col_l1:
        st.markdown("""
        * **⭐ COMPRA (Trend Alta):** O preço caiu, mas a tendência principal é de ALTA (Preço acima da Média de 200 dias). É o setup ideal.
        * **⚠️ REPIQUE:** O preço caiu, mas a tendência é de BAIXA (Preço abaixo da Média de 200). Cuidado redobrado.
        * **I.S. (Índice de Sobrevenda):** De 0 a 100. Acima de 80 indica que caiu "demais" e pode repicar.
        """)
    with col_l2:
        st.markdown("""
        * **SMA 200 (Linha Dourada):** Média Móvel de 200 dias. Funciona como suporte em tendências de alta.
        * **Var 7D:** Variação acumulada nos últimos 7 dias.
        * **Volume:** Quantidade de negociações no dia.
        """)

if st.button("🔄 Atualizar Análise", type="primary"):
    with st.spinner("Conectando à API e baixando dados..."):
        lista_bdrs, mapa_nomes = obter_dados_brapi()
        df = buscar_dados(lista_bdrs)
        
    if not df.empty:
        df_calc = calcular_indicadores(df)
        oportunidades = analisar_oportunidades(df_calc, mapa_nomes)
        
        if oportunidades:
            df_res = pd.DataFrame(oportunidades)
            
            # Ordenação Inteligente: Primeiro SETUP, depois I.S.
            df_res = df_res.sort_values(by=['Trend', 'IS'], ascending=[False, False])
            
            qtd_ouro = df_res[df_res['Trend'] == True].shape[0]
            st.success(f"{len(oportunidades)} oportunidades encontradas! ({qtd_ouro} na Estratégia Ouro ⭐)")
            
            # --- TABELA INTERATIVA ---
            st.dataframe(
                df_res.style.map(estilizar_potencial, subset=['Potencial'])
                            .map(estilizar_is, subset=['IS'])
                            .map(estilizar_setup, subset=['Setup'])
                .format({
                    'Preco': 'R$ {:.2f}',
                    'Volume': '{:,.0f}', # Volume Inteiro com separador
                    'Queda_Dia': '{:.2f}%',
                    'Var_7d': '{:.2f}%',
                    'Gap': '{:.2f}%',
                    'IS': '{:.0f}',
                    'RSI14': '{:.0f}',
                    'Stoch': '{:.0f}'
                }),
                column_order=("Ticker", "Empresa", "Setup", "Preco", "Queda_Dia", "Var_7d", "IS", "Volume", "Sinais"),
                column_config={
                    "Setup": st.column_config.Column("Estratégia", width="medium"),
                    "Var_7d": st.column_config.NumberColumn("7 Dias"),
                    "Volume": st.column_config.NumberColumn("Vol.", format="%d"), # Força inteiro
                    "IS": st.column_config.NumberColumn("I.S.", help="Índice de Sobrevenda"),
                    "Sinais": st.column_config.TextColumn("Sinais Técnicos", width="large")
                },
                use_container_width=True,
                hide_index=True
            )
            
            # --- BOTÃO WHATSAPP ---
            if st.button("📱 Enviar Relatório WhatsApp"):
                top = df_res.head(10)
                msg = f"🦅 *BDR ALERT {VERSAO}*\n📅 {obter_hora_brasil()}\n\n"
                for _, r in top.iterrows():
                    icon = "⭐" if r['Trend'] else "🔻"
                    msg += f"{icon} *{r['Ticker']}* ({r['Queda_Dia']:.2f}%)\n"
                    msg += f"   💰 R${r['Preco']:.2f} | 7D: {r['Var_7d']:.1f}%\n"
                    msg += f"   📊 IS: {r['IS']:.0f} | {r['Sinais']}\n"
                    msg += "   ────────────────\n"
                
                if enviar_whatsapp(msg): st.success("Relatório enviado!")
                else: st.error("Erro no envio.")

            # --- TOP 5 GRÁFICOS ---
            st.divider()
            st.subheader("🔍 Análise Gráfica - Melhores Oportunidades")
            
            top5 = df_res.head(5)
            
            for _, row in top5.iterrows():
                ticker = row['Ticker']
                try:
                    df_ticker = df_calc.xs(ticker, axis=1, level=1).dropna()
                    
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        # Passamos o setup para o título do gráfico
                        fig = plotar_grafico(df_ticker, ticker, row['Empresa'], row['Setup'])
                        st.pyplot(fig)
                        
                    with col2:
                        setup_val = row['Setup']
                        cor_bola = "🟢" if "COMPRA" in setup_val else "🟡"
                        
                        st.markdown(f"### {cor_bola} {setup_val}")
                        st.metric("Queda Hoje", f"{row['Queda_Dia']:.2f}%", delta_color="inverse")
                        st.metric("I.S. (Sobrevenda)", f"{row['IS']:.0f}/100")
                        st.write(f"**Score:** {row['Score']}/10")
                        st.info(f"📋 **Sinais:** {row['Sinais']}")
                        
                    st.divider()
                except Exception: continue
        else:
            st.warning("Nenhuma BDR em queda encontrada hoje.")
    else:
        st.error("Erro ao carregar dados.")
