# -*- coding: utf-8 -*-
'''
Created on 25 April 2014

@author: Kimon Tsitsikas

Copyright © 2013-2014 Kimon Tsitsikas, Delmic

This file is part of Odemis.

Odemis is free software: you can redistribute it and/or modify it under the terms 
of the GNU General Public License version 2 as published by the Free Software 
Foundation.

Odemis is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; 
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR 
PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with 
Odemis. If not, see http://www.gnu.org/licenses/.
'''
import logging
import time
import os
import unittest
import subprocess

from odemis.util import driver
from odemis import model
from odemis.dataio import hdf5
import odemis
from odemis.acq import align
from odemis.acq.align import autofocus
from scipy import ndimage

logging.basicConfig(format=" - %(levelname)s \t%(message)s")
logging.getLogger().setLevel(logging.DEBUG)
_frm = "%(asctime)s  %(levelname)-7s %(module)-15s: %(message)s"
logging.getLogger().handlers[0].setFormatter(logging.Formatter(_frm))

# ODEMISD_CMD = ["/usr/bin/python2", "-m", "odemis.odemisd.main"]
# -m doesn't work when run from PyDev... not entirely sure why
ODEMISD_CMD = ["/usr/bin/python2", os.path.dirname(odemis.__file__) + "/odemisd/main.py"]
ODEMISD_ARG = ["--log-level=2", "--log-target=testdaemon.log", "--daemonize"]
CONFIG_PATH = os.path.dirname(odemis.__file__) + "/../../install/linux/usr/share/odemis/"
logging.debug("Config path = %s", CONFIG_PATH)
SECOM_LENS_CONFIG = CONFIG_PATH + "secom-focus-test.odm.yaml"  # 7x7


class TestAutofocus(unittest.TestCase):
    """
    Test autofocus functions
    """
    backend_was_running = False

    @classmethod
    def setUpClass(cls):

        if driver.get_backend_status() == driver.BACKEND_RUNNING:
            logging.info("A running backend is already found, skipping tests")
            cls.backend_was_running = True
            return

        # run the backend as a daemon
        # we cannot run it normally as the child would also think he's in a unittest
        cmd = ODEMISD_CMD + ODEMISD_ARG + [SECOM_LENS_CONFIG]
        ret = subprocess.call(cmd)
        if ret != 0:
            logging.error("Failed starting backend with '%s'", cmd)
        time.sleep(1)  # time to start

        # find components by their role
        cls.ebeam = model.getComponent(role="e-beam")
        cls.sed = model.getComponent(role="se-detector")
        cls.ccd = model.getComponent(role="ccd")
        cls.focus = model.getComponent(role="focus")
        cls.align = model.getComponent(role="align")
        cls.light = model.getComponent(role="light")
        cls.light_filter = model.getComponent(role="filter")

    @classmethod
    def tearDownClass(cls):
        if cls.backend_was_running:
            return
        # end the backend
        cmd = ODEMISD_CMD + ["--kill"]
        subprocess.call(cmd)
        model._core._microscope = None  # force reset of the microscope for next connection
        time.sleep(1)  # time to stop

    def setUp(self):
        self.data = hdf5.read_data("grid_10x10.h5")
        C, T, Z, Y, X = self.data[0].shape
        self.data[0].shape = Y, X
        self.fake_img = self.data[0]

        if self.backend_was_running:
            self.skipTest("Running backend found")

    def test_measure_focus(self):
        """
        Test MeasureFocus
        """
        input = self.fake_img

        prev_res = autofocus.MeasureFocus(input)
        for i in range(1, 10, 1):
            input = ndimage.gaussian_filter(input, sigma=i)
            res = autofocus.MeasureFocus(input)
            self.assertGreater(prev_res, res)
            prev_res = res

    def test_autofocus(self):
        """
        Test AutoFocus
        """
        focus = self.focus
        ebeam = self.ebeam
        ccd = self.ccd
        focus.moveAbs({"z": 60e-06})
        future_focus = align.AutoFocus(ccd, ebeam, focus, 10e-06)
        foc_pos, fm_final = future_focus.result()
        self.assertAlmostEqual(foc_pos, 0, 4)

if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAutofocus)
    unittest.TextTestRunner(verbosity=2).run(suite)
