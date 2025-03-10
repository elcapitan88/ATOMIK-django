from fastapi import APIRouter

from . import users, webhooks, trades, system

admin_router = APIRouter()

admin_router.include_router(users.router, prefix="/users", tags=["admin-users"])
admin_router.include_router(webhooks.router, prefix="/webhooks", tags=["admin-webhooks"])
admin_router.include_router(trades.router, prefix="/trades", tags=["admin-trades"])
admin_router.include_router(system.router, prefix="/system", tags=["admin-system"])