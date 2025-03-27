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


import io
import os
import json


class Parser:
    def __init__(self):
        # config
        this_dir = os.path.dirname(os.path.realpath(__file__))
        with open(os.path.join(this_dir, 'config.json')) as json_file:
            cfg = json.load(json_file)

        self.plain_table = {y: x for x, y in cfg['plain_table'].items()}
        self.modifier_table = {y: x for x, y in cfg['modifier_table'].items()}
        self.entry_delimiter_list = cfg['entry_delimiter_keycodes']
        self.modifier_list = cfg['modifier_keycodes']

        # vsr setup
        self.current_string_buffer = io.StringIO()
        self.modifiers_pressed = []
        self.delimiters_pressed = []
        self.completed_string_buffer_array = []

    def parse(self, key, down):
        if key in self.modifier_list:
            if down or down == 1:
                self.modifiers_pressed.append(key)
            else:
                self.modifiers_pressed.remove(key)
            return

        if key in self.entry_delimiter_list:
            if down or down == 1:
                self.delimiters_pressed.append(key)
            else:
                self.delimiters_pressed.remove(key)

            if all(elem in self.delimiters_pressed for elem in self.entry_delimiter_list):
                self.completed_string_buffer_array.append(self.current_string_buffer.getvalue())
                self.current_string_buffer.close()
                self.current_string_buffer = io.StringIO()
                return

        try:
            if down == 1:
                if len(self.modifiers_pressed) > 0:
                    value = self.modifier_table[key]  # does not currently differentiate between modifiers
                else:
                    value = self.plain_table[key]
                # print("Parsed > ",value)
                self.current_string_buffer.write(value)
        except KeyError:
            pass  # ignore if key not found
        return

    def complete_available(self):
        return len(self.completed_string_buffer_array) != 0

    def get_next_string(self):
        if len(self.completed_string_buffer_array) > 0:
            val = self.completed_string_buffer_array[0]
            del self.completed_string_buffer_array[0]
            return val
        else:
            return ""


if __name__ == "__main__":
    print('Running Keyparser.py unit tests...')
    x = Parser()
    x.parse(42, 1)  # shift down
    x.parse(30, 1)  # a down
    x.parse(42, 0)  # shift up
    x.parse(30, 0)  # a up
    x.parse(48, 1)  # b down
    x.parse(48, 0)
    x.parse(28, 1)
    x.parse(28, 0)
    assert x.complete_available()
    assert x.get_next_string() == 'Ab'
    assert not x.complete_available()

    x.parse(30, 1)
    x.parse(30, 0)
    x.parse(31, 1)
    x.parse(31, 0)
    x.parse(32, 1)
    x.parse(32, 0),
    x.parse(28, 1),
    x.parse(28, 0),

    x.parse(47, 1)
    x.parse(47, 0)
    x.parse(48, 1)
    x.parse(48, 0)
    x.parse(49, 1)
    x.parse(49, 0),
    x.parse(28, 1),
    x.parse(28, 0),

    assert x.get_next_string() == 'asd'
    assert x.get_next_string() == 'vbn'
    assert not x.complete_available()

    print("successs")
