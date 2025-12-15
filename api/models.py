from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal, Union

AddServerStatus = Literal[
    "added",
    "config_required",
    "secrets_required",
    "failed"
]

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: str = "gpt-5-mini"
    provider: str = "openai"
    mode: str = Field("dynamic", description="dynamic, code or default")
    inital_servers: List[str] = []
    max_iterations: int=5
    stream: bool=False

class MCPServerConfig(BaseModel):
    name: str
    activate: bool = True
    config: Optional[Dict[str, Any]] = None
    secrets: Optional[Dict[str, str]] = None

class AddServerResult(BaseModel):
    status: AddServerStatus
    server: str
    message: Optional[str] = None
    required_configs: Optional[List[Dict[str, Any]]] = None
    required_secrets: Optional[List[str]] = None
    instructions: Optional[str] = None
    raw_response: Optional[str] = None

class MCPRemoveRequest(BaseModel):
    name:str

class MCPFindRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    content: str
    active_servers: List[str]
    available_tools: List[str]
    finish_reason: str

class ConfigInterruptResponse(BaseModel):
    interrupt_type: Literal["config_required"]
    server: str
    required_configs: List[Dict[str, Any]]
    conversation_state: List[Dict[str, Any]]
    active_servers: List[str]
    available_tools: List[str]
    interrupt_id: str
    instructions: Optional[str] = None

class SecretsRequiredResponse(BaseModel):
    interrupt_type: Literal["secrets_required"]
    server: str
    required_secrets: List[str]
    active_servers: List[str]
    available_tools: List[str]
    message: str
    instructions: Optional[str] = None

class ChatResumeRequest(BaseModel):
    interrupt_id: str
    provided_configs: Optional[Dict[str, Any]] = None
    active_servers: Optional[List[str]] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    max_iterations: Optional[int] = None

ChatResponseUnion = Union[ChatResponse, ConfigInterruptResponse, SecretsRequiredResponse]