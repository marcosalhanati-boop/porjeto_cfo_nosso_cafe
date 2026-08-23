import os
import sys
import requests
import psycopg2
import holidays
import smtplib
import calendar
import time
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from dotenv import load_dotenv

# Novo SDK oficial do Google
import google.genai as genai

load_dotenv()

# Configurações
SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PWD = os.getenv("GMAIL_APP_PWD")
DESTINATARIOS_RAW = os.getenv("DESTINATARIO", "")

TZ_BR = ZoneInfo("America/Sao_Paulo")

MODELOS_PREFERENCIA = ['gemini-3.6-flash', 'gemini-3.7-flash', 'gemini-3.5-flash-lite']


def validar_configuracao():
    """ Garante que as variáveis de ambiente essenciais existem antes de rodar o job. """
    obrigatorias = {
        "SAIPOS_TOKEN": SAIPOS_TOKEN,
        "SUPABASE_DB_URL": DB_URL,
        "GEMINI_API_KEY": GEMINI_KEY,
        "GMAIL_USER": GMAIL_USER,
        "GMAIL_APP_PWD": GMAIL_APP_PWD,
    }
    faltando = [nome for nome, valor in obrigatorias.items() if not valor]
    if faltando:
        raise RuntimeError(
            f"Variáveis de ambiente obrigatórias ausentes: {', '.join(faltando)}. "
            "Verifique os secrets configurados no GitHub Actions / .env."
        )
    if not DESTINATARIOS_RAW:
        print("Aviso: nenhum DESTINATARIO configurado — o e-mail não será enviado.")


def extrair_forma_pagamento(venda):
    pagamentos = venda.get('payments', [])
    if not pagamentos:
        return "Não Informado"
    return pagamentos[0].get('payment_method_name', 'Outros')


def buscar_vendas_saipos(ontem_str, tentativas=3, espera_base=5):
    """ Busca vendas na API da Saipos com timeout, retry com backoff e tratamento de erro. """
    url = "https://data.saipos.io/v1/search_sales_v3"
    headers = {"Authorization": f"Bearer {SAIPOS_TOKEN}", "Accept": "application/json"}
    params = {
        "p_date_column_filter": "shift_date",
        "p_filter_date_start": f"{ontem_str}T00:00:00",
        "p_filter_date_end": f"{ontem_str}T23:59:59"
    }

    for tentativa in range(1, tentativas + 1):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            print(f"Timeout ao consultar a Saipos (tentativa {tentativa}/{tentativas}).")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            print(f"Erro HTTP {status} ao consultar a Saipos (tentativa {tentativa}/{tentativas}): {e}")
            if status is not None and status < 500:
                break
        except requests.exceptions.RequestException as e:
            print(f"Erro ao consultar a API da Saipos (tentativa {tentativa}/{tentativas}): {e}")

        if tentativa < tentativas:
            time.sleep(espera_base * tentativa)

    print("Falha ao obter vendas da Saipos após todas as tentativas. Prosseguindo sem novos dados de sync.")
    return []


def enviar_email_html_com_grafico(assunto, corpo_html, caminho_foto):
    if not DESTINATARIOS_RAW:
        return
    lista_emails = [e.strip() for e in DESTINATARIOS_RAW.split(',')]

    msg = MIMEMultipart('related')
    msg['From'] = GMAIL_USER
    msg['To'] = ", ".join(lista_emails)
    msg['Subject'] = assunto

    msg_html = MIMEText(corpo_html, 'html', 'utf-8')
    msg.attach(msg_html)

    if caminho_foto and os.path.exists(caminho_foto):
        with open(caminho_foto, 'rb') as f:
            img = MIMEImage(f.read())
            img.add_header('Content-ID', '<grafico>')
            img.add_header('Content-Disposition', 'inline', filename=caminho_foto)
            msg.attach(img)

    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=30) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PWD)
            server.send_message(msg)
            print("E-mail com gráfico enviado com sucesso!")
    except Exception as e:
        print(f"Erro e-mail: {e}")


def obter_datas_tres_meses(ontem_dt):
    """ Centraliza o cálculo das janelas de datas do mês atual, anterior e retrasado. """
    dia_fechamento = ontem_dt.day

    inicio_atual = ontem_dt.replace(day=1)
    fim_atual = ontem_dt

    mes_anterior_dt = (inicio_atual - timedelta(days=1))
    ultimo_dia_mes_ant = calendar.monthrange(mes_anterior_dt.year, mes_anterior_dt.month)[1]
    dia_fim_ant = min(dia_fechamento, ultimo_dia_mes_ant)
    inicio_ant = mes_anterior_dt.replace(day=1)
    fim_ant_mtd = mes_anterior_dt.replace(day=dia_fim_ant)
    fim_ant_completo = mes_anterior_dt.replace(day=ultimo_dia_mes_ant)

    mes_retrasado_dt = (inicio_ant - timedelta(days=1))
    ultimo_dia_mes_retr = calendar.monthrange(mes_retrasado_dt.year, mes_retrasado_dt.month)[1]
    dia_fim_retr = min(dia_fechamento, ultimo_dia_mes_retr)
    inicio_retr = mes_retrasado_dt.replace(day=1)
    fim_retr_mtd = mes_retrasado_dt.replace(day=dia_fim_retr)
    fim_retr_completo = mes_retrasado_dt.replace(day=ultimo_dia_mes_retr)

    return {
        "mes_anterior_dt": mes_anterior_dt,
        "mes_retrasado_dt": mes_retrasado_dt,
        "inicio_atual": inicio_atual, "fim_atual": fim_atual,
        "inicio_ant": inicio_ant, "fim_ant_mtd": fim_ant_mtd, "fim_ant_completo": fim_ant_completo,
        "inicio_retr": inicio_retr, "fim_retr_mtd": fim_retr_mtd, "fim_retr_completo": fim_retr_completo,
    }


def obter_comparativo_mtd_texto(cursor, datas):
    def buscar_total(ini, fim):
        cursor.execute(
            "SELECT SUM(valor_total) FROM vendas WHERE data_venda >= %s AND data_venda <= %s",
            (ini.strftime('%Y-%m-%d'), fim.strftime('%Y-%m-%d'))
        )
        res = cursor.fetchone()[0]
        return float(res) if res else 0.0

    t_atual = buscar_total(datas["inicio_atual"], datas["fim_atual"])
    t_ant = buscar_total(datas["inicio_ant"], datas["fim_ant_mtd"])
    t_retr = buscar_total(datas["inicio_retr"], datas["fim_retr_mtd"])

    def calc_var(atual, base):
        return ((atual - base) / base * 100) if base > 0 else 0

    v_ant = calc_var(t_atual, t_ant)
    v_retr = calc_var(t_atual, t_retr)

    dia_fechamento = datas["fim_atual"].day
    texto = f"📈 COMPARATIVO MTD (Acumulado até dia {dia_fechamento})\n"
    texto += f"------------------------------------------\n"
    texto += f"ESTE MÊS ({datas['fim_atual'].strftime('%b/%y')}): R$ {t_atual:,.2f}\n"
    texto += f"MÊS ANTERIOR ({datas['mes_anterior_dt'].strftime('%b/%y')}): R$ {t_ant:,.2f} ({v_ant:+.1f}% {'🟢 ↑' if v_ant >= 0 else '🔴 ↓'})\n"
    texto += f"MÊS RETRASADO ({datas['mes_retrasado_dt'].strftime('%b/%y')}): R$ {t_retr:,.2f} ({v_retr:+.1f}% {'🟢 ↑' if v_retr >= 0 else '🔴 ↓'})\n"
    texto += f"------------------------------------------\n"
    return texto


def gerar_grafico_acumulado(cursor, ontem_dt, datas):
    """
    Busca faturamento dia a dia dos 3 meses e plota:
    - Eixo esquerdo: valores acumulados em R$ (Mês Atual, Mês Anterior, Mês Retrasado e Meta)
    - Eixo direito: variação percentual do mês atual vs. anterior e vs. retrasado
    """

    def buscar_por_dia(ini, fim):
        cursor.execute("""
            SELECT extract(day from data_venda)::int as dia, SUM(valor_total) as total
            FROM vendas WHERE data_venda >= %s AND data_venda <= %s
            GROUP BY dia ORDER BY dia
        """, (ini.strftime('%Y-%m-%d'), fim.strftime('%Y-%m-%d')))
        return {r[0]: float(r[1]) for r in cursor.fetchall()}

    vendas_atual = buscar_por_dia(datas["inicio_atual"], datas["fim_atual"])
    vendas_anterior = buscar_por_dia(datas["inicio_ant"], datas["fim_ant_completo"])
    vendas_retrasado = buscar_por_dia(datas["inicio_retr"], datas["fim_retr_completo"])

    dias_mes = list(range(1, 32))
    df = pd.DataFrame(index=dias_mes)
    df['Atual'] = df.index.map(vendas_atual).fillna(0.0)
    df['Anterior_Real'] = df.index.map(vendas_anterior).fillna(0.0)
    df['Retrasado_Real'] = df.index.map(vendas_retrasado).fillna(0.0)
    df['Anterior_Meta'] = df['Anterior_Real'] * 1.02  # Mês anterior + 2%

    df['Acumulado_Atual'] = df['Atual'].cumsum()
    df['Acumulado_Meta'] = df['Anterior_Meta'].cumsum()
    df['Acumulado_Anterior_Real'] = df['Anterior_Real'].cumsum()
    df['Acumulado_Retrasado'] = df['Retrasado_Real'].cumsum()

    # Esconde dias futuros do mês atual
    df.loc[df.index > ontem_dt.day, 'Acumulado_Atual'] = None

    # Variações percentuais
    base_ant = df['Acumulado_Anterior_Real'].replace(0, np.nan)
    base_retr = df['Acumulado_Retrasado'].replace(0, np.nan)
    df['Var_Pct_Anterior'] = (df['Acumulado_Atual'] - base_ant) / base_ant * 100
    df['Var_Pct_Retrasado'] = (df['Acumulado_Atual'] - base_retr) / base_retr * 100

    # --- Plot ---
    fig, ax1 = plt.subplots(figsize=(10, 5.5))

    # Plotando os 3 meses no eixo principal (R$)
    ax1.plot(df.index, df['Acumulado_Retrasado'],
              label=f'Retrasado ({datas["mes_retrasado_dt"].strftime("%b/%y")})',
              color='#bdc3c7', linestyle=':', marker='.', alpha=0.8)

    ax1.plot(df.index, df['Acumulado_Anterior_Real'],
              label=f'Anterior ({datas["mes_anterior_dt"].strftime("%b/%y")})',
              color='#7f8c8d', linestyle='--', marker='.', alpha=0.8)

    ax1.plot(df.index, df['Acumulado_Meta'],
              label=f'Meta (Ant. +2%)',
              color='#e67e22', linestyle='--', marker='')

    ax1.plot(df.index, df['Acumulado_Atual'],
              label='Mês Atual', color='#27ae60', linewidth=2.5, marker='o')

    ax1.set_title('Evolução do Faturamento Acumulado - Nosso Café', fontsize=14, fontweight='bold', pad=15)
    ax1.set_xlabel('Dia do Mês', fontsize=11)
    ax1.set_ylabel('Acumulado (R$)', fontsize=11)
    ax1.grid(True, linestyle=':', alpha=0.6)
    ax1.set_xticks(range(1, 32, 2))

    # Eixo secundário (%)
    ax2 = ax1.twinx()
    ax2.plot(df.index, df['Var_Pct_Anterior'], label='% vs Mês Anterior',
              color='#2980b9', linestyle='-.', marker='x', linewidth=1.3, alpha=0.85)
    ax2.plot(df.index, df['Var_Pct_Retrasado'], label='% vs Mês Retrasado',
              color='#8e44ad', linestyle='-.', marker='+', linewidth=1.3, alpha=0.85)
    ax2.axhline(0, color='#7f8c8d', linewidth=0.8, alpha=0.5)
    ax2.set_ylabel('Variação (%)', fontsize=11)

    # Legenda combinada
    linhas1, labels1 = ax1.get_legend_handles_labels()
    linhas2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(linhas1 + linhas2, labels1 + labels2, loc='upper left', fontsize=8.5)

    plt.tight_layout()
    caminho_grafico = 'acumulado_cfo.png'
    plt.savefig(caminho_grafico, dpi=150)
    plt.close()
    return caminho_grafico


def calcular_meta_dinamica(cursor, data_analise):
    br_holidays = holidays.Brazil()
    is_feriado_fds = data_analise.weekday() >= 5 or data_analise in br_holidays
    dia_semana = data_analise.weekday()

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

    media_historica = float(resultado) if resultado else (1800.0 if is_feriado_fds else 1200.0)
    return round(media_historica * 1.025, 2)


def gerar_relatorio_ia(texto_prompt):
    try:
        client = genai.Client(api_key=GEMINI_KEY.strip())
    except Exception as e_critico:
        print(f"Erro ao inicializar client do Google Gemini: {e_critico}")
        return ""

    for modelo in MODELOS_PREFERENCIA:
        try:
            print(f"Tentando: {modelo}...")
            response = client.models.generate_content(model=modelo, contents=texto_prompt)
            if response and response.text:
                print(f"Sucesso com: {modelo}!")
                return response.text
        except Exception as e_mod:
            print(f"Modelo {modelo} recusou: {e_mod}")
            continue

    return ""


def job_completo():
    validar_configuracao()

    ontem_dt = datetime.now(TZ_BR) - timedelta(days=1)
    ontem_dt = ontem_dt.replace(tzinfo=None)
    ontem_str = ontem_dt.strftime("%Y-%m-%d")
    dia_semana_pt = {0: "Segunda", 1: "Terça", 2: "Quarta", 3: "Quinta", 4: "Sexta", 5: "Sábado", 6: "Domingo"}
    nome_dia = dia_semana_pt[ontem_dt.weekday()]
    print(f"--- Iniciando Processamento: {ontem_str} ({nome_dia}) ---")

    datas = obter_datas_tres_meses(ontem_dt)

    vendas = buscar_vendas_saipos(ontem_str)

    conn = None
    caminho_grafico = None
    try:
        conn = psycopg2.connect(DB_URL)

        with conn.cursor() as cur:
            for v in vendas:
                if v.get('canceled') == 'Y':
                    continue
                forma = extrair_forma_pagamento(v)
                cur.execute("""
                    INSERT INTO vendas (id_venda, data_venda, valor_total, forma_pagamento)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id_venda) DO UPDATE SET
                        valor_total = EXCLUDED.valor_total,
                        forma_pagamento = EXCLUDED.forma_pagamento;
                """, (v.get('id_sale'), v.get('created_at'), v.get('total_amount'), forma))
            conn.commit()

        with conn.cursor() as cur:
            meta_hoje = calcular_meta_dinamica(cur, ontem_dt.date())

            cur.execute("SELECT SUM(valor_total) FROM vendas WHERE data_venda::date = %s", (ontem_str,))
            venda_dia = float(cur.fetchone()[0] or 0)

            cur.execute(
                "SELECT SUM(valor_total) FROM vendas WHERE date_trunc('month', data_venda) = date_trunc('month', %s::date)",
                (ontem_str,)
            )
            acumulado_mes = float(cur.fetchone()[0] or 0)

            cur.execute(
                "SELECT SUM(valor_total) FROM vendas WHERE date_trunc('month', data_venda) = date_trunc('month', %s::date)",
                (datas["mes_anterior_dt"].strftime('%Y-%m-%d'),)
            )
            total_mes_anterior_completo = float(cur.fetchone()[0] or 0)

            meta_mensal_cfo = total_mes_anterior_completo * 1.02
            percentual_atingido_meta = (acumulado_mes / meta_mensal_cfo * 100) if meta_mensal_cfo > 0 else 0.0

            cur.execute(
                "SELECT SUM(valor_total) FROM vendas WHERE date_trunc('year', data_venda) = date_trunc('year', %s::date)",
                (ontem_str,)
            )
            acumulado_ano = float(cur.fetchone()[0] or 0)

            dia_atual = ontem_dt.day
            media_diaria_mes = acumulado_mes / dia_atual
            ultimo_dia = calendar.monthrange(ontem_dt.year, ashes=ontem_dt.month)[1] if hasattr(ontem_dt, 'month') else calendar.monthrange(ontem_dt.year, ontem_dt.month)[1]
            projecao_final = media_diaria_mes * ultimo_dia

            bloco_comparativo_texto = obter_comparativo_mtd_texto(cur, datas)

            caminho_grafico = gerar_grafico_acumulado(cur, ontem_dt, datas)

        texto_prompt = f"""
        Aja como Diretor financeiro do 'Nosso Café'. O relatório é para as gestoras Marcela e Natali.
        Analise os resultados de {ontem_str} ({nome_dia}):

        - VENDA REAL DO DIA: R${venda_dia:.2f}
        - META DIÁRIA CALCULADA (Média Histórica + 2.5%): R${meta_hoje:.2f}
        - PERFORMANCE DO DIA: {'✅ ACIMA DA META' if venda_dia >= meta_hoje else '❌ ABAIXO DA META'}
        - SUPERÁVIT/DÉFICIT DIÁRIO: R${venda_dia - meta_hoje:.2f}

        - ACUMULADO MÊS ATUAL: R${acumulado_mes:.2f}
        - META MENSAL CFO (Mês Anterior Completo + 2%): R${meta_mensal_cfo:.2f}
        - % DA META MENSAL ATINGIDO ATÉ AGORA: {percentual_atingido_meta:.1f}%

        - ACUMULADO ANO: R${acumulado_ano:.2f}
        - PROJEÇÃO FINAL DO MÊS: R${projecao_final:.2f}
        - COMPARATIVO DE PERÍODOS ANTERIORES (MTD):
        {bloco_comparativo_texto}

        Diretrizes:
        1. Foque em análise financeira e estratégica.
        2. Avalie se o ritmo atual (% da meta mensal atingido e projeção) é seguro.
        3. Destaque o crescimento anual.
        4. Seja direto, executivo e profissional.
        """

        relatorio_ia = gerar_relatorio_ia(texto_prompt)
        if not relatorio_ia:
            relatorio_ia = "O sistema de análise estratégica automática da IA está indisponível temporariamente, mas os dados abaixo foram calculados com sucesso."

        bloco_comparativo_html = bloco_comparativo_texto.replace('\n', '<br>')
        relatorio_ia_html = relatorio_ia.replace('\n', '<br>')

        corpo_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 650px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #6F4E37; border-bottom: 2px solid #6F4E37; padding-bottom: 5px;">☕ RELATÓRIO FINANCEIRO DIÁRIO - NOSSO CAFÉ</h2>
            <p><strong>Competência:</strong> {ontem_str} ({nome_dia})</p>

            <div style="background-color: #fcfcfc; padding: 15px; border-radius: 5px; border-left: 5px solid #6F4E37; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 20px;">
                <span style="font-size: 15px;">{bloco_comparativo_html}</span>
                <hr style="border: 0; border-top: 1px solid #eee; margin: 12px 0;">
                <strong>🎯 META MENSAL CFO (Mês Anterior + 2%):</strong> R$ {meta_mensal_cfo:,.2f}<br>
                <strong>📊 DESEMPENHO DA META MENSAL:</strong> <span style="color: {'#27ae60' if percentual_atingido_meta >= 100 else '#d35400'}; font-weight: bold;">{percentual_atingido_meta:.1f}% atingidos</span><br>
                <strong>📅 ACUMULADO NO ANO (YTD):</strong> R$ {acumulado_ano:,.2f}
            </div>

            <h3 style="color: #2c3e50; margin-top: 25px; margin-bottom: 10px;">📈 EVOLUÇÃO ACUMULADA DIA A DIA (3 MESES)</h3>
            <p style="font-size: 13px; color: #7f8c8d; margin-bottom: 15px;">
                A linha verde é o mês atual. A tracejada cinza é o mês anterior real e a laranja é a meta. A pontilhada cinza-claro é o mês retrasado.
                As linhas no eixo direito mostram a variação percentual acumulada do mês atual frente aos dois meses anteriores.
            </p>

            <div style="text-align: center; margin-bottom: 25px;">
                <img src="cid:grafico" alt="Gráfico de Evolução de Vendas" style="max-width: 100%; height: auto; border: 1px solid #eaeded; border-radius: 6px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);"/>
            </div>

            <h3 style="color: #6F4E37; margin-top: 25px; margin-bottom: 10px;">📊 ANÁLISE ESTRATÉGICA DO CFO</h3>
            <div style="background-color: #fdf6f0; padding: 18px; border-radius: 6px; font-style: italic; border: 1px solid #f5e6da; color: #4a3728;">
                {relatorio_ia_html}
            </div>

            <hr style="border: 0; border-top: 1px solid #eee; margin-top: 35px;">
            <p style="font-size: 11px; color: #999; text-align: center;">Gerado automaticamente pelo ecossistema de dados do Nosso Café.</p>
        </body>
        </html>
        """

        enviar_email_html_com_grafico(f"Relatório Diário Nosso Café - {ontem_str}", corpo_html, caminho_grafico)

    finally:
        if caminho_grafico and os.path.exists(caminho_grafico):
            os.remove(caminho_grafico)
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    try:
        job_completo()
    except Exception as e:
        print(f"Erro fatal no job: {e}")
        sys.exit(1)
