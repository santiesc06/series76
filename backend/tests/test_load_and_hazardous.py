"""ingest load (idempotent) and the hazardous-area interpretation rules."""

import json

from sqlalchemy import func, select

from app.db.models import CatalogTable, Part, Rating
from app.services import hazardous
from ingest import paths
from ingest.load import load_dataset

XP = {"zone": 1, "division": 1, "nec_gas_groups": ["C", "D"], "iec_gas_group": "IIB",
      "dust_rated": False}  # fmt: skip


def test_load_is_idempotent(db):
    dataset = json.loads(paths.PROCESSED.read_text(encoding="utf-8"))
    first = load_dataset(db, dataset)
    second = load_dataset(db, dataset)
    assert first == second == {"tables": 7, "parts": 68, "ratings": 111}
    assert db.scalar(select(func.count()).select_from(CatalogTable)) == 7
    assert db.scalar(select(func.count()).select_from(Part)) == 68
    assert db.scalar(select(func.count()).select_from(Rating)) == 111


def test_marked_areas_are_covered():
    assert hazardous.check(XP, zone=1, gas_group="IIB") == []
    assert hazardous.check(XP, zone=2, division=2, gas_group="IIA") == []
    assert hazardous.check(XP, division=1, gas_group="D") == []


def test_unmarked_areas_are_not_covered():
    assert hazardous.check(XP, zone=0)
    assert hazardous.check(XP, gas_group="IIC")
    assert hazardous.check(XP, gas_group="B")
    assert hazardous.check(XP, dust=True)


def test_weatherproof_is_never_suitable_for_hazardous_areas():
    assert hazardous.check(None, zone=2)
