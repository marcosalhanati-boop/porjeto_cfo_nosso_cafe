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

# Carrega variáveis de ambiente (.env ou Secrets do GitHub)
load_dotenv()

def gerar_fechamento_mensal():
    # 1. Configuração de Datas (Mês Anterior)
    hoje = datetime.now()
    primeiro_dia_mes_atual = hoje.replace(day=1)
    ultimo_dia_mes_passado = primeiro_dia_mes_atual - timedelta(days=1)
    primeiro_dia_mes_passado = ultimo_dia_mes_passado.replace(day=1)
    
    mes_nome = primeiro_dia_mes_passado.strftime('%B/%Y')
    inicio_str = primeiro_dia_mes_passado.strftime('%Y-%m-%d')
    fim_str = ultimo_dia_mes_passado.strftime('%Y-%m-%d')

    conn = psycopg2.connect(os.getenv("SUPABASE_DB_URL"))
    cur = conn.cursor()

    try:
        # 2. Análise Financeira (Vendas)
        query_financeiro = """
            SELECT data_venda::date, valor_total, forma_pagamento 
            FROM vendas 
            WHERE data_venda >= %s AND data_venda <= %s
        """
        df_financeiro = pd.read_sql(query_financeiro, conn, params=(inicio_str, fim_str))
        
        if df_financeiro.empty:
            print(f"Sem dados financeiros para {mes_nome}")
            return

        faturamento_total = df_financeiro['valor_total'].sum()
        ticket_medio = df_financeiro['valor_total'].mean()

        # 3. Análise de Mix de Produtos (Top 5 e Bottom 5)
        # Mais vendidos
        cur.execute("""
            SELECT produto, SUM(quantidade) as total 
            FROM itens_venda 
            WHERE data_venda >= %s AND data_venda <= %s
            GROUP BY produto 
            ORDER BY total DESC 
            LIMIT 5
        """, (inicio_str, fim_str))
        mais_vendidos = cur.fetchall()

        # Menos vendidos
        cur.execute("""
            SELECT produto, SUM(quantidade) as total 
            FROM itens_venda 
            WHERE data_venda >= %s AND data_venda <= %s
            GROUP BY produto 
            ORDER BY total ASC 
            LIMIT 5
        """, (inicio_str, fim_str))
        menos_vendidos = cur.fetchall()

        # 4. Geração do Gráfico de Evolução Semanal
        df_financeiro['data_venda'] = pd.to_datetime(df_financeiro['data_venda'])
        df_semanal = df_financeiro.resample('W-MON', on='data_venda')['valor_total'].sum()
        
        plt.figure(figsize=(10, 5))
        df_semanal.plot(kind='line', marker='o', color='#8B4513', linewidth=2)
        plt.title(f'Evolução Semanal de Faturamento - {mes_nome}')
        plt.ylabel('Faturamento (R$)')
        plt.grid(True, linestyle='--', alpha=0.6)
        plt.tight_layout()
        
        grafico_path = 'faturamento_mensal.png'
        plt.savefig(grafico_path)
        plt.close()

        # 5. Montagem do Corpo do E-mail (HTML)
        texto_mais = "".join([f"<li>{p[0]}: {int(p[1])} unid.</li>" for p in mais_vendidos])
        texto_menos = "".join([f"<li>{p[0]}: {int(p[1])} unid.</li>" for p in menos_vendidos])

        corpo_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2 style="color: #8B4513;">📊 FECHAMENTO MENSAL - NOSSO CAFÉ</h2>
            <p>Olá Marcela e Natali, aqui está a análise estratégica de <b>{mes_nome}</b>:</p>
            
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;"><b>Faturamento Total:</b></td>
                    <td style="padding: 10px; border: 1px solid #ddd;">R$ {faturamento_total:,.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;"><b>Ticket Médio:</b></td>
                    <td style="padding: 10px; border: 1px solid #ddd;">R$ {ticket_medio:,.2f}</td>
                </tr>
            </table>

            <h3 style="color: #2e7d32;">🏆 Campeões de Venda (Top 5)</h3>
            <ul>{texto_mais}</ul>

            <h3 style="color: #c62828;">⚠️ Baixa Saída (Atenção)</h3>
            <ul>{texto_menos}</ul>

            <h3>📈 Evolução Semanal</h3>
            <p>O gráfico abaixo mostra o comportamento do faturamento ao longo do mês:</p>
            <img src="cid:grafico_mensal" style="width: 100%; max-width: 600px;">
            
            <p style="font-size: 12px; color: #777; margin-top: 20px;">
                Relatório gerado automaticamente pelo Sistema de Gestão de Dados - Nosso Café.
            </p>
        </body>
        </html>
        """

        enviar_email(f"Fechamento Estratégico: {mes_nome}", corpo_html, grafico_path)
        print(f"Relatório de {mes_nome} enviado com sucesso!")

    except Exception as e:
        print(f"Erro ao gerar fechamento: {e}")
    finally:
        cur.close()
        conn.close()

def enviar_email(assunto, html, imagem_path):
    msg = MIMEMultipart('related')
    msg['Subject'] = assunto
    msg['From'] = os.getenv("GMAIL_USER")
    msg['To'] = os.getenv("DESTINATARIO") # Pode ser uma string com emails separados por vírgula

    msg.attach(MIMEText(html, 'html'))

    with open(imagem_path, 'rb') as f:
        img = MIMEImage(f.read())
        img.add_header('Content-ID', '<grafico_mensal>')
        msg.attach(img)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(os.getenv("GMAIL_USER"), os.getenv("GMAIL_APP_PWD"))
        server.send_message(msg)

if __name__ == "__main__":
    gerar_fechamento_mensal()

if __name__ == "__main__":
    gerar_fechamento()
