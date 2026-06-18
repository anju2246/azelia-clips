"""Template storage and persistence."""

from pathlib import Path
from packages.clips.templates.models import ClipTemplate


class TemplateNotFound(Exception):
    """Template does not exist."""
    pass


class TemplateReadOnly(Exception):
    """Cannot modify a built-in template."""
    pass


class TemplateInvalid(Exception):
    """Template validation failed."""
    pass


class TemplateStore:
    """Persists templates to disk as .azt files."""

    def __init__(self, templates_dir: Path):
        """Initialize store with a templates directory."""
        self.templates_dir = templates_dir

    def list_all(self) -> list[ClipTemplate]:
        """List all templates (built-ins + custom)."""
        raise NotImplementedError

    def get(self, id: str) -> ClipTemplate:
        """Get a template by id. Raises TemplateNotFound."""
        raise NotImplementedError

    def create(self, template: ClipTemplate) -> ClipTemplate:
        """Create a new custom template. Disambiguates slug if collision."""
        raise NotImplementedError

    def update(self, id: str, template: ClipTemplate) -> ClipTemplate:
        """Update an existing template. Raises TemplateReadOnly for built-ins."""
        raise NotImplementedError

    def delete(self, id: str) -> None:
        """Delete a template. Raises TemplateReadOnly for built-ins, TemplateNotFound if missing."""
        raise NotImplementedError

    def clone(self, id: str, name: str) -> ClipTemplate:
        """Clone a template with a new name."""
        raise NotImplementedError

    def export_bytes(self, id: str) -> bytes:
        """Export template as .azt bytes."""
        raise NotImplementedError

    def import_bytes(self, data: bytes) -> ClipTemplate:
        """Import template from .azt bytes."""
        raise NotImplementedError

    def resolve(self, id: str | None) -> ClipTemplate:
        """Resolve template ID. None → splitscreen builtin. Raises TemplateNotFound."""
        raise NotImplementedError
