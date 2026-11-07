"""Step 1: render PDF pages and transcribe each table with a vision model.

Each model is reached through an OpenAI-compatible API (Google AI Studio and OpenRouter both offer
one), so a model is just base URL + key + name. One request per table keeps the task focused.
Output: data/interim/extractions/<label>/<table_code>.json
"""

import base64
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import pymupdf
from openai import BadRequestError, OpenAI

from app.config import get_settings
from ingest import layouts, paths

RENDER_DPI = 300


@dataclass(frozen=True)
class ExtractionModel:
    label: str  # "a" or "b"
    base_url: str
    api_key: str
    model: str


def configured_models() -> dict[str, ExtractionModel]:
    s = get_settings()
    return {
        "a": ExtractionModel(
            "a", s.extraction_a_base_url, s.extraction_a_api_key, s.extraction_a_model
        ),
        "b": ExtractionModel(
            "b",
            s.extraction_b_base_url,
            s.extraction_b_api_key or s.openrouter_api_key,
            s.extraction_b_model,
        ),
    }


def render_pages() -> dict[int, bytes]:
    """Render every PDF page to PNG (also saved to data/interim/pages for human review)."""
    paths.PAGES.mkdir(parents=True, exist_ok=True)
    images: dict[int, bytes] = {}
    with pymupdf.open(paths.PDF) as doc:
        for index, page in enumerate(doc, start=1):
            png = page.get_pixmap(dpi=RENDER_DPI).tobytes("png")
            (paths.PAGES / f"page_{index}.png").write_bytes(png)
            images[index] = png
    return images


def build_prompt(table: dict) -> str:
    columns = layouts.LAYOUTS[table["layout"]]
    column_lines = "\n".join(f'- "{c.key}": {c.header}' for c in columns)
    return f"""You are transcribing one table from an image of a product datasheet page.

Transcribe ONLY the table titled "{table["title"]}" (the {table["position"]} table on this page).
It has {table["expected_rows"]} data rows.

Return a JSON object {{"rows": [...]}} with one object per data row, top to bottom, using exactly
these keys:
{column_lines}

Rules:
- Copy every value exactly as printed, as a string (e.g. "1,330", "0.7"). Do not convert, round,
  compute or fill in anything.
- "Motor Power" cells are merged across several rows: repeat the merged value on every row it spans.
- If a row's values are shown as "N/A" (one merged N/A area), set every value key of that
  row to "N/A".
- If a cell is empty, use null.
- Ignore the bold formatting inside part numbers; copy the characters only.
- Output only the JSON object, no commentary."""


def _parse_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(cleaned)


def extract_table(client: OpenAI, model: ExtractionModel, table: dict, png: bytes) -> dict:
    image_url = "data:image/png;base64," + base64.b64encode(png).decode()
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": build_prompt(table)},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    ]
    started = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model.model,
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
    except (
        BadRequestError
    ):  # some providers reject response_format; the prompt already asks for JSON
        response = client.chat.completions.create(
            model=model.model, messages=messages, temperature=0
        )
    raw = response.choices[0].message.content or ""
    usage = response.usage.model_dump() if response.usage else None
    return {
        "table_code": table["code"],
        "model": model.model,
        "provider": model.base_url,
        "extracted_at": datetime.now(UTC).isoformat(),
        "duration_s": round(time.monotonic() - started, 2),
        "usage": usage,
        "raw_response": raw,
        "rows": _parse_json(raw).get("rows", []),
    }


def run(labels: list[str], tables: list[str] | None = None) -> None:
    metadata = paths.load_metadata()
    selected = [t for t in metadata["tables"] if not tables or t["code"] in tables]
    pages = render_pages()
    models = configured_models()
    for label in labels:
        model = models[label]
        if not (model.api_key and model.model):
            raise SystemExit(f"Extraction model '{label}' is not configured (see .env.example).")
        # max_retries: the SDK retries 429/5xx with exponential backoff (free tiers are often busy)
        client = OpenAI(base_url=model.base_url, api_key=model.api_key, timeout=180, max_retries=4)
        out_dir = paths.EXTRACTIONS / label
        out_dir.mkdir(parents=True, exist_ok=True)
        for table in selected:
            print(f"[{label}] {model.model}: extracting {table['code']} ...", flush=True)
            result = extract_table(client, model, table, pages[table["page"]])
            target = out_dir / f"{table['code']}.json"
            target.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[{label}]   {len(result['rows'])} rows in {result['duration_s']} s", flush=True)
