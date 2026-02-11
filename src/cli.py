"""Command-line interface for Celia Clips."""

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="celia",
    help="🎬 Celia Clips: Turn podcasts into viral short-form clips",
    add_completion=False,
)
console = Console()


if __name__ == "__main__":
    app()

