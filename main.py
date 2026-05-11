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

def extrair_forma_pagamento(venda):
    pagamentos = venda.get('payments', [])
    if not pagamentos:
        return "Não Informado"
    return pagamentos[0].get('payment_method_name', 'Outros')

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

def obter_comparativo_mtd(cursor):
    ontem = datetime.now() - timedelta(days=1)
    dia_fechamento = ontem.day
    
    # Cálculos de datas para os 3 meses
    inicio_atual = ontem.replace(day=1).strftime('%Y-%m-%d')
    fim_atual = ontem.strftime('%Y-%m-%d')
    
    mes_anterior_dt = (ontem.replace(day=1) - timedelta(days=1))
    inicio_ant = mes_anterior_dt.replace(day=1).strftime('%Y-%m-%d')
    fim_ant = mes_anterior_dt.replace(day=dia_fechamento).strftime('%Y-%m-%d')
    
    mes_retrasado_dt = (mes_anterior_dt.replace(day=1) - timedelta(days=1))
    inicio_retr = mes_retrasado_dt.replace(day=1).strftime('%Y-%m-%d')
    fim_retr = mes_retrasado_dt.replace(day=dia_fechamento).strftime('%Y-%m-%d')

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

    # MUDANÇA AQUI: Criar a string de retorno
    texto_comparativo = (
        f"Mês Atual (até dia {ontem.day}): R${t_atual:.2f}\n"
        f"Mês Anterior (mesmo período): R${t_ant:.2f} ({s_ant} {v_ant:.1f}%)\n"
        f"Mês Retrasado (mesmo período): R${t_retr:.2f} ({s_retr} {v_retr:.1f}%)"
    )
    return texto_comparativo # Importante!

def calcular_meta_dinamica(cursor, data_analise):
    """
    Calcula a meta baseada na média dos últimos 3 meses para o mesmo dia da semana,
    aplicando um crescimento de 2.5%.
    """
    br_holidays = holidays.Brazil()
    is_feriado_fds = data_analise.weekday() >= 5 or data_analise in br_holidays
    dia_semana = data_analise.weekday()
    
    # Busca a média do mesmo dia da semana nos últimos 90 dias
    query = """
        SELECT AVG(total_dia) FROM (
            SELECT data_venda::date, SUM(valor_total) as total_dia
            FROM vendas
            WHERE data_venda::date < %s 
            AND data_venda::date >= %s - INTERVAL '90 days'
            AND extract(dow from data_venda) = %s
            GROUP BY data_venda::date
        ) as historico
    """
    
    cursor.execute(query, (data_analise, data_analise, dia_semana))
    resultado = cursor.fetchone()[0]
    
    # Se não houver histórico suficiente, usa um fallback seguro
    media_historica = float(resultado) if resultado else (1800.0 if is_feriado_fds else 1200.0)
    
    # Aplica crescimento de 2.5%
    meta_sugerida = media_historica * 1.025
    return round(meta_sugerida, 2)

def job_completo():
    # 1. Datas
    ontem_dt = datetime.now() - timedelta(days=1)
    ontem_str = ontem_dt.strftime("%Y-%m-%d")
    dia_semana_pt = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 4: "Sexta", 5: "Sábado", 6: "Domingo"}
    nome_dia = dia_semana_pt[ontem_dt.weekday()]
    print(f"--- Iniciando Processamento: {ontem_str} ({nome_dia}) ---")

    # --- 2. SYNC SAIPOS -> SUPABASE (Com Forma de Pagamento) ---
    url = "https://data.saipos.io/v1/search_sales_v3"
    headers = {"Authorization": f"Bearer {SAIPOS_TOKEN}", "Accept": "application/json"}
    params = {
        "p_date_column_filter": "shift_date", 
        "p_filter_date_start": f"{ontem_str}T00:00:00", 
        "p_filter_date_end": f"{ontem_str}T23:59:59"
    }
    
    # ESTA É A LINHA QUE ESTAVA FALTANDO:
    r = requests.get(url, headers=headers, params=params)
    
    vendas = r.json() if r.status_code == 200 else []
    
    conn = psycopg2.connect(DB_URL)
    with conn.cursor() as cur:
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
    # --- 3. MÉTRICAS E NOVA META ---
    cur = conn.cursor()
    meta_hoje = calcular_meta_dinamica(cur, ontem_dt.date())
    
    # Venda do dia
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE data_venda::date = %s", (ontem_str,))
    venda_dia = float(cur.fetchone()[0] or 0)

    # Acumulado do mês
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE date_trunc('month', data_venda) = date_trunc('month', %s::date)", (ontem_str,))
    acumulado_mes = float(cur.fetchone()[0] or 0)

    # Acumulado do Ano (YTD)
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE date_trunc('year', data_venda) = date_trunc('year', %s::date)", (ontem_str,))
    acumulado_ano = float(cur.fetchone()[0] or 0)

    # Projeção
    dia_atual = ontem_dt.day
    media_diaria_mes = acumulado_mes / dia_atual
    ultimo_dia = calendar.monthrange(ontem_dt.year, ontem_dt.month)[1]
    projecao_final = media_diaria_mes * ultimo_dia

    # Busca o comparativo MTD
    bloco_comparativo_html = obter_comparativo_mtd(cur)
    
    # --- 4. ANÁLISE IA PARA GESTÃO (Marcela e Natali) ---
    texto_prompt = f"""
    Aja como Diretor financeiro do 'Nosso Café'. O relatório é para as gestoras Marcela e Natali.
    Analise os resultados de {ontem_str} ({nome_dia}):
    
    - VENDA REAL: R${venda_dia:.2f}
    - META CALCULADA (Histórico + 2.5%): R${meta_hoje:.2f}
    - PERFORMANCE: {'✅ ACIMA DA META' if venda_dia >= meta_hoje else '❌ ABAIXO DA META'}
    - SUPERÁVIT/DÉFICIT: R${venda_dia - meta_hoje:.2f}
    
    - ACUMULADO MÊS: R${acumulado_mes:.2f}
    - ACUMULADO ANO: R${acumulado_ano:.2f}
    - PROJEÇÃO FINAL: R${projecao_final:.2f}
    - COMPARATIVO DE PERÍODOS ANTERIORES:
    {bloco_comparativo_html}  <-- Agora a variável será inserida aqui

    Diretrizes:
    1. Foque em análise financeira e estratégica.
    2. Comente se a projeção de R${projecao_final:.2f} atende às expectativas de crescimento.
    3. Informe o R${acumulado_ano:.2f} e seu crescimento.
    4. Mencione a equipe brevemente apenas se o resultado for excepcional.
    5. Seja direto, executivo e profissional.
    """
    
    # ... (segue o código do loop de modelos da IA que já está funcionando) ...

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
Meta: R${meta_hoje:.2f} (Superávit: R${venda_dia - meta_hoje:.2f})

📊 **INDICADORES MENSAIS**
Acumulado: R${acumulado_mes:.2f}
Acumulado Ano: R${acumulado_ano:.2f}
Média Diária: R${media_diaria_mes:.2f}
Projeção Final: R${projecao_final:.2f}

Nota: O sistema de IA (CFO) está em manutenção, mas os números acima são oficiais.
"""
        
    enviar_email(f"Relatório Diário Nosso Café - {ontem_str}", relatorio_ia)

if __name__ == "__main__":
    job_completo()
