import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
import seaborn as sns
import requests
from datetime import datetime
import pytz
import warnings

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Monitor BDRs - Swing Trade",
    page_icon="📉",
    layout="wide"
)

warnings.filterwarnings('ignore')
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

PERIODO = "6mo"
TERMINACOES_BDR = ('31', '32', '33', '34', '35', '39')

# --- FUNÇÕES ---

@st.cache_data(ttl=3600)
def obter_dados_brapi():
    try:
        url = "https://brapi.dev/api/quote/list"
        r = requests.get(url, timeout=30)
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
        df = yf.download(sa_tickers, period=PERIODO, auto_adjust=True, progress=False, timeout=60)
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
        progresso.progress((i + 1) / total)
        try:
            close = df_calc[('Close', ticker)]
            volume = df_calc[('Volume', ticker)]
            
            # RSI
            delta = close.diff()
            ganho = delta.clip(lower=0).rolling(14).mean()
            perda = -delta.clip(upper=0).rolling(14).mean()
            rs = ganho / perda
            df_calc[('RSI14', ticker)] = 100 - (100 / (1 + rs))

            # Médias e Bollinger
            df_calc[('EMA20', ticker)] = close.ewm(span=20).mean()
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
    
    # Classificação
    def classificar(s):
        if s >= 4: return "Muito Alta"
        if s >= 2: return "Alta"
        if s >= 1: return "Média"
        return "Baixa"

    try:
        close = row_ticker.get('Close')
        rsi = row_ticker.get('RSI14')
        macd_hist = row_ticker.get('MACD_Hist')
        bb_lower = row_ticker.get('BB_Lower')
        
        # Pontuação
        if pd.notna(rsi) and rsi < 30:
            sinais.append("RSI Oversold")
            score += 3
        elif pd.notna(rsi) and rsi < 40:
            score += 1
            
        if pd.notna(macd_hist) and macd_hist > 0:
            sinais.append("MACD Positivo")
            score += 1
            
        if pd.notna(close) and pd.notna(bb_lower):
            if close < bb_lower * 1.02:
                sinais.append("Suporte BB")
                score += 2

        fibo = calcular_fibonacci(df_ticker)
        if fibo and (fibo['61.8%'] * 0.99 <= close <= fibo['61.8%'] * 1.01):
            sinais.append("Fibo Golden Zone")
            score += 2

        return sinais, score, classificar(score)
    except:
        return [], 0, "Indefinida"

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
            
            if pd.isna(preco) or pd.isna(preco_ant): continue

            # Variações
            queda_dia = ((preco - preco_ant) / preco_ant) * 100
            gap = ((preco_open - preco_ant) / preco_ant) * 100
            
            var_7d = np.nan
            if len(df_ticker) > 6:
                preco_7d = df_ticker['Close'].iloc[-6]
                var_7d = ((preco - preco_7d) / preco_7d) * 100

            if queda_dia >= 0: continue 

            sinais, score, classificacao = gerar_sinal(last, df_ticker)
            
            nome_completo = mapa_nomes.get(ticker, ticker)
            nome_curto = nome_completo.split()[0] if nome_completo else ticker
            nome_curto = nome_curto.replace(',', '').replace('.', '')

            resultados.append({
                'Ticker': ticker,
                'Empresa': nome_curto,
                'Preco': preco,
                'Queda_Dia': queda_dia,
                'Gap': gap,
                'Var_7D': var_7d,
                'RSI14': last.get('RSI14', np.nan),
                'Potencial': classificacao,
                'Score': score,
                'Sinais': ", ".join(sinais) if sinais else "-"
            })
        except: continue
    return resultados

def plotar_grafico(df_ticker, ticker, empresa, rsi):
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, gridspec_kw={'height_ratios': [3, 1]})
    
    close = df_ticker['Close']
    
    ax1 = axes[0]
    ax1.plot(close.index, close.values, label='Close', color='#333333')
    ax1.plot(close.index, df_ticker['EMA20'], label='EMA20', alpha=0.7, color='blue', linewidth=1)
    ax1.fill_between(close.index, df_ticker['BB_Lower'], df_ticker['BB_Upper'], alpha=0.15, color='gray')
    ax1.set_title(f'{ticker} - {empresa}', fontweight='bold')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    ax2.plot(close.index, df_ticker['RSI14'], color='orange')
    ax2.axhline(30, color='red', linestyle='--', linewidth=1)
    ax2.axhline(70, color='green', linestyle='--', linewidth=1)
    ax2.fill_between(close.index, 0, 30, alpha=0.2, color='red')
    ax2.set_ylabel('RSI')
    ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    return fig

# Função para colorir a tabela
def estilizar_potencial(val):
    color = ''
    if val == 'Muito Alta':
        color = 'background-color: #2e7d32; color: white; font-weight: bold' # Verde escuro
    elif val == 'Alta':
        color = 'background-color: #66bb6a; color: black; font-weight: bold' # Verde claro
    elif val == 'Média':
        color = 'background-color: #ffa726; color: black' # Laranja
    elif val == 'Baixa':
        color = 'background-color: #e0e0e0; color: black' # Cinza
    return color

# --- LAYOUT DO APP ---

st.title("📉 Monitor BDR - Swing Trade")
st.markdown("Rastreamento de BDRs em queda com análise de potencial de compra.")

if st.button("🔄 Atualizar Análise", type="primary"):
    with st.spinner("Conectando à API e baixando dados..."):
        lista_bdrs, mapa_nomes = obter_dados_brapi()
        df = buscar_dados(lista_bdrs)
        
    if not df.empty:
        df_calc = calcular_indicadores(df)
        oportunidades = analisar_oportunidades(df_calc, mapa_nomes)
        
        if oportunidades:
            df_res = pd.DataFrame(oportunidades)
            
            # ORDENAÇÃO: Queda do Dia (Ascendente = maior queda negativa primeiro)
            df_res = df_res.sort_values(by='Queda_Dia', ascending=True)
            
            st.success(f"{len(oportunidades)} oportunidades encontradas! (Ordenado por Maior Queda)")
            
            # --- TABELA INTERATIVA COLORIDA ---
            # Aplicamos o estilo (cores) antes de enviar para o Streamlit
            st.dataframe(
                df_res.style.map(estilizar_potencial, subset=['Potencial'])
                .format({
                    'Preco': 'R$ {:.2f}',
                    'Queda_Dia': '{:.2f}%',
                    'Gap': '{:.2f}%',
                    'Var_7D': '{:.2f}%',
                    'RSI14': '{:.1f}'
                }),
                column_config={
                    "Score": st.column_config.ProgressColumn(
                        "Força", format="%d", min_value=0, max_value=10
                    ),
                    "Potencial": st.column_config.Column("Sinal")
                },
                use_container_width=True,
                hide_index=True
            )
            
            # --- TOP 5 (MAIORES QUEDAS) ---
            st.divider()
            st.subheader("🔍 Top 5 Maiores Quedas")
            
            top5 = df_res.head(5)
            
            for _, row in top5.iterrows():
                ticker = row['Ticker']
                try:
                    df_ticker = df_calc.xs(ticker, axis=1, level=1).dropna()
                    
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        fig = plotar_grafico(df_ticker, ticker, row['Empresa'], row['RSI14'])
                        st.pyplot(fig)
                        
                    with col2:
                        # Exibindo o potencial com cor visualmente
                        potencial = row['Potencial']
                        cor_bola = "🟢" if "Alta" in potencial else "🟡" if "Média" in potencial else "⚪"
                        
                        st.markdown(f"### {cor_bola} {potencial}")
                        st.metric("Queda Hoje", f"{row['Queda_Dia']:.2f}%", delta_color="inverse")
                        st.metric("Gap", f"{row['Gap']:.2f}%")
                        st.write(f"**Score:** {row['Score']}/10")
                        st.caption(f"Sinais: {row['Sinais']}")
                        
                    st.divider()
                except Exception: continue
        else:
            st.warning("Nenhuma BDR em queda encontrada hoje.")
    else:
        st.error("Erro ao carregar dados.")
