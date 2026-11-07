"""File locations used by the ingestion pipeline."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "data"

PDF = DATA / "raw" / "series_76_electric_data.pdf"
METADATA = DATA / "table_metadata.yaml"
INTERIM = DATA / "interim"  # git-ignored scratch output
PAGES = INTERIM / "pages"
EXTRACTIONS = INTERIM / "extractions"
COMPARISON_REPORT = INTERIM / "comparison.md"
MERGED = INTERIM / "merged.json"
RESOLUTIONS = DATA / "review" / "resolutions.yaml"  # committed: audit trail of human decisions
PROCESSED = DATA / "processed" / "actuators.json"  # committed: the verified dataset


def load_metadata() -> dict:
    with METADATA.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
