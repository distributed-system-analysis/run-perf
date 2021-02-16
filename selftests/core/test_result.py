#!/bin/env python3
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
#
# Copyright: Red Hat Inc. 2020
# Author: Lukas Doktor <ldoktor@redhat.com>
"""
Tests for the result.py module
"""

# pylint: disable=W0212

import unittest
from runperf import result


class ResultUtils(unittest.TestCase):

    """Various profile unit tests"""

    def test_get_uncertainty(self):
        self.assertEqual(result.get_uncertainty(1), 7)
        self.assertEqual(result.get_uncertainty(4), 1.4)
        self.assertEqual(result.get_uncertainty(8), 1.2)
        self.assertEqual(result.get_uncertainty(9), 1)
        self.assertEqual(result.get_uncertainty(50), 1)
        self.assertRaises(ValueError, result.get_uncertainty, 0)
        self.assertRaises(ValueError, result.get_uncertainty, -5)
