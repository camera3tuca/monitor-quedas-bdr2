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
import time

# --- CONFIGURAÇÃO DA PÁGINA ---
VERSAO_APP = "v2.7 (Lotes Inteligentes)"

st.set_page_config(
    page_title=f"Monitor BDR {VERSAO_APP}",
    page_icon="🦅",
    layout="wide"
)

warnings.filterwarnings('ignore')
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

PERIODO = "1y" 
TERMINACOES_BDR = ('31', '32', '33', '34', '35', '39')

# --- GERENCIAMENTO DE SEGREDOS ---
try:
    WHATSAPP_PHONE = st.secrets["WHATSAPP_PHONE"]
    WHATSAPP_APIKEY = st.secrets["WHATSAPP_APIKEY"]
    BRAPI_API_TOKEN = st.secrets["BRAPI_API_TOKEN"]
except Exception:
    st.error("❌ ERRO CRÍTICO: Chaves de API não encontradas!")
    st.stop()

# --- SESSÃO ---
if 'dados_carregados' not in st.session_state:
    st.session_state.dados_carregados = False
if 'df_resultado' not in st.session_state:
    st.session_state.df_resultado = pd.DataFrame()
if 'df_calculado' not in st.session_state:
    st.session_state.df_calculado = pd.DataFrame()

# --- FUNÇÕES AUXILIARES ---
def obter_hora_brasil():
    fuso = pytz.timezone('America/Sao_Paulo')
    return datetime.now(fuso).strftime('%d/%m/%Y %H:%M:%S')

def enviar_whatsapp_textmebot(mensagem):
    try:
        texto_codificado = urllib.parse.quote(mensagem)
        phone = WHATSAPP_PHONE.strip()
        if not phone.startswith("+"): phone = "+" + phone
        url = f"https://api.textmebot.com/send.php?recipient={phone}&apikey={WHATSAPP_APIKEY}&text={texto_codificado}"
        r = requests.get(url, timeout=30)
        if r.status_code == 200: return True, "Enviado!"
        else: return False, f"Erro {r.status_code}"
    except Exception as e: return False, str(e)

# --- COLETA DE DADOS (ESTRATÉGIA DE LOTES) ---

@st.cache_data(ttl=3600)
def obter_dados_brapi():
    try:
        url = f"https://brapi.dev/api/quote/list?token={BRAPI_API_TOKEN}"
        r = requests.get(url, timeout=30)
        dados = r.json().get('stocks', [])
        bdrs_raw = [d for d in dados if d['stock'].endswith(TERMINACOES_BDR)]
        lista_tickers = [d['stock'] for d in bdrs_raw]
        mapa_nomes = {d['stock']: d.get('name', d['stock']) for d in bdrs_raw}
        return lista_tickers, mapa_nomes
    except Exception: return [], {}

def buscar_dados_em_lotes(tickers):
    if not tickers: return pd.DataFrame()
    
    sa_tickers = [f"{t}.SA" for t in tickers]
    
    # Configuração dos Lotes
    TAMANHO_LOTE = 50 
    total_lotes = len(sa_tickers) // TAMANHO_LOTE + 1
    lista_dfs = []
    
    barra_progresso = st.progress(0)
    status = st.empty()
    
    for i in range(0, len(sa_tickers), TAMANHO_LOTE):
        lote = sa_tickers[i : i + TAMANHO_LOTE]
        if not lote: continue
        
        perc = (i / len(sa_tickers))
        barra_progresso.progress(perc)
        status.text(f"Baixando lote {i//TAMANHO_LOTE + 1}/{total_lotes}...")
        
        try:
            # Baixa o lote pequeno (Rápido e Seguro)
            df_lote = yf.download(lote, period=PERIODO, auto_adjust=True, progress=False, threads=True)
            
            if not df_lote.empty:
                # Tratamento MultiIndex imediato
                if isinstance(df_lote.columns, pd.MultiIndex):
                    df_lote.columns = pd.MultiIndex.from_tuples([(c[0], c[1].replace(".SA", "")) for c in df_lote.columns])
                lista_dfs.append(df_lote)
                
        except Exception as e:
            print(f"Erro no lote {i}: {e}")
            continue
            
    barra_progresso.empty()
    status.empty()
    
    if not lista_dfs:
        return pd.DataFrame()
        
    # Junta todos os pedaços num DataFrame gigante
    try:
        df_final = pd.concat(lista_dfs, axis=1)
        # Remove colunas duplicadas se houver
        df_final = df_final.loc[:, ~df_final.columns.duplicated()]
        return df_final.dropna(axis=1, how='all')
    except:
        return pd.DataFrame()

# --- CÁLCULOS (MANTIDOS IGUAIS) ---

def calcular_indicadores(df):
    df_calc = df.copy()
    tickers = df_calc.columns.get_level_values(1).unique()
    
    status_text = st.empty()
    
    # Cálculo vetorizado onde possível para acelerar
    # (Mantemos o loop para segurança dos indicadores complexos)
    for i, ticker in enumerate(tickers):
        if i % 50 == 0: status_text.text(f"Processando indicadores: {i}/{len(tickers)}")
        try:
            close = df_calc[('Close', ticker)]
            high = df_calc[('High', ticker)]
            low = df_calc[('Low', ticker)]
            
            delta = close.diff()
            ganho = delta.clip(lower=0).rolling(14).mean()
            perda = -delta.clip(upper=0).rolling(14).mean()
            rs = ganho / perda
            df_calc[('RSI14', ticker)] = 100 - (100 / (1 + rs))

            lowest_low = low.rolling(14).min()
            highest_high = high.rolling(14).max()
            df_calc[('Stoch_K', ticker)] = 100 * ((close - lowest_low) / (highest_high - lowest_low))

            df_calc[('SMA200', ticker)] = close.rolling(window=200).mean()
            
            sma20 = close.rolling(20).mean()
            std = close.rolling(20).std()
            df_calc[('BB_Lower', ticker)] = sma20 - (std * 2)
            df_calc[('BB_Upper', ticker)] = sma20 + (std * 2)
            df_calc[('EMA20', ticker)] = close.ewm(span=20).mean()
        except: continue
        
    status_text.empty()
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
        if s >= 4: return "💎 Ouro"
        if s >= 2: return "🥈 Prata"
        if s >= 1: return "🥉 Bronze"
        return "⚪ Neutro"

    try:
        close = row_ticker.get('Close')
        sma200 = row_ticker.get('SMA200')
        rsi = row_ticker.get('RSI14')
        stoch = row_ticker.get('Stoch_K')
        bb_lower = row_ticker.get('BB_Lower')
        
        tendencia_alta = False
        if pd.notna(sma200) and pd.notna(close):
            if close > sma200:
                tendencia_alta = True
                sinais.append("Trend Alta")
                score += 3
            else:
                sinais.append("Trend Baixa")

        if pd.notna(rsi):
            if rsi < 30:
                sinais.append("RSI Baixo")
                score += 3
            elif rsi < 40:
                score += 1
        
        if pd.notna(stoch) and stoch < 20:
            sinais.append("Stoch Fundo")
            score += 2
            
        if pd.notna(close) and pd.notna(bb_lower):
            if close < bb_lower * 1.02:
                sinais.append("BB Suporte")
                score += 1

        fibo = calcular_fibonacci(df_ticker)
        if fibo and (fibo['61.8%'] * 0.99 <= close <= fibo['61.8%'] * 1.01):
            sinais.append("Fibo 61.8")
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
            if len(df_ticker) < 200: continue

            last = df_ticker.iloc[-1]
            anterior = df_ticker.iloc[-2]
            
            preco = last.get('Close')
            preco_ant = anterior.get('Close')
            preco_open = last.get('Open')
            volume = last.get('Volume')
            sma200 = last.get('SMA200')
            
            if pd.isna(preco) or pd.isna(preco_ant): continue

            # Filtro de Queda
            queda_dia = ((preco - preco_ant) / preco_ant) * 100
            if queda_dia >= 0: continue 
            
            gap = ((preco_open - preco_ant) / preco_ant) * 100

            sinais, score, classificacao, tendencia_alta = gerar_sinal(last, df_ticker)

            rsi = last.get('RSI14', 50)
            stoch = last.get('Stoch_K', 50)
            is_index = ((100 - rsi) + (100 - stoch)) / 2
            dist_sma200 = ((preco - sma200) / sma200) * 100 if pd.notna(sma200) else 0

            nome_completo = mapa_nomes.get(ticker, ticker)
            nome_curto = nome_completo.split()[0].replace(',', '').title()

            status_visual = "⭐ STRATEGY" if tendencia_alta else "⚠️ Contra-Tend."

            resultados.append({
                'Ticker': ticker,
                'Empresa': nome_curto,
                'Preco': preco,
                'Volume': volume,
                'Queda_Dia': queda_dia,
                'Gap': gap,
                'IS': is_index,
                'Dist_SMA200': dist_sma200,
                'RSI14': rsi,
                'Setup': status_visual,
                'Tendencia_Alta': tendencia_alta,
                'Potencial': classificacao,
                'Score': score,
                'Sinais': ", ".join(sinais)
            })
        except: continue
    return resultados

def plotar_grafico(df_ticker, ticker, empresa, is_val, tendencia_alta):
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True, gridspec_kw={'height_ratios': [3, 1, 1]})
    
    close = df_ticker['Close']
    sma200 = df_ticker['SMA200']
    
    ax1 = axes[0]
    ax1.plot(close.index, close.values, label='Preço', color='#333333', linewidth=1.5)
    cor_sma = '#FFD700' if tendencia_alta else '#FF5252'
    ax1.plot(close.index, sma200, label='SMA 200', color=cor_sma, linewidth=2.5)
    ax1.plot(close.index, df_ticker['EMA20'], label='EMA 20', color='blue', alpha=0.5)
    ax1.fill_between(close.index, df_ticker['BB_Lower'], df_ticker['BB_Upper'], alpha=0.1, color='gray')
    ax1.set_title(f'{ticker} - {empresa}', fontweight='bold')
    ax1.legend(loc='best')
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    ax2.plot(close.index, df_ticker['RSI14'], color='orange')
    ax2.axhline(30, color='red', linestyle='--')
    ax2.axhline(70, color='green', linestyle='--')
    ax2.set_ylabel('RSI')
    ax2.set_ylim(0, 100)
    
    ax3 = axes[2]
    if 'Stoch_K' in df_ticker.columns:
        ax3.plot(close.index, df_ticker['Stoch_K'], color='purple')
        ax3.axhline(20, color='red', linestyle='--')
        ax3.axhline(80, color='green', linestyle='--')
    ax3.set_ylabel('Stoch')
    ax3.set_ylim(0, 100)
    
    plt.tight_layout()
    return fig

def estilizar_is(val):
    if val >= 75: return 'background-color: #d32f2f; color: white; font-weight: bold'
    elif val >= 60: return 'background-color: #ffa726; color: black'
    return 'color: #888888'

def estilizar_setup(val):
    if "STRATEGY" in val:
        return 'background-color: #1b5e20; color: white; font-weight: bold; border-radius: 5px'
    return 'color: #757575'

def formatar_msg_whatsapp(df_res, hora):
    top = df_res.head(10)
    msg = f"🦅 *RELATÓRIO DE QUEDAS*\n"
    msg += f"🗓️ {hora}\n"
    qtd_strategy = df_res[df_res['Tendencia_Alta'] == True].shape[0]
    msg += f"🚨 *{len(df_res)}* Total | ⭐ *{qtd_strategy}* Estratégia\n"
    msg += "━━━━━━━━━━━━━━━━\n"
    for _, row in top.iterrows():
        icon = "⭐" if row['Tendencia_Alta'] else "🔻"
        msg += f"{icon} *{row['Ticker']}* ({row['Queda_Dia']:.1f}%)\n"
        msg += f"   💰 R${row['Preco']:.2f} | 📊 I.S.: {row['IS']:.0f}\n"
        sinais = row['Sinais'] if row['Sinais'] else "Queda"
        msg += f"   🛠 {sinais}\n" 
        msg += "   ────────────────\n"
    msg += "\n🔗 _Acesse o App para gráficos_"
    return msg

def exibir_legendas():
    with st.expander("ℹ️ ENTENDA OS SINAIS E INDICADORES (CLIQUE AQUI)"):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("""
            **📊 Indicadores:**
            * **I.S. (Índice de Sobrevenda):** Varia de 0 a 100. Vermelho (>80) = Muito barato.
            * **RSI (IFR):** Abaixo de 30 = Sobrevendido.
            * **Stoch (Estocástico):** Abaixo de 20 = Fundo.
            """)
        with c2:
            st.markdown("""
            **🛠 Sinais Técnicos:**
            * **Trend Alta:** Preço acima da Média de 200.
            * **BB Suporte:** Preço tocou na banda inferior.
            * **Fibo 61.8:** Retração de ouro.
            """)
            st.info("⭐ **Estratégia Ouro:** Trend Alta + Queda forte.")

# --- LAYOUT PRINCIPAL ---

st.title(f"🦅 Monitor BDR - Swing Trade")
exibir_legendas()

col_btn1, col_btn2 = st.columns([1, 4])
with col_btn1:
    btn_analisar = st.button("🔄 Rastrear Mercado", type="primary")

if btn_analisar:
    # --- PROCESSO DE BUSCA OTIMIZADO ---
    lista_bdrs, mapa_nomes = obter_dados_brapi()
    
    # Chama a nova função em lotes
    df = buscar_dados_em_lotes(lista_bdrs)
        
    if not df.empty:
        df_calc = calcular_indicadores(df)
        oportunidades = analisar_oportunidades(df_calc, mapa_nomes)
        
        if oportunidades:
            df_res = pd.DataFrame(oportunidades)
            df_res = df_res.sort_values(by=['Tendencia_Alta', 'Queda_Dia'], ascending=[False, True])
            
            st.session_state.dados_carregados = True
            st.session_state.df_resultado = df_res
            st.session_state.df_calculado = df_calc
            st.toast("Análise concluída!", icon="✅")
        else:
            st.warning("Nenhuma oportunidade encontrada.")
            st.session_state.dados_carregados = False
    else:
        st.error("Não foi possível baixar dados (Yahoo instável). Tente novamente em 1 min.")

# 3. EXIBIÇÃO DOS DADOS
if st.session_state.dados_carregados:
    df_res = st.session_state.df_resultado
    df_calc = st.session_state.df_calculado
    
    qtd_strategy = df_res[df_res['Tendencia_Alta'] == True].shape[0]
    m1, m2, m3 = st.columns(3)
    m1.metric("Oportunidades", len(df_res))
    m2.metric("Estratégia Ouro", qtd_strategy)
    
    if m3.button("📱 Enviar Relatório WhatsApp"):
        hora_atual = obter_hora_brasil()
        msg_zap = formatar_msg_whatsapp(df_res, hora_atual)
        with st.spinner("Enviando..."):
            sucesso, retorno = enviar_whatsapp_textmebot(msg_zap)
            if sucesso: st.success("Enviado!")
            else: st.error(f"Erro: {retorno}")
    
    st.divider()
    
    st.dataframe(
        df_res.style.map(estilizar_setup, subset=['Setup'])
                    .map(estilizar_is, subset=['IS'])
        .format({
            'Preco': 'R$ {:.2f}',
            'Queda_Dia': '{:.2f}%',
            'Gap': '{:.2f}%',
            'Dist_SMA200': '{:.2f}%',
            'IS': '{:.0f}'
        }),
        column_order=("Ticker", "Empresa", "Setup", "Preco", "Queda_Dia", "Gap", "IS", "Volume", "Sinais"),
        column_config={
            "Setup": st.column_config.Column("Estratégia", width="medium"),
            "Volume": st.column_config.NumberColumn("Volume", format="%d"),
            "IS": st.column_config.NumberColumn("I.S.", help="0-100"),
            "Sinais": st.column_config.TextColumn("Motivos", width="large")
        },
        use_container_width=True,
        hide_index=True
    )
    
    st.divider()
    st.subheader("🎯 Gráficos (Top 5 Estratégia)")
    
    top_graficos = df_res.head(5)
    for _, row in top_graficos.iterrows():
        try:
            df_ticker = df_calc.xs(row['Ticker'], axis=1, level=1).dropna()
            icon = "⭐" if row['Tendencia_Alta'] else "⚠️"
            st.markdown(f"### {icon} {row['Ticker']} - {row['Empresa']}")
            fig = plotar_grafico(df_ticker, row['Ticker'], row['Empresa'], row['IS'], row['Tendencia_Alta'])
            st.pyplot(fig)
            st.divider()
        except: continue
