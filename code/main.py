# packages
import tomli
import time
import logging
import zmq
# local
from variable_blackboard import Blackboard
from barcode_scan import BarcodeScanner
from wrapper import MQTTServiceWrapper

logger = logging.getLogger("main")
logging.basicConfig(level=logging.DEBUG)  # move to log config file using python functionality


def get_config():
    with open("./config.toml", "rb") as f:
        toml_conf = tomli.load(f)
    logger.info(f"config:{toml_conf}")
    return toml_conf


def config_valid(config):
    return True


def create_building_blocks(config):
    bbs = {}

    bs_out = {"type": zmq.PUSH, "address": "tcp://127.0.0.1:4000", "bind": True}
    inter_in = {"type": zmq.PULL, "address": "tcp://127.0.0.1:4000", "bind": False}
    inter_out = {"type": zmq.PUSH, "address": "tcp://127.0.0.1:4001", "bind": True}
    wrapper_in = {"type": zmq.PULL, "address": "tcp://127.0.0.1:4001", "bind": False}

    bbs["bs"] = BarcodeScanner(config, {'out': bs_out})
    bbs["inter"] = Blackboard(config, {'in': inter_in, 'out': inter_out})
    bbs["wrapper"] = MQTTServiceWrapper(config, wrapper_in)

    logger.debug(f"bbs {bbs}")
    return bbs


def start_building_blocks(bbs):
    for key in bbs:
        p = bbs[key].start()


def monitor_building_blocks(bbs):
    while True:
        time.sleep(1)
        for key in bbs:
            # logger.debug(f"{bbs[key].exitcode}, {bbs[key].is_alive()}")
            # todo actually monitor
            pass


if __name__ == "__main__":
    conf = get_config()
    # todo set logging level from config file
    if config_valid(conf):
        bbs = create_building_blocks(conf)
        start_building_blocks(bbs)
        monitor_building_blocks(bbs)
    else:
        raise Exception("bad config")
