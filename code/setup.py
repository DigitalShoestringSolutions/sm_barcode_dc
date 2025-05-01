import logging
import utilities.config_manager as config_manager
from main import handle_args
import evdev

from barcode_scan import BarcodeScanner

if __name__ == "__main__":
    module_conf_file, user_conf_file, log_level = handle_args()
    logging.basicConfig(level=logging.WARNING)
    conf = config_manager.get_config(module_conf_file, user_conf_file)

    # get all static variables as fingerprint
    fingerprint = []
    for var in conf["variable"]:
        if var["type"]=="static":
            fingerprint.append(f'{var["name"]} = {var["value"]}')

    barcode_scan = BarcodeScanner(conf,{})
    
    print("")
    print("==========================================")
    print("Setting up Barcode Scanning Service Module")
    print("==========================================")
    print("")
    print(f"Service module configured with: \n  {', \n  '.join(fingerprint)}")
    print("")
    scanner_spec = None
    while True:
        print("==========================================")
        print("Identifying barcode scanner:")
        print("==========================================")
        
        print("If the Scanner is plugged in, please unplug it now.\n Press Enter to continue.")
        input()
        available_without = barcode_scan.available_devices()
        print("Please plug it back in and press Enter to continue.")
        input()
        available_with = barcode_scan.available_devices()
        
        # get differences
        for id in available_without.keys():
            del available_with[id]
        
        
        print("==========================================")
        if len(available_with) == 0: # no difference
            print("No change in USB devices detected between when scanner was plugged in and unplugged")
        elif len(available_with) == 1:
            print("Found")
            scanner_spec = available_with[0]
            break
        else:
            print("Multiple USB device changes detected between when scanner was plugged in and unplugged")
        
        print("==========================================")
        
        while True:
            print("Try again? [y/n]")
            answer = input()
            if answer in ["y","Y","n","N"]:
                break
            print('unexpected response, please enter "y" or "n" followed by Enter')
        if answer in ["n","N"]:
            break
    
     # fall back to select from list
    if scanner_spec is None:
        print("==========================================")
        print("The auto dectection process didn't work -\nfalling back to selecting from a list\n")
        while True:
            print("")
            available_list =  list(barcode_scan.available_devices().values())
            if len(available_list) == 0:
                print("No USB devices detected...")
            else:
                for index, entry in enumerate(available_list):
                    print(f'{index+1} - {entry["serial"]} {entry["vendor_model"]}')
            
            print("")
            raw_selected_index = input("Which entry is the barcode scanner that should be used?\n(enter the Number, enter 0 to re-scan): ")
            try:
                selected_index = int(raw_selected_index)
                if selected_index == 0:
                    continue
                scanner_spec = available_list[selected_index-1]
                break
            except ValueError:
                print("\n!! Input was not a valid number, please try again.")
            except IndexError:
                if len(available_list)>=1:
                    print(f"\n!! Number was too high, expected a number between 1 and {len(available_list)}.")
                else:
                    print(f"\n!! No devices available to select from")
            
            print("==========================================") 

    
    # validate test scan
    print(scanner_spec)
    dev = scanner_spec["dev"]
    scanner_device = barcode_scan.grab_exclusive_access(evdev.InputDevice(dev.device_node))
    
    import asyncio
    loop = asyncio.new_event_loop()
    generator =  barcode_scan.key_event_loop()
    
    print("==========================================")
    print("Checking barcode scanner works:")
    print("==========================================")
    print("Please scan a barcode to check that the scanner is working.")
    print("All scanned barcodes will be printed below.")
    while True:
        try: 
            barcode, timestamp = loop.run_until_complete(generator.__anext__())
            print(f"Scanner read: {barcode}")
            while True:
                print("Is this correct? [y/n]")
                answer = input()
                if answer in ["y","Y","n","N"]:
                    break
                print('unexpected response, please enter "y" or "n" followed by Enter')
            if answer in ["y","Y"]:
                break
        except StopAsyncIteration:
            print("An error occured when reading from the barcode scanner")
            break 
    
    # save identity to file in data volume
    print("==========================================")
    print("Saving Scanner ID to file:")
    print("==========================================")
    print("")
    
    scanner_identity = {
        "serial": scanner_spec["serial"],
        "vendor_model": scanner_spec["vendor_model"],
        "connection_point": scanner_spec["connection_point"],
        "platform": scanner_spec["platform"],
    }
    import json
    with open("/app/data/scanner_id") as f:
        json.dump(scanner_identity,f)
     
    print("==========================================")
    print("Finished")
    print("==========================================")
    