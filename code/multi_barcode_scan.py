import time
import datetime


import evdev
import asyncio
import zmq
import zmq.asyncio
import json
import traceback

import logging
import multiprocessing
from KeyParser.Keyparser import Parser


context = zmq.asyncio.Context()
logger = logging.getLogger("main.multi_barcode_scan")


class DeviceManager(dict):
    # singleton to manage udev context
    __udev_ctx = None

    def __init__(self, init_device_set={}):
        super().__init__(init_device_set)
        self.target_paths = {}
        self.event_loop_generators = {}

    @classmethod
    def get_udev_context(cls):
        if cls.__udev_ctx == None:
            try:
                import pyudev

                logger.info("pyudev version: {vsn}".format(vsn=pyudev.__version__))
                logger.info("udev version: {vsn}".format(vsn=pyudev.udev_version()))
            except ImportError:
                logger.error("Unable to import pyudev. Ensure that it is installed")
                exit(0)

            cls.__udev_ctx = pyudev.Context()
        return cls.__udev_ctx

    @classmethod
    def find_scanner_by_path(cls,path):
        logger.info(f"Searching for scanner at path: {path}")
        for device in cls.get_udev_context().list_devices(subsystem="input", ID_BUS="usb"):
            if  device.device_node is not None and device.properties.get("ID_PATH") == path:
                logger.info(f"Found device {device.device_node}")
                try:
                    return evdev.InputDevice(device.device_node)
                except OSError as e:
                    if e.errno == 19: # no device at node
                        logger.error(f"Device at {device.device_node} not available")
                        raise e
        return None

    def set_target_device_paths(self, devices_path_map):
        for loc_id, path in devices_path_map.items():
            self.target_paths[loc_id] = path

    def find_and_bind_targets(self):
        for loc_id, path in self.target_paths.items():
            if loc_id in self: # already found and bound
                continue
            device = self.find_scanner_by_path(path)
            if device is not None:
                device.grab()
                self[loc_id] = device

    def device_lost(self, loc_id):
        if loc_id in self:
            del self[loc_id]
        if loc_id in self.event_loop_generators:
            del self.event_loop_generators[loc_id]
            
    def initialise_event_generators(self):
        for device_id, device in self.items():
            self.event_loop_generators[device_id] = key_event_generator(device)
            
    def recover_disconnected_devices(self):
        for loc_id, path in self.target_paths.items():
            if loc_id not in self:
                device = self.find_scanner_by_path(path)
                logger.info(f"attempt to recover device for path {path} got device {device}")
                if device is not None:
                    device.grab()
                    self[loc_id] = device
                    self.event_loop_generators[loc_id] = key_event_generator(device)
                    logger.info(f"Reconnected to device for location_id {loc_id}")


class BarcodeScannerManager(multiprocessing.Process):

    def __init__(self, config, zmq_conf):
        super().__init__()

        self.scanner_map_exists, self.scanner_map = load_scanner_map()

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

        device_manager = DeviceManager()
        device_manager.set_target_device_paths(self.scanner_map)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        device_scan_task = asyncio.Task(
            device_scan_loop(device_manager, self.dispatch), loop=loop
        )

        device_recovery_task = asyncio.Task(recovery_loop(device_manager), loop=loop)

        while True:
            # monitor task
            done, pending = loop.run_until_complete(
                asyncio.wait([device_scan_task, device_recovery_task], return_when=asyncio.FIRST_COMPLETED)
            )
            if device_scan_task in done:
                logger.error("Device scan loop ended unexpectedly - restarting")
                device_scan_task = asyncio.Task(
                    device_scan_loop(device_manager, self.dispatch), loop=loop
                )
            if device_recovery_task in done:
                logger.error("Device revovery loop ended unexpectedly - restarting")
                device_scan_task.cancel()
                device_scan_task = asyncio.Task(
                    device_scan_loop(device_manager, self.dispatch), loop=loop
                )
                device_recovery_task = asyncio.Task(recovery_loop(device_manager), loop=loop)

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
        with open("/app/data/scanner_map.json", "w") as f:
            json.dump(scanner_map, f)
    except FileNotFoundError:
        logger.error("Unable to write scanner map at /app/data/scanner_map.json")


###################
# RECOVERY LOOPS
###################
async def recovery_loop(device_manager:DeviceManager, interval_seconds:int=10):
    while True:
        device_manager.recover_disconnected_devices()
        await asyncio.sleep(interval_seconds)

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


async def device_scan_loop(device_manager:DeviceManager, dispatch_coro):
    # handles complete scans from the key_event_loop
    async for payload in multi_device_scan_generator(device_manager):
        await dispatch_coro(payload)


async def multi_device_scan_generator(device_manager: DeviceManager):
    device_manager.initialise_event_generators()

    # initial setup
    next_event_tasks = {
        device_id: asyncio.Task(gen.__anext__())
        for device_id, gen in device_manager.event_loop_generators.items()
    }
    
    while True:
        # schedule any generators that don't have a pending task
        for device_id, generator in device_manager.event_loop_generators.items():
            if device_id not in next_event_tasks or next_event_tasks[device_id].done():
                next_event_tasks[device_id] = asyncio.Task(
                    generator.__anext__()
                )

        if len(next_event_tasks) == 0:
            # no devices connected - wait and retry
            await asyncio.sleep(1)
            continue
        
        done, _pending = await asyncio.wait(
            next_event_tasks.values(), return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            device_id = None
            # get device id for completed task
            for dev_id, dev_task in next_event_tasks.items():
                if dev_task == task:
                    device_id = dev_id
                    break
            # process completed task
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
                except OSError as e:
                    if e.errno == 19:  # device disconnected
                        logger.error(f"Device {device_id} disconnected")
                        device_manager.device_lost(device_id)
                        del next_event_tasks[device_id]
                        continue
