"""Clip-template CRUD endpoints (F1).

Templates live per-profile under <data_dir>/templates/<slug>.azt. Built-ins are
synthesized read-only presets. Domain exceptions map to the spec's HTTP codes.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from packages.clips.templates.models import ClipTemplate, LayoutSpec, SubtitleSpec
from packages.clips.templates.store import (
    TemplateNotFound,
    TemplateReadOnly,
    TemplateStore,
)
from packages.core.config import settings
from server.middleware.auth import User, require_auth
from server.models import (
    CloneTemplateRequest,
    CreateTemplateRequest,
    TemplateListResponse,
    UpdateTemplateRequest,
)

router = APIRouter()


def _store() -> TemplateStore:
    return TemplateStore(settings.templates_dir())


def _slugify(name: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (slug or "template")[:48]


def _not_found(id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error_code": "TEMPLATE_NOT_FOUND", "message": "Template no encontrado"},
    )


def _read_only(id: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"error_code": "TEMPLATE_READONLY", "message": "Los presets no se editan; clónalo primero"},
    )


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates(user: User = Depends(require_auth)):
    return TemplateListResponse(templates=_store().list_all())


@router.get("/templates/{id}", response_model=ClipTemplate)
async def get_template(id: str, user: User = Depends(require_auth)):
    try:
        return _store().get(id)
    except TemplateNotFound:
        raise _not_found(id)


@router.post("/templates", response_model=ClipTemplate, status_code=201)
async def create_template(req: CreateTemplateRequest, user: User = Depends(require_auth)):
    now = datetime.now().isoformat()
    template = ClipTemplate(
        id=_slugify(req.name),
        name=req.name,
        description=req.description,
        author=req.author,
        is_builtin=False,
        created_at=now,
        updated_at=now,
        subtitles=req.subtitles or SubtitleSpec(),
        layout=req.layout or LayoutSpec(),
    )
    return _store().create(template)


@router.put("/templates/{id}", response_model=ClipTemplate)
async def update_template(id: str, req: UpdateTemplateRequest, user: User = Depends(require_auth)):
    store = _store()
    try:
        existing = store.get(id)
    except TemplateNotFound:
        raise _not_found(id)
    if existing.is_builtin:
        raise _read_only(id)

    updated = existing.model_copy(
        update={
            "name": req.name,
            "description": req.description,
            "author": req.author,
            "subtitles": req.subtitles or existing.subtitles,
            "layout": req.layout or existing.layout,
            "updated_at": datetime.now().isoformat(),
        }
    )
    try:
        return store.update(id, updated)
    except TemplateReadOnly:
        raise _read_only(id)
    except TemplateNotFound:
        raise _not_found(id)


@router.delete("/templates/{id}")
async def delete_template(id: str, user: User = Depends(require_auth)):
    try:
        _store().delete(id)
    except TemplateReadOnly:
        raise _read_only(id)
    except TemplateNotFound:
        raise _not_found(id)
    return {"status": "deleted", "id": id}


@router.post("/templates/{id}/clone", response_model=ClipTemplate, status_code=201)
async def clone_template(id: str, req: CloneTemplateRequest, user: User = Depends(require_auth)):
    try:
        return _store().clone(id, req.name)
    except TemplateNotFound:
        raise _not_found(id)
