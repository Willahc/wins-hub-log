#!/usr/bin/env python3
import os
import sys
import csv
import argparse

def main():
    parser = argparse.ArgumentParser(description="Prepara CSV de enriquecimento para o formato do importador.")
    parser.add_argument("--input", required=True, help="Caminho do CSV de entrada (resultado do enriquecedor)")
    parser.add_argument("--output", required=True, help="Caminho do CSV de saída (para o importador)")
    parser.add_argument("--fonte-contato", default="BrasilAPI/Receita CNPJ", help="Valor para coluna fonte_contato")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"Erro: Arquivo de entrada '{args.input}' nao encontrado.")
        sys.exit(1)
        
    cols_to_write = [
        "tipo_empresa", "id", "cnpj", "nome", "telefone",
        "email", "site", "socios", "fonte_contato", "observacao_contato"
    ]
    
    rows_written = 0
    with open(args.input, "r", encoding="utf-8-sig") as f_in:
        # Detectar delimitador
        sample = f_in.read(2048)
        f_in.seek(0)
        delimiter = ";"
        if sample:
            if "," in sample and (sample.count(",") > sample.count(";")):
                delimiter = ","
                
        reader = csv.DictReader(f_in, delimiter=delimiter)
        
        output_rows = []
        for row in reader:
            # Mapear
            out_row = {col: "" for col in cols_to_write}
            out_row["tipo_empresa"] = row.get("tipo_empresa", "").strip()
            out_row["id"] = row.get("id", "").strip()
            out_row["cnpj"] = row.get("cnpj", "").strip()
            out_row["nome"] = row.get("nome", "").strip()
            out_row["telefone"] = row.get("telefone_encontrado", "").strip()
            out_row["email"] = row.get("email_encontrado", "").strip()
            out_row["site"] = row.get("site", "").strip()
            out_row["socios"] = row.get("socios_encontrados", "").strip()
            out_row["fonte_contato"] = args.fonte_contato
            
            obs_parts = []
            obs_col = row.get("observacao", "").strip()
            if obs_col:
                obs_parts.append(obs_col)
            addr = row.get("endereco_encontrado", "").strip()
            if addr:
                obs_parts.append(f"Endereço: {addr}")
                
            out_row["observacao_contato"] = " | ".join(obs_parts) if obs_parts else "Contato enriquecido por CNPJ via base publica"
            
            output_rows.append(out_row)
            
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=cols_to_write, delimiter=";")
        writer.writeheader()
        writer.writerows(output_rows)
        rows_written = len(output_rows)
        
    print(f"Sucesso: {rows_written} linhas preparadas em '{args.output}'.")

if __name__ == "__main__":
    main()
