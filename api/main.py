from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from provider import LLMProviderFactory
import routes
from logger import logger
from config import settings
from langfuse import get_client
from services.redis_client import init_redis, close_redis
from services.langfuse_client import init_langfuse, flush_langfuse

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MCP Gateway API...")
    await init_redis()
    if settings.langfuse_enabled:
        #langfuse = init_langfuse(settings)
        langfuse = get_client()
        if langfuse:
            logger.info("Langfuse tracing enabled")
    LLMProviderFactory.initialize_provider()

    yield

    logger.info("Shutting down MCP Gateway API...")
    #flush_langfuse()
    langfuse.flush()
    await close_redis()

app = FastAPI(
    title="MCP Gateway Client",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "mcp-gateway-client"}

app.include_router(routes.router)