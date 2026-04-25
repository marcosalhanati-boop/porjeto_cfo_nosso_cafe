import os
import psycopg2
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage

load_dotenv()

def gerar_fechamento():
    conn = psycopg2.connect(os.getenv("SUPABASE_DB_URL"))
    
    # Define o período do mês anterior
    hoje = datetime.now()
    primeiro_dia_mes_atual = hoje.replace(day=1)
    ultimo_dia_mes_passado = primeiro_dia_mes_atual - timedelta(days=1)
    primeiro_dia_mes_passado = ultimo_dia_mes_passado.replace(day=1)
    
    mes_nome = primeiro_dia_mes_passado.strftime('%B/%Y')

    # 1. Busca dados do banco
    query = """
        SELECT data_venda::date, valor_total, forma_pagamento 
        FROM vendas 
        WHERE data_venda >= %s AND data_venda <= %s
    """
    df = pd.read_sql(query, conn, params=(primeiro_dia_mes_passado, ultimo_dia_mes_passado))
    
    if df.empty:
        print("Nenhuma venda encontrada para o fechamento.")
        return

    # 2. Análise Financeira
    faturamento_total = df['valor_total'].sum()
    ticket_medio = df['valor_total'].mean()
    top_formas = df.groupby('forma_pagamento')['valor_total'].sum().sort_values(ascending=False)

    # 3. Evolução Semanal (Gráfico)
    df['data_venda'] = pd.to_datetime(df['data_venda'])
    df_semanal = df.resample('W-MON', on='data_venda')['valor_total'].sum()
    
    plt.figure(figsize=(10, 6))
    df_semanal.plot(kind='line', marker='o', color='#8B4513', linewidth=2)
    plt.title(f'Evolução Semanal de Faturamento - {mes_nome}')
    plt.ylabel('Faturamento (R$)')
    plt.xlabel('Semana (Início na Segunda)')
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()
    
    grafico_path = 'faturamento_semanal.png'
    plt.savefig(grafico_path)
    plt.close()

    # 4. Composição do E-mail
    corpo_email = f"""
    <html>
    <body>
        <h2>📊 FECHAMENTO MENSAL - NOSSO CAFÉ ({mes_nome})</h2>
        <p>Olá Marcela e Natali, segue o resumo estratégico do mês encerrado:</p>
        <ul>
            <li><b>Faturamento Total:</b> R$ {faturamento_total:,.2f}</li>
            <li><b>Ticket Médio:</b> R$ {ticket_medio:,.2f}</li>
            <li><b>Forma de Pagamento Principal:</b> {top_formas.index[0]} (R$ {top_formas.iloc[0]:,.2f})</li>
        </ul>
        <p>O gráfico abaixo detalha a performance semana a semana:</p>
        <img src="cid:image1">
        <br>
        <p>Este relatório foi gerado automaticamente pelo CFO Digital.</p>
    </body>
    </html>
    """
    
    enviar_email_com_grafico(f"Fechamento Estratégico: {mes_nome}", corpo_email, grafico_path)

def enviar_email_com_grafico(assunto, corpo, imagem_path):
    msg = MIMEMultipart('related')
    msg['Subject'] = assunto
    msg['From'] = os.getenv("GMAIL_USER")
    msg['To'] = os.getenv("DESTINATARIO")

    msg_html = MIMEText(corpo, 'html')
    msg.attach(msg_html)

    with open(imagem_path, 'rb') as f:
        img = MIMEImage(f.read())
        img.add_header('Content-ID', '<image1>')
        msg.attach(img)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(os.getenv("GMAIL_USER"), os.getenv("GMAIL_APP_PWD"))
        server.send_message(msg)

if __name__ == "__main__":
    gerar_fechamento()
