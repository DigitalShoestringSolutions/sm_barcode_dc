#
#   This file is part of Shoestring Barcode Scanning Service Module.
#   Copyright (c) 2024 Shoestring and University of Cambridge
#
#   Authors:
#   Greg Hawkridge <ghawkridge@gmail.com>
#
#   Shoestring Barcode Scanning Service Module is free software:
#   you can redistribute it and/or modify it under the terms of the
#   GNU General Public License as published by the Free Software
#   Foundation, either version 3 of the License, or (at your option)
#   any later version.
#
#   Shoestring Barcode Scanning Service Module is distributed in
#   the hope that it will be useful, but WITHOUT ANY WARRANTY;
#   without even the implied warranty of MERCHANTABILITY or FITNESS
#   FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
#   details.
#
#   You should have received a copy of the GNU General Public License along
#   with Shoestring Barcode Scanning Service Module.
#   If not, see <https://www.gnu.org/licenses/>.


# packages
import signal
import tomli
import time
import logging
import argparse
import zmq
import sys
import os

# local
import utilities.config_manager as config_manager
from variable_blackboard import Blackboard
from barcode_scan import BarcodeScanner
from wrapper import MQTTServiceWrapper

logger = logging.getLogger("main")
terminate_flag = False

def create_building_blocks(config):
    bbs = {}

    bs_out = {"type": zmq.PUSH, "address": "tcp://127.0.0.1:4000", "bind": True}
    inter_in = {"type": zmq.PULL, "address": "tcp://127.0.0.1:4000", "bind": False}
    inter_out = {"type": zmq.PUSH, "address": "tcp://127.0.0.1:4001", "bind": True}
    wrapper_in = {"type": zmq.PULL, "address": "tcp://127.0.0.1:4001", "bind": False}

    bbs["bs"] = {
        "class": BarcodeScanner,
        "args": [config, {"out": bs_out}],
    }

    bbs["inter"] = {
        "class": Blackboard,
        "args": [config, {"in": inter_in, "out": inter_out}],
    }
    bbs["wrapper"] = {
        "class": MQTTServiceWrapper,
        "args": [config, wrapper_in],
    }

    logger.debug(f"bbs {bbs}")
    return bbs


def start_building_blocks(bbs):
    for key in bbs:
        start_building_block(bbs[key])


def start_building_block(bb):
    cls = bb["class"]
    args = bb["args"]

    process = cls(*args)

    process.start()
    bb["process"] = process


def monitor_building_blocks(bbs):
    while True:
        time.sleep(1)
        if terminate_flag:
            logger.info("Terminating gracefully")
            for key in bbs:
                process = bbs[key]["process"]
                process.join()
            return

        for key in bbs:
            process = bbs[key]["process"]
            if process.is_alive() is False:
                logger.warning(
                    f"Building block {key} stopped with exit: {process.exitcode}"
                )
                logger.info(f"Restarting Building block {key}")
                start_building_block(bbs[key])


def graceful_signal_handler(sig, _frame):
    logger.info(
        f"Received {signal.Signals(sig).name}. Triggering graceful termination."
    )
    # todo handle gracefully
    global terminate_flag
    terminate_flag = True
    signal.alarm(3)


def harsh_signal_handler(sig, _frame):
    logger.debug(f"Received {signal.Signals(sig).name}.")
    if terminate_flag:
        logger.error(
            f"Failed to terminate gracefully before timeout - hard terminating"
        )
        sys.exit(0)


def handle_args():
    levels = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    parser = argparse.ArgumentParser(
        description="Validate config file for sensing data collection service module.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--log",
        choices=["debug", "info", "warning", "error"],
        help="Log level",
        default="info",
        type=str,
    )
    parser.add_argument("--module_config", help="Module config file", type=str)
    parser.add_argument("--user_config", help="User config file", type=str)
    args = parser.parse_args()

    log_level = levels.get(args.log, logging.INFO)
    module_conf_file = args.module_config
    user_conf_file = args.user_config

    return module_conf_file, user_conf_file, log_level

if __name__ == "__main__":
    module_conf_file, user_conf_file, log_level = handle_args()
    logging.basicConfig(level=log_level)
    conf = config_manager.get_config(module_conf_file, user_conf_file)
    signal.signal(signal.SIGINT, graceful_signal_handler)
    signal.signal(signal.SIGTERM, graceful_signal_handler)
    signal.signal(signal.SIGALRM, harsh_signal_handler)
    bbs = create_building_blocks(conf)
    start_building_blocks(bbs)
    monitor_building_blocks(bbs)

    logger.info("Done")
