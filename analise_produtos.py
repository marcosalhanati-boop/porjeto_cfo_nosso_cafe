import os
import requests
import psycopg2
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

def rodar_carga_diaria_itens():
    # Define "ontem" dinamicamente
    ontem_dt = datetime.now() - timedelta(days=1)
    ontem_str = ontem_dt.strftime('%Y-%m-%d')
    
    print(f"--- Iniciando Carga Diária: {ontem_str} ---")
    
    url = "https://data.saipos.io/v1/sales_items"
    headers = {
        "Authorization": f"Bearer {os.getenv('SAIPOS_TOKEN').replace('Bearer ', '')}",
        "accept": "application/json"
    }
    
    params = {
        "p_date_column_filter": "shift_date",
        "p_filter_date_start": f"{ontem_str} 00:00",
        "p_filter_date_end": f"{ontem_str} 23:59"
    }

    try:
        r = requests.get(url, headers=headers, params=params)
        vendas = r.json() if r.status_code == 200 else []

        conn = psycopg2.connect(os.getenv("SUPABASE_DB_URL"))
        cur = conn.cursor()

        for venda in vendas:
            id_venda = venda.get('id_sale')
            shift_date = venda.get('shift_date')
            
            # Tratamento de segurança para itens nulos
            items = venda.get('items') or []
            
            for item in items:
                if item.get('deleted') == 1: continue # Regra do PDF
                
                # INSERT com ON CONFLICT para evitar duplicatas caso o script rode 2x
                cur.execute("""
                    INSERT INTO itens_venda (id_venda, data_venda, produto, quantidade, valor_unitario, valor_total_item)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id_venda, produto) DO NOTHING;
                """, (
                    id_venda, 
                    shift_date, 
                    item.get('desc_sale_item'), 
                    float(item.get('quantity') or 0), 
                    float(item.get('unit_price') or 0),
                    float(item.get('quantity') or 0) * float(item.get('unit_price') or 0)
                ))
        
        conn.commit()
        print(f"Carga de {ontem_str} finalizada com sucesso.")
    except Exception as e:
        print(f"Erro: {e}")
    finally:
        if 'conn' in locals(): cur.close(); conn.close()

if __name__ == "__main__":
    rodar_carga_diaria_itens()
