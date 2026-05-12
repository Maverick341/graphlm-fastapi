import logging
import sys
from app.core.config import settings

def setup_logger(name: str = "graphlm") -> logging.Logger:
    """
    Configure and return a standardized logger for the application.
    """
    logger = logging.getLogger(name)
    
    # Set the logging level based on the environment configuration
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO
    logger.setLevel(log_level)
    
    # Avoid adding multiple handlers if the logger is retrieved multiple times
    if not logger.handlers:
        # Console handler outputs to stdout
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        
        # Format the log output
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(formatter)
        
        # Add the console handler to the logger
        logger.addHandler(console_handler)
        
        # Optional: Prevent log messages from being propagated to the root logger
        logger.propagate = False

    return logger

# Create a default logger instance to be imported throughout the app
logger = setup_logger()
