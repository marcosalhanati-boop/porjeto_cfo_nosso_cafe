import os
import requests
import psycopg2
import holidays
import smtplib
import google.generativeai as genai
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# Configurações
SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PWD = os.getenv("GMAIL_APP_PWD")
DESTINATARIOS_RAW = os.getenv("DESTINATARIO", "")

def enviar_email(assunto, corpo):
    if not DESTINATARIOS_RAW:
        print("Erro: Nenhum destinatário configurado.")
        return
    lista_emails = [e.strip() for e in DESTINATARIOS_RAW.split(',')]
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = ", ".join(lista_emails)
    msg['Subject'] = assunto
    msg.attach(MIMEText(corpo, 'plain'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PWD)
            server.sendmail(GMAIL_USER, lista_emails, msg.as_string())
        print(f"E-mail enviado com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")

def obter_meta(data_analise):
    br_holidays = holidays.Brazil()
    if data_analise.weekday() >= 5 or data_analise in br_holidays:
        return 1800.0
    return 1200.0

def job_completo():
    # 1. Datas
    ontem_dt = datetime.now() - timedelta(days=1)
    ontem_str = ontem_dt.strftime("%Y-%m-%d")
    print(f"--- Iniciando Processamento: {ontem_str} ---")

    # 2. Sync Saipos -> Supabase
    url = "https://data.saipos.io/v1/search_sales_v3"
    headers = {"Authorization": f"Bearer {SAIPOS_TOKEN}", "Accept": "application/json"}
    params = {
        "p_date_column_filter": "shift_date", 
        "p_filter_date_start": f"{ontem_str}T00:00:00", 
        "p_filter_date_end": f"{ontem_str}T23:59:59"
    }
    r = requests.get(url, headers=headers, params=params)
    vendas = r.json() if r.status_code == 200 else []
    
    conn = psycopg2.connect(DB_URL)
    with conn.cursor() as cur:
        for v in vendas:
            if v.get('canceled') == 'Y': continue
            cur.execute("""
                INSERT INTO vendas (id_venda, data_venda, valor_total)
                VALUES (%s, %s, %s)
                ON CONFLICT (id_venda) DO UPDATE SET valor_total = EXCLUDED.valor_total;
            """, (v.get('id_sale'), v.get('created_at'), v.get('total_amount')))
        conn.commit()

    # --- 3. MÉTRICAS E PROJEÇÃO ---
    cur = conn.cursor()
    meta = obter_meta(ontem_dt.date())
    
    # Venda do dia
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE data_venda::date = %s", (ontem_str,))
    venda_dia = float(cur.fetchone()[0] or 0)

    # Acumulado do mês
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE date_trunc('month', data_venda) = date_trunc('month', %s::date)", (ontem_str,))
    acumulado_mes = float(cur.fetchone()[0] or 0)

    # Média diária real do mês atual
    dia_atual = ontem_dt.day
    media_diaria_mes = acumulado_mes / dia_atual

    # Projeção para o fim do mês
    import calendar
    ultimo_dia = calendar.monthrange(ontem_dt.year, ontem_dt.month)[1]
    dias_restantes = ultimo_dia - dia_atual
    projecao_final = acumulado_mes + (media_diaria_mes * dias_restantes)

    # Média histórica das últimas 4 semanas (mesmo dia da semana)
    cur.execute("""
        SELECT AVG(total) FROM (
            SELECT SUM(valor_total) as total FROM vendas 
            WHERE extract(dow from data_venda) = extract(dow from %s::date)
            AND data_venda::date < %s GROUP BY data_venda::date ORDER BY data_venda::date DESC LIMIT 4
        ) t
    """, (ontem_str, ontem_str))
    media_4_semanas = float(cur.fetchone()[0] or 0)
    conn.close()
    
   # --- 4. ANÁLISE COM GEMINI (Versão com Projeção e Auto-Correção) ---
    texto_prompt = f"""
    Analise os resultados do 'Nosso Café' em {ontem_str}:
    - Venda Real: R${venda_dia:.2f} (Meta: R${meta:.2f})
    - Acumulado Mês: R${acumulado_mes:.2f}
    - Média Diária no Mês: R${media_diaria_mes:.2f}
    - Projeção Final do Mês: R${projecao_final:.2f}
    - Média das últimas 4 {nome_dia}s: R${media_4_semanas:.2f}

    Instruções:
    1. Comente sobre o superávit de ontem.
    2. Avalie se a projeção final (R${projecao_final:.2f}) está saudável para o negócio.
    3. Elogie a equipe (Bárbara, Laryssa, Marcela, Natali e Keity) pelo resultado.
    """

    try:
        genai.configure(api_key=GEMINI_KEY.strip())
        # Tentativa 1: Nome direto
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(texto_prompt)
            relatorio_ia = response.text
        except:
            # Tentativa 2: Nome com prefixo (caso a primeira falhe)
            model = genai.GenerativeModel('models/gemini-1.5-flash')
            response = model.generate_content(texto_prompt)
            relatorio_ia = response.text
            
    except Exception as e:
        # Se as duas falharem, o e-mail vai com os dados formatados por nós:
        relatorio_ia = f"""
        🚀 **RELATÓRIO DE VENDAS - NOSSO CAFÉ**
        
        Ontem ({nome_dia}): R${venda_dia:.2f}
        Meta: R${meta:.2f} (Superávit: R${venda_dia - meta:.2f})
        
        📊 **VISÃO MENSAL**
        Acumulado: R${acumulado_mes:.2f}
        Média Diária: R${media_diaria_mes:.2f}
        Projeção Fim do Mês: R${projecao_final:.2f}
        
        *Nota: Análise automática indisponível no momento.*
        """

    # 5. Envio
    assunto = f"Relatório Diário Nosso Café - {ontem_str}"
    enviar_email(assunto, relatorio_ia)

if __name__ == "__main__":
    job_completo()
