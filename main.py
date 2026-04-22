import os
import requests
import psycopg2
import holidays
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google import genai
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

    # 3. Métricas
    cur = conn.cursor()
    meta = obter_meta(ontem_dt.date())
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE data_venda::date = %s", (ontem_str,))
    venda_dia = float(cur.fetchone()[0] or 0)
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE date_trunc('month', data_venda) = date_trunc('month', %s::date)", (ontem_str,))
    acumulado_mes = float(cur.fetchone()[0] or 0)
    cur.execute("""
        SELECT AVG(total) FROM (
            SELECT SUM(valor_total) as total FROM vendas 
            WHERE extract(dow from data_venda) = extract(dow from %s::date)
            AND data_venda::date < %s GROUP BY data_venda::date ORDER BY data_venda::date DESC LIMIT 4
        ) t
    """, (ontem_str, ontem_str))
    media_4_semanas = float(cur.fetchone()[0] or 0)
    conn.close()

    # 4. Análise IA (Correção: Definição do Prompt e Modelo)
    dia_semana_pt = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 4: "Sexta", 5: "Sábado", 6: "Domingo"}
    nome_dia = dia_semana_pt[ontem_dt.weekday()]

    # Definimos o prompt PRIMEIRO para evitar o erro de 'name not defined'
    texto_prompt = f"""
    Aja como CFO analítico do 'Nosso Café'. Marcos é o dono. Analise {ontem_str} ({nome_dia}):
    - Venda Real: R${venda_dia:.2f} (Meta: R${meta:.2f})
    - Acumulado Mês: R${acumulado_mes:.2f}
    - Média das últimas 4 {nome_dia}s: R${media_4_semanas:.2f}

    Instruções:
    1. Seja direto e profissional.
    2. Compare a venda com a meta e a média histórica.
    3. Se bateu a meta, elogie o esforço da equipe (Bárbara, Laryssa, Marcela, Natali e Keity).
    4. Se não bateu, sugira um ajuste rápido.
    """

    try:
        client = genai.Client(api_key=GEMINI_KEY.strip())
        
        # Lista modelos e escolhe o melhor disponível
        modelos_disponiveis = [m.name for m in client.models.list()]
        print(f"Modelos: {modelos_disponiveis}")
        
        # Ordem de preferência
        opcoes = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-3-flash']
        modelo_escolhido = next((opt for opt in opcoes if any(opt in m for m in modelos_disponiveis)), 'gemini-1.5-flash')
        
        print(f"Usando: {modelo_escolhido}")

        response = client.models.generate_content(
            model=modelo_escolhido, 
            contents=texto_prompt
        )
        relatorio_ia = response.text
    except Exception as e:
        print(f"Erro IA: {e}")
        relatorio_ia = f"Análise resumida (IA indisponível):\nVenda: R${venda_dia:.2f}\nMeta: R${meta:.2f}\nAcumulado: R${acumulado_mes:.2f}"

    # 5. Envio
    assunto = f"Relatório Diário Nosso Café - {ontem_str}"
    enviar_email(assunto, relatorio_ia)

if __name__ == "__main__":
    job_completo()
