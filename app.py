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
warnings.filterwarnings('ignore')

st.set_page_config(page_title="Monitor BDR", layout="wide", page_icon="📈")

plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

PERIODO = "6mo"
TERMINACOES_BDR = ('31', '32', '33', '34', '35', '39')

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
        st.error(f"❌ Erro ao buscar BRAPI: {e}")
        return [], {}

@st.cache_data(ttl=3600)
def buscar_dados(tickers):
    if not tickers:
        return pd.DataFrame()
    
    sa_tickers = [f"{t}.SA" for t in tickers]
    
    try:
        with st.spinner("Baixando dados do Yahoo Finance..."):
            df = yf.download(
                sa_tickers, 
                period=PERIODO, 
                auto_adjust=True, 
                progress=False,
                timeout=60
            )
        
        if df.empty:
            return pd.DataFrame()
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = pd.MultiIndex.from_tuples(
                [(c[0], c[1].replace(".SA", "")) for c in df.columns]
            )
        
        return df.dropna(axis=1, how='all')
    except Exception as e:
        st.error(f"Erro ao baixar: {str(e)[:80]}")
        return pd.DataFrame()

def calcular_indicadores(df):
    df_calc = df.copy()
    tickers = df_calc.columns.get_level_values(1).unique()
    
    for ticker in tickers:
        try:
            close = df_calc[('Close', ticker)]
            volume = df_calc[('Volume', ticker)]
            high = df_calc[('High', ticker)]
            low = df_calc[('Low', ticker)]
            
            delta = close.diff()
            ganho = delta.clip(lower=0).rolling(14).mean()
            perda = -delta.clip(upper=0).rolling(14).mean()
            rs = ganho / perda
            rsi = 100 - (100 / (1 + rs))
            df_calc[('RSI14', ticker)] = rsi
            
            df_calc[('EMA20', ticker)] = close.ewm(span=20).mean()
            df_calc[('EMA50', ticker)] = close.ewm(span=50).mean()
            
            sma = close.rolling(20).mean()
            std = close.rolling(20).std()
            df_calc[('BB_Lower', ticker)] = sma - (std * 2)
            df_calc[('BB_Upper', ticker)] = sma + (std * 2)
            df_calc[('BB_Middle', ticker)] = sma
            
            ema_12 = close.ewm(span=12).mean()
            ema_26 = close.ewm(span=26).mean()
            macd = ema_12 - ema_26
            signal = macd.ewm(span=9).mean()
            df_calc[('MACD_Hist', ticker)] = macd - signal
            
            df_calc[('Vol_Med', ticker)] = volume.rolling(20).mean()
        except:
            continue
    
    return df_calc

def calcular_fibonacci(df_ticker):
    try:
        if len(df_ticker) < 50:
            return None
        
        high = df_ticker['High'].max()
        low = df_ticker['Low'].min()
        diff = high - low
        
        fibo_levels = {
            '0%': low,
            '23.6%': low + (diff * 0.236),
            '38.2%': low + (diff * 0.382),
            '50%': low + (diff * 0.5),
            '61.8%': low + (diff * 0.618),
            '78.6%': low + (diff * 0.786),
            '100%': high
        }
        return fibo_levels
    except:
        return None

def gerar_sinal(row_ticker, df_ticker):
    sinais = []
    score = 0
    try:
        close = row_ticker.get('Close')
        rsi = row_ticker.get('RSI14')
        macd_hist = row_ticker.get('MACD_Hist')
        bb_lower = row_ticker.get('BB_Lower')
        bb_upper = row_ticker.get('BB_Upper')
        bb_middle = row_ticker.get('BB_Middle')
        
        if pd.notna(rsi) and rsi < 30:
            sinais.append("🔴 RSI Oversold")
            score += 3
        elif pd.notna(rsi) and rsi < 40:
            sinais.append("⚠️ RSI Fraco")
            score += 1
        
        if pd.notna(rsi) and rsi > 70:
            sinais.append("⚠️ RSI Sobrecompra")
            score -= 1
        
        if pd.notna(macd_hist) and macd_hist > 0:
            sinais.append("✅ MACD Positivo")
            score += 1
        elif pd.notna(macd_hist) and macd_hist < 0:
            sinais.append("❌ MACD Negativo")
            score -= 1
        
        if pd.notna(close) and pd.notna(bb_lower):
            if close < bb_lower * 1.02:
                sinais.append("💪 Suporte BB (Forte)")
                score += 2
            elif close < bb_lower * 1.05:
                sinais.append("📍 Próximo Suporte BB")
                score += 1
        
        if pd.notna(close) and pd.notna(bb_upper):
            if close > bb_upper * 0.98:
                sinais.append("⛔ Resistência BB (Forte)")
                score -= 1
        
        if pd.notna(close) and pd.notna(bb_middle):
            distancia = abs(close - bb_middle) / bb_middle * 100
            if distancia < 5:
                sinais.append("↔️ Próximo Média")
                score += 1
        
        fibo = calcular_fibonacci(df_ticker)
        if fibo:
            fibo_618 = fibo['61.8%']
            fibo_382 = fibo['38.2%']
            
            if fibo_618 * 0.99 <= close <= fibo_618 * 1.01:
                sinais.append("🟡 Fibo Golden Zone (61.8%)")
                score += 2
            elif fibo_382 * 0.99 <= close <= fibo_382 * 1.01:
                sinais.append("🟡 Fibo Support (38.2%)")
                score += 1
        
        if len(df_ticker) > 5:
            variacao_5d = df_ticker['Close'].pct_change().tail(5).std()
            if variacao_5d > 0.03:
                sinais.append("⚡ Alta Volatilidade")
                score += 1
        
        if len(df_ticker) > 2:
            rsi_trend = df_ticker['RSI14'].tail(3)
            close_trend = df_ticker['Close'].tail(3)
            
            if (close_trend.iloc[-1] < close_trend.iloc[0]) and (rsi_trend.iloc[-1] > rsi_trend.iloc[0]):
                sinais.append("🔄 Divergência Bullish")
                score += 3
        
        return sinais, score
    except:
        return [], 0

def analisar_tendencia(df_ticker):
    try:
        close = df_ticker['Close']
        ema20 = df_ticker.get('EMA20')
        ema50 = df_ticker.get('EMA50')
        
        if ema20 is None or ema50 is None:
            return "Indefinida"
        
        ultimo = close.iloc[-1]
        if ultimo > ema20.iloc[-1] > ema50.iloc[-1]:
            return "Altista Forte"
        elif ultimo > ema50.iloc[-1]:
            return "Altista"
        elif ultimo < ema20.iloc[-1] < ema50.iloc[-1]:
            return "Baixista"
        else:
            return "Lateral"
    except:
        return "Indefinida"

def analisar_oportunidades(df_calc, mapa_nomes):
    resultados = []
    tickers = df_calc.columns.get_level_values(1).unique()
    
    for ticker in tickers:
        try:
            df_ticker = df_calc.xs(ticker, axis=1, level=1).dropna()
            if len(df_ticker) < 50:
                continue
            
            last = df_ticker.iloc[-1]
            anterior = df_ticker.iloc[-2]
            
            preco = last.get('Close')
            preco_ant = anterior.get('Close')
            preco_open = last.get('Open')
            volume = last.get('Volume')
            
            if pd.isna(preco) or pd.isna(preco_ant) or pd.isna(volume):
                continue
            
            queda_dia = ((preco - preco_ant) / preco_ant) * 100
            
            if queda_dia >= 0:
                continue
            
            gap_abertura = ((preco_open - preco_ant) / preco_ant) * 100
            queda_7d = ((preco - df_ticker['Close'].iloc[-5]) / df_ticker['Close'].iloc[-5]) * 100
            rsi = last.get('RSI14', np.nan)
            tendencia = analisar_tendencia(df_ticker)
            sinais, score = gerar_sinal(last, df_ticker)
            
            nome = mapa_nomes.get(ticker, ticker)
            primeiro_nome = nome.split()[0] if nome else ticker
            
            resultados.append({
                'Ticker': ticker,
                'Empresa': primeiro_nome,
                'Preco': preco,
                'Volume': volume,
                'Gap': gap_abertura,
                'Queda_Dia': queda_dia,
                'Var_7D': queda_7d,
                'RSI14': rsi,
                'Tendencia': tendencia,
                'Sinais': sinais,
                'Score': score
            })
        except:
            continue
    
    return resultados

def plotar_grafico(df_ticker, ticker, empresa, queda_dia, rsi):
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    
    close = df_ticker['Close']
    
    ax1 = axes[0]
    ax1.plot(close.index, close.values, label='Close', linewidth=2, color='black')
    ax1.plot(close.index, df_ticker['EMA20'], label='EMA20', alpha=0.7)
    ax1.plot(close.index, df_ticker['EMA50'], label='EMA50', alpha=0.7)
    ax1.fill_between(close.index, df_ticker['BB_Lower'], df_ticker['BB_Upper'], alpha=0.2, color='gray')
    ax1.set_ylabel('Preço (R$)', fontsize=11, fontweight='bold')
    ax1.set_title(f'{ticker} - {empresa} | Queda: {queda_dia:.2f}% | RSI: {rsi:.1f}', 
                 fontsize=13, fontweight='bold', color='darkred')
    ax1.legend(loc='best')
    ax1.grid(True, alpha=0.3)
    
    ax2 = axes[1]
    rsi_vals = df_ticker['RSI14']
    ax2.plot(close.index, rsi_vals, label='RSI14', color='orange', linewidth=2)
    ax2.axhline(y=30, color='red', linestyle='--', linewidth=2, alpha=0.7, label='Sobrevenda')
    ax2.axhline(y=70, color='green', linestyle='--', linewidth=2, alpha=0.7, label='Sobrecompra')
    ax2.fill_between(close.index, 0, 30, alpha=0.2, color='red')
    ax2.set_ylabel('RSI', fontsize=11, fontweight='bold')
    ax2.set_xlabel('Data', fontsize=11)
    ax2.set_ylim([0, 100])
    ax2.legend(loc='best')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    return fig

# ===== UI =====

st.title("📈 Monitor BDR - Swing Trade")

fuso = pytz.timezone('America/Sao_Paula')
hora_br = datetime.now(fuso).strftime('%d/%m/%Y %H:%M:%S')
st.caption(f"⏰ Brasil: {hora_br}")

st.markdown("---")

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    st.write("**Status do Monitor**")
with col2:
    rodar_analise = st.button("🚀 Rodar Análise", use_container_width=True, type="primary")
with col3:
    st.write("")

st.markdown("---")

if rodar_analise:
    lista_bdrs, mapa_nomes = obter_dados_brapi()
    
    if lista_bdrs:
        st.info(f"✓ {len(lista_bdrs)} BDRs encontradas")
        
        df = buscar_dados(lista_bdrs)
        
        if not df.empty:
            st.success("✓ Dados carregados com sucesso!")
            
            df_calc = calcular_indicadores(df)
            oportunidades = analisar_oportunidades(df_calc, mapa_nomes)
            
            if oportunidades:
                oportunidades.sort(key=lambda x: x['Queda_Dia'])
                
                st.success(f"✓ {len(oportunidades)} BDRs em queda encontradas!")
                
                # Tabela Principal
                st.subheader("📊 Tabela de Oportunidades")
                
                df_show = pd.DataFrame(oportunidades)
                df_display = df_show.copy()
                df_display['Preco'] = df_display['Preco'].apply(lambda x: f"R$ {x:.2f}")
                df_display['Volume'] = df_display['Volume'].apply(lambda x: f"{x:,.0f}")
                df_display['Gap'] = df_display['Gap'].apply(lambda x: f"{x:.2f}%")
                df_display['Queda_Dia'] = df_display['Queda_Dia'].apply(lambda x: f"{x:.2f}%")
                df_display['Var_7D'] = df_display['Var_7D'].apply(lambda x: f"{x:.2f}%")
                df_display['RSI14'] = df_display['RSI14'].apply(lambda x: f"{x:.1f}")
                
                cols_print = ['Ticker', 'Empresa', 'Preco', 'Volume', 'Gap', 'Queda_Dia', 'Var_7D', 'RSI14', 'Tendencia']
                st.dataframe(df_display[cols_print], use_container_width=True, hide_index=True)
                
                # Sinais
                st.subheader("🎯 Sinais por BDR")
                for oport in oportunidades:
                    sinais_str = " | ".join(oport['Sinais']) if oport['Sinais'] else "Sem sinais"
                    score_color = "🟢" if oport['Score'] >= 5 else "🟡" if oport['Score'] >= 2 else "🔴"
                    st.write(f"{score_color} **{oport['Ticker']}**: {sinais_str} *(Score: {oport['Score']})*")
                
                # Gráficos Top 5
                st.subheader("📈 Gráficos - Top 5 Maiores Quedas")
                
                for i, oport in enumerate(oportunidades[:5], 1):
                    ticker = oport['Ticker']
                    try:
                        df_ticker = df_calc.xs(ticker, axis=1, level=1).dropna()
                        fig = plotar_grafico(df_ticker, ticker, oport['Empresa'], oport['Queda_Dia'], oport['RSI14'])
                        st.pyplot(fig)
                    except Exception as e:
                        st.error(f"Erro ao gerar gráfico de {ticker}: {e}")
                
                # Resumo Detalhado
                st.subheader("📋 Resumo Detalhado - Top 10")
                
                for oport in oportunidades[:10]:
                    with st.expander(f"🎯 {oport['Ticker']} - {oport['Empresa']} | Queda: {oport['Queda_Dia']:.2f}%"):
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Preço", f"R$ {oport['Preco']:.2f}")
                            st.metric("Volume", f"{oport['Volume']:,.0f}")
                        with col2:
                            st.metric("Gap Abertura", f"{oport['Gap']:.2f}%")
                            st.metric("Queda Dia", f"{oport['Queda_Dia']:.2f}%")
                        with col3:
                            st.metric("RSI14", f"{oport['RSI14']:.1f}")
                            st.metric("Score", f"{oport['Score']}/10")
                        
                        st.write(f"**Tendência:** {oport['Tendencia']}")
                        st.write(f"**Variação 7 dias:** {oport['Var_7D']:.2f}%")
                        sinais_str = " | ".join(oport['Sinais']) if oport['Sinais'] else "Sem sinais"
                        st.write(f"**Sinais:** {sinais_str}")
            else:
                st.warning("⚠️ Nenhuma BDR em queda no dia.")
        else:
            st.error("❌ Erro ao baixar dados")
    else:
        st.error("❌ Nenhuma BDR encontrada")
