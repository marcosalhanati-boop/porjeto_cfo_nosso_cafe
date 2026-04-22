import os
import requests
import psycopg2
import holidays
import smtplib
from google import genai
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

# Configurações de Ambiente
SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")      # Seu e-mail (ex: marcos@gmail.com)
GMAIL_APP_PWD = os.getenv("GMAIL_APP_PWD") # A senha de 16 dígitos que você gerou
DESTINATARIO = os.getenv("DESTINATARIO")   # Para quem vai o e-mail

genai.configure(api_key=GEMINI_KEY)

def enviar_email(assunto, corpo):
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = DESTINATARIO
    msg['Subject'] = assunto
    msg.attach(MIMEText(corpo, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PWD)
        server.send_message(msg)
        server.quit()
        print("E-mail enviado com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")

def obter_meta(data):
    br_holidays = holidays.Brazil()
    if data.weekday() >= 5 or data in br_holidays:
        return 1800.0
    return 1200.0

def job_completo():
    # 1. SINCRONIZAÇÃO (SAIPOS -> SUPABASE)
    ontem_dt = datetime.now() - timedelta(days=1)
    ontem_str = ontem_dt.strftime("%Y-%m-%d")
    
    print(f"--- Sincronizando: {ontem_str} ---")
    # ... (sua lógica de request da Saipos que já funciona) ...
    # Assumindo que os dados já foram inseridos aqui

    # 2. CÁLCULO DE MÉTRICAS
    conn = psycopg2.connect(DB_URL)
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
            AND data_venda::date < %s GROUP BY data_venda::date LIMIT 4
        ) t
    """, (ontem_str, ontem_str))
    media_4_semanas = float(cur.fetchone()[0] or 0)
    conn.close()

    # 3. ANÁLISE IA (GEMINI)
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"""
    Aja como CFO do 'Nosso Café'. Marcos é o dono. Analise {ontem_str}:
    - Venda: R${venda_dia:.2f} (Meta: R${meta:.2f})
    - Mês: R${acumulado_mes:.2f}
    - Média das últimas 4 {ontem_dt.strftime('%A')}s: R${media_4_semanas:.2f}
    Seja direto e traga um diagnóstico de performance.
    """
    analise = model.generate_content(prompt).text

    # 4. DISPARO DO E-MAIL
    assunto = f"Relatório Diário Nosso Café - {ontem_str}"
    enviar_email(assunto, analise)

if __name__ == "__main__":
    job_completo()
