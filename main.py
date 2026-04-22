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

# Carrega variáveis do arquivo .env (local) ou do GitHub Secrets (nuvem)
load_dotenv()

# Configurações de Ambiente
SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PWD = os.getenv("GMAIL_APP_PWD")
# Lista de e-mails separados por vírgula no GitHub Secrets
DESTINATARIOS_RAW = os.getenv("DESTINATARIO", "")

def enviar_email(assunto, corpo):
    """Envia o relatório para a lista de e-mails configurada."""
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
        print(f"E-mail enviado com sucesso para: {msg['To']}")
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")

def obter_meta(data_analise):
    """Define a meta: R$1800 para FDS/Feriados, R$1200 para dias úteis."""
    br_holidays = holidays.Brazil()
    if data_analise.weekday() >= 5 or data_analise in br_holidays:
        return 1800.0
    return 1200.0

def job_completo():
    # --- 1. CONFIGURAÇÃO DE DATAS ---
    ontem_dt = datetime.now() - timedelta(days=1)
    ontem_str = ontem_dt.strftime("%Y-%m-%d")
    print(f"--- Iniciando Processamento: {ontem_str} ---")

    # --- 2. SINCRONIZAÇÃO SAIPOS -> SUPABASE ---
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

    # --- 3. CÁLCULO DE MÉTRICAS NO BANCO ---
    cur = conn.cursor()
    meta = obter_meta(ontem_dt.date())

    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE data_venda::date = %s", (ontem_str,))
    venda_dia = float(cur.fetchone()[0] or 0)

    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE date_trunc('month', data_venda) = date_trunc('month', %s::date)", (ontem_str,))
    acumulado_mes = float(cur.fetchone()[0] or 0)

    # Média das mesmas DOW (Day of Week) nas últimas 4 semanas
    cur.execute("""
        SELECT AVG(total) FROM (
            SELECT SUM(valor_total) as total FROM vendas 
            WHERE extract(dow from data_venda) = extract(dow from %s::date)
            AND data_venda::date < %s 
            GROUP BY data_venda::date 
            ORDER BY data_venda::date DESC LIMIT 4
        ) t
    """, (ontem_str, ontem_str))
    media_4_semanas = float(cur.fetchone()[0] or 0)
    conn.close()

    # --- 4. ANÁLISE COM GEMINI (Seleção Automática de Modelo) ---
    try:
        client = genai.Client(api_key=GEMINI_KEY.strip())
        
        # 1. Vamos listar os modelos para ver qual o nome exato que sua conta aceita
        modelos_disponiveis = [m.name for m in client.models.list()]
        print(f"Modelos encontrados na sua conta: {modelos_disponiveis}")

        # 2. Tentamos selecionar o melhor na ordem de preferência
        # No Google Cloud/AI Studio em 2026, os nomes perderam o prefixo 'models/' em muitos casos
        opcoes = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-3-flash']
        modelo_escolhido = None
        
        for opcao in opcoes:
            # Verifica se a opção (ou 'models/'+opcao) está na lista
            if any(opcao in m for m in modelos_disponiveis):
                modelo_escolhido = opcao
                break
        
        if not modelo_escolhido:
            # Se não achou nenhum da lista, pega o primeiro que aparecer
            modelo_escolhido = modelos_disponiveis[0].split('/')[-1]

        print(f"Usando o modelo: {modelo_escolhido}")

        response = client.models.generate_content(
            model=modelo_escolhido, 
            contents=prompt
        )
        relatorio_ia = response.text

    except Exception as e:
        print(f"Erro ao chamar IA: {e}")
        relatorio_ia = f"Erro na análise de IA: {e}\n\nVenda: R${venda_dia:.2f}\nMeta: R${meta:.2f}"

    # --- 5. ENVIO DO RELATÓRIO ---
    assunto = f"Relatório Diário Nosso Café - {ontem_str}"
    enviar_email(assunto, relatorio_ia)
    print("Processo finalizado com sucesso.")

if __name__ == "__main__":
    job_completo()
