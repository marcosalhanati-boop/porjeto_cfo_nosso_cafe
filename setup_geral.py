import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()
SAIPOS_TOKEN = os.getenv("SAIPOS_TOKEN")

def inspecionar_venda_real():
    data_alvo = "2026-04-20"
    url = "https://data.saipos.io/v1/sales_items"
    
    headers = {
        "Authorization": f"Bearer {SAIPOS_TOKEN}",
        "Accept": "application/json"
    }
    
    params = {
        "p_date_column_filter": "shift_date", 
        "p_filter_date_start": f"{data_alvo}T00:00:00", 
        "p_filter_date_end": f"{data_alvo}T23:59:59", 
        "p_limit": "50" # Pegamos uma amostra maior para achar uma não cancelada
    }
    
    print(f"--- 1. Conectando para Inspeção em: {url} ---")
    try:
        r = requests.get(url, headers=headers, params=params, timeout=40)
        dados = r.json()
        
        if isinstance(dados, list):
            # Procura a primeira que não esteja cancelada
            venda_valida = next((v for v in dados if v.get('canceled') != 'Y' and v.get('deleted') != 'Y'), None)
            
            if venda_valida:
                print("\n--- ESTRUTURA DA VENDA ATIVA ENCONTRADA ---")
                print(json.dumps(venda_valida, indent=2))
                print("--- FIM DO CONTEÚDO ---\n")
            else:
                print("A API retornou dados, mas todas as linhas parecem canceladas ou deletadas.")
                if len(dados) > 0:
                    print("Exemplo da primeira linha (mesmo cancelada):")
                    print(json.dumps(dados[0], indent=2))
        else:
            print(f"A API não retornou uma lista. Resposta: {dados}")
            
    except Exception as e:
        print(f"Erro ao processar: {e}")

if __name__ == "__main__":
    inspecionar_venda_real()