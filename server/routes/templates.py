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
    TemplateChatRequest,
    TemplateChatResponse,
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


@router.post("/templates/chat", response_model=TemplateChatResponse)
async def chat_template(req: TemplateChatRequest, user: User = Depends(require_auth)):
    """AI-assisted edit: returns an updated draft (not persisted).

    With a reference image, vision runs through Claude Code only (no Anthropic
    fallback); the image is written to a temp file and removed afterwards.
    """
    import os
    import tempfile

    from packages.clips.templates import ai_editor

    image_path: str | None = None
    tmp_handle: str | None = None

    try:
        if req.image_b64:
            if not ai_editor.vision_available():
                raise HTTPException(
                    status_code=422,
                    detail={"error_code": "VISION_UNAVAILABLE", "message": "Adjuntar imagen requiere Claude Code"},
                )
            try:
                data, ext = ai_editor.decode_reference_image(req.image_b64)
            except ai_editor.ImageInvalid as e:
                raise HTTPException(
                    status_code=422,
                    detail={"error_code": "IMAGE_INVALID", "message": str(e)},
                )
            fd, tmp_handle = tempfile.mkstemp(suffix=ext, prefix="azelia_ref_")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            image_path = tmp_handle
        else:
            # Text-only path still requires some LLM provider.
            try:
                ai_editor.get_llm()
            except ValueError:
                raise HTTPException(
                    status_code=503,
                    detail={"error_code": "LLM_UNAVAILABLE", "message": "Configura Claude Code o una API key"},
                )

        try:
            result = ai_editor.edit(
                req.template,
                [m.model_dump() for m in req.messages],
                image_path=image_path,
            )
        except ai_editor.TemplateChatError:
            raise HTTPException(
                status_code=502,
                detail={"error_code": "LLM_BAD_OUTPUT", "message": "El asistente no pudo generar un cambio válido"},
            )

        return TemplateChatResponse(
            explanation=result["explanation"],
            template=result["template"],
            provider_used=result.get("provider_used", ""),
        )
    finally:
        if tmp_handle and os.path.exists(tmp_handle):
            try:
                os.unlink(tmp_handle)
            except OSError:
                pass
