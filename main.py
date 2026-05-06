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

# Importação do novo SDK
import google.genai as genai

load_dotenv()

# Configurações
SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PWD = os.getenv("GMAIL_APP_PWD")
DESTINATARIOS_RAW = os.getenv("DESTINATARIO", "")

def obter_comparativo_mtd(cursor):
    ontem = datetime.now() - timedelta(days=1)
    dia_fechamento = ontem.day
    
    # Cálculos de datas para os 3 meses
    inicio_atual = ontem.replace(day=1).strftime('%Y-%m-%d')
    fim_atual = ontem.strftime('%Y-%m-%d')
    
    mes_anterior_dt = (ontem.replace(day=1) - timedelta(days=1))
    inicio_ant = mes_anterior_dt.replace(day=1).strftime('%Y-%m-%d')
    # Proteção para meses com dias diferentes (ex: comparar dia 31 com mês de 30 dias)
    ultimo_dia_ant = calendar.monthrange(mes_anterior_dt.year, mes_anterior_dt.month)[1]
    dia_fim_ant = min(dia_fechamento, ultimo_dia_ant)
    fim_ant = mes_anterior_dt.replace(day=dia_fim_ant).strftime('%Y-%m-%d')
    
    mes_retrasado_dt = (mes_anterior_dt.replace(day=1) - timedelta(days=1))
    inicio_retr = mes_retrasado_dt.replace(day=1).strftime('%Y-%m-%d')
    ultimo_dia_retr = calendar.monthrange(mes_retrasado_dt.year, mes_retrasado_dt.month)[1]
    dia_fim_retr = min(dia_fechamento, ultimo_dia_retr)
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

    v_ant, v_retr = calc_var(t_atual, t_ant), calc_var(t_atual, t_retr)
    s_ant = "🟢 ↑" if v_ant >= 0 else "🔴 ↓"
    s_retr = "🟢 ↑" if v_retr >= 0 else "🔴 ↓"

    return f"""
    <div style="border: 2px solid #8B4513; padding: 15px; border-radius: 10px; margin-bottom: 20px; font-family: sans-serif;">
        <h3 style="color: #8B4513; margin-top: 0;">📈 Comparativo MTD (Até dia {dia_fechamento})</h3>
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="background-color: #f2f2f2;">
                <th style="padding: 8px; border-bottom: 1px solid #ddd; text-align: left;">Mês</th>
                <th style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">Total</th>
                <th style="padding: 8px; border-bottom: 1px solid #ddd; text-align: center;">%</th>
            </tr>
            <tr>
                <td style="padding: 8px;">{ontem.strftime('%b/%y')}</td>
                <td style="padding: 8px; text-align: right;"><b>R$ {t_atual:,.2f}</b></td>
                <td style="padding: 8px; text-align: center;">-</td>
            </tr>
            <tr>
                <td style="padding: 8px;">{mes_anterior_dt.strftime('%b/%y')}</td>
                <td style="padding: 8px; text-align: right;">R$ {t_ant:,.2f}</td>
                <td style="padding: 8px; text-align: center; color: {'green' if v_ant >=0 else 'red'};"><b>{v_ant:+.1f}% {s_ant}</b></td>
            </tr>
            <tr>
                <td style="padding: 8px;">{mes_retrasado_dt.strftime('%b/%y')}</td>
                <td style="padding: 8px; text-align: right;">R$ {t_retr:,.2f}</td>
                <td style="padding: 8px; text-align: center; color: {'green' if v_retr >=0 else 'red'};"><b>{v_retr:+.1f}% {s_retr}</b></td>
            </tr>
        </table>
    </div>
    """

def extrair_forma_pagamento(venda):
    pagamentos = venda.get('payments', [])
    if not pagamentos: return "Não Informado"
    return pagamentos[0].get('payment_method_name', 'Outros')

def enviar_email(assunto, corpo_html):
    if not DESTINATARIOS_RAW: 
        print("Erro: Variável DESTINATARIO não configurada.")
        return
    
    lista_emails = [e.strip() for e in DESTINATARIOS_RAW.split(',')]
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = ", ".join(lista_emails)
    msg['Subject'] = assunto
    msg.attach(MIMEText(corpo_html, 'html'))

    try:
        # Usando a porta 465 (SSL) que é mais estável no GitHub Actions
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PWD)
            server.send_message(msg)
            print("E-mail enviado com sucesso!")
    except Exception as e:
        print(f"Erro fatal ao enviar e-mail: {e}")

def calcular_meta_dinamica(cursor, data_analise):
    br_holidays = holidays.Brazil()
    is_feriado_fds = data_analise.weekday() >= 5 or data_analise in br_holidays
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
    media_historica = float(resultado) if resultado else (1800.0 if is_feriado_fds else 1200.0)
    return round(media_historica * 1.025, 2)

def job_completo():
    ontem_dt = datetime.now() - timedelta(days=1)
    ontem_str = ontem_dt.strftime("%Y-%m-%d")
    dia_semana_pt = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 4: "Sexta", 5: "Sábado", 6: "Domingo"}
    nome_dia = dia_semana_pt[ontem_dt.weekday()]
    
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # --- 1. SYNC SAIPOS ---
    url = "https://data.saipos.io/v1/search_sales_v3"
    headers = {"Authorization": f"Bearer {SAIPOS_TOKEN}", "Accept": "application/json"}
    params = {
        "p_date_column_filter": "shift_date", 
        "p_filter_date_start": f"{ontem_str}T00:00:00", 
        "p_filter_date_end": f"{ontem_str}T23:59:59"
    }
    
    r = requests.get(url, headers=headers, params=params)
    vendas = r.json() if r.status_code == 200 else []
    
    for v in vendas:
        if v.get('canceled') == 'Y': continue
        forma = extrair_forma_pagamento(v)
        cur.execute("""
            INSERT INTO vendas (id_venda, data_venda, valor_total, forma_pagamento)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id_venda) DO UPDATE SET 
                valor_total = EXCLUDED.valor_total,
                forma_pagamento = EXCLUDED.forma_pagamento;
        """, (v.get('id_sale'), v.get('created_at'), v.get('total_amount'), forma))
    conn.commit()

    # --- 2. MÉTRICAS E MTD (ETAPA 2) ---
    html_comparativo_mtd = obter_comparativo_mtd(cur) # <-- CHAMADA DA ETAPA 2
    
    meta_hoje = calcular_meta_dinamica(cur, ontem_dt.date())
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE data_venda::date = %s", (ontem_str,))
    venda_dia = float(cur.fetchone()[0] or 0)

    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE date_trunc('month', data_venda) = date_trunc('month', %s::date)", (ontem_str,))
    acumulado_mes = float(cur.fetchone()[0] or 0)

    dia_atual = ontem_dt.day
    media_diaria_mes = acumulado_mes / dia_atual
    ultimo_dia = calendar.monthrange(ontem_dt.year, ontem_dt.month)[1]
    projecao_final = media_diaria_mes * ultimo_dia
    
    # --- 3. PROMPT PARA IA ---
    texto_prompt = f"""
    Aja como CFO do 'Nosso Café'. Relatório para Marcela e Natali.
    Analise {ontem_str} ({nome_dia}):
    - VENDA REAL: R${venda_dia:.2f} | META: R${meta_hoje:.2f}
    - ACUMULADO MÊS: R${acumulado_mes:.2f} | PROJEÇÃO: R${projecao_final:.2f}
    Analise se a projeção atende ao crescimento de 2.5% MTD. Seja direto e executivo.
    """
    
    # --- 4. EXECUÇÃO IA ---
    relatorio_ia = ""
    try:
        client = genai.Client(api_key=GEMINI_KEY.strip())
        modelos = [m.name for m in client.models.list()]
        preferencia = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-3-flash']
        
        for p in preferencia:
            for m in modelos:
                if p in m:
                    try:
                        response = client.models.generate_content(model=m, contents=texto_prompt)
                        if response.text:
                            relatorio_ia = response.text.replace('\n', '<br>') # Formata quebras para HTML
                            break
                    except: continue
            if relatorio_ia: break
    except: pass

    if not relatorio_ia:
        relatorio_ia = f"Venda: R${venda_dia:.2f} | Meta: R${meta_hoje:.2f}<br>Projeção: R${projecao_final:.2f}"

    # --- 5. MONTAGEM FINAL DO E-MAIL (HTML) ---
    corpo_final = f"""
    <html>
    <body style="font-family: sans-serif; line-height: 1.6;">
        <h2 style="color: #8B4513;">☕ Relatório Diário - Nosso Café</h2>
        <p>Dados referentes a <b>{ontem_str} ({nome_dia})</b></p>
        
        {html_comparativo_mtd}
        
        <div style="background: #fefefe; border-left: 5px solid #8B4513; padding: 15px; margin-top: 20px;">
            {relatorio_ia}
        </div>
        
        <p style="font-size: 11px; color: #888; margin-top: 30px;">
            Gerado automaticamente via Gestão de Dados Nosso Café.
        </p>
    </body>
    </html>
    """
        
    enviar_email(f"Relatório Diário Nosso Café - {ontem_str}", corpo_final)
    cur.close()
    conn.close()

if __name__ == "__main__":
    job_completo()
