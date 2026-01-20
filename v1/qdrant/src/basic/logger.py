import logging
import colorlog
import os

# def get_logger(name):
#     logger = logging.getLogger(name)
#     logger.setLevel('DEBUG')

#     # Create handlers
#     c_handler = logging.StreamHandler()
#     f_handler = RotatingFileHandler('.log.log', maxBytes=1024*1024*5, backupCount=5)
#     c_handler.setLevel('DEBUG')
#     f_handler.setLevel('DEBUG')

#     # Create formatters and add it to handlers
#     c_format = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
#     f_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#     c_handler.setFormatter(c_format)
#     f_handler.setFormatter(f_format)

#     # Add handlers to the logger
#     logger.addHandler(c_handler)
#     logger.addHandler(f_handler)

#     return logger

def get_colorlogger(name: str = __name__):
    """
    Returns a logger object with colored output.
    """
    verbose = os.environ.get('VERBOSE', '2')
    if verbose == '0' or verbose.lower() == 'none':
        level = logging.CRITICAL + 1
    elif verbose == '1' or verbose.lower() == 'error':
        level = logging.ERROR
    elif verbose == '2' or verbose.lower() == 'all':
        level = logging.DEBUG
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

if __name__ == '__main__':
    # Example usage
    os.environ['VERBOSE'] = '1'  # Set verbosity level
    logger = get_colorlogger('MyTestLogger')
    logger.debug("This is a debug message.")
    logger.info("This is an info message.")
    logger.warning("This is a warning message.")
    logger.error("This is an error message.")
    logger.critical("This is a critical message.")