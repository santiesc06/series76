"""Step 4: load the verified dataset into PostgreSQL.

Idempotent: the catalog tables are replaced in one transaction, so running it twice (e.g. on
every container start) gives the same result. Conversations are never touched. Needs no API key.
"""

import json

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ingest import paths
from ingest.normalize import match_key


def load_dataset(session: Session, dataset: dict) -> dict[str, int]:
    from app.db.models import CatalogTable, Part, Rating

    session.execute(delete(Rating))
    session.execute(delete(Part))
    session.execute(delete(CatalogTable))
    session.flush()

    for t in dataset["tables"]:
        session.add(
            CatalogTable(
                code=t["code"],
                title=t["title"],
                page=t["page"],
                enclosure=t["enclosure"],
                voltage=t["voltage"],
                phase=t["phase"],
                current_type=t["current_type"],
                frequency_dependent=t["frequency_dependent"],
                service_split=t["service_split"],
                layout=t["layout"],
                certifications=t["certifications"],
                markings=t["markings"],
                hazardous=t["hazardous"],
                summary_claim=t.get("summary_claim"),
                notes=t["notes"],
                footnotes=t["footnotes"],
            )
        )
    session.flush()

    positions: dict[str, int] = {}
    ratings = 0
    for p in dataset["parts"]:
        position = positions.get(p["table_code"], 0)
        positions[p["table_code"]] = position + 1
        part = Part(
            part_number=p["part_number"],
            match_key=match_key(p["part_number"]),
            model_code=p["model_code"],
            size=p["size"],
            table_code=p["table_code"],
            data_available=p["data_available"],
            csa_certified=p["csa_certified"],
            position=position,
            motor_power_w=p["motor_power_w"],
            speed_s_60hz=p["speed_s_60hz"],
            speed_s_50hz=p["speed_s_50hz"],
            fla_a_60hz=p["fla_a_60hz"],
            fla_a_50hz=p["fla_a_50hz"],
            lra_a_60hz=p["lra_a_60hz"],
            lra_a_50hz=p["lra_a_50hz"],
            ratings=[Rating(**r) for r in p["ratings"]],
        )
        ratings += len(p["ratings"])
        session.add(part)
    session.flush()
    return {"tables": len(dataset["tables"]), "parts": len(dataset["parts"]), "ratings": ratings}


def run() -> None:
    from app.db.session import SessionLocal

    dataset = json.loads(paths.PROCESSED.read_text(encoding="utf-8"))
    with SessionLocal() as session, session.begin():
        counts = load_dataset(session, dataset)
    print(
        f"Loaded {counts['tables']} tables, {counts['parts']} parts, "
        f"{counts['ratings']} ratings from {paths.PROCESSED.name}"
    )
