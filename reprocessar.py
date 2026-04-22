import os
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")

def rodar():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        # 1. Limpa Abril
        print("Limpando Abril/2026 no Supabase...")
        cur.execute("DELETE FROM vendas WHERE data_venda >= '2026-04-01' AND data_venda <= '2026-04-30'")
        
        # 2. Busca na Saipos
        url = "https://data.saipos.io/v1/search_sales_v3"
        headers = {"Authorization": f"Bearer {SAIPOS_TOKEN}", "Accept": "application/json"}
        params = {
            "p_date_column_filter": "shift_date", 
            "p_filter_date_start": "2026-04-01T00:00:00", 
            "p_filter_date_end": "2026-04-30T23:59:59"
        }
        
        r = requests.get(url, headers=headers, params=params)
        vendas = r.json() if r.status_code == 200 else []
        print(f"Encontradas {len(vendas)} vendas na Saipos.")

        # 3. Insere (Ajuste aqui as colunas se necessário)
        for v in vendas:
            if v.get('canceled') == 'Y': continue
            cur.execute("""
                INSERT INTO vendas (id_venda, data_venda, valor_total)
                VALUES (%s, %s, %s)
            """, (v.get('id_sale'), v.get('created_at'), v.get('total_amount')))
        
        conn.commit()
        print("Reprocessamento concluído com sucesso!")
    except Exception as e:
        print(f"Erro: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    rodar()
