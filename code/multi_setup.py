import logging
import asyncio
import evdev
import json
import multi_barcode_scan
import traceback
import requests

import utilities.config_manager as config_manager
from main import handle_args

logger = logging.getLogger("multi_setup")


def get_input(prompt, variant="text", options=None):
    spec = {"type": "input", "prompt": prompt, "variant": variant}
    if options is not None:
        spec["options"] = options
    print(json.dumps(spec))
    return input()


def print_output(message, variant="info"):
    print(json.dumps({"type": "output", "message": message, "variant": variant}))


def bind_all(udev_ctx):
    all_devices = []

    for device_details in udev_ctx.list_devices(subsystem="input", ID_BUS="usb"):
        if device_details.device_node is not None:
            try:
                if device_details.properties["ID_INPUT_KEYBOARD"] == "1":
                    # grab
                    device = evdev.InputDevice(device_details.device_node)
                    device.grab()

                    all_devices.append({"details": device_details, "device": device})
            except Exception as e:
                pass

    return all_devices


def release_all(all_devices):
    for entry in all_devices:
        try:
            entry["device"].ungrab()
        except Exception as e:
            pass


if __name__ == "__main__":
    try:
        module_conf_file, user_conf_file, log_level = handle_args()
        logging.basicConfig(level=logging.WARNING)
        conf = config_manager.get_config(module_conf_file, user_conf_file)

        url = conf.get(
            "location_list_url", "http://identity-sds.docker.local/id/list/loc"
        )
        response = requests.get(url)
        location_list = response.json()

        if conf["module_enabled"] != True:
            print_output("Module not enabled - exiting", variant="success")
        else:
            print_output(
                "Setting up Barcode Scanning Service Module", variant="heading"
            )
            setup, _scanner_map = multi_barcode_scan.load_scanner_map()
            # fetch from identity service

            if setup:
                print_output("Barcode scanner already set up", variant="success")
                answer = get_input("Redo setup? ", variant="confirm")
                if answer.lower() in ["y", "yes"]:
                    setup = False

            if not setup:
                all_devices = bind_all(
                    multi_barcode_scan.DeviceManager.get_udev_context()
                )
                if len(all_devices) == 0:
                    print_output(
                        "No barcode scanners detected - please connect and try again",
                        variant="error",
                    )
                    exit(0)

                devices_with_ids = {
                    index: entry["device"] for index, entry in enumerate(all_devices)
                }
                all_scanners_generator = multi_barcode_scan.multi_device_scan_generator(
                    devices_with_ids
                )
                identified_map = {}

                loop = asyncio.new_event_loop()
                for location in location_list:
                    print_output(
                        f"Please scan a barcode using the scanner for location: {location['name']}",
                        variant="heading",
                    )

                    confirmed = None
                    listen_task = None

                    while True:
                        try:
                            if listen_task is None or listen_task.done():
                                listen_task = asyncio.Task(
                                    all_scanners_generator.__anext__(), loop=loop
                                )
                            done, _pending = loop.run_until_complete(
                                asyncio.wait(
                                    [listen_task],
                                    timeout=30,
                                    return_when=asyncio.FIRST_COMPLETED,
                                )
                            )
                            if listen_task in done:
                                reading = listen_task.result()
                                device_id = reading["id"]
                                if device_id == confirmed:
                                    break
                                else:
                                    if device_id in identified_map.keys():
                                        loc_id = identified_map[device_id][
                                            "location_id"
                                        ]
                                        loc_name = next(
                                            (
                                                loc["name"]
                                                for loc in location_list
                                                if loc["id"] == loc_id
                                            ),
                                            "unknown",
                                        )
                                        print_output(
                                            f"This scanner is already set for location {loc_name}",
                                            variant="error",
                                        )
                                        continue

                                    confirmed = device_id
                                    print_output(
                                        f"Scanned barcode: {reading['barcode']}. Please scan again to confirm.",
                                        variant="info",
                                    )
                                continue
                        except asyncio.TimeoutError:
                            print_output(
                                "No barcode scanned - please try again", variant="error"
                            )

                    device_details = all_devices[device_id]["details"]
                    print_output(
                        f"Second scan confirmed - scanner set for location {location['name']}",
                        variant="success",
                    )

                    identified_map[device_id] = {
                        "location_id": location["id"],
                        "path": device_details.properties["ID_PATH"],
                    }
                release_all(all_devices)
                scanner_map = {
                    details["location_id"]: details["path"]
                    for details in identified_map.values()
                }
                multi_barcode_scan.write_scanner_map(scanner_map)
                print_output("Setup complete!", variant="success")
    except Exception:
        print_output("Setup failed - please check logs", variant="error")
        print_output(traceback.format_exc(), variant="error")
