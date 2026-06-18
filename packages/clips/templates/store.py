"""Template storage and persistence.

Custom templates live as ``<slug>.azt`` JSON files under a per-profile
``templates_dir``. Built-ins are synthesized in memory (see ``builtins.py``)
and never written to disk; they are read-only.
"""

import re
from pathlib import Path

from pydantic import ValidationError

from packages.clips.templates.builtins import get_builtin, list_builtins
from packages.clips.templates.models import SCHEMA_VERSION, ClipTemplate


class TemplateNotFound(Exception):
    """Template does not exist."""

    pass


class TemplateReadOnly(Exception):
    """Cannot modify a built-in template."""

    pass


class TemplateInvalid(Exception):
    """Template validation failed."""

    pass


_DEFAULT_BUILTIN = "splitscreen"


def _slugify(name: str) -> str:
    """Derive a filesystem-safe slug from a display name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (slug or "template")[:48]


class TemplateStore:
    """Persists templates to disk as .azt files."""

    def __init__(self, templates_dir: Path):
        """Initialize store with a templates directory."""
        self.templates_dir = Path(templates_dir)

    # ── helpers ──────────────────────────────────────────────────────────

    def _path(self, id: str) -> Path:
        return self.templates_dir / f"{id}.azt"

    def _slug_taken(self, slug: str) -> bool:
        return get_builtin(slug) is not None or self._path(slug).exists()

    def _unique_slug(self, base: str) -> str:
        """Return ``base`` or the first ``base-N`` suffix that is free."""
        if not self._slug_taken(base):
            return base
        i = 2
        while self._slug_taken(f"{base}-{i}"):
            i += 1
        return f"{base}-{i}"

    def _write(self, template: ClipTemplate) -> None:
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self._path(template.id).write_bytes(template.to_azt_bytes())

    def _read(self, path: Path) -> ClipTemplate:
        try:
            return ClipTemplate.from_azt_bytes(path.read_bytes())
        except ValidationError as e:
            raise TemplateInvalid(f"{path.name}: {e}") from e

    # ── reads ────────────────────────────────────────────────────────────

    def list_all(self) -> list[ClipTemplate]:
        """List all templates (built-ins first, then custom sorted by id)."""
        templates = list_builtins()
        if self.templates_dir.exists():
            for path in sorted(self.templates_dir.glob("*.azt")):
                templates.append(self._read(path))
        return templates

    def get(self, id: str) -> ClipTemplate:
        """Get a template by id. Raises TemplateNotFound."""
        builtin = get_builtin(id)
        if builtin is not None:
            return builtin
        path = self._path(id)
        if not path.exists():
            raise TemplateNotFound(id)
        return self._read(path)

    def resolve(self, id: str | None) -> ClipTemplate:
        """Resolve a template id. None → splitscreen builtin. Raises TemplateNotFound."""
        if id is None:
            return get_builtin(_DEFAULT_BUILTIN)
        return self.get(id)

    # ── writes ───────────────────────────────────────────────────────────

    def create(self, template: ClipTemplate) -> ClipTemplate:
        """Create a new custom template. Disambiguates slug on collision."""
        slug = self._unique_slug(template.id)
        final = template.model_copy(update={"id": slug, "is_builtin": False})
        self._write(final)
        return final

    def update(self, id: str, template: ClipTemplate) -> ClipTemplate:
        """Update an existing template. Raises TemplateReadOnly for built-ins."""
        if get_builtin(id) is not None:
            raise TemplateReadOnly(id)
        if not self._path(id).exists():
            raise TemplateNotFound(id)
        final = template.model_copy(update={"id": id, "is_builtin": False})
        self._write(final)
        return final

    def delete(self, id: str) -> None:
        """Delete a template. Raises TemplateReadOnly for built-ins, TemplateNotFound if missing."""
        if get_builtin(id) is not None:
            raise TemplateReadOnly(id)
        path = self._path(id)
        if not path.exists():
            raise TemplateNotFound(id)
        path.unlink()

    def clone(self, id: str, name: str) -> ClipTemplate:
        """Clone any template (built-in or custom) into a new editable custom one."""
        src = self.get(id)
        copy = src.model_copy(
            update={"id": _slugify(name), "name": name, "is_builtin": False}
        )
        return self.create(copy)

    # ── import / export ──────────────────────────────────────────────────

    def export_bytes(self, id: str) -> bytes:
        """Export template as .azt bytes."""
        return self.get(id).to_azt_bytes()

    def import_bytes(self, data: bytes) -> ClipTemplate:
        """Import template from .azt bytes as a new custom template."""
        try:
            template = ClipTemplate.from_azt_bytes(data)
        except ValidationError as e:
            raise TemplateInvalid(str(e)) from e
        if template.schema_version != SCHEMA_VERSION:
            raise TemplateInvalid(
                f"Unsupported schema_version {template.schema_version}"
            )
        forced = template.model_copy(update={"is_builtin": False})
        return self.create(forced)
