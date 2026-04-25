import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

def diagnostico_saipos():
    # Testando com Ontem
    ontem_dt = datetime.now() - timedelta(days=1)
    ontem_str = ontem_dt.strftime('%Y-%m-%d')
    
    print(f"--- DIAGNÓSTICO DE CARGA ---")
    print(f"Data de busca: {ontem_str}")
    
    url = "https://data.saipos.io/v1/sales_items"
    headers = {
        "Authorization": os.getenv("SAIPOS_TOKEN"),
        "accept": "application/json"
    }
    
    # Testamos dois formatos de data comuns na Saipos
    formatos_para_testar = [
        f"{ontem_str} 00:00:00",
        ontem_str
    ]

    for data_teste in formatos_para_testar:
        params = {
            "p_date_column_filter": "shift_date",
            "p_filter_date_start": data_teste,
            "p_filter_date_end": f"{ontem_str} 23:59:59" if " " in data_teste else ontem_str
        }
        
        print(f"\nTestando formato: {params['p_filter_date_start']}")
        r = requests.get(url, headers=headers, params=params)
        
        print(f"Status Code: {r.status_code}")
        
        if r.status_code == 200:
            vendas = r.json()
            print(f"Vendas encontradas: {len(vendas)}")
            
            if len(vendas) > 0:
                primeira_venda = vendas[0]
                print(f"ID da primeira venda: {primeira_venda.get('id_sale')}")
                itens = primeira_venda.get('items', [])
                print(f"Quantidade de itens na primeira venda: {len(itens)}")
                if len(itens) > 0:
                    print(f"Exemplo de produto: {itens[0].get('desc_sale_item')}")
                return # Se encontrou, paramos por aqui
        else:
            print(f"Erro na resposta: {r.text}")

if __name__ == "__main__":
    diagnostico_saipos()
