import logging
import asyncio
import evdev
import json
import multi_barcode_scan
import traceback
import requests
import time

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


async def setup_locations(location_list, old_scanner_map, all_devices):
    devices_with_ids = {
        index: entry["device"] for index, entry in enumerate(all_devices)
    }
    all_scanners_generator = multi_barcode_scan.multi_device_scan_generator(
        devices_with_ids
    )
    
    identified_map = {}
    end_early_flag = False
    
    for location in location_list:
        if end_early_flag:
            break
        print_output(
            f"Please scan a barcode using the scanner for location: {location['name']}\nTo skip this location, type/scan 'skip' and press Enter.\nTo end setup, type/scan 'end' and press Enter.",
            variant="heading",
        )
    
        confirmed = None
        selected_device = None
        
        # get device for location
        while True:
            reading = await all_scanners_generator.__anext__()
            device_id = reading["id"]
            barcode_content = reading["barcode"]
            if barcode_content.lower() == "skip":
                print_output(
                    f"Skipping location {location['name']}",
                    variant="info",
                )
                if old_scanner_map[location["id"]] is not None:
                    print_output(
                        "This location had a previous scanner assigned - do you want to keep this assignment? \nType/scan 'yes' or 'no' then press enter.",
                        variant="info",
                    )
                    while True:
                        response = await all_scanners_generator.__anext__()
                        if response["barcode"].lower() in ["yes", "no"]:
                            break
                        print_output(
                            "Unexpected response, please type/scan 'yes' or 'no' then press enter.",
                            variant="error",
                        )
                    if response["barcode"].lower() in ["yes", "y"]:
                        selected_device = old_scanner_map[location["id"]]
                break
            if barcode_content.lower() == "end":
                print_output(
                    "Ending setup as requested", variant="info"
                )
                end_early_flag = True
                break
            if device_id == confirmed:
                selected_device = device_id
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
        
        # if device selected, confirm and save
        if selected_device is not None:
            device_details = all_devices[selected_device]["details"]
            print_output(
                f"Second scan confirmed - scanner set for location {location['name']}",
                variant="success",
            )

            identified_map[selected_device] = {
                "location_id": location["id"],
                "path": device_details.properties["ID_PATH"],
            }
    
    return identified_map


if __name__ == "__main__":
    try:
        module_conf_file, user_conf_file, log_level = handle_args()
        logging.basicConfig(level=logging.WARNING)
        conf = config_manager.get_config(module_conf_file, user_conf_file)

        # fetch from identity servic
        print_output("Fetching location list...", variant="info")
        url = conf.get(
            "location_list_url", "http://identity-sds.docker.local/id/list/loc"
        )
        retry_count = 0
        while retry_count < 3:
            try:
                response = requests.get(url)
                location_list = response.json()
                break
            except Exception as e:
                retry_count += 1
                time.sleep(5)
                if retry_count >= 3:
                    raise e

        if conf["module_enabled"] != True:
            print_output("Module not enabled - exiting", variant="success")
        else:
            print_output(
                "Setting up Barcode Scanning Service Module", variant="heading"
            )
            setup, old_scanner_map = multi_barcode_scan.load_scanner_map()

            if setup:
                print_output("Barcode scanner already set up", variant="success")
                answer = get_input("Redo setup? ", variant="confirm")
                if answer.lower() in ["y", "yes"]:
                    setup = False

            if not setup:

                get_input(
                    "Please ensure all barcode scanners are now connected",
                    variant="continue",
                )
                time.sleep(2)
                all_devices = bind_all(
                    multi_barcode_scan.DeviceManager.get_udev_context()
                )
                if len(all_devices) == 0:
                    print_output(
                        "No barcode scanners detected - please connect and try again",
                        variant="error",
                    )
                    exit(0)      

                loop = asyncio.new_event_loop()

                identified_map = loop.run_until_complete(setup_locations())             
                
                release_all(all_devices)
                scanner_map = {
                    details["location_id"]: details["path"]
                    for details in identified_map.values()
                }
                multi_barcode_scan.write_scanner_map(scanner_map)
                print_output("Setup complete!", variant="success")
    except Exception:
        print_output("Setup failed - please check logs", variant="error")
        print_output(traceback.format_exc(), variant="log")
