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

def function(name, value, extra):
    mapping = {"receive": "I", "send": "O"}
    return mapping[value]
