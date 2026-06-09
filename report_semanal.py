import os
import psycopg2
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

# Configurações do ambiente (Reaproveita as suas variáveis existentes)
DB_URL = os.getenv("SUPABASE_DB_URL")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PWD = os.getenv("GMAIL_APP_PWD")
DESTINATARIOS_RAW = os.getenv("DESTINATARIO", "")

def enviar_email_semanal_html(assunto, corpo_html):
    if not DESTINATARIOS_RAW:
        print("Erro: Nenhum destinatário configurado na variável DESTINATARIO.")
        return
    lista_emails = [e.strip() for e in DESTINATARIOS_RAW.split(',')]
    
    msg = MIMEMultipart('alternative')
    msg['From'] = GMAIL_USER
    msg['To'] = ", ".join(lista_emails)
    msg['Subject'] = assunto
    
    msg.attach(MIMEText(corpo_html, 'html', 'utf-8'))
            
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PWD)
            server.send_message(msg)
            print("E-mail semanal enviado com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")

def obter_top10_produtos_semanal(cursor):
    # Query inteligente usando Window Functions (DENSE_RANK) para calcular a consistência
    query = """
    WITH historico_vendas_semana AS (
        SELECT 
            date_trunc('week', data_venda) AS semana,
            forma_pagamento AS produto_nome, -- DICA: Mude para o campo do nome do produto caso use tabela de itens
            SUM(valor_total) AS faturamento_produto
        FROM vendas
        WHERE data_venda >= date_trunc('week', CURRENT_DATE) - INTERVAL '6 weeks'
          AND data_venda < date_trunc('week', CURRENT_DATE)
        GROUP BY semana, forma_pagamento
    ),
    ranking_semanal AS (
        SELECT 
            semana,
            produto_nome,
            faturamento_produto,
            DENSE_RANK() OVER (PARTITION BY semana ORDER BY faturamento_produto DESC) AS rank_posicao
        FROM historico_vendas_semana
    ),
    recorrencia_top10 AS (
        SELECT 
            produto_nome,
            COUNT(*) AS semanas_no_top10
        FROM ranking_semanal
        WHERE rank_posicao <= 10
        GROUP BY produto_nome
    )
    SELECT 
        r.produto_nome,
        r.faturamento_produto,
        COALESCE(rec.semanas_no_top10, 0) AS semanas_recorrentes
    FROM ranking_semanal r
    LEFT JOIN recorrencia_top10 rec ON r.produto_nome = rec.produto_nome
    WHERE r.semana = date_trunc('week', CURRENT_DATE) - INTERVAL '1 week'
      AND r.rank_posicao <= 10
    ORDER BY r.faturamento_produto DESC;
    """
    cursor.execute(query)
    return cursor.fetchall()

def executar_workflow_semanal():
    print("--- Iniciando Relatório Semanal de Mix de Vendas ---")
    
    if not DB_URL:
        print("Erro: SUPABASE_DB_URL não configurada.")
        return

    try:
        conn = psycopg2.connect(DB_URL)
        with conn.cursor() as cur:
            resultados = obter_top10_produtos_semanal(cur)
            
            if not resultados:
                print("Nenhum dado encontrado para a semana anterior.")
                return
                
            # Estruturação dinâmica das linhas do relatório em HTML
            linhas_tabela_html = ""
            for idx, (nome_prod, faturamento, semanas) in enumerate(resultados, 1):
                medalha = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}º"
                
                # Badges estilizadas para destacar consistência comercial
                if semanas >= 5:
                    status_tag = f'<span style="background-color: #e8f8f5; color: #27ae60; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: bold;">{semanas}/6 sem 🔥</span>'
                elif semanas == 1:
                    status_tag = f'<span style="background-color: #fef9e7; color: #f39c12; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: bold;">{semanas}/6 sem 🆕</span>'
                else:
                    status_tag = f'<span style="background-color: #f2f4f4; color: #7f8c8d; padding: 4px 10px; border-radius: 12px; font-size: 11px;">{semanas}/6 sem</span>'
                
                linhas_tabela_html += f"""
                <tr style="border-bottom: 1px solid #f1f1f1;">
                    <td style="padding: 12px; text-align: center; font-weight: bold;">{medalha}</td>
                    <td style="padding: 12px; font-weight: bold; color: #2c3e50;">{nome_prod}</td>
                    <td style="padding: 12px; text-align: right; color: #27ae60; font-weight: bold;">R$ {faturamento:,.2f}</td>
                    <td style="padding: 12px; text-align: center;">{status_tag}</td>
                </tr>
                """
            
            hoje_str = datetime.now().strftime("%d/%m/%Y")
            
            # Layout do E-mail em HTML (Identidade visual elegante e limpa)
            corpo_html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9;">
                <div style="background-color: #ffffff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); border-top: 6px solid #6F4E37;">
                    <h2 style="color: #6F4E37; margin-top: 0; text-align: center; font-size: 22px;">🏆 MIX DE VENDAS & CONSISTÊNCIA</h2>
                    <p style="text-align: center; color: #7f8c8d; font-size: 14px;">Relatório Semanal Estratégico — {hoje_str}</p>
                    
                    <p>Olá, Gestão <strong>Nosso Café</strong>,</p>
                    <p>Aqui está o levantamento analítico dos <strong>Top 10 produtos mais vendidos</strong> da última semana fechada, cruzado com o histórico de consistência das últimas 6 semanas:</p>
                    
                    <table style="width: 100%; border-collapse: collapse; margin-top: 25px;">
                        <thead>
                            <tr style="background-color: #6F4E37; color: white;">
                                <th style="padding: 12px; border-top-left-radius: 4px; text-align: center;">Pos.</th>
                                <th style="padding: 12px; text-align: left;">Produto</th>
                                <th style="padding: 12px; text-align: right;">Caixa Gerado</th>
                                <th style="padding: 12px; text-align: center; border-top-right-radius: 4px;">No Top 10</th>
                            </tr>
                        </thead>
                        <tbody>
                            {linhas_tabela_html}
                        </tbody>
                    </table>
                    
                    <div style="background-color: #fdf6f0; border-left: 4px solid #e59866; padding: 15px; margin-top: 30px; border-radius: 4px; font-size: 13px; color: #6e4e37;">
                        <strong>💡 Notas de Análise de Padrão:</strong><br>
                        • <strong>Consistência Alta (5/6 ou 6/6 sem) 🔥:</strong> São os produtos principais da casa. Sustentam o faturamento de forma previsível.<br>
                        • <strong>Surgimento Novo (1/6 sem) 🆕:</strong> Indica picos sazonais, tração de campanhas ou novos hábitos que merecem atenção.
                    </div>
                    
                    <hr style="border: 0; border-top: 1px solid #eee; margin: 30px 0 20px 0;">
                    <p style="font-size: 11px; color: #999; text-align: center; margin-bottom: 0;">Controladoria Automatizada — Nosso Café Atibaia</p>
                </div>
            </body>
            </html>
            """
            
            enviar_email_semanal_html(f"[CFO] Top 10 Produtos & Consistência Semanal - {hoje_str}", corpo_html)
            
        conn.close()
    except Exception as e:
        print(f"Erro crítico no processamento semanal: {e}")

if __name__ == "__main__":
    executar_workflow_semanal()
