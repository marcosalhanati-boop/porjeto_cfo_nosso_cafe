import os
import requests
import psycopg2
import holidays
import smtplib
import calendar
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import google.genai as genai

load_dotenv()

# Configurações
SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PWD = os.getenv("GMAIL_APP_PWD")
DESTINATARIOS_RAW = os.getenv("DESTINATARIO", "")

def obter_comparativo_mtd_texto(cursor):
    ontem = datetime.now() - timedelta(days=1)
    dia_fechamento = ontem.day
    
    # Datas
    inicio_atual = ontem.replace(day=1).strftime('%Y-%m-%d')
    fim_atual = ontem.strftime('%Y-%m-%d')
    
    mes_anterior_dt = (ontem.replace(day=1) - timedelta(days=1))
    dia_fim_ant = min(dia_fechamento, calendar.monthrange(mes_anterior_dt.year, mes_anterior_dt.month)[1])
    inicio_ant = mes_anterior_dt.replace(day=1).strftime('%Y-%m-%d')
    fim_ant = mes_anterior_dt.replace(day=dia_fim_ant).strftime('%Y-%m-%d')
    
    mes_retrasado_dt = (mes_anterior_dt.replace(day=1) - timedelta(days=1))
    dia_fim_retr = min(dia_fechamento, calendar.monthrange(mes_retrasado_dt.year, mes_retrasado_dt.month)[1])
    inicio_retr = mes_retrasado_dt.replace(day=1).strftime('%Y-%m-%d')
    fim_retr = mes_retrasado_dt.replace(day=dia_fim_retr).strftime('%Y-%m-%d')

    def buscar_total(ini, fim):
        cursor.execute("SELECT SUM(valor_total) FROM vendas WHERE data_venda >= %s AND data_venda <= %s", (ini, fim))
        res = cursor.fetchone()[0]
        return float(res) if res else 0.0

    t_atual = buscar_total(inicio_atual, fim_atual)
    t_ant = buscar_total(inicio_ant, fim_ant)
    t_retr = buscar_total(inicio_retr, fim_retr)

    def calc_var(atual, base):
        return ((atual - base) / base * 100) if base > 0 else 0

    v_ant = calc_var(t_atual, t_ant)
    v_retr = calc_var(t_atual, t_retr)
    
    # Formatação em texto puro
    texto = f"📈 COMPARATIVO MTD (Acumulado até dia {dia_fechamento})\n"
    texto += f"------------------------------------------\n"
    texto += f"ESTE MÊS ({ontem.strftime('%b/%y')}): R$ {t_atual:,.2f}\n"
    texto += f"MÊS ANTERIOR ({mes_anterior_dt.strftime('%b/%y')}): R$ {t_ant:,.2f} ({v_ant:+.1f}% {'🟢 ↑' if v_ant >=0 else '🔴 ↓'})\n"
    texto += f"MÊS RETRASADO ({mes_retrasado_dt.strftime('%b/%y')}): R$ {t_retr:,.2f} ({v_retr:+.1f}% {'🟢 ↑' if v_retr >=0 else '🔴 ↓'})\n"
    texto += f"------------------------------------------\n"
    return texto

def extrair_forma_pagamento(venda):
    pagamentos = venda.get('payments', [])
    return pagamentos[0].get('payment_method_name', 'Outros') if pagamentos else "Não Informado"

def enviar_email_texto(assunto, corpo):
    if not DESTINATARIOS_RAW: return
    lista_emails = [e.strip() for e in DESTINATARIOS_RAW.split(',')]
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = ", ".join(lista_emails)
    msg['Subject'] = assunto
    
    # VOLTAMOS PARA PLAIN TEXT
    msg.attach(MIMEText(corpo, 'plain'))
    
    try:
        # Usando a porta 465 (SSL) que é mais resiliente
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PWD)
            server.send_message(msg)
            print("E-mail enviado!")
    except Exception as e:
        print(f"Erro e-mail: {e}")

def calcular_meta_dinamica(cursor, data_analise):
    br_holidays = holidays.Brazil()
    dia_semana = data_analise.weekday()
    query = """
        SELECT AVG(total_dia) FROM (
            SELECT data_venda::date as dt, SUM(valor_total) as total_dia
            FROM vendas
            WHERE data_venda::date < %s 
            AND data_venda::date >= %s - INTERVAL '90 days'
            AND extract(dow from data_venda) = %s
            GROUP BY data_venda::date
        ) as historico
    """
    cursor.execute(query, (data_analise, data_analise, dia_semana))
    resultado = cursor.fetchone()[0]
    media = float(resultado) if resultado else 1200.0
    return round(media * 1.025, 2)

def job_completo():
    ontem_dt = datetime.now() - timedelta(days=1)
    ontem_str = ontem_dt.strftime("%Y-%m-%d")
    dia_semana_pt = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 4: "Sexta", 5: "Sábado", 6: "Domingo"}
    nome_dia = dia_semana_pt[ontem_dt.weekday()]
    
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # 1. Sync Saipos
    url = "https://data.saipos.io/v1/search_sales_v3"
    headers = {"Authorization": f"Bearer {SAIPOS_TOKEN}"}
    params = {"p_date_column_filter": "shift_date", "p_filter_date_start": f"{ontem_str}T00:00:00", "p_filter_date_end": f"{ontem_str}T23:59:59"}
    
    r = requests.get(url, headers=headers, params=params)
    vendas = r.json() if r.status_code == 200 else []
    
    for v in vendas:
        if v.get('canceled') == 'Y': continue
        forma = extrair_forma_pagamento(v)
        cur.execute("""
            INSERT INTO vendas (id_venda, data_venda, valor_total, forma_pagamento)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id_venda) DO UPDATE SET valor_total = EXCLUDED.valor_total;
        """, (v.get('id_sale'), v.get('created_at'), v.get('total_amount'), forma))
    conn.commit()

    # 2. Métricas
    comparativo_texto = obter_comparativo_mtd_texto(cur)
    meta_hoje = calcular_meta_dinamica(cur, ontem_dt.date())
    
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE data_venda::date = %s", (ontem_str,))
    venda_dia = float(cur.fetchone()[0] or 0)
    
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE date_trunc('month', data_venda) = date_trunc('month', %s::date)", (ontem_str,))
    acumulado_mes = float(cur.fetchone()[0] or 0)

    # --- 3. Análise IA com Ajuste de Nomenclatura ---
    relatorio_ia = ""
    prompt = f"Aja como CFO do 'Nosso Café'. Analise o dia {ontem_str} ({nome_dia}): Venda R${venda_dia:.2f}, Meta R${meta_hoje:.2f}. Acumulado do mês R${acumulado_mes:.2f}. Seja direto, executivo e destaque se batemos a meta."
    
    # Adicionamos 'models/' antes para evitar o erro 404 de 'não encontrado'
    modelos_para_testar = ['models/gemini-1.5-flash', 'models/gemini-1.5-flash-8b', 'models/gemini-1.0-pro']

    print("Iniciando tentativa de conexão com Gemini...")
    try:
        # Importante: Garantir que o cliente use a versão estável da API
        client = genai.Client(api_key=GEMINI_KEY.strip())
        
        for modelo in modelos_para_testar:
            try:
                print(f"Testando modelo: {modelo}...")
                # No SDK novo, às vezes passar o nome direto funciona melhor
                response = client.models.generate_content(model=modelo, contents=prompt)
                
                if response and response.text:
                    relatorio_ia = response.text
                    print(f"Sucesso com o modelo: {modelo}")
                    break
            except Exception as e_modelo:
                print(f"Modelo {modelo} falhou: {e_modelo}")
                continue
                
    except Exception as e_client:
        print(f"Erro ao inicializar cliente Gemini: {e_client}")

    # Fallback caso todos os modelos falhem
    if not relatorio_ia:
        print("Todos os modelos de IA falharam. Usando resumo técnico.")
        relatorio_ia = f"Venda: R${venda_dia:.2f} | Meta: R${meta_hoje:.2f}\nAcumulado Mês: R${acumulado_mes:.2f}"

    # 4. Montagem Final (Texto Puro)
    corpo_final = f"""☕ RELATÓRIO DIÁRIO - NOSSO CAFÉ
Dados de: {ontem_str} ({nome_dia})

{comparativo_texto}

📊 ANÁLISE DO CFO:
{relatorio_ia}

---
Gerado automaticamente.
"""
        
    enviar_email_texto(f"Relatório Diário Nosso Café - {ontem_str}", corpo_final)
    cur.close()
    conn.close()

if __name__ == "__main__":
    job_completo()
