"""Step 2: diff the two independent extractions cell by cell.

Rows are matched by **model code** (e.g. `763B`): the rest of the part number is printed
identically on every row of a table, so it comes from the hand-checked `part_number_suffix` in
data/table_metadata.yaml instead of from 68 separate transcriptions. A transcribed part number
that differs from model code + suffix is reported as a warning.

Cells where both models agree are accepted. Every disagreement (or a row only one model saw) is a
conflict that a human resolves against the PDF in data/review/resolutions.yaml.
Output: data/interim/merged.json and a readable data/interim/comparison.md
"""

import json
import re

from ingest import layouts, paths
from ingest.normalize import clean_part_number, parse_value

ASTERISK_FIELD = "footnote_marker"
MODEL_CODE_RE = re.compile(r"^76[1-7][A-Z]")


def _load(label: str, code: str) -> dict:
    path = paths.EXTRACTIONS / label / f"{code}.json"
    if not path.exists():
        raise SystemExit(f"Missing extraction {path}. Run: python -m ingest extract")
    return json.loads(path.read_text(encoding="utf-8"))


def _index(rows: list[dict], suffix: str) -> tuple[dict[str, dict], list[str]]:
    """Index rows by canonical part number; return also the transcriptions that differ from it."""
    indexed: dict[str, dict] = {}
    misread: list[str] = []
    for position, row in enumerate(rows):
        part, marked = clean_part_number(row.get("part_number", ""))
        code = MODEL_CODE_RE.match(part)
        canonical = code.group(0) + suffix if code else part  # unparseable: will not align
        if part != canonical or not code:
            misread.append(part)
        indexed[canonical] = {"row": row, "marked": marked, "position": position}
    return indexed, misread


def compare_table(
    table: dict, rows_a: list[dict], rows_b: list[dict]
) -> tuple[list, list, dict, dict]:
    (a, misread_a), (b, misread_b) = (
        _index(rows_a, table["part_number_suffix"]),
        _index(rows_b, table["part_number_suffix"]),
    )
    order = sorted(set(a) | set(b), key=lambda p: (a.get(p) or b.get(p))["position"])
    merged_rows, conflicts = [], []
    stats = {"cells": 0, "agree": 0}
    missing = {"row": {}, "marked": None, "position": None}
    for part in order:
        # A row seen by only one model: every cell becomes a conflict, so a human confirms it.
        ra, rb = a.get(part, missing), b.get(part, missing)
        values: dict[str, object] = {}
        for key in layouts.value_keys(table["layout"]):
            va, vb = parse_value(ra["row"].get(key)), parse_value(rb["row"].get(key))
            if ra is missing:
                va = "(row missing)"
            if rb is missing:
                vb = "(row missing)"
            stats["cells"] += 1
            if va == vb:
                stats["agree"] += 1
                values[key] = va
            else:
                values[key] = None
                conflicts.append(
                    {"table": table["code"], "part_number": part, "field": key, "a": va, "b": vb}
                )
        marked = ra["marked"] if ra["marked"] == rb["marked"] else None
        if marked is None:
            conflicts.append(
                {
                    "table": table["code"],
                    "part_number": part,
                    "field": ASTERISK_FIELD,
                    "a": ra["marked"],
                    "b": rb["marked"],
                }
            )
        merged_rows.append({"part_number": part, "marked": marked, "values": values})
    return merged_rows, conflicts, stats, {"a": misread_a, "b": misread_b}


def run() -> None:
    metadata = paths.load_metadata()
    merged: dict = {"models": {}, "tables": {}, "conflicts": [], "misread_part_numbers": {}}
    report = ["# Extraction comparison", ""]
    total_cells = total_agree = 0
    for table in metadata["tables"]:
        ext_a, ext_b = _load("a", table["code"]), _load("b", table["code"])
        merged["models"] = {"a": ext_a["model"], "b": ext_b["model"]}
        rows, conflicts, stats, misread = compare_table(table, ext_a["rows"], ext_b["rows"])
        merged["tables"][table["code"]] = rows
        merged["conflicts"].extend(conflicts)
        merged["misread_part_numbers"][table["code"]] = misread
        total_cells += stats["cells"]
        total_agree += stats["agree"]
        report.append(
            f"## {table['code']} (page {table['page']}, {table['title']}): "
            f"rows A={len(ext_a['rows'])} B={len(ext_b['rows'])} "
            f"expected={table['expected_rows']}, "
            f"{stats['agree']}/{stats['cells']} cells agree"
        )
        for label, parts in misread.items():
            if parts:
                report.append(
                    f"- ⚠️ Model {label.upper()} transcribed {len(parts)} part numbers differently "
                    f"from model code + `{table['part_number_suffix']}` (e.g. `{parts[0]}`); "
                    f"rows were matched by model code."
                )
        for c in conflicts:
            report.append(f"- `{c['part_number']}` **{c['field']}**: A=`{c['a']}` B=`{c['b']}`")
        report.append("")
    report.insert(
        2,
        f"Models: A=`{merged['models']['a']}`, B=`{merged['models']['b']}`. "
        f"**{total_agree}/{total_cells} cells agree, {len(merged['conflicts'])} conflicts.**\n",
    )
    paths.MERGED.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    paths.COMPARISON_REPORT.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report[:3]))
    print(f"Report: {paths.COMPARISON_REPORT}")
