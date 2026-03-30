"""Project-relative paths: raw data/cache under ``data/``, HTML plots under ``output/``."""

from pathlib import Path

DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")

# DuckDB cache and NetCDF downloads live under data/
DB_FILE = DATA_DIR / "dust_cache.duckdb"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
