import os
import requests
import psycopg2
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")

def job_diario():
    # Busca sempre os dados de ontem
    ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    url = "https://data.saipos.io/v1/search_sales_v3"
    
    headers = {"Authorization": f"Bearer {SAIPOS_TOKEN}", "Accept": "application/json"}
    params = {
        "p_date_column_filter": "shift_date", 
        "p_filter_date_start": f"{ontem}T00:00:00", 
        "p_filter_date_end": f"{ontem}T23:59:59"
    }

    print(f"--- Iniciando automação diária: {ontem} ---")
    
    try:
        r = requests.get(url, headers=headers, params=params, timeout=60)
        vendas = r.json() if r.status_code == 200 else []
        
        if not vendas:
            print(f"Nenhuma venda encontrada para {ontem}.")
            return

        conn = psycopg2.connect(DB_URL)
        with conn.cursor() as cur:
            for v in vendas:
                if v.get('canceled') == 'Y': continue
                
                pagamentos = v.get('payments') or []
                forma = pagamentos[0].get('payment_method', {}).get('desc_payment_method', 'Outros') if pagamentos else 'Outros'
                
                cur.execute("""
                    INSERT INTO vendas (id_venda, data_venda, valor_total, forma_pagamento)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (id_venda) DO UPDATE SET 
                    valor_total = EXCLUDED.valor_total,
                    forma_pagamento = EXCLUDED.forma_pagamento;
                """, (v.get('id_sale'), v.get('created_at'), v.get('total_amount'), forma))
            
            conn.commit()
            print(f"Sucesso: {len(vendas)} vendas de ontem sincronizadas.")
        conn.close()

    except Exception as e:
        print(f"Erro na automação: {e}")

if __name__ == "__main__":
    job_diario()