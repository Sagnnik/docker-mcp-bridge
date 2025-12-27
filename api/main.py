from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from providers import LLMProviderFactory
from router import mcp_routes, chat_routes
from utils.logger import logger
from config import settings
from services.redis_client import init_redis, close_redis
from services.langfuse_client import init_langfuse, flush_langfuse

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MCP Gateway API...")
    await init_redis()
    if settings.infisical_enabled:
        from services.docker_secrets import initialize_docker_secrets
        initialize_docker_secrets()

    langfuse = init_langfuse(settings)  
    if langfuse:
        logger.info("Langfuse tracing enabled")
    LLMProviderFactory.initialize_provider()

    yield

    logger.info("Shutting down MCP Gateway API...")
    flush_langfuse()
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

app.include_router(chat_routes.router)
app.include_router(mcp_routes.router)