import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

def processar_itens_estrategicos():
    # Endereço correto conforme o PDF 
    url = "https://data.saipos.io/v1/sales_items"
    headers = {
        "Authorization": os.getenv("SAIPOS_TOKEN"), # Bearer xyz [cite: 27]
        "accept": "application/json"
    }
    
    # Filtros seguindo a documentação 
    params = {
        "p_date_column_filter": "shift_date",
        "p_filter_date_start": "2026-04-24 00:00:00", # Exemplo: ontem
        "p_filter_date_end": "2026-04-24 23:59:59"
    }

    r = requests.get(url, headers=headers, params=params)
    vendas = r.json() if r.status_code == 200 else []

    dados_para_analise = []

    for venda in vendas:
        # Acessando o array de itens detalhado no layout 
        for item in venda.get('items', []):
            if item.get('deleted') == 1: continue # Pula itens deletados 
            
            dados_para_analise.append({
                "produto": item.get('desc_sale_item'), # 
                "qtd": item.get('quantity'),
                "valor_unitario": item.get('unit_price'), # 
                "id_venda": venda.get('id_sale') # 
            })

    df = pd.DataFrame(dados_para_analise)
    
    # Ranking para Natali e Marcela
    ranking = df.groupby('produto').agg({'qtd': 'sum', 'valor_unitario': 'mean'})
    print(ranking.sort_values(by='qtd', ascending=False).head(10))

if __name__ == "__main__":
    processar_itens_estrategicos()
