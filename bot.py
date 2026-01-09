import pandas as pd
import yfinance as yf
import requests
import urllib.parse
import os
from datetime import datetime
import pytz

# --- CONFIGURAÇÕES ---
# O robô pega as senhas das Variáveis de Ambiente do GitHub (não do secrets.toml)
try:
    WHATSAPP_PHONE = os.environ["WHATSAPP_PHONE"]
    WHATSAPP_APIKEY = os.environ["WHATSAPP_APIKEY"]
    BRAPI_API_TOKEN = os.environ["BRAPI_API_TOKEN"]
except KeyError:
    print("Erro: Chaves de API não encontradas nas variáveis de ambiente.")
    exit()

PERIODO = "1y"
TERMINACOES_BDR = ('31', '32', '33', '34', '35', '39')

# --- FUNÇÕES (Reaproveitadas do App) ---

def obter_hora_brasil():
    fuso = pytz.timezone('America/Sao_Paulo')
    return datetime.now(fuso).strftime('%d/%m/%Y %H:%M:%S')

def enviar_whatsapp(mensagem):
    print(f"Tentando enviar mensagem...")
    try:
        texto_encoded = urllib.parse.quote(mensagem)
        url = f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_PHONE}&text={texto_encoded}&apikey={WHATSAPP_APIKEY}"
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            print("Mensagem enviada com sucesso!")
        else:
            print(f"Erro API CallMeBot: {r.status_code}")
    except Exception as e:
        print(f"Erro de conexão: {e}")

def obter_dados_brapi():
    url = f"https://brapi.dev/api/quote/list?token={BRAPI_API_TOKEN}"
    r = requests.get(url, timeout=30)
    dados = r.json().get('stocks', [])
    bdrs_raw = [d for d in dados if d['stock'].endswith(TERMINACOES_BDR)]
    lista_tickers = [d['stock'] for d in bdrs_raw]
    # Mapa simplificado para economizar memória
    mapa_nomes = {d['stock']: d.get('name', d['stock']) for d in bdrs_raw}
    return lista_tickers, mapa_nomes

def buscar_dados(tickers):
    if not tickers: return pd.DataFrame()
    sa_tickers = [f"{t}.SA" for t in tickers]
    df = yf.download(sa_tickers, period=PERIODO, auto_adjust=True, progress=False, timeout=120)
    
    if df.empty: return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = pd.MultiIndex.from_tuples([(c[0], c[1].replace(".SA", "")) for c in df.columns])
    
    return df.dropna(axis=1, how='all')

def calcular_tudo(df):
    df_calc = df.copy()
    tickers = df_calc.columns.get_level_values(1).unique()
    
    # Lista para guardar resultados sem loop complexo depois
    resultados = []
    
    for ticker in tickers:
        try:
            # Seleciona dados do ticker
            df_ticker = df_calc.xs(ticker, axis=1, level=1).dropna()
            if len(df_ticker) < 200: continue

            close = df_ticker['Close']
            high = df_ticker['High']
            low = df_ticker['Low']
            
            # Indicadores Básicos
            last_close = close.iloc[-1]
            prev_close = close.iloc[-2]
            sma200 = close.rolling(200).mean().iloc[-1]
            
            # Queda
            queda_dia = ((last_close - prev_close) / prev_close) * 100
            if queda_dia >= 0: continue # Pula se não for queda
            
            # Tendencia
            tendencia_alta = last_close > sma200
            
            # RSI
            delta = close.diff()
            ganho = delta.clip(lower=0).rolling(14).mean()
            perda = -delta.clip(upper=0).rolling(14).mean()
            rs = ganho / perda
            rsi = 100 - (100 / (1 + rs))
            last_rsi = rsi.iloc[-1]
            
            # Estocástico
            lowest_low = low.rolling(14).min()
            highest_high = high.rolling(14).max()
            stoch = 100 * ((close - lowest_low) / (highest_high - lowest_low))
            last_stoch = stoch.iloc[-1]
            
            # I.S.
            is_index = ((100 - last_rsi) + (100 - last_stoch)) / 2
            
            # Sinais Resumidos (Texto)
            sinais = []
            if tendencia_alta: sinais.append("Trend Alta")
            if last_rsi < 30: sinais.append("RSI Baixo")
            if last_stoch < 20: sinais.append("Stoch Fundo")
            
            # BB Check
            sma20 = close.rolling(20).mean()
            std = close.rolling(20).std()
            bb_lower = sma20 - (std * 2)
            if last_close < bb_lower.iloc[-1] * 1.02: sinais.append("BB Suporte")

            resultados.append({
                'Ticker': ticker,
                'Preco': last_close,
                'Queda_Dia': queda_dia,
                'IS': is_index,
                'Tendencia_Alta': tendencia_alta,
                'Sinais': ", ".join(sinais)
            })
            
        except Exception: continue
        
    return pd.DataFrame(resultados)

# --- EXECUÇÃO PRINCIPAL ---

if __name__ == "__main__":
    print("🤖 Iniciando Bot BDR...")
    hora = obter_hora_brasil()
    
    print("1. Buscando lista na BRAPI...")
    tickers, mapa_nomes = obter_dados_brapi()
    
    print(f"2. Baixando dados de {len(tickers)} ativos via Yahoo...")
    df_market = buscar_dados(tickers)
    
    if not df_market.empty:
        print("3. Calculando indicadores...")
        df_res = calcular_tudo(df_market)
        
        if not df_res.empty:
            # Ordenação
            df_res = df_res.sort_values(by=['Tendencia_Alta', 'Queda_Dia'], ascending=[False, True])
            
            # Filtra Top 10
            top10 = df_res.head(10)
            qtd_strategy = df_res[df_res['Tendencia_Alta'] == True].shape[0]
            
            # Formata Mensagem
            msg = f"🦅 *BDR ALERT - BOM DIA*\n"
            msg += f"🗓️ {hora}\n"
            msg += f"🚨 *{len(df_res)}* Quedas | ⭐ *{qtd_strategy}* Estratégia\n\n"
            msg += "*🏆 TOP 10 MAIORES QUEDAS:*\n"
            
            for _, row in top10.iterrows():
                nome = mapa_nomes.get(row['Ticker'], row['Ticker']).split()[0]
                icon = "⭐" if row['Tendencia_Alta'] else "🔻"
                msg += f"{icon} *{row['Ticker']}* - {nome}\n"
                msg += f"   📉 {row['Queda_Dia']:.1f}% | 💵 R${row['Preco']:.2f}\n"
                msg += f"   📊 I.S. {row['IS']:.0f} | {row['Sinais']}\n"
                msg += "   - - - - - - - -\n"
            
            msg += "\n🔗 _Acesse o App para ver os gráficos_"
            
            # Envia
            enviar_whatsapp(msg)
        else:
            print("Nenhuma oportunidade encontrada hoje.")
    else:
        print("Erro ao baixar dados do mercado.")
