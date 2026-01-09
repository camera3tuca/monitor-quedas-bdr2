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

# Configuração da Página
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

@st.cache_data(ttl=3600) # Cache por 1 hora
def obter_dados_brapi():
    try:
        url = "https://brapi.dev/api/quote/list"
        r = requests.get(url, timeout=30)
        dados = r.json().get('stocks', [])
        # Filtra apenas os tickers que terminam com as terminações de BDR
        bdrs_raw = [d for d in dados if d['stock'].endswith(TERMINACOES_BDR)]
        lista_tickers = [d['stock'] for d in bdrs_raw]
        mapa_nomes = {d['stock']: d.get('name', d['stock']) for d in bdrs_raw}
        return lista_tickers, mapa_nomes
    except Exception as e:
        st.error(f"Erro ao buscar BRAPI: {e}")
        return [], {}

@st.cache_data(ttl=1800) # Cache por 30 min
def buscar_dados(tickers):
    if not tickers:
        return pd.DataFrame()

    sa_tickers = [f"{t}.SA" for t in tickers]

    try:
        # Streamlit não mostra o progresso do yfinance, então desativamos
        df = yf.download(
            sa_tickers,
            period=PERIODO,
            auto_adjust=True,
            progress=False,
            timeout=60
        )

        if df.empty:
            return pd.DataFrame()

        # Ajuste de MultiIndex se necessário
        if isinstance(df.columns, pd.MultiIndex):
            # Se houver MultiIndex (ex: Price, Ticker), simplifica
            df.columns = pd.MultiIndex.from_tuples(
                [(c[0], c[1].replace(".SA", "")) for c in df.columns]
            )

        return df.dropna(axis=1, how='all')
    except Exception as e:
        st.error(f"Erro ao baixar dados: {str(e)[:100]}")
        return pd.DataFrame()

def calcular_indicadores(df):
    df_calc = df.copy()
    tickers = df_calc.columns.get_level_values(1).unique()
    
    # Barra de progresso visual
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
            rsi = 100 - (100 / (1 + rs))
            df_calc[('RSI14', ticker)] = rsi

            # Médias e Bollinger
            df_calc[('EMA20', ticker)] = close.ewm(span=20).mean()
            df_calc[('EMA50', ticker)] = close.ewm(span=50).mean()
            
            sma = close.rolling(20).mean()
            std = close.rolling(20).std()
            df_calc[('BB_Lower', ticker)] = sma - (std * 2)
            df_calc[('BB_Upper', ticker)] = sma + (std * 2)
            df_calc[('BB_Middle', ticker)] = sma

            # MACD
            ema_12 = close.ewm(span=12).mean()
            ema_26 = close.ewm(span=26).mean()
            macd = ema_12 - ema_26
            signal = macd.ewm(span=9).mean()
            df_calc[('MACD_Hist', ticker)] = macd - signal

            df_calc[('Vol_Med', ticker)] = volume.rolling(20).mean()
        except:
            continue
            
    progresso.empty() # Remove a barra ao terminar
    return df_calc

def calcular_fibonacci(df_ticker):
    try:
        if len(df_ticker) < 50: return None
        high = df_ticker['High'].max()
        low = df_ticker['Low'].min()
        diff = high - low
        return {
            '0%': low, '23.6%': low + (diff * 0.236), '38.2%': low + (diff * 0.382),
            '50%': low + (diff * 0.5), '61.8%': low + (diff * 0.618),
            '78.6%': low + (diff * 0.786), '100%': high
        }
    except: return None

def gerar_sinal(row_ticker, df_ticker):
    sinais = []
    score = 0
    try:
        close = row_ticker.get('Close')
        rsi = row_ticker.get('RSI14')
        macd_hist = row_ticker.get('MACD_Hist')
        bb_lower = row_ticker.get('BB_Lower')
        bb_upper = row_ticker.get('BB_Upper')
        
        # Lógica simplificada para brevidade
        if pd.notna(rsi) and rsi < 30:
            sinais.append("🔴 RSI Oversold")
            score += 3
        elif pd.notna(rsi) and rsi < 40:
            sinais.append("⚠️ RSI Fraco")
            score += 1
            
        if pd.notna(macd_hist) and macd_hist > 0:
            sinais.append("✅ MACD Positivo")
            score += 1
            
        if pd.notna(close) and pd.notna(bb_lower):
            if close < bb_lower * 1.02:
                sinais.append("💪 Suporte BB")
                score += 2

        fibo = calcular_fibonacci(df_ticker)
        if fibo:
            if fibo['61.8%'] * 0.99 <= close <= fibo['61.8%'] * 1.01:
                sinais.append("🟡 Fibo Golden Zone")
                score += 2

        if len(df_ticker) > 2:
            rsi_trend = df_ticker['RSI14'].tail(3)
            close_trend = df_ticker['Close'].tail(3)
            if (close_trend.iloc[-1] < close_trend.iloc[0]) and (rsi_trend.iloc[-1] > rsi_trend.iloc[0]):
                sinais.append("🔄 Divergência Bullish")
                score += 3

        return sinais, score
    except:
        return [], 0

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
            
            if pd.isna(preco) or pd.isna(preco_ant): continue

            queda_dia = ((preco - preco_ant) / preco_ant) * 100
            
            # Filtro: Apenas quedas
            if queda_dia >= 0: continue

            sinais, score = gerar_sinal(last, df_ticker)
            nome = mapa_nomes.get(ticker, ticker)

            resultados.append({
                'Ticker': ticker,
                'Empresa': nome,
                'Preco': preco,
                'Queda_Dia': queda_dia,
                'RSI14': last.get('RSI14', np.nan),
                'Sinais': ", ".join(sinais),
                'Score': score
            })
        except: continue
    return resultados

def plotar_grafico(df_ticker, ticker, empresa, rsi):
    # Retorna a figura (fig) em vez de mostrar (plt.show)
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, gridspec_kw={'height_ratios': [3, 1]})
    
    close = df_ticker['Close']
    
    # Preço
    ax1 = axes[0]
    ax1.plot(close.index, close.values, label='Close', color='black')
    ax1.plot(close.index, df_ticker['EMA20'], label='EMA20', alpha=0.7, color='blue')
    ax1.fill_between(close.index, df_ticker['BB_Lower'], df_ticker['BB_Upper'], alpha=0.2, color='gray')
    ax1.set_title(f'{ticker} - {empresa}', fontweight='bold')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)

    # RSI
    ax2 = axes[1]
    ax2.plot(close.index, df_ticker['RSI14'], color='orange')
    ax2.axhline(30, color='red', linestyle='--')
    ax2.axhline(70, color='green', linestyle='--')
    ax2.set_ylabel('RSI')
    ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    return fig

# --- LAYOUT DO APP ---

st.title("📉 Monitor BDR - Swing Trade")
st.markdown("Rastreamento de BDRs em queda com análise técnica automática.")

fuso = pytz.timezone('America/Sao_Paulo')
st.caption(f"Última atualização: {datetime.now(fuso).strftime('%d/%m/%Y %H:%M:%S')}")

if st.button("🔄 Atualizar Análise"):
    with st.spinner("Buscando lista de BDRs..."):
        lista_bdrs, mapa_nomes = obter_dados_brapi()
    
    if lista_bdrs:
        st.info(f"Analisando {len(lista_bdrs)} ativos...")
        
        with st.spinner("Baixando cotações do Yahoo Finance..."):
            df = buscar_dados(lista_bdrs)
            
        if not df.empty:
            st.write("Calculando indicadores...")
            df_calc = calcular_indicadores(df)
            
            oportunidades = analisar_oportunidades(df_calc, mapa_nomes)
            
            if oportunidades:
                df_res = pd.DataFrame(oportunidades)
                df_res = df_res.sort_values('Queda_Dia')
                
                # Exibir tabela interativa
                st.subheader("📋 Tabela de Oportunidades")
                st.dataframe(
                    df_res.style.format({
                        'Preco': 'R$ {:.2f}',
                        'Queda_Dia': '{:.2f}%',
                        'RSI14': '{:.1f}',
                        'Score': '{:.0f}'
                    }),
                    use_container_width=True
                )
                
                # Top 5 Gráficos
                st.divider()
                st.subheader("📊 Top 5 Maiores Quedas")
                
                top5 = df_res.head(5)
                cols = st.columns(1) # Uma coluna para gráficos grandes
                
                for _, row in top5.iterrows():
                    ticker = row['Ticker']
                    try:
                        df_ticker = df_calc.xs(ticker, axis=1, level=1).dropna()
                        fig = plotar_grafico(df_ticker, ticker, row['Empresa'], row['RSI14'])
                        st.pyplot(fig)
                        st.markdown(f"**Sinais:** {row['Sinais']} | **Score:** {row['Score']}")
                        st.divider()
                    except Exception as e:
                        st.error(f"Erro ao plotar {ticker}")
            else:
                st.warning("Nenhuma BDR em queda encontrada hoje.")
        else:
            st.error("Falha ao baixar dados do Yahoo Finance.")
    else:
        st.error("Falha ao obter lista da BRAPI.")
else:
    st.info("Clique no botão acima para iniciar a varredura.")
