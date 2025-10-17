import logging
import utilities.config_manager as config_manager
from main import handle_args
import evdev
import json

from barcode_scan import BarcodeScanner



def get_input(prompt, variant="text", options=None):
    spec = {"type": "input", "prompt": prompt, "variant": variant}
    if options is not None:
        spec["options"] = options
    print(json.dumps(spec))
    return input()

def print_output(message,variant="info"):
    print(json.dumps({"type": "output", "message": message, "variant": variant}))

        
def setup(barcode_scan):
    scanner_spec = auto_detect_barcode_scanner()
    # fall back to select from list
    if scanner_spec is None:
        print_output("The auto dectection process didn't work -falling back to selecting from a list")
        print_output("Select barcode scanner",variant="heading")
        
        scanner_spec = select_scanner()
    
    
    dev = scanner_spec["dev"]
    barcode_scan.grab_exclusive_access(evdev.InputDevice(dev.device_node))
    
    test_scanner(barcode_scan)
    save_scanner_id(scanner_spec)

def auto_detect_barcode_scanner():
    scanner_spec = None
    while True:
        print_output("Identifying barcode scanner:", variant="heading")
        
        get_input("If the Scanner is plugged in, please unplug it now.", variant="continue")
        available_without = barcode_scan.available_devices()
        get_input("Please plug it back in.", variant="continue")
        available_with = barcode_scan.available_devices()
        
        # get differences
        for id in available_without.keys():
            del available_with[id]
        
        if len(available_with) == 0: # no difference
            print_output("No change in USB devices detected between when scanner was plugged in and unplugged", variant="error")
        elif len(available_with) == 1:
            print_output("Found", variant="success")
            scanner_spec = list(available_with.values())[0]
            break
        else:
             print_output("Multiple USB device changes detected between when scanner was plugged in and unplugged")
             
        while True:
            answer = get_input("Would you like to try again? ",variant="confirm")
            if answer in ["y","Y","n","N"]:
                break
            print_output('unexpected response, please enter "y" or "n" followed by Enter')
        if answer in ["n","N"]:
            break
        
    return scanner_spec

def select_scanner():
    scanner_spec = None
    while True:
        available_list =  list(barcode_scan.available_devices().values())
        options = {0: "Re-scan"}
        if len(available_list) == 0:
            print_output("No USB devices detected...", variant="error")
        else:
            for index, entry in enumerate(available_list):
                options[index+1] = f'{entry["serial"]} {entry["vendor_model"]}'
                # print_output(f'{index+1} - {entry["serial"]} {entry["vendor_model"]}')
        
        raw_selected_index = get_input("Which entry is the barcode scanner that should be used?", variant="select", options=options)
        try:
            selected_index = int(raw_selected_index)
            if selected_index == 0:
                continue
            scanner_spec = available_list[selected_index-1]
            break
        except ValueError:
            print_output("Input was not a valid number, please try again.",variant="error")
        except IndexError:
            if len(available_list)>=1:
                print_output(f"Number was too high, expected a number between 1 and {len(available_list)}.",variant="error")
            else:
                print_output(f"No devices available to select from",variant="error")
        
        
    return scanner_spec

def test_scanner(barcode_scan):
    # validate test scan
    
    import asyncio
    loop = asyncio.new_event_loop()
    generator =  barcode_scan.key_event_loop()
    
    print_output("Checking barcode scanner works", variant="heading")
    print_output(
        "Please scan a barcode to check that the scanner is working.\n"+
        "All scanned barcodes will be printed below.")
    listen_task = None
    while True:
        try:
            if listen_task is None or listen_task.done():
                listen_task = asyncio.Task(generator.__anext__(),loop=loop) 
            print_output("Listening for barcode scan...")
            done, _pending = loop.run_until_complete(asyncio.wait([listen_task],timeout=30,return_when=asyncio.FIRST_COMPLETED))
            if listen_task in done:
                barcode, timestamp = listen_task.result()
                print_output(f"Scanner read: {barcode}")
                while True:
                    answer = get_input("Is this correct?",variant="confirm")
                    if answer in ["y","Y","n","N"]:
                        break
                    print_output('unexpected response, please enter "y" or "n" followed by Enter', variant="error")
                if answer in ["y","Y"]:
                    break
                print_output("Scan again:")
            else:
                current_buffer = barcode_scan.parser.current_string_buffer.getvalue()
            print_output(f"Listening for barcode timed out - current buffer: {current_buffer}",variant="error")
        except StopAsyncIteration:
            print_output("An error occured when reading from the barcode scanner",variant="error")
            break 
            

def save_scanner_id(scanner_spec):
    # save identity to file in data volume
    print_output("Saving Scanner ID to file", variant="heading")
    
    scanner_identity = {
        "serial": scanner_spec["serial"],
        "vendor_model": scanner_spec["vendor_model"],
        "connection_point": scanner_spec["connection_point"],
        "platform": scanner_spec["platform"],
    }
    import json
    with open("/app/data/scanner_id","w") as f:
        json.dump(scanner_identity,f)



if __name__ == "__main__":
    module_conf_file, user_conf_file, log_level = handle_args()
    logging.basicConfig(level=logging.WARNING)
    conf = config_manager.get_config(module_conf_file, user_conf_file)
    
    if conf["module_enabled"] != True:
        print_output("Module not enabled - exiting",variant="success")
    else:

        # get all static variables as fingerprint
        fingerprint = []
        for var in conf["variable"].values():
            if var["type"]=="static":
                fingerprint.append(f'{var["name"]} = {var["value"]}')

        barcode_scan = BarcodeScanner(conf,{})
        
        print_output("Setting up Barcode Scanning Service Module", variant="heading")
        print_output(f"Service module configured with: \n  {', \n  '.join(fingerprint)}")
        
        if barcode_scan.scanner_serial != "":
            print_output("Barcode scanner already set up",variant="success")
            
            while True:
                while True:
                    options = {1: "Redo setup", 2: "Test barcode scanner", 3: "Exit"}
                    raw_selected_option = get_input("Select an option: ", variant="select", options=options)
                    try:
                        selected_option = int(raw_selected_option)
                        break
                    except ValueError:
                        print_output("Input was not a valid number, please try again.",variant="error")
                
                if selected_option == 1:
                    setup(barcode_scan)
                elif selected_option == 2:
                    barcode_scan.find_scanner()
                    test_scanner(barcode_scan)
                elif selected_option == 3:
                    break
        else:
            setup(barcode_scan)
            
        print_output("Setup complete - exiting", variant="success")