"""
Logging configuration for ShortsMaker project.

Integrates with Prefect logging and provides file rotation.
"""
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_file_logging(
    log_dir: str = "logs",
    log_file: str = "shorts_maker.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    log_level: int = logging.INFO
):
    """
    Set up file logging with rotation for the entire application.

    Args:
        log_dir: Directory to store log files
        log_file: Name of the log file
        max_bytes: Maximum size of log file before rotation (default: 10MB)
        backup_count: Number of backup files to keep (default: 5)
        log_level: Logging level (default: INFO)
    """
    # Create logs directory if it doesn't exist
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Full path to log file
    log_file_path = log_path / log_file

    # Create rotating file handler
    file_handler = RotatingFileHandler(
        filename=log_file_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )

    # Set format
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)

    # Add handler to root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    root_logger.setLevel(log_level)

    # Also configure Prefect logger to use the same handler
    prefect_logger = logging.getLogger("prefect")
    prefect_logger.addHandler(file_handler)

    return file_handler


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    When running inside Prefect tasks/flows, this will automatically use
    Prefect's logger. Otherwise, it uses standard Python logging.

    Args:
        name: Name of the logger (typically __name__)

    Returns:
        Logger instance
    """
    # Try to get Prefect logger if available (inside a task/flow)
    try:
        from prefect import get_run_logger
        return get_run_logger()
    except Exception:
        # Fall back to standard Python logger
        return logging.getLogger(name)
