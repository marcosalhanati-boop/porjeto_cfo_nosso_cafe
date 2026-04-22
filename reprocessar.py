import os
import requests
import psycopg2
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")

def rodar():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # 1. Limpa o mês de Abril para evitar duplicatas
    print("Limpando dados de Abril/2026...")
    cur.execute("DELETE FROM vendas WHERE data_venda >= '2026-04-01' AND data_venda <= '2026-04-30'")
    print(f"Limpeza concluída. Removidos {cur.rowcount} registros antigos.")

    # 2. Loop dia a dia (de 01/04 até 21/04)
    # Fazer dia a dia evita que a API da Saipos trave ou limite os resultados
    data_inicio = datetime(2026, 4, 1)
    data_fim = datetime(2026, 4, 21) # Até ontem
    
    dia_atual = data_inicio
    total_geral = 0

    while dia_atual <= data_fim:
        data_str = dia_atual.strftime("%Y-%m-%d")
        print(f"Buscando dia: {data_str}...")
        
        url = "https://data.saipos.io/v1/search_sales_v3"
        headers = {"Authorization": f"Bearer {SAIPOS_TOKEN}", "Accept": "application/json"}
        params = {
            "p_date_column_filter": "shift_date", 
            "p_filter_date_start": f"{data_str}T00:00:00", 
            "p_filter_date_end": f"{data_str}T23:59:59"
        }
        
        try:
            r = requests.get(url, headers=headers, params=params)
            vendas = r.json() if r.status_code == 200 else []
            
            cont_dia = 0
            for v in vendas:
                if v.get('canceled') == 'Y': continue
                
                cur.execute("""
                    INSERT INTO vendas (id_venda, data_venda, valor_total)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id_venda) DO NOTHING;
                """, (v.get('id_sale'), v.get('created_at'), v.get('total_amount')))
                cont_dia += 1
            
            conn.commit() # Salva o dia processado
            print(f" -> Sucesso: {cont_dia} vendas inseridas.")
            total_geral += cont_dia
            
        except Exception as e_dia:
            print(f" -> Erro no dia {data_str}: {e_dia}")
        
        dia_atual += timedelta(days=1)

    print(f"\n--- REPROCESSAMENTO FINALIZADO ---")
    print(f"Total de vendas recuperadas: {total_geral}")
    cur.close()
    conn.close()

if __name__ == "__main__":
    rodar()
