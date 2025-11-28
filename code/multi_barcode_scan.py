import time
import datetime


import evdev
import asyncio
import zmq
import zmq.asyncio
import json

import logging
import multiprocessing
from KeyParser.Keyparser import Parser


context = zmq.asyncio.Context()
logger = logging.getLogger("main.multi_barcode_scan")


class DeviceManager:
    # singleton to manage udev context
    __udev_ctx = None

    @classmethod
    def get_udev_context(self):
        if self.__udev_ctx == None:
            try:
                import pyudev

                logger.info("pyudev version: {vsn}".format(vsn=pyudev.__version__))
                logger.info("udev version: {vsn}".format(vsn=pyudev.udev_version()))
            except ImportError:
                logger.error("Unable to import pyudev. Ensure that it is installed")
                exit(0)

            self.__udev_ctx = pyudev.Context()
        return self.__udev_ctx


class BarcodeScannerManager(multiprocessing.Process):

    def __init__(self, config, zmq_conf):
        super().__init__()

        self.scanner_map_exists, self.scanner_map = self.load_scanner_map()

        self.zmq_conf = zmq_conf
        self.zmq_out = None

    def do_connect(self):
        self.zmq_out = context.socket(self.zmq_conf["out"]["type"])
        if self.zmq_conf["out"]["bind"]:
            self.zmq_out.bind(self.zmq_conf["out"]["address"])
        else:
            self.zmq_out.connect(self.zmq_conf["out"]["address"])

    def run(self):
        self.do_connect()
        logger.info("connected")

        if not self.scanner_map_exists:
            logger.error("Scanner map not configured - unable to run! hibernating")
            while True:
                time.sleep(3600)

        devices_dict = {}
        
        for loc_id, device_path in self.scanner_map.items():
            device = evdev.InputDevice(device_path)
            device.grab()
            devices_dict[loc_id] = device

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        device_scan_task = asyncio.Task(
            device_scan_loop(devices_dict, self.dispatch), loop=loop
        )

        while True:
            # monitor task
            done, pending = loop.run_until_complete(
                asyncio.wait([device_scan_task], return_when=asyncio.FIRST_COMPLETED)
            )
            if device_scan_task in done:
                logger.error("Device scan loop ended unexpectedly - restarting")
                device_scan_task = asyncio.Task(
                    device_scan_loop(devices_dict, self.dispatch), loop=loop
                )

    async def dispatch(self, payload):
        logger.debug(f"ZMQ dispatch of {payload}")
        await self.zmq_out.send_json(payload)


###################
# Scanner map loading and writing
###################


def load_scanner_map():
    try:
        with open("/app/data/scanner_map.json", "r") as f:
            scanner_map = json.load(f)
            return True, scanner_map
    except FileNotFoundError:
        logger.error(
            "Service Module not set up - couldn't find scanner map at /app/data/scanner_map.json"
        )
        return False, {}


def write_scanner_map(scanner_map):
    try:
        with open("/app/data/scanner_map", "w") as f:
            json.dump(scanner_map, f)
    except FileNotFoundError:
        logger.error("Unable to write scanner map at /app/data/scanner_map.json")


###################
# EVENT LOOPS
###################


async def key_event_generator(device):
    parser = Parser()
    # handles key events from the barcode scanner
    async for event in device.async_read_loop():
        if event.type == 1:  # key event
            parser.parse(event.code, event.value)
            if parser.complete_available():
                msg_content = parser.get_next_string()

                __dt = -1 * (
                    time.timezone if (time.localtime().tm_isdst == 0) else time.altzone
                )
                tz = datetime.timezone(datetime.timedelta(seconds=__dt))

                timestamp = (
                    datetime.datetime.fromtimestamp(event.sec, tz=tz)
                    + datetime.timedelta(microseconds=event.usec)
                ).isoformat()
                yield msg_content, timestamp


async def device_scan_loop(devices_dict, dispatch_coro):
    # handles complete scans from the key_event_loop
    async for payload in multi_device_scan_generator(devices_dict):
        await dispatch_coro(payload)


async def multi_device_scan_generator(devices_dict):
    # handles complete scans from multiple devices
    event_generators = {}
    for device_id, device in devices_dict.items():
        event_generators[device_id] = key_event_generator(device)

    next_event_tasks = {
        device_id: asyncio.Task(gen.__anext__())
        for device_id, gen in event_generators.items()
    }
    while True:
        done, _pending = await asyncio.wait(
            next_event_tasks.values(), return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            device_id = None
            for dev_id, dev_task in next_event_tasks.items():
                if dev_task == task:
                    device_id = dev_id
                    break
            if device_id is not None:
                try:
                    barcode, timestamp = task.result()
                    payload = {
                        "id": device_id,
                        "barcode": barcode,
                        "timestamp": timestamp,
                    }
                    yield payload
                except StopAsyncIteration:
                    logger.error(
                        f"Device {device_id} event generator stopped unexpectedly"
                    )
                    continue
                # schedule next event read
                next_event_tasks[device_id] = asyncio.Task(
                    event_generators[device_id].__anext__()
                )
