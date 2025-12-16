from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from logger import logger
import json
from core import AgentCore
from models import (
    ChatRequest, 
    ChatResponse, 
    ChatResumeRequest,
    SecretsRequiredResponse, 
    ConfigInterruptResponse, 
    ChatResponseUnion
)
from gateway_client import MCPGatewayAPIClient
from provider import LLMProviderFactory
from state_manager import (
    generate_interrupt_id, 
    store_interrupt_state,
    get_interrupt_state, 
    cleanup_interrupt_state
)

router = APIRouter()

@router.post("/chat", response_model=ChatResponseUnion, tags=['chat'])
async def chat(request: ChatRequest):
    try:
        pass
    except:
        pass