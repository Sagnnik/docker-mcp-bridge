"""
File: services/docker_secrets.py
Manages Docker MCP secrets for admin-only configuration.
This fetches secrets from the Infisical secrets manager and loads them into Docker MCP.

Note: 
- All secrets are admin-configured and global (no per-user isolation)
- MCP servers can only read pre-configured secret names (e.g., github.personal_access_token)
- Secrets must be set before running MCP servers
"""

import subprocess
from typing import Dict, Tuple, List, Optional
from utils.logger import logger
from services.secrets_manager import InfisicalSecretsManager

secrets_manager = InfisicalSecretsManager()


def set_docker_secret(secret_name: str, secret_value: str) -> Tuple[bool, str]:
    """
    Set a single Docker MCP secret.
    - secret_name: Name of the secret (e.g., 'github.personal_access_token')
    - secret_value: Value of the secret
    """
    try:
        cmd = ["docker", "mcp", "secret", "set", f"{secret_name}={secret_value}"]
        logger.info(f"Setting Docker secret: {secret_name}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=True
        )
        
        logger.info(f"Successfully set Docker secret: {secret_name}")
        return (True, result.stdout.strip() if result.stdout else "Success")
    
    except subprocess.TimeoutExpired:
        error_msg = f"Timeout setting secret: {secret_name}"
        logger.error(error_msg)
        return (False, error_msg)
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Error setting secret {secret_name}: {e.stderr}"
        logger.error(error_msg)
        return (False, error_msg)
        
    except Exception as e:
        error_msg = f"Unexpected error setting secret {secret_name}: {str(e)}"
        logger.error(error_msg)
        return (False, error_msg)


def load_and_set_secret(secret_name: str) -> Tuple[bool, str]:
    """
    Load a secret from Infisical and set it in Docker MCP.
    - secret_name: Name of the secret to load and set

    Returns:
    - Tuple of (success, message)
    """
    logger.info(f"Loading secret '{secret_name}' from Infisical...")
    
    # Load from secrets manager
    secret_value = secrets_manager.get_secret(secret_name)
    
    if secret_value is None:
        error_msg = f"Secret '{secret_name}' not found in Infisical"
        logger.error(error_msg)
        return (False, error_msg)
    
    # Set in Docker MCP
    success, message = set_docker_secret(secret_name, secret_value)
    
    if success:
        logger.info(f"Successfully loaded and set secret: {secret_name}")
    else:
        logger.error(f"Failed to set secret {secret_name} in Docker: {message}")
    
    return (success, message)


def load_and_set_all_secrets() -> Dict[str, Tuple[bool, str]]:
    """
    Load all secrets from Infisical and set them in Docker MCP.
    This is called during initialization in lifespan. 
    Pre-configures all MCP servers with their required secrets.
    
    Returns:
    - Dict mapping secret_name to (success, message) tuple
    """
    logger.info("Loading all secrets from Infisical...")
    
    # Get all secrets from Infisical
    secrets_list = secrets_manager.list_all_secrets()
    
    if not secrets_list:
        logger.warning("No secrets found in Infisical")
        return {}
    
    logger.info(f"Found {len(secrets_list)} secrets in Infisical. Setting them in Docker MCP...")
    
    results = {}
    success_count = 0
    
    # Set each secret in Docker MCP
    for secret_item in secrets_list:
        secret_name = secret_item['secret_name']
        secret_value = secret_item['secret_value']
        
        success, message = set_docker_secret(secret_name, secret_value)
        results[secret_name] = (success, message)
        
        if success:
            success_count += 1
    
    logger.info(f"Completed setting secrets. Success: {success_count}/{len(secrets_list)}")
    
    return results


def load_and_set_secrets_batch(secret_names: List[str]) -> Dict[str, Tuple[bool, str]]:
    """
    Load and set multiple specific secrets from Infisical.
    - secret_names: List of secret names to load and set
    
    Returns:
    - Dict mapping secret_name to (success, message) tuple
    """
    logger.info(f"Loading {len(secret_names)} secrets from Infisical...")
    
    results = {}
    success_count = 0
    
    for secret_name in secret_names:
        success, message = load_and_set_secret(secret_name)
        results[secret_name] = (success, message)
        
        if success:
            success_count += 1
    
    logger.info(f"Completed batch secret loading. Success: {success_count}/{len(secret_names)}")
    
    return results


def verify_docker_secret(secret_name: str) -> bool:
    """
    Verify that a secret exists in Docker MCP.
    
    Args:
        secret_name: Name of the secret to verify
    
    Returns:
        True if secret exists, False otherwise
    """
    try:
        cmd = ["docker", "mcp", "secret", "list"]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            check=True
        )
        
        if secret_name in result.stdout:
            logger.info(f"Secret '{secret_name}' verified in Docker MCP")
            return True
        else:
            logger.warning(f"Secret '{secret_name}' not found in Docker MCP")
            return False
    
    except Exception as e:
        logger.error(f"Error verifying secret '{secret_name}': {e}")
        return False

def initialize_docker_secrets() -> bool:
    """
    Initialize Docker MCP with all secrets from Infisical.
    
    Returns:
    - True if all secrets were set successfully, False otherwise
    """
    logger.info("Initializing Docker MCP secrets...")
    
    results = load_and_set_all_secrets()
    
    if not results:
        logger.warning("No secrets to initialize")
        return True
    
    all_success = all(success for success, _ in results.values())
    
    if all_success:
        logger.info("All Docker MCP secrets initialized successfully")
    else:
        failed_secrets = [name for name, (success, _) in results.items() if not success]
        logger.error(f"Failed to initialize some secrets: {failed_secrets}")
    
    return all_success