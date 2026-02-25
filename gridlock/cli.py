"""
Gridlock City Builder CLI

Commands:
  gridlock build <city>     — Build a .gdlk city package from source data
  gridlock validate <file>  — Read and validate a .gdlk file
  gridlock info <file>      — Print summary of a .gdlk file
  gridlock serve <city>     — Start the simulation server for a city

Examples:
  gridlock build portland
  gridlock build portland --bbox 45.43,-122.84,45.65,-122.47
  gridlock build portland --skip-stages 2,4
  gridlock validate data/output/portland.gdlk
  gridlock serve portland
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import click
import yaml

from gridlock.gdlk_format import GdlkReader
from gridlock.pipeline.orchestrator import run_pipeline
from gridlock.utils.logging import setup_logging

_BASE = Path(__file__).parent.parent
_CITIES_DIR = _BASE / "cities"
_DATA_DIR = _BASE / "data"


@click.group()
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    show_default=True,
)
@click.option("--log-file", default=None, metavar="FILE", help="Also write logs to FILE.")
def main(log_level: str, log_file: str | None) -> None:
    """Gridlock — real-world city transit simulation pipeline."""
    setup_logging(level=log_level, log_file=log_file)


@main.command()
@click.argument("city")
@click.option("--bbox", default=None, metavar="S,W,N,E",
              help="Override bounding box (WGS84 degrees).")
@click.option("--gtfs", default=None, metavar="FILE", help="Path to GTFS .zip.")
@click.option("--census", default=None, metavar="FILE", help="Census shapefile/GeoJSON.")
@click.option("--land-use", default=None, metavar="FILE", help="Land use shapefile/GeoJSON.")
@click.option("--npmrds", default=None, metavar="FILE", help="NPMRDS CSV file.")
@click.option("--output-dir", default=None, metavar="DIR", help="Directory for .gdlk output.")
@click.option("--skip-stages", default="", metavar="N,N",
              help="Comma-separated stage numbers to skip (e.g. '2,4').")
@click.option("--no-resume", is_flag=True, help="Ignore checkpoints; run all stages fresh.")
def build(
    city: str,
    bbox: str | None,
    gtfs: str | None,
    census: str | None,
    land_use: str | None,
    npmrds: str | None,
    output_dir: str | None,
    skip_stages: str,
    no_resume: bool,
) -> None:
    """Build a city data package (.gdlk) from OSM, GTFS, and census data.

    CITY is a city slug matching a file in cities/<city>.yaml,
    or a path to a YAML config file.
    """
    log = logging.getLogger(__name__)

    config = _load_city_config(city)

    if bbox:
        parts = [float(x) for x in bbox.split(",")]
        if len(parts) != 4:
            raise click.BadParameter("bbox must be S,W,N,E (4 values)", param_hint="--bbox")
        config["bbox"] = {"south": parts[0], "west": parts[1], "north": parts[2], "east": parts[3]}

    bbox_tuple: tuple[float, float, float, float] = (
        config["bbox"]["south"],
        config["bbox"]["west"],
        config["bbox"]["north"],
        config["bbox"]["east"],
    )
    skip_list = [int(x.strip()) for x in skip_stages.split(",") if x.strip().isdigit()]

    raw_dir = _DATA_DIR / "raw"
    out_dir = Path(output_dir) if output_dir else _DATA_DIR / "output"
    processed_dir = _DATA_DIR / "processed"
    os.makedirs(out_dir, exist_ok=True)

    gtfs_path = gtfs or _resolve_gtfs(config, raw_dir)
    census_path = census or _resolve_file(raw_dir / "census" / f"{config.get('slug', city)}_census.geojson")
    land_use_path = land_use or _resolve_file(raw_dir / "land_use" / f"{config.get('slug', city)}_land_use.geojson")

    click.echo(f"Building: {config.get('name', city)}")
    click.echo(f"  bbox:   {bbox_tuple}")
    click.echo(f"  output: {out_dir}")
    if skip_list:
        click.echo(f"  skipping stages: {skip_list}")

    output_path = run_pipeline(
        city_slug=config.get("slug", city),
        city_name=config.get("name", city),
        bbox=bbox_tuple,
        crs_epsg=config.get("crs_epsg", 32610),
        gtfs_path=gtfs_path,
        census_path=census_path,
        land_use_path=land_use_path,
        npmrds_path=npmrds,
        output_dir=str(out_dir),
        processed_dir=str(processed_dir),
        validation_config=config.get("validation", {}),
        resume=not no_resume,
        skip_stages=skip_list,
    )
    click.echo(click.style(f"\nDone: {output_path}", fg="green", bold=True))


@main.command()
@click.argument("gdlk_file")
def validate(gdlk_file: str) -> None:
    """Read a .gdlk file and report validation statistics."""
    reader = GdlkReader()
    try:
        info = reader.read_header(gdlk_file)
        val = reader.read_validation(gdlk_file)
    except Exception as e:
        raise click.ClickException(str(e))

    click.echo(f"File:    {gdlk_file}")
    click.echo(f"Version: {info['version']}")
    click.echo(f"City:    {info['metadata'].get('city_name', 'unknown')}")
    click.echo(f"Nodes:   {info['metadata'].get('node_count', '?')}")
    click.echo(f"Edges:   {info['metadata'].get('edge_count', '?')}")

    if val:
        status = click.style("PASSED", fg="green") if val.get("passed") else click.style("WARNING", fg="yellow")
        click.echo(f"\nValidation: {status}")
        click.echo(f"  VMT error:     {val.get('vmt_error_pct', 0):.1f}%")
        click.echo(f"  Transit error: {val.get('transit_error_pct', 0):.1f}%")
    else:
        click.echo("\nNo validation data in file.")


@main.command()
@click.argument("gdlk_file")
def info(gdlk_file: str) -> None:
    """Print full header/metadata of a .gdlk file as JSON."""
    reader = GdlkReader()
    try:
        data = reader.read_header(gdlk_file)
    except Exception as e:
        raise click.ClickException(str(e))
    click.echo(json.dumps(data, indent=2))


@main.command()
@click.argument("city")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True)
@click.option("--gdlk-file", default=None, metavar="FILE",
              help="Path to pre-built .gdlk file. Defaults to data/output/<city>.gdlk.")
def serve(city: str, host: str, port: int, gdlk_file: str | None) -> None:
    """Start the Gridlock simulation server for a city."""
    import uvicorn

    gdlk_path = gdlk_file or str(_DATA_DIR / "output" / f"{city}.gdlk")
    if not os.path.exists(gdlk_path):
        raise click.ClickException(
            f"City package not found: {gdlk_path}\n"
            f"Run 'gridlock build {city}' first."
        )

    os.environ["GRIDLOCK_CITY"] = city
    os.environ["GRIDLOCK_GDLK_PATH"] = gdlk_path

    click.echo(f"Starting Gridlock server for {city!r} on http://{host}:{port}")
    click.echo(f"  WebSocket: ws://{host}:{port}/ws")
    click.echo(f"  API docs:  http://{host}:{port}/docs")
    uvicorn.run("gridlock.server.app:app", host=host, port=port, reload=False)


# ── Helpers ────────────────────────────────────────────────────────────────

def _load_city_config(city: str) -> dict:
    yaml_path = _CITIES_DIR / f"{city}.yaml"
    if not yaml_path.exists():
        yaml_path = Path(city)
    if not yaml_path.exists():
        raise click.ClickException(
            f"City config not found: '{city}'. "
            f"Create cities/{city}.yaml or pass a YAML file path."
        )
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def _resolve_gtfs(config: dict, raw_dir: Path) -> str | None:
    import requests
    slug = config.get("slug", "city")
    local = raw_dir / "gtfs" / f"{slug}_gtfs.zip"
    if local.exists():
        return str(local)
    url = config.get("gtfs_url")
    if not url:
        return None
    click.echo(f"Downloading GTFS from {url} …")
    try:
        r = requests.get(url, timeout=180)
        r.raise_for_status()
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(r.content)
        click.echo(f"  Saved to {local}")
        return str(local)
    except Exception as e:
        click.echo(click.style(f"  GTFS download failed: {e}", fg="yellow"), err=True)
        return None


def _resolve_file(path: Path) -> str | None:
    return str(path) if path.exists() else None
