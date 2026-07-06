#!/usr/bin/env python3
"""
gerar_matches_controlado.py
===========================
Script CLI para geração controlada de matches preditivos por corredor,
prioridade mínima e limite.

Uso:
python scripts/gerar_matches_controlado.py --corredor "MS->PR" --prioridade Alta --limit 5000
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
    parser = argparse.ArgumentParser(description="Geração controlada de matches preditivos.")
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
    print(f"Limite Transportadoras: {args.limit_transp or 'Sem limite'}")
    print(f"Limite Embarcadores:    {args.limit_emb or 'Sem limite'}")
    print("-" * 60)

    start_time = time.time()

    with app.app_context():
        try:
            total_processado = gerar_matches_preditivos(
                db_session=db.session,
                corredor=args.corredor,
                prioridade_minima=args.prioridade,
                limite_matches=args.limit,
                limite_transportadoras=args.limit_transp,
                limite_embarcadores=args.limit_emb
            )
            
            elapsed = time.time() - start_time
            print("-" * 60)
            print("EXECUÇÃO CONCLUÍDA COM SUCESSO!")
            print(f"Total de Matches Gravados/Atualizados: {total_processado:,}")
            print(f"Tempo total de execução:               {elapsed:.2f} segundos")
            print("=" * 60)
            
        except Exception as e:
            print(f"\nERRO DURANTE A GERAÇÃO DE MATCHES: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    main()
