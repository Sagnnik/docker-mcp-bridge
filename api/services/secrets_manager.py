from infisical_sdk import InfisicalSDKClient, BaseSecret
from config import settings
from abc import ABC, abstractmethod
from logger import logger
from typing import Optional, Dict

class InfisicalSecretsManager:
    def __init__(self):
        logger.info("Initializing Infisical Secrets Manager...")
        self._client = InfisicalSDKClient(
            host=settings.infisical_url,
            token=settings.infisical_token,
            cache_ttl=300
        )
        self.secret_cache: Dict[str, str] = {}
        logger.info("Infisical Secrets manager initialized")

    def _get_secret_path(self, username: Optional[str] = None) -> str:
        """
        Admin secrets are stored at the root path ("/")
        User secrets are stored at "/users/{username}/"
        """
        return f"/users/{username}/" if username else "/"

    def _get_cache_key(self, secret_name: str, username: Optional[str] = None) -> str:
        """Generate a cache key for the secret"""
        return f"{username}:{secret_name}" if username else f"admin:{secret_name}"

    def get_secret(self, secret_name: str, username: Optional[str] = None) -> Optional[str]:
        """Fetch a secret by name from Cache or Infisical"""
        cache_key = self._get_cache_key(secret_name, username)
        if cache_key in self.secret_cache:
            logger.info(f"Returning cached secret for: {secret_name} (user: {username or 'admin'})")
            return self.secret_cache[cache_key]
        
        # Try to get admin secret first
        admin_secret = self._fetch_secret_from_infisical(secret_name, None)
        if admin_secret:
            return admin_secret
        
        # If no admin secret and username is provided, try user-specific secret
        if username:
            logger.info(f"No admin secret found for '{secret_name}', checking user secret for '{username}'")
            user_secret = self._fetch_secret_from_infisical(secret_name, username)
            return user_secret
        
        logger.warning(f"Secret '{secret_name}' not found in admin or user scope")
        return None

    def _fetch_secret_from_infisical(self, secret_name: str, username: Optional[str] = None) -> Optional[str]:
        secret_path = self._get_secret_path(username)
        cache_key = self._get_cache_key(secret_name, username)
        
        try:
            logger.info(f"Fetching secret '{secret_name}' from Infisical at path '{secret_path}'...")
            secret = self._client.secrets.get_secret_by_name(
                secret_name=secret_name,
                project_id=settings.infisical_proj,
                environment_slug=settings.infisical_env,
                secret_path=secret_path,
            )
            secret_value = secret.secretValue
            
            if secret_value:
                self.secret_cache[cache_key] = secret_value
                logger.info(f"Successfully fetched and cached secret '{secret_name}' (user: {username or 'admin'})")
            else:
                logger.warning(f"Secret '{secret_name}' found but has no value at path '{secret_path}'")
            
            return secret_value
        
        except Exception as e:
            logger.debug(f"Secret '{secret_name}' not found at path '{secret_path}': {e}")
            return None

    def create_secret(self, secret_name: str, secret_value: str, username: Optional[str] = None, secret_comment: Optional[str] = None) -> bool:
        """Create a new secret in Infisical"""
        secret_path = self._get_secret_path(username)
        cache_key = self._get_cache_key(secret_name, username)
        
        try:
            logger.info(f"Creating secret '{secret_name}' at path '{secret_path}'...")
            secret = self._client.secrets.create_secret_by_name(
                secret_name=secret_name,
                project_id=settings.infisical_proj,
                secret_path=secret_path,
                environment_slug=settings.infisical_env,
                secret_value=secret_value,
                secret_comment=secret_comment or f"Created for user: {username or 'admin'}"
            )

            secret_val = secret.secretValue
            if secret_val:
                self.secret_cache[cache_key] = secret_val
                logger.info(f"Successfully created and cached secret '{secret_name}' (user: {username or 'admin'})")
                return True
            else:
                logger.warning(f"Secret '{secret_name}' created but has no value")
                return False
        
        except Exception as e:
            logger.error(f"Failed to create secret '{secret_name}' at path '{secret_path}': {e}")
            return False

    def update_secret(self, secret_name: str, secret_value: str, username: Optional[str] = None, secret_comment: Optional[str] = None, new_secret_name: Optional[str] = None) -> bool:
        """Update an existing secret in Infisical"""
        secret_path = self._get_secret_path(username)
        old_cache_key = self._get_cache_key(secret_name, username)
        
        try:
            logger.info(f"Updating secret '{secret_name}' at path '{secret_path}'...")
            secret = self._client.secrets.update_secret_by_name(
                current_secret_name=secret_name,
                project_id=settings.infisical_proj,
                secret_path=secret_path,
                environment_slug=settings.infisical_env,
                secret_value=secret_value,
                secret_comment=secret_comment,
                new_secret_name=new_secret_name
            )

            # Clear old cache entry
            if old_cache_key in self.secret_cache:
                del self.secret_cache[old_cache_key]
            
            # Cache with new name if renamed
            final_name = new_secret_name or secret_name
            new_cache_key = self._get_cache_key(final_name, username)
            
            secret_val = secret.secretValue
            if secret_val:
                self.secret_cache[new_cache_key] = secret_val
                logger.info(f"Successfully updated and cached secret '{final_name}' (user: {username or 'admin'})")
                return True
            else:
                logger.warning(f"Secret '{final_name}' updated but has no value")
                return False
        
        except Exception as e:
            logger.error(f"Failed to update secret '{secret_name}' at path '{secret_path}': {e}")
            return False

    def delete_secret(self, secret_name: str, username: Optional[str] = None) -> bool:
        """Delete a secret from Infisical"""
        secret_path = self._get_secret_path(username)
        cache_key = self._get_cache_key(secret_name, username)
        
        try:
            logger.info(f"Deleting secret '{secret_name}' at path '{secret_path}'...")
            self._client.secrets.delete_secret_by_name(
                secret_name=secret_name,
                project_id=settings.infisical_proj,
                environment_slug=settings.infisical_env,
                secret_path=secret_path
            )

            # Clear from cache
            if cache_key in self.secret_cache:
                del self.secret_cache[cache_key]
            
            logger.info(f"Successfully deleted secret '{secret_name}' (user: {username or 'admin'})")
            return True
        
        except Exception as e:
            logger.error(f"Failed to delete secret '{secret_name}' at path '{secret_path}': {e}")
            return False

    def clear_cache(self, username: Optional[str] = None):
        """
        Clear cached secrets. If username is provided, only clears that user's cache.
        """
        if username:
            keys_to_remove = [key for key in self.secret_cache.keys() if key.startswith(f"{username}:")]
            for key in keys_to_remove:
                del self.secret_cache[key]
            logger.info(f"Cleared cache for user: {username}")
        else:
            self.secret_cache.clear()
            logger.info("Cleared all cached secrets")