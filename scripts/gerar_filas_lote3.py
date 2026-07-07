#!/usr/bin/env python3
import os
import csv

def main():
    input_path = "exports/contatos/pendentes_sem_contato_apos_receita.csv"
    trans_output_path = "exports/contatos/fila_nao_consultados_transportadoras_lote3.csv"
    emb_output_path = "exports/contatos/fila_nao_consultados_embarcadores_lote3.csv"

    if not os.path.exists(input_path):
        print(f"Erro: Arquivo de entrada '{input_path}' nao encontrado.")
        return

    # Definir colunas exigidas pelo enriquecedor
    cols_to_write = [
        "tipo_empresa", "id", "cnpj", "nome", "telefone", "email", "site", 
        "socios", "score_match", "prioridade", "corredor", "fonte_contato", "observacao_contato"
    ]

    trans_rows = []
    emb_rows = []

    count_total = 0
    count_nao_consultados = 0
    count_trans = 0
    count_emb = 0

    with open(input_path, "r", encoding="utf-8-sig") as f_in:
        reader = csv.DictReader(f_in, delimiter=";")
        for row in reader:
            count_total += 1
            classif = row.get("classificacao", "").strip()
            if classif != "nao_consultado":
                continue

            count_nao_consultados += 1
            tipo_empresa = row.get("tipo_empresa", "").strip().lower()

            out_row = {col: "" for col in cols_to_write}
            out_row["tipo_empresa"] = row.get("tipo_empresa", "").strip()
            out_row["id"] = row.get("id", "").strip()
            out_row["cnpj"] = row.get("cnpj", "").strip()
            out_row["nome"] = row.get("nome", "").strip()
            out_row["score_match"] = row.get("score_match_max", "").strip()
            out_row["corredor"] = row.get("corredor", "").strip()

            if tipo_empresa == "transportadora":
                trans_rows.append(out_row)
                count_trans += 1
            elif tipo_empresa == "embarcador":
                emb_rows.append(out_row)
                count_emb += 1
            else:
                print(f"Aviso: tipo_empresa desconhecido: '{tipo_empresa}' na linha com CNPJ {out_row['cnpj']}")

    # Gravar arquivos de saída
    os.makedirs(os.path.dirname(trans_output_path), exist_ok=True)
    
    with open(trans_output_path, "w", encoding="utf-8-sig", newline="") as f_trans:
        writer = csv.DictWriter(f_trans, fieldnames=cols_to_write, delimiter=";")
        writer.writeheader()
        writer.writerows(trans_rows)

    with open(emb_output_path, "w", encoding="utf-8-sig", newline="") as f_emb:
        writer = csv.DictWriter(f_emb, fieldnames=cols_to_write, delimiter=";")
        writer.writeheader()
        writer.writerows(emb_rows)

    print("=========================================")
    print("Resumo da divisão:")
    print(f"Total lido de pendentes: {count_total}")
    print(f"Total nao_consultado: {count_nao_consultados}")
    print(f"  Transportadoras gravadas: {count_trans} -> {trans_output_path}")
    print(f"  Embarcadores gravados: {count_emb} -> {emb_output_path}")
    print("=========================================")

if __name__ == "__main__":
    main()
