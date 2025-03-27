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

try:
    import tomllib
except ImportError:
    import tomli as tomllib

import jsonschema
import json
import os
import logging
import sys
import time

logger = logging.getLogger("config")


def get_config(arg_module_file=None, arg_user_file=None):
    user_config_file, user_config_src = select_file(
        arg_user_file, "USER_CONFIG_FILE", "./user_config/user_config.toml"
    )

    user_config = load_config(user_config_file, user_config_src)
    user_config_specified_module_config_file = user_config.get(
        "module_config_file", None)

    other_module_config_sources = [
        (user_config_specified_module_config_file, "user config")]
    module_config_file, module_config_src = select_file(
        arg_module_file,
        "MODULE_CONFIG_FILE",
        "./module_config/module_config.toml",
        other_sources=other_module_config_sources,
    )

    module_config = load_config(module_config_file, module_config_src)

    with open("./config_schema.json", "rb") as f:
        schema = json.load(f)

    do_validate(module_config, schema, "module")

    combined_config = combine(module_config, user_config)
    env_var_overwrite(combined_config)

    do_validate(combined_config, schema, "combined")

    logger.info(f"Final Config: {combined_config}")
    return combined_config


def select_file(arg_file, env_var, default, other_sources=[]):
    config_file = (default, "default")
    
    for file, src in other_sources:
        if file:
            config_file = (file, src)

    if arg_file:
        config_file = (arg_file, "args")

    env_file = os.getenv(env_var)

    if env_file:
        config_file = (env_file, "env")

    return config_file


def load_config(filename, src):
    try:
        with open(filename, "rb") as f:
            config = tomllib.load(f)
        logger.info(f'Loaded config file "{filename}" specified in {src}')
        return config
    except FileNotFoundError:
        logger.critical(
            f'Config File Not Found - unable to load config file "{filename}" specified by {src}.')
        logger.critical("Unable to start solution - please specify a valid config file or make sure the service module can access the file specified")
        while True:
            logger.critical("Config File not found - Going to sleep to avoid unnecessary restarts")     
            time.sleep(36000)        


def do_validate(config, schema, label=""):
    try:
        jsonschema.validate(instance=config, schema=schema,
                            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)
    except jsonschema.ValidationError as v_err:
        logger.critical(
            f"CONFIG ERROR on {label} - {v_err.json_path} >> {v_err.message}")
        logger.critical("Config File is not valid -- unable to start the solution -- please correct the issues flagged above and try again.")
        while True:
            logger.critical("Config File not valid - Going to sleep to avoid unnecessary restarts")     
            time.sleep(36000)        


def combine(A, B):
    output = A.copy()
    do_combine(output, B)
    return output


def do_combine(original, new):
    for k, v in new.items():
        if k in original:
            if isinstance(original[k], dict):    # handle nesting
                do_combine(original[k], v)
            else:   # handle value replacement
                original[k] = v
        else:  # handle new value
            original[k] = v


def env_var_overwrite(config, parent=None):
    for key, value in config.items():
        current_key = f"{parent}__{key.upper()}" if parent else key.upper()
        if isinstance(value, dict):
            env_var_overwrite(value, parent=current_key)
        else:
            new_value = os.environ.get(current_key)
            if new_value is not None:
                logger.info(f"Overwrote config with {current_key}:{new_value}")
                config[key] = new_value


if __name__ == "__main__":
    print(get_config())
