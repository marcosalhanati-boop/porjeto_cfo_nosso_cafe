import os
import requests
import psycopg2
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")

def job_itens_detalhados():
    # Ontem para análise diária
    ontem_dt = datetime.now() - timedelta(days=1)
    ontem_str = ontem_dt.strftime('%Y-%m-%d')
    
    url = "https://data.saipos.io/v1/sales_items"
    headers = {"Authorization": f"Bearer {SAIPOS_TOKEN}", "accept": "application/json"}
    params = {
        "p_date_column_filter": "shift_date",
        "p_filter_date_start": f"{ontem_str} 00:00:00",
        "p_filter_date_end": f"{ontem_str} 23:59:59"
    }

    print(f"Buscando itens de: {ontem_str}")
    r = requests.get(url, headers=headers, params=params)
    vendas = r.json() if r.status_code == 200 else []

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    itens_processados = 0
    try:
        for venda in vendas:
            data_venda = venda.get('shift_date')
            id_venda = venda.get('id_sale')
            
            for item in venda.get('items', []):
                # Regra da documentação: ignorar itens deletados (transferências)
                if item.get('deleted') == 1:
                    continue
                
                nome_produto = item.get('desc_sale_item')
                qtd = float(item.get('quantity', 0))
                preco_unit = float(item.get('unit_price', 0))
                total_item = qtd * preco_unit
                
                cur.execute("""
                    INSERT INTO itens_venda (id_venda, data_venda, produto, quantidade, valor_unitario, valor_total_item)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (id_venda, data_venda, nome_produto, qtd, preco_unit, total_item))
                itens_processados += 1
        
        conn.commit()
        print(f"Sucesso! {itens_processados} itens inseridos no banco.")
        
    except Exception as e:
        print(f"Erro ao salvar itens: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    job_itens_detalhados()
