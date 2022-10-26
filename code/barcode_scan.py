import datetime
import logging
import multiprocessing
import sys
import time

import evdev
import asyncio
import zmq
import zmq.asyncio

from KeyParser.Keyparser import Parser

context = zmq.asyncio.Context()
logger = logging.getLogger("main.barcode_scan")

__dt = -1 * (time.timezone if (time.localtime().tm_isdst == 0) else time.altzone)
tz = datetime.timezone(datetime.timedelta(seconds=__dt))


class BarcodeScanner(multiprocessing.Process):
    def __init__(self, config, zmq_conf):
        super().__init__()
        # config
        scanner_config = config['input']['scanner']
        self.scanner_serial = scanner_config.get('serial', "")
        self.connection_point = scanner_config.get('connection_point', ['*'])

        # declaration
        self.udev_ctx = None
        self.scanner_device = None

        self.zmq_conf = zmq_conf
        self.zmq_out = None

        # setup
        self.parser = Parser()

        count = 1
        found = self.find_scanner()

        while not found and count < 3:
            time.sleep(2)
            count = count + 1
            found = self.find_scanner()

        if not found:
            logger.error("Retries exceeded! hibernating")
            while True:
                time.sleep(3600)

        self.grab_exclusive_access()

    def find_scanner(self):
        try:
            import pyudev
            logger.info("pyudev version: {vsn}".format(vsn=pyudev.__version__))
            logger.info("udev version: {vsn}".format(vsn=pyudev.udev_version()))
        except ImportError:
            logger.error("Unable to import pyudev. Ensure that it is installed", file=sys.stderr)
            exit(0)

        self.udev_ctx = pyudev.Context()

        logger.info("Looking for barcode reader with serial number {sn} on connection point {cp}".format(
            sn=self.scanner_serial, cp=self.connection_point))

        for dev in self.udev_ctx.list_devices(subsystem='input', ID_BUS='usb'):
            if dev.device_node is not None:

                try:
                    serial_option_1 = dev.properties['ID_SERIAL']
                    serial_option_2 = f"{dev.properties['ID_VENDOR_ID']}_{dev.properties['ID_MODEL_ID']}"
                    if dev.properties['ID_INPUT_KEYBOARD'] == "1" and (
                            serial_option_1 == self.scanner_serial or serial_option_2 == self.scanner_serial):
                        if self.connection_point[0] != '*':
                            _, connection_point = dev.properties['ID_PATH'].split('-usb-')
                            cp_entries = connection_point.split(':')
                            match = True
                            for i in range(0, len(self.connection_point)):
                                if self.connection_point[i] != cp_entries[i]:
                                    match = False
                                    break
                            if not match:
                                continue

                        logger.info('Scanner found')
                        self.scanner_device = evdev.InputDevice(dev.device_node)
                        return True
                except Exception as e:
                    logger.error(e)

        logger.warning("BS> Error: Scanner not found", file=sys.stderr)

        for dev in self.udev_ctx.list_devices(subsystem='input', ID_BUS='usb'):
            if dev.device_node is not None:

                try:
                    if dev.properties['ID_INPUT_KEYBOARD'] == "1":
                        _, connection_point = dev.properties['ID_PATH'].split('-usb-')
                        serial_option_1 = dev.properties['ID_SERIAL']
                        serial_option_2 = f"{dev.properties['ID_VENDOR_ID']}_{dev.properties['ID_MODEL_ID']}"
                        logger.info(
                            f"available: {serial_option_1} or "
                            f"{serial_option_2} on connection point {connection_point.split(':')}")
                except Exception as e:
                    logger.error(e)

        return False

    def grab_exclusive_access(self):
        self.scanner_device.grab()

    def do_connect(self):
        self.zmq_out = context.socket(self.zmq_conf['out']['type'])
        if self.zmq_conf['out']["bind"]:
            self.zmq_out.bind(self.zmq_conf['out']["address"])
        else:
            self.zmq_out.connect(self.zmq_conf['out']["address"])

    def run(self):
        self.do_connect()
        logger.info("connected")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            loop.run_until_complete(self.scan_loop())

    async def key_event_loop(self):
        # handles key events from the barcode scanner
        async for event in self.scanner_device.async_read_loop():
            if event.type == 1:  # key event
                self.parser.parse(event.code, event.value)
                if self.parser.complete_available():
                    msg_content = self.parser.get_next_string()
                    timestamp = (datetime.datetime.fromtimestamp(event.sec, tz=tz) + datetime.timedelta(
                        microseconds=event.usec)).isoformat()
                    yield msg_content, timestamp

    async def scan_loop(self):
        # handles complete scans from the key_event_loop
        async for barcode, timestamp in self.key_event_loop():
            payload = {'barcode': barcode, 'timestamp': timestamp}
            await self.dispatch(payload)

    async def dispatch(self, payload):
        logger.debug(f"ZMQ dispatch of {payload}")
        await self.zmq_out.send_json(payload)
