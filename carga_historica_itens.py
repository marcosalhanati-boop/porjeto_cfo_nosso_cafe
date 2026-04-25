import os
import requests
import psycopg2
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")

def rodar_backfill_itens():
    # Configuração do período: de 01/01/2026 até ontem
    data_inicio = datetime(2026, 1, 1)
    data_fim = datetime.now() - timedelta(days=1)
    
    token_formatado = f"Bearer {SAIPOS_TOKEN.replace('Bearer ', '')}"
    headers = {
        "Authorization": token_formatado,
        "accept": "application/json"
    }
    
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    
    # 1. Limpeza de segurança (evitar duplicatas se você rodar o script duas vezes)
    print(f"Limpando dados antigos de itens de 2026 no banco...")
    cur.execute("DELETE FROM itens_venda WHERE data_venda >= '2026-01-01'")
    conn.commit()

    dia_atual = data_inicio
    while dia_atual <= data_fim:
        data_str = dia_atual.strftime('%Y-%m-%d')
        print(f"-> Processando dia: {data_str}...")
        
        url = "https://data.saipos.io/v1/sales_items"
        params = {
            "p_date_column_filter": "shift_date",
            "p_filter_date_start": f"{data_str} 00:00",
            "p_filter_date_end": f"{data_str} 23:59"
        }

        try:
            r = requests.get(url, headers=headers, params=params)
            if r.status_code != 200:
                print(f"   [!] Erro Saipos no dia {data_str}: {r.status_code}")
                dia_atual += timedelta(days=1)
                continue

            vendas = r.json()
            itens_dia = 0
            
            for venda in vendas:
                id_venda = venda.get('id_sale')
                shift_date = venda.get('shift_date')
                lista_itens = venda.get('items')
                
                if lista_itens is None: continue

                for item in lista_itens:
                    if item.get('deleted') == 1: continue
                    
                    cur.execute("""
                        INSERT INTO itens_venda (id_venda, data_venda, produto, quantidade, valor_unitario, valor_total_item)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        id_venda, 
                        shift_date, 
                        item.get('desc_sale_item', 'Indefinido'), 
                        float(item.get('quantity') or 0), 
                        float(item.get('unit_price') or 0),
                        float(item.get('quantity') or 0) * float(item.get('unit_price') or 0)
                    ))
                    itens_dia += 1
            
            conn.commit() # Salva o progresso dia após dia
            print(f"   [OK] {len(vendas)} vendas | {itens_dia} itens salvos.")
            
        except Exception as e:
            print(f"   [X] Erro no dia {data_str}: {e}")
            conn.rollback()
        
        dia_atual += timedelta(days=1)

    print("\n--- CARGA HISTÓRICA CONCLUÍDA COM SUCESSO ---")
    cur.close()
    conn.close()

if __name__ == "__main__":
    rodar_backfill_itens()
