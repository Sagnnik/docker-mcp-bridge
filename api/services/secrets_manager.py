from infisical_sdk import InfisicalSDKClient, BaseSecret
from config import settings
from utils.logger import logger
from typing import Optional, Dict, List

class InfisicalSecretsManager:
    """
    Secrets Manager for admin-only secrets.
    All secrets are stored at the root path ("/") and are global.
    """
    
    def __init__(self):
        logger.info("Initializing Infisical Secrets Manager...")
        self._client = InfisicalSDKClient(
            host=settings.infisical_url,
            token=settings.infisical_token,
            cache_ttl=300
        )
        self.secret_cache: Dict[str, str] = {}
        logger.info("Infisical Secrets Manager initialized")

    def get_secret(self, secret_name: str) -> Optional[str]:
        """Get a secret from Infisical"""
        # Check cache first
        if secret_name in self.secret_cache:
            logger.info(f"Returning cached secret for: {secret_name}")
            return self.secret_cache[secret_name]
        
        try:
            logger.info(f"Fetching secret '{secret_name}' from Infisical...")
            secret = self._client.secrets.get_secret_by_name(
                secret_name=secret_name,
                project_id=settings.infisical_proj,
                environment_slug=settings.infisical_env,
                secret_path="/",
            )
            secret_value = secret.secretValue
            
            if secret_value:
                self.secret_cache[secret_name] = secret_value
                logger.info(f"Successfully fetched and cached secret '{secret_name}'")
            else:
                logger.warning(f"Secret '{secret_name}' not found or has no value")
            
            return secret_value
        
        except Exception as e:
            logger.error(f"Failed to fetch secret '{secret_name}' from Infisical: {e}")
            return None

    def list_all_secrets(self) -> List[Dict[str, str]]:
        """
        List all secrets from Infisical.
        
        Returns:
            List of dicts with 'secret_name' and 'secret_value' keys
        """
        try:
            logger.info("Fetching all secrets from Infisical...")
            secrets_response = self._client.secrets.list_secrets(
                project_id=settings.infisical_proj,
                environment_slug=settings.infisical_env,
                secret_path="/",
                expand_secret_references=True,
                include_imports=False
            )
            
            secrets_list = []
            for secret in secrets_response.secrets:
                secret_name = secret.secretKey
                secret_value = secret.secretValue
                
                if secret_value:
                    # Cache the secret
                    self.secret_cache[secret_name] = secret_value
                    secrets_list.append({
                        'secret_name': secret_name,
                        'secret_value': secret_value
                    })
            
            logger.info(f"Successfully fetched {len(secrets_list)} secrets from Infisical")
            return secrets_list
        
        except Exception as e:
            logger.error(f"Failed to list secrets from Infisical: {e}")
            return []

    def create_secret(self, secret_name: str, secret_value: str, secret_comment: Optional[str] = None) -> bool:
        """Create a new secret in Infisical"""
        try:
            logger.info(f"Creating secret '{secret_name}'...")
            secret = self._client.secrets.create_secret_by_name(
                secret_name=secret_name,
                project_id=settings.infisical_proj,
                secret_path="/",
                environment_slug=settings.infisical_env,
                secret_value=secret_value,
                secret_comment=secret_comment or "Created by admin"
            )

            secret_val = secret.secretValue
            if secret_val:
                self.secret_cache[secret_name] = secret_val
                logger.info(f"Successfully created and cached secret '{secret_name}'")
                return True
            else:
                logger.warning(f"Secret '{secret_name}' created but has no value")
                return False
        
        except Exception as e:
            logger.error(f"Failed to create secret '{secret_name}': {e}")
            return False

    def update_secret(
        self, 
        secret_name: str, 
        secret_value: str,
        secret_comment: Optional[str] = None, 
        new_secret_name: Optional[str] = None
        ) -> bool:
        """Update an existing secret in Infisical"""
        try:
            logger.info(f"Updating secret '{secret_name}'...")
            secret = self._client.secrets.update_secret_by_name(
                current_secret_name=secret_name,
                project_id=settings.infisical_proj,
                secret_path="/",
                environment_slug=settings.infisical_env,
                secret_value=secret_value,
                secret_comment=secret_comment,
                new_secret_name=new_secret_name
            )

            # Clear old cache entry
            if secret_name in self.secret_cache:
                del self.secret_cache[secret_name]
            
            # Cache with new name if renamed
            final_name = new_secret_name or secret_name
            secret_val = secret.secretValue
            
            if secret_val:
                self.secret_cache[final_name] = secret_val
                logger.info(f"Successfully updated and cached secret '{final_name}'")
                return True
            else:
                logger.warning(f"Secret '{final_name}' updated but has no value")
                return False
        
        except Exception as e:
            logger.error(f"Failed to update secret '{secret_name}': {e}")
            return False

    def delete_secret(self, secret_name: str) -> bool:
        """Delete a secret from Infisical"""
        try:
            logger.info(f"Deleting secret '{secret_name}'...")
            self._client.secrets.delete_secret_by_name(
                secret_name=secret_name,
                project_id=settings.infisical_proj,
                environment_slug=settings.infisical_env,
                secret_path="/"
            )

            # Clear from cache
            if secret_name in self.secret_cache:
                del self.secret_cache[secret_name]
            
            logger.info(f"Successfully deleted secret '{secret_name}'")
            return True
        
        except Exception as e:
            logger.error(f"Failed to delete secret '{secret_name}': {e}")
            return False

    def clear_cache(self):
        """Clear all cached secrets."""
        self.secret_cache.clear()
        logger.info("Cleared all cached secrets")