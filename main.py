import os
import requests
import psycopg2
import smtplib
import calendar
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import google.genai as genai

load_dotenv()

# Pegando variáveis de ambiente
SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PWD = os.getenv("GMAIL_APP_PWD")
DESTINATARIOS_RAW = os.getenv("DESTINATARIO", "")

def enviar_email_debug(assunto, corpo):
    print("Tentando enviar e-mail...")
    if not DESTINATARIOS_RAW:
        print("Erro: A variável DESTINATARIO está vazia!")
        return
    
    lista_emails = [e.strip() for e in DESTINATARIOS_RAW.split(',')]
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = ", ".join(lista_emails)
    msg['Subject'] = assunto
    msg.attach(MIMEText(corpo, 'plain'))
    
    try:
        # Usando porta 587 + starttls (Configuração padrão que funcionava antes)
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PWD)
        server.sendmail(GMAIL_USER, lista_emails, msg.as_string())
        server.quit()
        print("E-mail enviado com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar e-mail: {str(e)}")

def job_completo():
    try:
        # 1. Configuração de Datas
        ontem_dt = datetime.now() - timedelta(days=1)
        ontem_str = ontem_dt.strftime("%Y-%m-%d")
        print(f"Iniciando relatório para: {ontem_str}")

        # 2. Conexão Banco
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        print("Conectado ao Supabase.")

        # 3. Busca Venda do Dia
        cur.execute("SELECT SUM(valor_total) FROM vendas WHERE data_venda::date = %s", (ontem_str,))
        venda_dia = float(cur.fetchone()[0] or 0)
        print(f"Venda encontrada: R$ {venda_dia}")

        # 4. Busca Acumulado Mês
        cur.execute("SELECT SUM(valor_total) FROM vendas WHERE date_trunc('month', data_venda) = date_trunc('month', %s::date)", (ontem_str,))
        acumulado_mes = float(cur.fetchone()[0] or 0)
        print(f"Acumulado mês: R$ {acumulado_mes}")

        # 5. Tentativa com IA (Se falhar, não trava o código)
        relatorio_ia = "Análise automática temporariamente indisponível."
        try:
            print("Chamando Gemini...")
            client = genai.Client(api_key=GEMINI_KEY.strip())
            prompt = f"Relatório Nosso Café {ontem_str}. Venda: R${venda_dia:.2f}. Acumulado: R${acumulado_mes:.2f}. Faça um comentário rápido e executivo."
            response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
            if response.text:
                relatorio_ia = response.text
                print("IA respondeu com sucesso.")
        except Exception as e_ia:
            print(f"Aviso: IA falhou, mas seguiremos com o e-mail. Erro: {e_ia}")

        # 6. Montagem do Texto
        corpo = f"""☕ RELATÓRIO DIÁRIO - NOSSO CAFÉ
Data: {ontem_str}

RESUMO FINANCEIRO:
Venda Ontem: R$ {venda_dia:,.2f}
Acumulado Mês: R$ {acumulado_mes:,.2f}

ANÁLISE DO CFO:
{relatorio_ia}

---
Gerado automaticamente.
"""

        # 7. Envio
        enviar_email_debug(f"Relatório Diário Nosso Café - {ontem_str}", corpo)

        cur.close()
        conn.close()

    except Exception as e_geral:
        print(f"ERRO CRÍTICO NO SCRIPT: {str(e_geral)}")

if __name__ == "__main__":
    job_completo()
