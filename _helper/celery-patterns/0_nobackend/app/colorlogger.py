import colorlog
import logging

def get_colorlogger(name: str = __name__, level: int = logging.DEBUG):
    """
    Returns a logger object with colored output.
    """
    # Create a logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Create a colorlog handler
    handler = colorlog.StreamHandler()

    # Create a formatter with custom colors
    formatter = colorlog.ColoredFormatter(
        '%(log_color)s%(levelname)-8s%(reset)s %(blue)s%(asctime)s%(reset)s %(name)s %(bold_purple)s%(filename)s:%(lineno)d%(reset)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        reset=True,
        log_colors={
            'DEBUG':    'cyan',
            'INFO':     'green',
            'WARNING':  'yellow',
            'ERROR':    'red',
            'CRITICAL': 'red,bg_white',
        },
        secondary_log_colors={},
        style='%'
    )

    # Set the formatter for the handler
    handler.setFormatter(formatter)

    # Add the handler to the logger
    # Check if the logger already has handlers to prevent duplicate logs
    if not logger.handlers:
        logger.addHandler(handler)

    return logger


