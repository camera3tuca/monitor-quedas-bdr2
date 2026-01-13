import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import matplotlib.pyplot as plt
import seaborn as sns
import requests
import urllib.parse
from datetime import datetime, timedelta
import pytz
import warnings

# --- CONFIGURAÇÃO DA PÁGINA ---
VERSAO = "v5.0 (Completa)"
st.set_page_config(
    page_title=f"Monitor BDR {VERSAO}",
    page_icon="🦅",
    layout="wide"
)

warnings.filterwarnings('ignore')
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

PERIODO = "1y" # Aumentei para 1 ano para calcular a SMA200 com precisão
TERMINACOES_BDR = ('31', '32', '33', '34', '35', '39')

# --- SEGREDOS (COM A CORREÇÃO DA BRAPI) ---
try:
    BRAPI_API_TOKEN = st.secrets["BRAPI_API_TOKEN"]
    WHATSAPP_PHONE = st.secrets["WHATSAPP_PHONE"]
    WHATSAPP_APIKEY = st.secrets["WHATSAPP_APIKEY"]
except:
    st.error("ERRO: Configure as chaves (BRAPI, WHATSAPP) nos Secrets do Streamlit.")
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
        # CORREÇÃO CRÍTICA DO ERRO "EXPECTING VALUE"
        url = f"https://brapi.dev/api/quote/list?token={BRAPI_API_TOKEN}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        
        dados = r.json().get('stocks', [])
        bdrs_raw = [d for d in dados if d['stock'].endswith(TERMINACOES_BDR)]
        lista_tickers = [d['stock'] for d in bdrs_raw]
        mapa_nomes = {d['stock']: d.get('name', d['stock']) for d in bdrs_raw}
        return lista_tickers, mapa_nomes
    except Exception as e:
        st.error(f"Erro BRAPI: {e}")
        return [], {}

@st.cache_data(ttl=1800)
def buscar_dados(tickers):
    if not tickers: return pd.DataFrame()
    sa_tickers = [f"{t}.SA" for t in tickers]
    try:
        # ignore_tz=True ajuda a evitar erros de fuso horário do Yahoo
        df = yf.download(sa_tickers, period=PERIODO, auto_adjust=True, progress=False, timeout=60, ignore_tz=True)
        if df.empty: return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = pd.MultiIndex.from_tuples([(c[0], c[1].replace(".SA", "")) for c in df.columns])
        return df.dropna(axis=1, how='all')
    except: return pd.DataFrame()

def calcular_indicadores(df):
    df_calc = df.copy()
    tickers = df_calc.columns.get_level_values(1).unique()
    
    progresso = st.progress(0)
    total = len(tickers)
    
    for i, ticker in enumerate(tickers):
        if i % 10 == 0: progresso.progress((i + 1) / total)
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

            # Estocástico
            lowest_low = low.rolling(14).min()
            highest_high = high.rolling(14).max()
            df_calc[('Stoch_K', ticker)] = 100 * ((close - lowest_low) / (highest_high - lowest_low))

            # Médias (Setup do Gráfico Preferido)
            df_calc[('SMA200', ticker)] = close.rolling(200).mean() # Tendência Longa
            df_calc[('EMA20', ticker)] = close.ewm(span=20).mean()  # Tendência Curta
            
            # Bollinger
            sma20 = close.rolling(20).mean()
            std = close.rolling(20).std()
            df_calc[('BB_Lower', ticker)] = sma20 - (std * 2)
            df_calc[('BB_Upper', ticker)] = sma20 + (std * 2)

        except: continue
            
    progresso.empty()
    return df_calc

def analisar_oportunidades(df_calc, mapa_nomes):
    resultados = []
    tickers = df_calc.columns.get_level_values(1).unique()

    for ticker in tickers:
        try:
            df_ticker = df_calc.xs(ticker, axis=1, level=1).dropna()
            if len(df_ticker) < 200: continue # Precisa de 200 dias para a SMA200

            last = df_ticker.iloc[-1]
            prev = df_ticker.iloc[-2]
            
            preco = last.get('Close')
            prev_close = prev.get('Close')
            
            if pd.isna(preco) or pd.isna(prev_close): continue

            # Variação do Dia
            queda_dia = ((preco - prev_close) / prev_close) * 100
            
            # Só queremos QUEDAS
            if queda_dia >= 0: continue 

            # Variação 7 Dias (aprox 5 pregões)
            var_7d = np.nan
            if len(df_ticker) >= 6:
                price_7d = df_ticker['Close'].iloc[-6]
                var_7d = ((preco - price_7d) / price_7d) * 100

            # --- SINAIS DO GRÁFICO PREFERIDO ---
            sinais = []
            
            # 1. Tendência de Alta (Preço > SMA200)
            sma200 = last.get('SMA200')
            tendencia_alta = False
            if pd.notna(sma200) and preco > sma200:
                tendencia_alta = True
                sinais.append("Trend Alta")
            
            # 2. RSI e Stoch
            rsi = last.get('RSI14', 50)
            stoch = last.get('Stoch_K', 50)
            if rsi < 30: sinais.append("RSI Baixo")
            if stoch < 20: sinais.append("Stoch Fundo")
            
            # 3. Bollinger
            bb_low = last.get('BB_Lower')
            if pd.notna(bb_low) and preco < bb_low * 1.02:
                sinais.append("Suporte BB")

            # Índice de Sobrevenda (Quanto maior, melhor)
            is_index = ((100 - rsi) + (100 - stoch)) / 2
            
            # Definição do Setup
            setup = "⚠️ Repique"
            if tendencia_alta:
                setup = "⭐ Ouro (Trend Alta)"

            # Tratamento de Nome
            nome = mapa_nomes.get(ticker, ticker).split()[0].replace(',', '').title()

            resultados.append({
                'Ticker': ticker,
                'Empresa': nome,
                'Preco': preco,
                'Queda_Dia': queda_dia,
                'Var_7d': var_7d,
                'Volume': last.get('Volume', 0),
                'IS': is_index,
                'Setup': setup,
                'Sinais': ", ".join(sinais),
                'Trend': tendencia_alta
            })
        except: continue
    return resultados

def plotar_grafico(df_ticker, ticker, empresa, setup):
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, gridspec_kw={'height_ratios': [3, 1, 1]})
    
    close = df_ticker['Close']
    sma200 = df_ticker['SMA200']
    
    # Gráfico Principal
    ax1 = axes[0]
    ax1.plot(close.index, close.values, label='Preço', color='#333333')
    
    # NOSSO GRÁFICO PREFERIDO: Média de 200 em Dourado
    if not sma200.isnull().all():
        ax1.plot(close.index, sma200, label='SMA 200 (Tendência)', color='gold', linewidth=2)
        
    ax1.plot(close.index, df_ticker['EMA20'], label='EMA 20', color='blue', alpha=0.6, linewidth=1)
    ax1.fill_between(close.index, df_ticker['BB_Lower'], df_ticker['BB_Upper'], alpha=0.1, color='gray')
    
    status_icon = "⭐" if "Ouro" in setup else "⚠️"
    ax1.set_title(f'{status_icon} {ticker} - {empresa} | {setup}', fontweight='bold')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)

    # RSI
    ax2 = axes[1]
    ax2.plot(close.index, df_ticker['RSI14'], color='orange', label='RSI')
    ax2.axhline(30, color='red', linestyle='--')
    ax2.axhline(70, color='green', linestyle='--')
    ax2.set_ylabel('RSI')
    ax2.set_ylim(0, 100)
    
    # Estocástico
    ax3 = axes[2]
    ax3.plot(close.index, df_ticker['Stoch_K'], color='purple', label='Stoch')
    ax3.axhline(20, color='red', linestyle='--')
    ax3.axhline(80, color='green', linestyle='--')
    ax3.set_ylabel('Stoch')
    ax3.set_ylim(0, 100)
    
    plt.tight_layout()
    return fig

# --- FUNÇÕES DE ESTILO ---
def estilizar_setup(val):
    if "Ouro" in val: return 'background-color: #1b5e20; color: white; font-weight: bold'
    return 'color: #555'

def estilizar_is(val):
    if val >= 75: return 'background-color: #d32f2f; color: white; font-weight: bold' # Vermelho forte
    elif val >= 60: return 'background-color: #ffa726; color: black' # Laranja
    return 'color: #888'

# --- LAYOUT DO APP ---

c1, c2 = st.columns([3, 1])
c1.title(f"🦅 Monitor BDR - {VERSAO}")
c2.markdown(f"**🕒 {obter_hora_brasil()} (Brasília)**")

# LEGENDAS (Expander)
with st.expander("ℹ️ LEGENDA DOS SINAIS (Clique para abrir)"):
    col_l1, col_l2 = st.columns(2)
    with col_l1:
        st.markdown("""
        * **⭐ Ouro (Trend Alta):** O preço caiu hoje, mas ainda está ACIMA da Média de 200 (Tendência Primária de Alta). Melhor cenário para compra.
        * **⚠️ Repique:** O preço caiu e está ABAIXO da Média de 200. É uma operação mais arriscada (contra a tendência).
        """)
    with col_l2:
        st.markdown("""
        * **I.S. (Índice de Sobrevenda):** De 0 a 100. Quanto maior (vermelho), mais "barato" o ativo está estatisticamente.
        * **Var 7D:** Quanto o ativo subiu ou caiu nos últimos 7 dias.
        """)

if st.button("🔄 Rastrear Oportunidades", type="primary"):
    with st.spinner("Conectando à BRAPI e baixando dados..."):
        lista_bdrs, mapa_nomes = obter_dados_brapi()
        df = buscar_dados(lista_bdrs)
        
    if not df.empty:
        df_calc = calcular_indicadores(df)
        oportunidades = analisar_oportunidades(df_calc, mapa_nomes)
        
        if oportunidades:
            df_res = pd.DataFrame(oportunidades)
            # Ordenar: Primeiro os setups "Ouro", depois pelo I.S. (mais descontados)
            df_res = df_res.sort_values(by=['Trend', 'IS'], ascending=[False, False])
            
            qtd_ouro = df_res[df_res['Trend'] == True].shape[0]
            st.success(f"{len(oportunidades)} quedas encontradas! ({qtd_ouro} em Tendência de Alta ⭐)")
            
            # --- TABELA ---
            st.dataframe(
                df_res.style.map(estilizar_setup, subset=['Setup'])
                            .map(estilizar_is, subset=['IS'])
                .format({
                    'Preco': 'R$ {:.2f}',
                    'Queda_Dia': '{:.2f}%',
                    'Var_7d': '{:.2f}%',
                    'IS': '{:.0f}',
                    'Volume': '{:,.0f}' # Volume Inteiro com separador
                }),
                column_order=("Ticker", "Empresa", "Setup", "Preco", "Queda_Dia", "Var_7d", "IS", "Volume", "Sinais"),
                column_config={
                    "Setup": st.column_config.Column("Estratégia", width="medium"),
                    "Var_7d": st.column_config.NumberColumn("7 Dias"),
                    "Volume": st.column_config.NumberColumn("Vol.", format="%d"), # Inteiro
                    "IS": st.column_config.NumberColumn("I.S.", help="0-100 (Quanto maior, mais barato)")
                },
                hide_index=True,
                use_container_width=True
            )
            
            # --- WHATSAPP ---
            if st.button("📱 Enviar Relatório WhatsApp"):
                top = df_res.head(10)
                msg = f"🦅 *BDR ALERT {VERSAO}*\n📅 {obter_hora_brasil()}\n\n"
                for _, r in top.iterrows():
                    icon = "⭐" if r['Trend'] else "🔻"
                    msg += f"{icon} *{r['Ticker']}* ({r['Queda_Dia']:.2f}%)\n"
                    msg += f"   💰 R${r['Preco']:.2f} | 7D: {r['Var_7d']:.1f}%\n"
                    msg += f"   📊 IS: {r['IS']:.0f} | {r['Sinais']}\n\n"
                
                if enviar_whatsapp(msg): st.success("Enviado com sucesso!")
                else: st.error("Erro ao enviar.")

            # --- GRÁFICOS ---
            st.divider()
            st.subheader("🎯 Top Oportunidades (Visual)")
            
            top5 = df_res.head(5)
            for _, row in top5.iterrows():
                try:
                    df_ticker = df_calc.xs(row['Ticker'], axis=1, level=1).dropna()
                    fig = plotar_grafico(df_ticker, row['Ticker'], row['Empresa'], row['Setup'])
                    st.pyplot(fig)
                    st.divider()
                except: continue
                
        else:
            st.warning("Nenhuma BDR em queda encontrada hoje.")
    else:
        st.error("Erro ao carregar dados.")
