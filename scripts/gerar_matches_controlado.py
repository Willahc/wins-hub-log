#!/usr/bin/env python3
"""
gerar_matches_controlado.py
===========================
Script CLI para geração controlada de matches preditivos por corredor,
prioridade mínima e limites de diversidade/qualidade.

Exemplo de uso:
python scripts/gerar_matches_controlado.py --corredor "MS->PR" --prioridade Alta --limit 5000 \
    --max-por-embarcador 10 --max-por-transportadora 30 --preferir-transportadoras-puras --replace
"""

import os
import sys
import argparse
import time
from pathlib import Path

# Adiciona a raiz do projeto ao path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from app import app, db
from radar.matching import gerar_matches_preditivos


def main():
    parser = argparse.ArgumentParser(description="Geração controlada e diversificada de matches preditivos.")
    parser.add_argument(
        "--corredor",
        required=True,
        help="Corredor alvo para geração de matches (ex: 'MS->PR', 'SP->DF')"
    )
    parser.add_argument(
        "--prioridade",
        default=None,
        help="Prioridade mínima dos embarcadores (Alta, Média, Baixa)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite máximo de matches a serem gerados"
    )
    parser.add_argument(
        "--max-por-embarcador",
        type=int,
        default=10,
        help="Máximo de matches permitidos por embarcador (default: 10)"
    )
    parser.add_argument(
        "--max-por-transportadora",
        type=int,
        default=30,
        help="Máximo de matches permitidos por transportadora (default: 30)"
    )
    parser.add_argument(
        "--preferir-transportadoras-puras",
        action="store_true",
        help="Aplica bônus para transportadoras puras e penaliza nomes de comércio/alimentos"
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Lança a substituição, limpando matches 'Sugerido' do corredor antes de rodar"
    )
    parser.add_argument(
        "--limit-transp",
        type=int,
        default=None,
        help="Limite de transportadoras carregadas para o cálculo"
    )
    parser.add_argument(
        "--limit-emb",
        type=int,
        default=None,
        help="Limite de embarcadores carregados para o cálculo"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("GERAÇÃO CONTROLADA DE MATCHES PREDITIVOS")
    print("=" * 60)
    print(f"Corredor:               {args.corredor}")
    print(f"Prioridade mínima Emb:  {args.prioridade or 'Qualquer'}")
    print(f"Limite de Matches:      {args.limit or 'Sem limite'}")
    print(f"Max por Embarcador:     {args.max_por_embarcador}")
    print(f"Max por Transportadora: {args.max_por_transportadora}")
    print(f"Preferir Transp. Puras: {args.preferir_transportadoras_puras}")
    print(f"Substituir (--replace): {args.replace}")
    print(f"Limite Transportadoras: {args.limit_transp or 'Sem limite'}")
    print(f"Limite Embarcadores:    {args.limit_emb or 'Sem limite'}")
    print("-" * 60)

    start_time = time.time()

    with app.app_context():
        try:
            res = gerar_matches_preditivos(
                db_session=db.session,
                corredor=args.corredor,
                prioridade_minima=args.prioridade,
                limite_matches=args.limit,
                limite_transportadoras=args.limit_transp,
                limite_embarcadores=args.limit_emb,
                max_matches_por_embarcador=args.max_por_embarcador,
                max_matches_por_transportadora=args.max_por_transportadora,
                preferir_transportadoras_puras=args.preferir_transportadoras_puras,
                replace=args.replace
            )
            
            elapsed = time.time() - start_time
            print("-" * 60)
            print("EXECUÇÃO CONCLUÍDA COM SUCESSO!")
            print(f"Tempo total de execução:               {elapsed:.2f} segundos")
            print("-" * 60)
            print("RELATÓRIO ESTATÍSTICO DE MATCHES:")
            print(f"  Total de Matches Gravados:           {res['total_matches']:,}")
            print(f"  Matches Apagados (Replace):          {res.get('deleted_count', 0):,}")
            print(f"  Retentativas por Database Lock:      {res.get('retries_lock', 0)}")
            print(f"  Embarcadores Únicos Atendidos:       {res['embarcadores_unicos']:,}")
            print(f"  Transportadoras Únicas Associadas:   {res['transportadoras_unicas']:,}")
            print(f"  Média de Matches por Embarcador:     {res['media_por_embarcador']}")
            print()
            
            print("  Top 10 Embarcadores Mais Repetidos:")
            for nome, count in res["top_embarcadores"]:
                print(f"    - {nome[:45]:<45}: {count} matches")
            print()
            
            print("  Top 10 Transportadoras Mais Repetidas:")
            for nome, count in res["top_transportadoras"]:
                print(f"    - {nome[:45]:<45}: {count} matches")
            print("=" * 60)
            
        except Exception as e:
            print(f"\nERRO DURANTE A GERAÇÃO DE MATCHES: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    main()
