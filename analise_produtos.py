import os
import requests
import psycopg2
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")
DB_URL = os.getenv("SUPABASE_DB_URL")

def rodar_carga_itens():
    ontem_dt = datetime.now() - timedelta(days=1)
    ontem_str = ontem_dt.strftime('%Y-%m-%d')
    
    print(f"--- Iniciando Carga de Itens: {ontem_str} ---")
    
    url = "https://data.saipos.io/v1/sales_items"
    
    # AJUSTE CHAVE: A documentação exige 'Bearer ' antes do token
    token_formatado = f"Bearer {SAIPOS_TOKEN.replace('Bearer ', '')}"
    
    headers = {
        "Authorization": token_formatado,
        "accept": "application/json"
    }
    
    # AJUSTE DATA: Seguindo o padrão do PDF (YYYY-MM-DD HH:MM)
    params = {
        "p_date_column_filter": "shift_date",
        "p_filter_date_start": f"{ontem_str} 00:00",
        "p_filter_date_end": f"{ontem_str} 23:59"
    }

    try:
        r = requests.get(url, headers=headers, params=params)
        
        if r.status_code != 200:
            print(f"Erro Saipos ({r.status_code}): {r.text}")
            return

        vendas = r.json()
        print(f"Sucesso! {len(vendas)} vendas recuperadas.")

        if not vendas:
            return

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        itens_inseridos = 0
        for venda in vendas:
            id_venda = venda.get('id_sale')
            shift_date = venda.get('shift_date')
            
            # O .get('items') or [] garante que, se não houver itens, 
            # ele retorna uma lista vazia em vez de None, evitando o erro.
            lista_itens = venda.get('items')
            if lista_itens is None:
                continue

            for item in lista_itens:
                # Filtro de deletados conforme PDF
                if item.get('deleted') == 1:
                    continue
                
                # Coleta os dados com segurança
                nome = item.get('desc_sale_item', 'Produto Indefinido')
                qtd = float(item.get('quantity') or 0)
                preco = float(item.get('unit_price') or 0)
                total = qtd * preco
                
                cur.execute("""
                    INSERT INTO itens_venda (id_venda, data_venda, produto, quantidade, valor_unitario, valor_total_item)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (id_venda, shift_date, nome, qtd, preco, total))
                itens_inseridos += 1
        
        conn.commit()
        print(f"Carga finalizada: {itens_inseridos} itens salvos no Supabase.")

    except Exception as e:
        print(f"Erro Crítico: {e}")
    finally:
        if 'conn' in locals():
            cur.close()
            conn.close()

if __name__ == "__main__":
    rodar_carga_itens()
