#!/usr/bin/env python3
"""Descarga el catalogo publico de modelos LLM de OpenRouter.

Genera dos ficheros dentro de ``open-data/``:

    open-data/llm-models.json
    open-data/llm-models.csv

Fuente: https://openrouter.ai/api/v1/models  (API publica, sin clave).
Licencia de los datos: ver ``open-data/README.md``.

Sin dependencias externas: solo la libreria estandar, para que pueda
ejecutarse en cualquier maquina con Python 3.9+.
"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://openrouter.ai/api/v1/models"
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "open-data"

FIELDS = [
    "id",
    "name",
    "context_length",
    "prompt_usd_per_mtok",
    "completion_usd_per_mtok",
    "modality",
    "created_iso",
]


def _per_mtok(value: str | None) -> float | None:
    """Convierte un precio por token (string) a USD por millon de tokens."""
    if value is None or value == "":
        return None
    try:
        return round(float(value) * 1_000_000, 6)
    except (TypeError, ValueError):
        return None


def _iso(ts: object) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def fetch(url: str = API_URL, timeout: float = 30.0) -> list[dict]:
    """Descarga el catalogo crudo desde la API."""
    req = urllib.request.Request(url, headers={"User-Agent": "keyrotor-open-data/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    return payload.get("data", [])


def normalize(raw: list[dict]) -> list[dict]:
    """Recorta cada modelo a las columnas utiles y ordena por id."""
    rows = []
    for model in raw:
        pricing = model.get("pricing") or {}
        arch = model.get("architecture") or {}
        rows.append(
            {
                "id": model.get("id", ""),
                "name": model.get("name", ""),
                "context_length": model.get("context_length"),
                "prompt_usd_per_mtok": _per_mtok(pricing.get("prompt")),
                "completion_usd_per_mtok": _per_mtok(pricing.get("completion")),
                "modality": arch.get("modality", ""),
                "created_iso": _iso(model.get("created")),
            }
        )
    rows.sort(key=lambda row: row["id"])
    return rows


def write(rows: list[dict], out_dir: Path = OUT_DIR) -> tuple[Path, Path]:
    """Escribe el pack en JSON y CSV."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "llm-models.json"
    csv_path = out_dir / "llm-models.csv"

    meta = {
        "source": API_URL,
        "license": "ver open-data/README.md",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(rows),
    }
    json_path.write_text(
        json.dumps({"meta": meta, "models": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Descarga el catalogo open de modelos LLM.")
    parser.add_argument("--url", default=API_URL, help="endpoint alternativo")
    parser.add_argument("--limit", type=int, default=0, help="0 = todos los modelos")
    args = parser.parse_args()

    rows = normalize(fetch(args.url))
    if args.limit > 0:
        rows = rows[: args.limit]
    json_path, csv_path = write(rows)
    print(f"{len(rows)} modelos -> {json_path.name}, {csv_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
