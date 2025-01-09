from fastapi import APIRouter
from .endpoints import auth, broker

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/v1/auth", tags=["auth"])
api_router.include_router(broker.router, prefix="/brokers", tags=["brokers"])