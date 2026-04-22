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

# MUDANÇA AQUI: Importação direta do novo SDK
import google.genai as genai

load_dotenv()

# Configurações
SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PWD = os.getenv("GMAIL_APP_PWD")
DESTINATARIOS_RAW = os.getenv("DESTINATARIO", "")

def enviar_email(assunto, corpo):
    if not DESTINATARIOS_RAW: return
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
    except Exception as e:
        print(f"Erro e-mail: {e}")

def obter_meta(data_analise):
    br_holidays = holidays.Brazil()
    if data_analise.weekday() >= 5 or data_analise in br_holidays:
        return 1800.0
    return 1200.0

def job_completo():
    # 1. Datas
    ontem_dt = datetime.now() - timedelta(days=1)
    ontem_str = ontem_dt.strftime("%Y-%m-%d")
    dia_semana_pt = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 4: "Sexta", 5: "Sábado", 6: "Domingo"}
    nome_dia = dia_semana_pt[ontem_dt.weekday()]
    print(f"--- Iniciando Processamento: {ontem_str} ({nome_dia}) ---")

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

    # 3. Métricas e Projeção
    cur = conn.cursor()
    meta = obter_meta(ontem_dt.date())
    
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE data_venda::date = %s", (ontem_str,))
    venda_dia = float(cur.fetchone()[0] or 0)

    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE date_trunc('month', data_venda) = date_trunc('month', %s::date)", (ontem_str,))
    acumulado_mes = float(cur.fetchone()[0] or 0)

    dia_atual = ontem_dt.day
    media_diaria_mes = acumulado_mes / dia_atual
    ultimo_dia = calendar.monthrange(ontem_dt.year, ontem_dt.month)[1]
    projecao_final = media_diaria_mes * ultimo_dia

    cur.execute("""
        SELECT AVG(total) FROM (
            SELECT SUM(valor_total) as total FROM vendas 
            WHERE extract(dow from data_venda) = extract(dow from %s::date)
            AND data_venda::date < %s GROUP BY data_venda::date ORDER BY data_venda::date DESC LIMIT 4
        ) t
    """, (ontem_str, ontem_str))
    media_4_semanas = float(cur.fetchone()[0] or 0)
    conn.close()

    # 4. Análise IA (Utilizando a nova biblioteca google-genai)
    texto_prompt = f"""
    Aja como CFO do 'Nosso Café'. Analise os resultados de {ontem_str} ({nome_dia}):
    - Venda Real: R${venda_dia:.2f} (Meta: R${meta:.2f})
    - Acumulado Mês: R${acumulado_mes:.2f}
    - Média Diária no Mês: R${media_diaria_mes:.2f}
    - Projeção Final do Mês: R${projecao_final:.2f}
    - Média das últimas 4 {nome_dia}s: R${media_4_semanas:.2f}

    Instruções: Comente o superávit, a projeção e elogie Bárbara, Laryssa, Marcela, Natali e Keity.
    """

    # --- 4. ANÁLISE COM GEMINI (PROTOCOLO DE TENTATIVA SIMPLIFICADO) ---
    relatorio_ia = ""
    try:
        client = genai.Client(api_key=GEMINI_KEY.strip())
        
        # 1. Busca os nomes de todos os modelos disponíveis sem filtrar por atributos
        # Em 2026, isso retorna uma lista de objetos onde o .name é o ID que precisamos
        modelos_disponiveis = [m.name for m in client.models.list()]
        print(f"Modelos encontrados na conta: {modelos_disponiveis}")

        # 2. Ordem de preferência (nossos "favoritos")
        preferencia = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-3-flash']
        
        # Reorganiza a fila: coloca os preferidos na frente, o resto depois
        fila_tentativa = []
        for p in preferencia:
            for m in modelos_disponiveis:
                if p in m: fila_tentativa.append(m)
        
        for m in modelos_disponiveis:
            if m not in fila_tentativa: fila_tentativa.append(m)

        # 3. Loop de execução
        for modelo_teste in fila_tentativa:
            try:
                print(f"Tentando: {modelo_teste}...")
                response = client.models.generate_content(
                    model=modelo_teste, 
                    contents=texto_prompt
                )
                if response and response.text:
                    relatorio_ia = response.text
                    print(f"Sucesso absoluto com: {modelo_teste}!")
                    break
            except Exception as e_mod:
                print(f"Modelo {modelo_teste} recusou: {e_mod}")
                continue

    except Exception as e_critico:
        print(f"Erro ao acessar API do Google: {e_critico}")

    # --- 4.1 FALLBACK FORMATADO (Mantido para segurança) ---
    if not relatorio_ia:
        relatorio_ia = f"""
🚀 **NOSSO CAFÉ - RELATÓRIO DE VENDAS**

Ontem ({nome_dia}): R${venda_dia:.2f}
Meta: R${meta:.2f} (Superávit: R${venda_dia - meta:.2f})

📊 **INDICADORES MENSAIS**
Acumulado: R${acumulado_mes:.2f}
Média Diária: R${media_diaria_mes:.2f}
Projeção Final: R${projecao_final:.2f}

Nota: O sistema de IA (CFO) está em manutenção, mas os números acima são oficiais.
"""
        
    enviar_email(f"Relatório Diário Nosso Café - {ontem_str}", relatorio_ia)

if __name__ == "__main__":
    job_completo()
