import pathlib
import json
import logging
import logging.config
import atexit
from logging.handlers import QueueHandler, QueueListener
from multiprocessing import Queue
from .Config import CONFIG

log_queue = Queue()


def setup_logging():
    config_file = pathlib.Path("utils/logging_configdict.json")
    dict_config = None
    with open(config_file) as f_in:
        dict_config = json.load(f_in)

    for logger in dict_config["loggers"]:
        dict_config["loggers"][logger]["level"] = CONFIG.LOG_LEVEL or 'WARNING'

    logging.config.dictConfig(dict_config)
    root_logger = logging.getLogger('root')
    queue_handler = QueueHandler(log_queue)
    root_logger.addHandler(queue_handler)
    queue_listener = QueueListener(log_queue, *logging.getLogger('notusable').handlers)

    # Iniciar el listener
    queue_listener.start()
    atexit.register(queue_listener.stop)
