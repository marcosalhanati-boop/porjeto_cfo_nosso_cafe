import os
import psycopg2
from datetime import datetime, timedelta
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
# Configure sua chave do AI Studio (Gemini)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def obter_metricas_nosso_cafe():
    conn = psycopg2.connect(os.getenv("SUPABASE_DB_URL"))
    cur = conn.cursor()
    
    hoje = datetime.now().date()
    ontem = hoje - timedelta(days=1)
    is_fds_ou_feriado = ontem.weekday() >= 5 # Simplificado: Sáb=5, Dom=6
    meta = 1800.0 if is_fds_ou_feriado else 1200.0
    
    # 1. Venda de Ontem
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE data_venda::date = %s", (ontem,))
    venda_ontem = cur.fetchone()[0] or 0.0
    
    # 2. Acumulado do Mês
    cur.execute("SELECT SUM(valor_total) FROM vendas WHERE date_trunc('month', data_venda) = date_trunc('month', %s::date)", (ontem,))
    acumulado_mes = cur.fetchone()[0] or 0.0
    
    # 3. Média das últimas 4 semanas (mesmo dia da semana)
    cur.execute("""
        SELECT AVG(diario.total) FROM (
            SELECT SUM(valor_total) as total FROM vendas 
            WHERE extract(dow from data_venda) = extract(dow from %s::date)
            AND data_venda::date < %s
            GROUP BY data_venda::date
            ORDER BY data_venda::date DESC LIMIT 4
        ) diario
    """, (ontem, ontem))
    media_4_semanas = cur.fetchone()[0] or 0.0
    
    conn.close()
    return venda_ontem, acumulado_mes, media_4_semanas, meta, ontem

def gerar_texto_analitico(venda, acumulado, media, meta, data):
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    Você é o analista de dados do 'Nosso Café'. 
    Escreva um e-mail curto e profissional para o dono (Marcos) analisando os dados de {data}:
    - Venda do dia: R${venda:.2f} (Meta: R${meta:.2f})
    - Acumulado do mês: R${acumulado:.2f}
    - Média das últimas 4 semanas para este mesmo dia da semana: R${media:.2f}
    
    Se a venda superou a meta, parabenize a equipe. Se ficou abaixo, sugira um foco em vendas sugestivas. 
    Use um tom motivador e direto.
    """
    
    response = model.generate_content(prompt)
    return response.text

# Aqui você integraria com uma biblioteca de e-mail (como smtplib)
# ou apenas imprimiria o resultado no log do GitHub Actions