"""
Script pour démarrer le projet
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# On charge le .env si il existe
from dotenv import load_dotenv
load_dotenv()

import uvicorn
from loguru import logger
from backend.config import get_config


def main():
    """Start the LLM Council server."""
    config = get_config()
    logger.info("=" * 60)
    logger.info("LLM COUNCIL - Local Deployment")
    logger.info("=" * 60)
    logger.info(f"Starting server at http://{config.api_host}:{config.api_port}")
    logger.info(f"Council Members: {len(config.council_members)}")
    for member in config.council_members:
        logger.info(f"   - {member.name} ({member.model}) @ {member.base_url}")
    logger.info(f"Chairman: {config.chairman.name} ({config.chairman.model}) @ {config.chairman.base_url}")
    logger.info("=" * 60)
    logger.info("Open http://localhost:8000 in your browser to access the frontend")
    logger.info("=" * 60)
    
    uvicorn.run(
        "backend.main:app",
        host=config.api_host,
        port=config.api_port,
        reload=config.debug,
        log_level="info" if config.debug else "warning",
    )


if __name__ == "__main__":
    main()
