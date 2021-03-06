#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Created on 16 Jul 2012

@author: Éric Piel
Testing class for main.py of cli.

Copyright © 2012 Éric Piel, Delmic

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
import Image
import StringIO
import logging
from odemis import model
from odemis.cli import main
from odemis.util import driver
import os
import re
import subprocess
import sys
import time
import unittest
from unittest.case import skip

logging.getLogger().setLevel(logging.DEBUG)

ODEMISD_CMD = ["python2", "-m", "odemis.odemisd.main"]
ODEMISCLI_CMD = ["python2", "-m", "odemis.cli.main"]
ODEMISD_ARG = ["--log-level=2", "--log-target=testdaemon.log", "--daemonize"]
CONFIG_PATH = os.path.dirname(__file__) + "/../../../../install/linux/usr/share/odemis/"
SECOM_CONFIG = CONFIG_PATH + "secom-sim.odm.yaml"

class TestWithoutBackend(unittest.TestCase):
    # all the test cases which don't need a backend running

    def setUp(self):
        # reset the logging (because otherwise it accumulates)
        if logging.root:
            del logging.root.handlers[:]
    
#    @skip("Simple")
    def test_help(self):
        """
        It checks handling help option
        """
        try:
            # change the stdout
            out = StringIO.StringIO()
            sys.stdout = out
            
            cmdline = "cli --help"
            ret = main.main(cmdline.split())
        except SystemExit, exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s' returned %d" % (cmdline, ret))
        
        output = out.getvalue()
        self.assertTrue("optional arguments" in output)
    
#    @skip("Simple")
    def test_error_command_line(self):
        """
        It checks handling when wrong number of argument is given
        """
        try:
            cmdline = "cli --set-attr Light power"
            ret = main.main(cmdline.split())
        except SystemExit, exc: # because it's handled by argparse
            ret = exc.code
        self.assertNotEqual(ret, 0, "trying to run erroneous '%s'" % cmdline)

#    @skip("Simple")
    def test_scan(self):
        try:
            # change the stdout
            out = StringIO.StringIO()
            sys.stdout = out
            
            cmdline = "cli --log-level=2 --scan"
            ret = main.main(cmdline.split())
        except SystemExit, exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s' returned %d" % (cmdline, ret))
        
        output = out.getvalue()
        # AndorCam3 SimCam should be there for sure
        self.assertTrue("andorcam3.AndorCam3" in output)
    
#@skip("Simple")
class TestWithBackend(unittest.TestCase):
    backend_was_running = False

    @classmethod
    def setUpClass(cls):
        if driver.get_backend_status() == driver.BACKEND_RUNNING:
            logging.info("A running backend is already found, skipping tests")
            cls.backend_was_running = True
            return

        # run the backend as a daemon
        # we cannot run it normally as the child would also think he's in a unittest
        cmd = ODEMISD_CMD + ODEMISD_ARG + [SECOM_CONFIG]
        ret = subprocess.call(cmd)
        if ret != 0:
            logging.error("Failed starting backend with '%s'", cmd)
        time.sleep(1) # time to start

    def setUp(self):
        if self.backend_was_running:
            self.skipTest("Running backend found")

        # reset the logging (because otherwise it accumulates)
        if logging.root:
            del logging.root.handlers[:]

    @classmethod
    def tearDownClass(cls):
        if cls.backend_was_running:
            return
        # end the backend
        cmd = ODEMISD_CMD + ["--kill"]
        subprocess.call(cmd)
        time.sleep(1) # time to stop

    def tearDown(self):
        model._core._microscope = None # force reset of the microscope for next connection
        time.sleep(1) # time to stop

    def test_list(self):
        try:
            # change the stdout
            out = StringIO.StringIO()
            sys.stdout = out
            
            cmdline = "cli --list"
            ret = main.main(cmdline.split())
        except SystemExit as exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s'" % cmdline)
        
        output = out.getvalue()
        self.assertTrue("Spectra" in output)
        self.assertTrue("Andor SimCam" in output)

    def test_check(self):
        try:
            cmdline = "cli --check"
            ret = main.main(cmdline.split())
        except SystemExit as exc:
            ret = exc.code
        self.assertEqual(ret, 0, "Not detecting backend running")

    def test_list_prop(self):
        try:
            # change the stdout
            out = StringIO.StringIO()
            sys.stdout = out
            
            cmdline = "cli --list-prop Spectra"
            ret = main.main(cmdline.split())
        except SystemExit as exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s'" % cmdline)
        
        output = out.getvalue()
        self.assertTrue("role" in output)
        self.assertTrue("swVersion" in output)
        self.assertTrue("power" in output)

    def test_encoding(self):
        """Check no problem happens due to unicode encoding to ascii"""
        f = open("test.txt", "w")
        cmd = ODEMISCLI_CMD + ["--list-prop", "Spectra"]
        ret = subprocess.check_call(cmd, stdout=f)
        self.assertEqual(ret, 0, "trying to run %s" % cmd)
        f.close()
        os.remove("test.txt")
    
    def test_set_attr(self):
        # to read attribute power
        regex = re.compile("\spower\s.*value:\s*([.0-9]+)")
        
        # read before
        try:
            # change the stdout
            out = StringIO.StringIO()
            sys.stdout = out
            
            cmdline = "cli --list-prop Spectra"
            ret = main.main(cmdline.split())
        except SystemExit as exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s'" % cmdline)
        
        output = out.getvalue()
        power = float(regex.search(output).group(1))
        self.assertGreaterEqual(power, 0, "power should be bigger than 0")   
        
        # set the new value
        try:
            # change the stdout
            out = StringIO.StringIO()
            sys.stdout = out
            
            cmdline = "cli --set-attr Spectra power 0"
            ret = main.main(cmdline.split())
        except SystemExit as exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s'" % cmdline)
        
        # read the new value
        try:
            # change the stdout
            out = StringIO.StringIO()
            sys.stdout = out
            
            cmdline = "cli --list-prop Spectra"
            ret = main.main(cmdline.split())
        except SystemExit as exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s'" % cmdline)
        
        output = out.getvalue()
        power = float(regex.search(output).group(1))
        self.assertEqual(power, 0, "power should be 0")
        
    def test_set_attr_dict(self):
        # set a dict, which is a bit complicated structure
        try:
            # change the stdout
            out = StringIO.StringIO()
            sys.stdout = out
            
            cmdline = ["cli", "--set-attr", "OLStage", "speed", "x: 0.5, y: 0.2"]
            ret = main.main(cmdline)
        except SystemExit as exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s'" % cmdline)
    
    def test_move(self):
        # TODO compare position VA
        # test move and also multiple move requests
        try:
            # change the stdout
            out = StringIO.StringIO()
            sys.stdout = out
            
            cmdline = "cli --move OLStage x 5 --move OLStage y -0.2"
            ret = main.main(cmdline.split())
        except SystemExit as exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s'" % cmdline)

    def test_position(self):
        try:
            # change the stdout
            out = StringIO.StringIO()
            sys.stdout = out

            cmdline = "cli --position OLStage x 50e-6"
            ret = main.main(cmdline.split())
        except SystemExit as exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s'" % cmdline)

    def test_reference(self):
        # On this simulated hardware, no component supports referencing, so
        # just check that referencing correctly reports this
        try:
            # change the stdout
            out = StringIO.StringIO()
            sys.stdout = out

            cmdline = "cli --reference OLStage x"
            ret = main.main(cmdline.split())
        except SystemExit as exc:
            ret = exc.code
        self.assertNotEqual(ret, 0, "Referencing should have failed with '%s'" % cmdline)

    def test_stop(self):
        try:
            # change the stdout
            out = StringIO.StringIO()
            sys.stdout = out
            
            cmdline = "cli --stop"
            ret = main.main(cmdline.split())
        except SystemExit as exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s'" % cmdline)
    
    def test_acquire(self):
        picture_name = "test.tiff"
        size = (1024, 1024)
        
        # change resolution
        try:
            # "Andor SimCam" contains a space, so cut the line ourselves
            cmdline = ["cli", "--set-attr", "Andor SimCam", "resolution", "%d,%d" % size]
            ret = main.main(cmdline)
        except SystemExit as exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s'" % cmdline)
        
        # acquire (simulated) image
        try:
            # "Andor SimCam" contains a space, so cut the line ourselves
            cmdline = ["cli", "--acquire", "Andor SimCam", "--output=%s" % picture_name]
            ret = main.main(cmdline)
        except SystemExit as exc:
            ret = exc.code
        self.assertEqual(ret, 0, "trying to run '%s'" % cmdline)
        
        st = os.stat(picture_name) # this test also that the file is created
        self.assertGreater(st.st_size, 0)
        im = Image.open(picture_name)
        self.assertEqual(im.format, "TIFF")
        self.assertEqual(im.size, size)
    
if __name__ == "__main__":
    unittest.main()
