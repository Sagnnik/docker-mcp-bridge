from providers.base import LLMProvider
from providers.openai import OpenAIProvider
from providers.openrouter import OpenRouterProvider
from typing import Dict

class LLMProviderFactory:
    _providers: Dict[str, LLMProvider] = {}

    @classmethod
    def initialize_provider(cls):
        cls._providers = {
            "openai": OpenAIProvider(),
            "openrouter": OpenRouterProvider(),
        }

    @classmethod
    def get_provider(cls, provider_name: str) -> LLMProvider:
        if not cls._providers:
            cls.initialize_provider()
        
        if provider_name not in cls._providers:
            raise ValueError(f"Unknown provider: {provider_name}")
        return cls._providers[provider_name]