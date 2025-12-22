from infisical_sdk import InfisicalSDKClient
from config import settings
from abc import ABC, abstractmethod
from logger import logger
from typing import Optional, Dict

class BaseSecretsManager(ABC):
    @abstractmethod
    def get_secret(self, secret_name:str) -> Optional[str]:
        pass

class InfisicalSecretsManager(BaseSecretsManager):
    def __init__(self):
        logger.info("Initializing Infisical Secrets Manager...")
        self._client = InfisicalSDKClient(
            host=settings.infisical_url,
            token=settings.infisical_token,
            cache_ttl= 300
        )
        self.secret_cache: Dict[str, str] = {}
        logger.info("Infisical Secrets manager initialized")

    def get_secret(self, secret_name:str) -> Optional[str]:
        if secret_name in self.secret_cache:
            logger.info(f"Returning Cached Secret for: {secret_name}")
            return self.secret_cache[secret_name]
        
        try:
            logger.info(f"Fetching secret '{secret_name}' from Infisical...")
            secret_value = self._client.secrets.get_secret_by_name(
                secret_name=secret_name,
                project_id=settings.infisical_proj,
                environment_slug=settings.infisical_env,
                secret_path="/",
            )
            if secret_value:
                self.secret_cache[secret_name] = secret_value
                logger.info(f"Successfully fetched and cached secret for '{secret_name}'")

            else:
                logger.warning(f"Secret '{secret_name}' not found or has no value in Infisical.")
            
            return secret_value
        except Exception as e:
            logger.error(f"Failed to fetch secret '{secret_name}' from Infisical: {e}")
            return None