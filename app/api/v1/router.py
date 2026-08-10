"""Aggregating router for all /api/v1 endpoints.

Feature modules register their routers here.
"""

from fastapi import APIRouter

from app.campaigns.router import router as campaigns_router
from app.graph.router import router as graph_router
from app.mailer.router import router as mailer_router
from app.rules.router import router as rules_router
from app.templates.router import preview_router
from app.templates.router import router as templates_router
from app.tenants.resend_router import router as tenants_resend_router
from app.tenants.router import router as tenants_router

router = APIRouter()
router.include_router(tenants_router)
router.include_router(tenants_resend_router)
router.include_router(templates_router)
router.include_router(preview_router)
router.include_router(rules_router)
router.include_router(campaigns_router)
router.include_router(graph_router)
router.include_router(mailer_router)
