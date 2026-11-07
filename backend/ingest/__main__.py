"""Ingestion CLI.

uv run python -m ingest extract [--models a b] [--tables CODE ...]   needs API keys
uv run python -m ingest compare     diff model A vs model B, cell by cell
uv run python -m ingest build       resolutions + validation -> data/processed/actuators.json
uv run python -m ingest load        actuators.json -> PostgreSQL (idempotent, no API key)
"""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m ingest",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract", help="transcribe the PDF tables with two vision models")
    extract.add_argument("--models", nargs="+", choices=["a", "b"], default=["a", "b"])
    extract.add_argument("--tables", nargs="+", help="only these table codes")
    sub.add_parser("compare", help="diff the two extractions cell by cell")
    sub.add_parser("build", help="apply resolutions, validate, write the canonical dataset")
    sub.add_parser("load", help="load the verified dataset into PostgreSQL")
    args = parser.parse_args()

    if args.command == "extract":
        from ingest import extract as step

        step.run(args.models, args.tables)
    elif args.command == "compare":
        from ingest import compare as step

        step.run()
    elif args.command == "build":
        from ingest import build as step

        step.run()
    elif args.command == "load":
        from ingest import load as step

        step.run()


if __name__ == "__main__":
    main()
