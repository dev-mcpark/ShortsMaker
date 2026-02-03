"""
Logging configuration for ShortsMaker project.
Provides centralized logging with file rotation.
"""
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# Pre-defined logger name
LOGGER_NAME = "shorts_maker"

def setup_logging(
    log_dir: str = "logs",
    log_file: str = "shorts_maker.log",
    max_bytes: int = 5 * 1024 * 1024,  # 5MB
    backup_count: int = 3,
    log_level: int = logging.INFO
):
    """
    Sets up the base logger with file rotation and console output.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file_path = log_path / log_file

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(log_level)
    
    # Avoid duplicate handlers
    if not logger.handlers:
        # Formatter
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 1. File Handler
        file_handler = RotatingFileHandler(
            filename=log_file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # 2. Console Handler (Optional, NiceGUI handles this too)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger

def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance. If name is provided, it returns a child logger.
    """
    base_logger = logging.getLogger(LOGGER_NAME)
    if name:
        # Return a logger that inherits from the base 'shorts_maker' logger
        if not name.startswith(f"{LOGGER_NAME}."):
            return logging.getLogger(f"{LOGGER_NAME}.{name}")
        return logging.getLogger(name)
    return base_logger