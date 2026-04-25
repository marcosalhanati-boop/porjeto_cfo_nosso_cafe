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

def gerar_fechamento_mensal_completo():
    # 1. Datas (Mês Anterior)
    hoje = datetime.now()
    primeiro_dia_mes_atual = hoje.replace(day=1)
    ultimo_dia_mes_passado = primeiro_dia_mes_atual - timedelta(days=1)
    primeiro_dia_mes_passado = ultimo_dia_mes_passado.replace(day=1)
    
    mes_nome = primeiro_dia_mes_passado.strftime('%B/%Y')
    inicio = primeiro_dia_mes_passado.strftime('%Y-%m-%d')
    fim = ultimo_dia_mes_passado.strftime('%Y-%m-%d')

    conn = psycopg2.connect(os.getenv("SUPABASE_DB_URL"))
    cur = conn.cursor()

    try:
        # 2. Dados Financeiros
        query_fin = "SELECT valor_total FROM vendas WHERE data_venda >= %s AND data_venda <= %s"
        df_fin = pd.read_sql(query_fin, conn, params=(inicio, fim))
        faturamento_total = df_fin['valor_total'].sum()
        ticket_medio = df_fin['valor_total'].mean()

        # 3. Top 10 Mais Vendidos
        cur.execute("""
            SELECT produto, SUM(quantidade) as qtd, SUM(valor_total_item) as receita
            FROM itens_venda 
            WHERE data_venda >= %s AND data_venda <= %s
            GROUP BY produto 
            ORDER BY qtd DESC 
            LIMIT 10
        """, (inicio, fim))
        top_10 = cur.fetchall()

        # 4. 10 Menos Vendidos (Atenção)
        cur.execute("""
            SELECT produto, SUM(quantidade) as qtd
            FROM itens_venda 
            WHERE data_venda >= %s AND data_venda <= %s
            GROUP BY produto 
            ORDER BY qtd ASC 
            LIMIT 10
        """, (inicio, fim))
        bottom_10 = cur.fetchall()

        # 5. Formatação das listas para HTML
        html_top = "".join([
            f"<tr><td>{i+1}º {p[0]}</td><td style='text-align:center;'>{int(p[1])}</td><td>R$ {p[2]:,.2f}</td></tr>" 
            for i, p in enumerate(top_10)
        ])
        
        html_bottom = "".join([
            f"<li>{p[0]} ({int(p[1])} unid.)</li>" for p in bottom_10
        ])

        # 6. Corpo do E-mail
        corpo_html = f"""
        <html>
        <body style="font-family: sans-serif; color: #333;">
            <h2 style="color: #8B4513;">📊 FECHAMENTO ESTRATÉGICO: {mes_nome}</h2>
            <p>Olá Marcela e Natali, segue a análise detalhada do <b>Nosso Café</b>:</p>
            
            <div style="background: #f9f9f9; padding: 15px; border-radius: 8px;">
                <b>Faturamento:</b> R$ {faturamento_total:,.2f}<br>
                <b>Ticket Médio:</b> R$ {ticket_medio:,.2f}
            </div>

            <h3 style="color: #2e7d32;">🏆 TOP 10 - OS QUERIDINHOS</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="background: #eee;">
                    <th style="text-align:left; padding: 8px;">Produto</th>
                    <th style="padding: 8px;">Qtd</th>
                    <th style="text-align:left; padding: 8px;">Receita</th>
                </tr>
                {html_top}
            </table>

            <h3 style="color: #c62828;">⚠️ 10 ITENS COM BAIXA SAÍDA</h3>
            <p style="font-size: 0.9em; color: #666;">Produtos que venderam menos e podem ser revisados no menu:</p>
            <ul>{html_bottom}</ul>

            <p style="margin-top: 20px;"><i>Insight: Analisar se os itens de baixa saída ocupam espaço de estoque desnecessário ou se precisam de uma ação promocional.</i></p>
        </body>
        </html>
        """

        # Envio do E-mail (Reutilizando sua função de envio)
        enviar_email(f"Relatório Mensal Nosso Café: {mes_nome}", corpo_html)
        print(f"Relatório de {mes_nome} enviado!")

    except Exception as e:
        print(f"Erro: {e}")
    finally:
        cur.close(); conn.close()

def enviar_email(assunto, html):
    msg = MIMEMultipart()
    msg['Subject'] = assunto
    msg['From'] = os.getenv("GMAIL_USER")
    msg['To'] = os.getenv("DESTINATARIO")
    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(os.getenv("GMAIL_USER"), os.getenv("GMAIL_APP_PWD"))
        server.send_message(msg)

if __name__ == "__main__":
    gerar_fechamento_mensal_completo()
