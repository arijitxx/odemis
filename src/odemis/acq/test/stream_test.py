#-*- coding: utf-8 -*-
"""
@author: Éric Piel

Copyright © 2013 Éric Piel, Delmic

This file is part of Odemis.

Odemis is free software: you can redistribute it and/or modify it under the terms
of the GNU General Public License version 2 as published by the Free Software
Foundation.

Odemis is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
Odemis. If not, see http://www.gnu.org/licenses/.
"""

# Test module for model.Stream classes
from __future__ import division

import logging
import numpy
from odemis import model
import odemis
from odemis.acq import stream, calibration
from odemis.driver import simcam
from odemis.util import driver, conversion, timeout, img
import os
import subprocess
import time
import unittest
from unittest.case import skip


logging.basicConfig(format=" - %(levelname)s \t%(message)s")
logging.getLogger().setLevel(logging.DEBUG)
_frm = "%(asctime)s  %(levelname)-7s %(module)-15s: %(message)s"
logging.getLogger().handlers[0].setFormatter(logging.Formatter(_frm))

ODEMISD_CMD = ["python2", "-m", "odemis.odemisd.main"]
ODEMISD_ARG = ["--log-level=2", "--log-target=testdaemon.log", "--daemonize"]
CONFIG_PATH = os.path.dirname(odemis.__file__) + "/../../install/linux/usr/share/odemis/"
SPARC_CONFIG = CONFIG_PATH + "sparc-sim.odm.yaml"
SECOM_CONFIG = CONFIG_PATH + "secom-sim.odm.yaml"

RGBCAM_CLASS = simcam.Camera
RGBCAM_KWARGS = dict(name="camera", role="overview", image="simcam-fake-overview.h5")

class FakeEBeam(model.Emitter):
    """
    Imitates an e-beam, sufficiently for the Streams
    """
    def __init__(self, name):
        model.Emitter.__init__(self, name, "fakeebeam", parent=None)
        self._shape = (2048, 2048)
        self.dwellTime = model.FloatContinuous(1e-6, (1e-6, 1), unit="s")
        self.resolution = model.ResolutionVA((256, 256), [(1, 1), self._shape])
        self.pixelSize = model.VigilantAttribute((1e-9, 1e-9), unit="m", readonly=True)
        self.magnification = model.FloatVA(1000.)
        self.scale = model.TupleContinuous((1, 1), [(1, 1), self._shape],
                                           cls=(int, long, float), unit="")
        self.translation = model.TupleContinuous((0, 0), ((0, 0), (0, 0)),
                                           cls=(int, long, float), unit="px")

class FakeDetector(model.Detector):
    """
    Imitates an SEM detector, but you need to send the data yourself (using
    comp.data.notify(d)
    """
    def __init__(self, name):
        model.Detector.__init__(self, name, "fakedet", parent=None)
        self.data = model.DataFlow()
        self._shape = (2 ** 16,)

# @skip("simple")
class StreamTestCase(unittest.TestCase):
    def assertTupleAlmostEqual(self, first, second, places=None, msg=None, delta=None):
        """
        check two tuples are almost equal (value by value)
        """
        for f, s in zip(first, second):
            self.assertAlmostEqual(f, s, places=places, msg=msg, delta=delta)


    def _check_square_pixel(self, st):
        rep = st.repetition.value
        roi = st.roi.value
        if roi == stream.UNDEFINED_ROI:
            return
        width = roi[2] - roi[0], roi[3] - roi[1]

        ratio = [n / r for n, r in zip(rep, width)]
        self.assertAlmostEqual(ratio[0], ratio[1], msg="rep = %s, roi = %s" % (rep, roi))

    def test_roi_rep_pxs_links(self):
        """
        Test the connections between .roi, .pixelSize and .repetition of a
        SpectrumStream.
        """
        ebeam = FakeEBeam("ebeam")
        ss = stream.SpectrumSettingsStream("test spec", None, None, ebeam)

        # if roi is UNDEFINED, everything is left unchanged
        ss.roi.value = stream.UNDEFINED_ROI
        ss.pixelSize.value = 1e-8
        self.assertEqual(ss.pixelSize.value, 1e-8)
        ss.repetition.value = (100, 100)
        self.assertEqual(ss.repetition.value, (100, 100))
        self.assertEqual(ss.roi.value, stream.UNDEFINED_ROI)

        # in any cases, a pixel is always square
        self._check_square_pixel(ss)

        # for any value set in ROI, the new ROI value respects:
        # ROI = pixelSize * repetition / phy_size
        # ROI < (0,0,1,1)
        rois = [(0, 0, 1, 1), (0.1, 0.1, 0.8, 0.8), (0.00001, 0.1, 1, 0.2)]
        epxs = ebeam.pixelSize.value
        eshape = ebeam.shape
        phy_size = [epxs[0] * eshape[0], epxs[1] * eshape[1]] # max physical ROI
        for roi in rois:
            ss.roi.value = roi
            new_roi = ss.roi.value
            rep = ss.repetition.value
            pxs = ss.pixelSize.value
            exp_roi_size = [rep[0] * pxs / phy_size[0],
                            rep[1] * pxs / phy_size[1]]
            roi_size = [new_roi[2] - new_roi[0], new_roi[3] - new_roi[1]]
            self.assertTupleAlmostEqual(roi_size, exp_roi_size,
                             msg="with roi = %s => %s" % (roi, new_roi))
            self.assertTrue(new_roi[0] >= 0 and new_roi[1] >= 0 and
                            new_roi[2] <= 1 and new_roi[3] <= 1,
                            "with roi = %s => %s" % (roi, new_roi))
            self._check_square_pixel(ss)

        ss.pixelSize.value = ss.pixelSize.range[0] # needed to get the finest grain
        ss.roi.value = (0.3, 0.65, 0.5, 0.9)
        # changing one repetition dimension is always respected.
        rep = list(ss.repetition.value)
        rep[0] //= 2
        ss.repetition.value = rep
        self.assertEqual(ss.repetition.value[0], rep[0])
        self._check_square_pixel(ss)
        rep = list(ss.repetition.value)
        rep[1] //= 2
        ss.repetition.value = rep
        self.assertEqual(ss.repetition.value[1], rep[1])
        self._check_square_pixel(ss)

        # Changing 2 repetition dimensions at once respects at least one
        rep = [rep[0] * 2, int(round(rep[1] * 1.4))]
        ss.repetition.value = rep
        new_rep = list(ss.repetition.value)
        self.assertTrue(rep[0] == new_rep[0] or rep[1] == new_rep[1])
        self._check_square_pixel(ss)

        # 1x1 repetition leads to a square ROI
        ss.repetition.value = (1, 1)
        new_roi = ss.roi.value
        roi_size = [new_roi[2] - new_roi[0], new_roi[3] - new_roi[1]]
        self.assertAlmostEqual(roi_size[0], roi_size[1])
        self._check_square_pixel(ss)

        ss.pixelSize.value = ss.pixelSize.range[0]
        ss.roi.value = (0, 0, 1, 1)
        # Changing pixel size to the minimum leads to the smallest pixel size
        ss.pixelSize.value = ss.pixelSize.range[0]
        self.assertAlmostEqual(ss.pixelSize.value, max(ebeam.pixelSize.value))
        self.assertEqual(tuple(ss.repetition.value), ebeam.shape)
        self._check_square_pixel(ss)


        # TODO: changing pixel size to a huge number leads to a 1x1 repetition

        # When changing both repetition dims, they are both respected
        ss.pixelSize.value = ss.pixelSize.range[0]
        ss.roi.value = (0.3, 0.65, 0.5, 0.6)
        ss.repetition.value = (3, 5)
        new_rep = (5, 6)
        ss.repetition.value = new_rep
        self.assertAlmostEqual(new_rep, ss.repetition.value)
        self._check_square_pixel(ss)

        # Changing the SEM magnification updates the pixel size (iff the
        # magnification cannot be automatically linked to the actual SEM
        # magnification).
        old_rep = ss.repetition.value
        old_roi = ss.roi.value
        old_pxs = ss.pixelSize.value
        old_mag = ebeam.magnification.value
        ebeam.magnification.value = old_mag * 2
        new_pxs = ss.pixelSize.value
        new_mag = ebeam.magnification.value
        mag_ratio = new_mag / old_mag
        pxs_ratio = new_pxs / old_pxs
        self.assertAlmostEqual(mag_ratio, 1 / pxs_ratio)
        self.assertEqual(old_rep, ss.repetition.value)
        self.assertEqual(old_roi, ss.roi.value)
        self._check_square_pixel(ss)


    def test_rgb_camera_stream(self):
        cam = RGBCAM_CLASS(**RGBCAM_KWARGS)
        rgbs = stream.RGBCameraStream("rgb", cam, cam.data, None) # no emitter

        dur = 0.1
        cam.exposureTime.value = dur

        # at start, no data
        img = rgbs.image.value
        self.assertIsNone(img)

        # acquire for a few seconds
        rgbs.should_update.value = True
        rgbs.is_active.value = True

        time.sleep(3 * dur)

        # Should have received a few images
        img = rgbs.image.value
        # check it looks like RGB
        self.assertEqual(img.metadata[model.MD_DIMS], "YXC")
        self.assertEqual(img.dtype, numpy.uint8)
        self.assertEqual(img.ndim, 3)
        self.assertEqual(img.shape, tuple(cam.resolution.value) + (3,))

        rgbs.is_active.value = False
        rgbs.should_update.value = False

        # Check it stopped updating
        img = rgbs.image.value
        time.sleep(2 * dur)
        img2 = rgbs.image.value
        self.assertIs(img, img2)

    def test_histogram(self):
        """
        Check the histogram updates correctly, including if the BPP changes
        """
        ebeam = FakeEBeam("ebeam")
        se = FakeDetector("se")
        ss = stream.SEMStream("test", se, se.data, ebeam)

        # without data, the histogram should be empty, and the intensity range
        # based on the depth of the detector
        h = ss.histogram.value
        ir = ss.intensityRange.range
        self.assertEqual(len(h), 0)
        self.assertEqual((ir[0][0], ir[1][1]), (0, se.shape[0] - 1))

        # "start" the stream, so it expects data
        ss.should_update.value = True
        ss.is_active.value = True

        # send a simple 8 bit image (with correct metadata) =>
        #  * The intensity range should update to 8-bit
        #  * The histogram should be 256 long
        d = numpy.zeros(ebeam.shape[::-1], "uint8")
        md = {model.MD_BPP: 8,
                    model.MD_PIXEL_SIZE: (1e-6, 2e-5), # m/px
                    model.MD_POS: (1e-3, -30e-3), # m
                    }
        da = model.DataArray(d, md)
        se.data.notify(da)

        time.sleep(0.5) # make sure all the delayed code is executed
        self.assertIsInstance(ss.image.value, model.DataArray)
        h = ss.histogram.value
        ir = ss.intensityRange.range
        self.assertEqual(len(h), 256)
        self.assertEqual((ir[0][0], ir[1][1]), (0, (2 ** 8) - 1))

        # Send a 16 bit image with 16 BPP =>
        #  * The intensity range should update to 16-bit
        #  * The histogram should stay not too long (<=1024 values)
        d = numpy.zeros(ebeam.shape[::-1], "uint16")
        md = {model.MD_BPP: 16,
                    model.MD_PIXEL_SIZE: (1e-6, 2e-5), # m/px
                    model.MD_POS: (1e-3, -30e-3), # m
                    }
        da = model.DataArray(d, md)
        se.data.notify(da)

        time.sleep(0.5) # make sure all the delayed code is executed
        self.assertIsInstance(ss.image.value, model.DataArray)
        h = ss.histogram.value
        ir = ss.intensityRange.range
        self.assertLessEqual(len(h), 1024)
        self.assertEqual((ir[0][0], ir[1][1]), (0, (2 ** 16) - 1))

        # Send a 16 bit image with 12 BPP =>
        #  * The intensity range should update to 12-bit
        #  * The histogram should stay not too long (<=1024 values)
        d = numpy.zeros(ebeam.shape[::-1], "uint16")
        md = {model.MD_BPP: 12,
                    model.MD_PIXEL_SIZE: (1e-6, 2e-5), # m/px
                    model.MD_POS: (1e-3, -30e-3), # m
                    }
        da = model.DataArray(d, md)
        se.data.notify(da)

        time.sleep(0.5) # make sure all the delayed code is executed
        self.assertIsInstance(ss.image.value, model.DataArray)
        h = ss.histogram.value
        ir = ss.intensityRange.range
        self.assertLessEqual(len(h), 1024)
        self.assertEqual((ir[0][0], ir[1][1]), (0, (2 ** 12) - 1))

# @skip("faster")
class SECOMTestCase(unittest.TestCase):
    """
    Tests to be run with a (simulated) SECOM
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
        cmd = ODEMISD_CMD + ODEMISD_ARG + [SECOM_CONFIG]
        ret = subprocess.call(cmd)
        if ret != 0:
            logging.error("Failed starting backend with '%s'", cmd)
        time.sleep(1) # time to start

        # Find CCD & SEM components
        cls.ccd = model.getComponent(role="ccd")
        cls.light = model.getComponent(role="light")
        cls.light_filter = model.getComponent(role="filter")
        cls.ebeam = model.getComponent(role="e-beam")
        cls.sed = model.getComponent(role="se-detector")

    @classmethod
    def tearDownClass(cls):
        if cls.backend_was_running:
            return
        # end the backend
        cmd = ODEMISD_CMD + ["--kill"]
        subprocess.call(cmd)
        model._core._microscope = None # force reset of the microscope for next connection
        time.sleep(1) # time to stop

    def setUp(self):
        if self.backend_was_running:
            self.skipTest("Running backend found")

    def test_default_fluo(self):
        """
        Check the default values for the FluoStream are fitting the current HW
        settings
        """
        em_choices = self.light_filter.axes["band"].choices

        # no light info
        self.light.emissions.value = [0] * len(self.light.emissions.value)
        s1 = stream.FluoStream("fluo1", self.ccd, self.ccd.data,
                               self.light, self.light_filter)
        # => stream emission is based on filter
        self.assertEqual(s1.excitation.choices, set(self.light.spectra.value))
        self.assertEqual(set(s1.emission.choices),
                         set(conversion.ensureTuple(em_choices.values())))

        em_idx = self.light_filter.position.value["band"]
        em_hw = em_choices[em_idx]
        self.assertEqual(s1.emission.value, conversion.ensureTuple(em_hw))

        # => stream excitation is light spectra closest below emission
        self.assertIn(s1.excitation.value, self.light.spectra.value)
        em_center = numpy.mean(em_hw)
        ex_centers = [s[2] for s in s1.excitation.choices]
        try:
            expected_ex = min([c for c in ex_centers if c < em_center],
                              key=lambda c: em_center - c)
        except ValueError: # no excitation < em_center
            expected_ex = min(ex_centers)
        self.assertEqual(s1.excitation.value[2], expected_ex)

        # with light info (last emission is used)
        self.light.emissions.value[-1] = 0.9
        s2 = stream.FluoStream("fluo2", self.ccd, self.ccd.data,
                               self.light, self.light_filter)
        # => stream emission is based on filter
        self.assertEqual(s2.excitation.choices, set(self.light.spectra.value))
        self.assertEqual(set(s2.emission.choices),
                         set(conversion.ensureTuple(em_choices.values())))

        em_idx = self.light_filter.position.value["band"]
        em_hw = em_choices[em_idx]
        self.assertEqual(s2.emission.value, conversion.ensureTuple(em_hw))

        # => stream excitation is based on light.emissions
        self.assertIn(s2.excitation.value, self.light.spectra.value)
        expected_ex = self.light.spectra.value[-1] # last value of emission
        self.assertEqual(s2.excitation.value, expected_ex)

    def test_fluo(self):
        """
        Check that the hardware settings are correctly set based on the settings
        """
        s1 = stream.FluoStream("fluo1", self.ccd, self.ccd.data,
                               self.light, self.light_filter)
        self.ccd.exposureTime = 1 # s, to avoid acquiring too many images

        # Check we manage to get at least one image
        self._image = None
        s1.image.subscribe(self._on_image)

        s1.should_update.value = True
        s1.is_active.value = True

        # change the stream setting (for each possible excitation)
        for i, exc in enumerate(self.light.spectra.value):
            s1.excitation.value = exc
            time.sleep(0.1)
            # check the hardware setting is updated
            exp_intens = [0] * len(self.light.spectra.value)
            exp_intens[i] = 1
            self.assertEqual(self.light.emissions.value, exp_intens)

        time.sleep(2)
        s1.is_active.value = False

        self.assertFalse(self._image is None, "No image received after 2s")

    def _on_image(self, im):
        self._image = im


# @skip("faster")
class SPARCTestCase(unittest.TestCase):
    """
    Tests to be run with a (simulated) SPARC
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
        cmd = ODEMISD_CMD + ODEMISD_ARG + [SPARC_CONFIG]
        ret = subprocess.call(cmd)
        if ret != 0:
            logging.error("Failed starting backend with '%s'", cmd)
        time.sleep(1) # time to start

        # Find CCD & SEM components
        cls.ccd = model.getComponent(role="ccd")
        cls.spec = model.getComponent(role="spectrometer")
        cls.ebeam = model.getComponent(role="e-beam")
        cls.sed = model.getComponent(role="se-detector")

    @classmethod
    def tearDownClass(cls):
        if cls.backend_was_running:
            return
        # end the backend
        cmd = ODEMISD_CMD + ["--kill"]
        subprocess.call(cmd)
        model._core._microscope = None # force reset of the microscope for next connection
        time.sleep(1) # time to stop

    def setUp(self):
        if self.backend_was_running:
            self.skipTest("Running backend found")

#    @skip("simple")
    def test_progressive_future(self):
        """
        Test .acquire interface (should return a progressive future with updates)
        """
        self.image = None
        self.done = False
        self.updates = 0

        # Create the stream
        sems = stream.SEMStream("test sem", self.sed, self.sed.data, self.ebeam)
        ars = stream.ARStream("test ar", self.ccd, self.ccd.data, self.ebeam)
        sas = stream.SEMARMDStream("test sem-ar", sems, ars)

        ars.roi.value = (0.1, 0.1, 0.8, 0.8)
        self.ccd.binning.value = (4, 4) # hopefully always supported

        # Long acquisition
        self.ccd.exposureTime.value = 0.2 # s
        ars.repetition.value = (2, 3)
        exp_shape = ars.repetition.value[::-1]
        num_ar = numpy.prod(ars.repetition.value)

        # Start acquisition
        timeout = 1 + 1.5 * sas.estimateAcquisitionTime()
        f = sas.acquire()
        f.add_update_callback(self.on_progress_update)
        f.add_done_callback(self.on_done)

        data = f.result(timeout)
        self.assertEqual(len(data), num_ar + 1)
        self.assertEqual(data[0].shape, exp_shape)
        self.assertGreaterEqual(self.updates, 4) # at least a couple of updates
        self.assertEqual(self.left, 0)
        self.assertTrue(self.done)
        self.assertTrue(not f.cancelled())

        # short acquisition
        self.done = False
        self.updates = 0
        self.ccd.exposureTime.value = 0.02 # s
        ars.repetition.value = (5, 4)
        exp_shape = ars.repetition.value[::-1]
        num_ar = numpy.prod(ars.repetition.value)

        # Start acquisition
        timeout = 1 + 1.5 * sas.estimateAcquisitionTime()
        f = sas.acquire()
        f.add_update_callback(self.on_progress_update)
        f.add_done_callback(self.on_done)

        data = f.result(timeout)
        self.assertEqual(len(data), num_ar + 1)
        self.assertEqual(data[0].shape, exp_shape)
        self.assertGreaterEqual(self.updates, 5) # at least a few updates
        self.assertEqual(self.left, 0)
        self.assertTrue(self.done)
        self.assertTrue(not f.cancelled())

#    @skip("simple")
    def test_sync_future_cancel(self):
        self.image = None

        # Create the stream
        sems = stream.SEMStream("test sem", self.sed, self.sed.data, self.ebeam)
        ars = stream.ARStream("test ar", self.ccd, self.ccd.data, self.ebeam)
        sas = stream.SEMARMDStream("test sem-ar", sems, ars)

        ars.roi.value = (0.1, 0.1, 0.8, 0.8)
        self.ccd.binning.value = (4, 4) # hopefully always supported

        # Long acquisition
        self.updates = 0
        self.ccd.exposureTime.value = 0.2 # s
        ars.repetition.value = (2, 3)

        # Start acquisition
        f = sas.acquire()
        f.add_update_callback(self.on_progress_update)
        f.add_done_callback(self.on_done)

        time.sleep(self.ccd.exposureTime.value) # wait a bit
        f.cancel()

        self.assertGreaterEqual(self.updates, 1) # at least at the end
        self.assertEqual(self.left, 0)
        self.assertTrue(f.cancelled())

        # short acquisition
        self.updates = 0
        self.ccd.exposureTime.value = 0.02 # s
        ars.repetition.value = (5, 4)

        # Start acquisition
        f = sas.acquire()
        f.add_update_callback(self.on_progress_update)
        f.add_done_callback(self.on_done)

        time.sleep(self.ccd.exposureTime.value) # wait a bit
        f.cancel()

        self.assertGreaterEqual(self.updates, 1) # at least at the end
        self.assertEqual(self.left, 0)
        self.assertTrue(f.cancelled())

    def on_done(self, future):
        self.done = True

    def on_progress_update(self, future, past, left):
        self.past = past
        self.left = left
        self.updates += 1

#    @skip("simple")
    def test_acq_ar(self):
        """
        Test short & long acquisition for AR
        """
        # Create the stream
        sems = stream.SEMStream("test sem", self.sed, self.sed.data, self.ebeam)
        ars = stream.ARStream("test ar", self.ccd, self.ccd.data, self.ebeam)
        sas = stream.SEMARMDStream("test sem-ar", sems, ars)

        ars.roi.value = (0.1, 0.1, 0.8, 0.8)
        self.ccd.binning.value = (4, 4) # hopefully always supported

        # Long acquisition (small rep to avoid being too long)
        # The acquisition method is different for time > 0.1 s, but we had bugs
        # with dwell time > 4s, so let's directly test both.
        self.ccd.exposureTime.value = 5 # s
        ars.repetition.value = (2, 3)
        exp_shape = ars.repetition.value[::-1]
        num_ar = numpy.prod(ars.repetition.value)

        # Start acquisition
        timeout = 1 + 1.5 * sas.estimateAcquisitionTime()
        start = time.time()
        f = sas.acquire()

        # wait until it's over
        data = f.result(timeout)
        dur = time.time() - start
        logging.debug("Acquisition took %g s", dur)
        self.assertTrue(f.done())
        self.assertEqual(len(data), len(sems.raw) + len(ars.raw))
        self.assertEqual(len(sems.raw), 1)
        self.assertEqual(sems.raw[0].shape, exp_shape)
        self.assertEqual(len(ars.raw), num_ar)
        md = ars.raw[0].metadata
        self.assertIn(model.MD_POS, md)
        self.assertIn(model.MD_AR_POLE, md)

        # Short acquisition (< 0.1s)
        self.ccd.exposureTime.value = 0.03 # s
        ars.repetition.value = (30, 20)
        exp_shape = ars.repetition.value[::-1]
        num_ar = numpy.prod(ars.repetition.value)

        # Start acquisition
        timeout = 1 + 1.5 * sas.estimateAcquisitionTime()
        start = time.time()
        f = sas.acquire()

        # wait until it's over
        data = f.result(timeout)
        dur = time.time() - start
        logging.debug("Acquisition took %g s", dur)
        self.assertTrue(f.done())
        self.assertEqual(len(data), len(sems.raw) + len(ars.raw))
        self.assertEqual(len(sems.raw), 1)
        self.assertEqual(sems.raw[0].shape, exp_shape)
        self.assertEqual(len(ars.raw), num_ar)
        md = ars.raw[0].metadata
        self.assertIn(model.MD_POS, md)
        self.assertIn(model.MD_AR_POLE, md)

#    @skip("simple")
    def test_acq_spec(self):
        """
        Test short & long acquisition for Spectrometer
        """
        # Create the stream
        sems = stream.SEMStream("test sem", self.sed, self.sed.data, self.ebeam)
        specs = stream.SpectrumStream("test spec", self.spec, self.spec.data, self.ebeam)
        sps = stream.SEMSpectrumMDStream("test sem-spec", sems, specs)

        specs.roi.value = (0.15, 0.6, 0.8, 0.8)

        # Long acquisition (small rep to avoid being too long) > 0.1s
        self.spec.exposureTime.value = 0.3 # s
        specs.repetition.value = (5, 6)
        exp_shape = specs.repetition.value[::-1]

        # Start acquisition
        timeout = 1 + 1.5 * sps.estimateAcquisitionTime()
        start = time.time()
        f = sps.acquire()

        # wait until it's over
        data = f.result(timeout)
        dur = time.time() - start
        logging.debug("Acquisition took %g s", dur)
        self.assertTrue(f.done())
        self.assertEqual(len(data), len(sems.raw) + len(specs.raw))
        self.assertEqual(len(sems.raw), 1)
        self.assertEqual(sems.raw[0].shape, exp_shape)
        self.assertEqual(len(specs.raw), 1)
        sshape = specs.raw[0].shape
        self.assertEqual(len(sshape), 5)
        self.assertGreater(sshape[0], 1) # should have at least 2 wavelengths
        sem_md = sems.raw[0].metadata
        spec_md = specs.raw[0].metadata
        self.assertAlmostEqual(sem_md[model.MD_POS], spec_md[model.MD_POS])
        self.assertAlmostEqual(sem_md[model.MD_PIXEL_SIZE], spec_md[model.MD_PIXEL_SIZE])

        # Short acquisition (< 0.1s)
        self.spec.exposureTime.value = 0.01 # s
        specs.repetition.value = (25, 60)
        exp_shape = specs.repetition.value[::-1]

        # Start acquisition
        timeout = 1 + 1.5 * sps.estimateAcquisitionTime()
        start = time.time()
        f = sps.acquire()

        # wait until it's over
        data = f.result(timeout)
        dur = time.time() - start
        logging.debug("Acquisition took %g s", dur)
        self.assertTrue(f.done())
        self.assertEqual(len(data), len(sems.raw) + len(specs.raw))
        self.assertEqual(len(sems.raw), 1)
        self.assertEqual(sems.raw[0].shape, exp_shape)
        self.assertEqual(len(specs.raw), 1)
        sshape = specs.raw[0].shape
        self.assertEqual(len(sshape), 5)
        self.assertGreater(sshape[0], 1) # should have at least 2 wavelengths
        sem_md = sems.raw[0].metadata
        spec_md = specs.raw[0].metadata
        self.assertAlmostEqual(sem_md[model.MD_POS], spec_md[model.MD_POS])
        self.assertAlmostEqual(sem_md[model.MD_PIXEL_SIZE], spec_md[model.MD_PIXEL_SIZE])

    def test_count(self):
        cs = stream.CameraCountStream("test count", self.spec, self.spec.data, self.ebeam)
        self.spec.exposureTime.value = 0.1
        exp = self.spec.exposureTime.value
        res = self.spec.resolution.value
        rot = numpy.prod(res) / self.spec.readoutRate.value
        dur = exp + rot
        cs.windowPeriod.value = 15 * dur

        # at start, no data => empty window
        window = cs.image.value
        self.assertEqual(len(window), 0)

        # acquire for a few seconds
        cs.should_update.value = True
        cs.is_active.value = True

        time.sleep(5 * dur)
        # Should have received at least a few data, and max 5
        window = cs.image.value
        logging.debug("%s", window)
        self.assertTrue(2 <= len(window) <= 5, len(window))
        self.assertEqual(window.ndim, 1)
        dates = window.metadata[model.MD_ACQ_DATE]
        self.assertLess(dates[0], dates[-1])
        first_date = dates[0]

        time.sleep(15 * dur)
        # Should have received enough data to fill the window
        window = cs.image.value
        logging.debug("%s", window)
        self.assertTrue(10 <= len(window) <= 16, len(window))

        time.sleep(5 * dur)
        # Window should stay long enough
        window = cs.image.value
        logging.debug("%s", window)
        self.assertTrue(10 <= len(window) <= 16, len(window))
        dates = window.metadata[model.MD_ACQ_DATE]
        self.assertTrue(first_date < dates[0] < dates[-1])


#@skip("faster")
class TestStaticStreams(unittest.TestCase):
    """
    Test static streams, which don't need any backend running
    """

#     @skip("simple")
    def test_ar(self):
        """Test StaticARStream"""
        # AR background data
        md = {model.MD_SW_VERSION: "1.0-test",
             model.MD_HW_NAME: "fake ccd",
             model.MD_DESCRIPTION: "AR",
             model.MD_ACQ_DATE: time.time(),
             model.MD_BPP: 12,
             model.MD_BINNING: (1, 1), # px, px
             model.MD_SENSOR_PIXEL_SIZE: (13e-6, 13e-6), # m/px
             model.MD_PIXEL_SIZE: (2e-5, 2e-5), # m/px
             model.MD_POS: (1.2e-3, -30e-3), # m
             model.MD_EXP_TIME: 1.2, # s
             model.MD_AR_POLE: (253.1, 65.1),
             model.MD_LENS_MAG: 0.4, # ratio
            }

        # AR data
        md0 = dict(md)
        data0 = model.DataArray(1500 + numpy.zeros((512, 1024), dtype=numpy.uint16), md0)
        md1 = dict(md)
        md1[model.MD_POS] = (1.5e-3, -30e-3)
        md1[model.MD_BASELINE] = 300 # AR background should take this into account
        data1 = model.DataArray(6345 + numpy.zeros((512, 1024), dtype=numpy.uint16), md1)

        logging.info("setting up stream")
        ars = stream.StaticARStream("test", [data0, data1])

        # Control AR projection
        im2d0 = ars.image.value
        # Check it's a RGB DataArray
        self.assertEqual(im2d0.shape[2], 3)

        logging.info("changing AR pos")
        # Wait a bit to be sure the projection doesn't get postponed to later
        time.sleep(0.2)
        # change position
        for p in ars.point.choices:
            if p != (None, None) and p != ars.point.value:
                ars.point.value = p
                break
        else:
            self.fail("Failed to find a second point in AR")

        im2d1 = ars.image.value
        # Check it's a RGB DataArray
        self.assertEqual(im2d1.shape[2], 3)

        self.assertFalse(im2d0 is im2d1)

        logging.info("testing image background correction")
        # test background correction from image
        dcalib = numpy.ones((1, 1, 1, 512, 1024), dtype=numpy.uint16)
        calib = model.DataArray(dcalib, md)

        time.sleep(0.2)
        ars.background.value = calib
        numpy.testing.assert_equal(ars.background.value, calib[0, 0, 0])

        im2dc = ars.image.value
        # Check it's a RGB DataArray
        self.assertEqual(im2dc.shape[2], 3)

        self.assertFalse(im2d1 is im2dc)

    def _create_spec_data(self):
        # Spectrum
        data = numpy.ones((251, 1, 1, 200, 300), dtype="uint16")
        data[:, 0, 0, :, 3] = numpy.random.randint(0, 2 ** 12 - 1, (200,))
        data[2, :, :, :, :] = range(300)
        data[200, 0, 0, 2] = range(300)
        wld = 433e-9 + numpy.array(range(data.shape[0])) * 0.1e-9
        md = {model.MD_SW_VERSION: "1.0-test",
             model.MD_HW_NAME: "fake ccd",
             model.MD_DESCRIPTION: "Spectrum",
             model.MD_ACQ_DATE: time.time(),
             model.MD_BPP: 12,
             model.MD_PIXEL_SIZE: (2e-5, 2e-5), # m/px
             model.MD_POS: (1.2e-3, -30e-3), # m
             model.MD_EXP_TIME: 0.2, # s
             model.MD_LENS_MAG: 60, # ratio
             model.MD_WL_LIST: wld,
            }
        return model.DataArray(data, md)

    def test_spec_2d(self):
        """Test StaticSpectrumStream 2D"""
        spec = self._create_spec_data()
        specs = stream.StaticSpectrumStream("test", spec)

        # Control spatial spectrum
        im2d = specs.image.value
        # Check it's a RGB DataArray
        self.assertEqual(im2d.shape, spec.shape[-2:] + (3,))
        # Check it's at the right position
        md2d = im2d.metadata
        self.assertEqual(md2d[model.MD_POS], spec.metadata[model.MD_POS])

        # change bandwidth to max
        specs.spectrumBandwidth.value = (specs.spectrumBandwidth.range[0][0],
                                         specs.spectrumBandwidth.range[1][1])
        im2d = specs.image.value
        self.assertEqual(im2d.shape, spec.shape[-2:] + (3,))

        # Check RGB spatial projection
        time.sleep(0.2)
        specs.fitToRGB.value = True
        im2d = specs.image.value
        self.assertEqual(im2d.shape, spec.shape[-2:] + (3,))

    def test_spec_0d(self):
        """Test StaticSpectrumStream 0D"""
        spec = self._create_spec_data()
        specs = stream.StaticSpectrumStream("test", spec)

        # Check 0D spectrum
        specs.selected_pixel.value = (1, 1)
        sp0d = specs.get_pixel_spectrum()
        wl0d = specs.get_spectrum_range()
        self.assertEqual(sp0d.shape, (spec.shape[0],))
        self.assertEqual(wl0d.shape, (spec.shape[0],))
        self.assertEqual(sp0d.dtype, spec.dtype)
        self.assertTrue(numpy.all(sp0d <= spec.max()))

    def test_spec_1d(self):
        """Test StaticSpectrumStream 1D"""
        spec = self._create_spec_data()
        specs = stream.StaticSpectrumStream("test", spec)

        # Check 1d spectrum on corner-case: parallel to the X axis
        specs.selected_line.value = [(3, 7), (3, 65)]
        sp1d = specs.get_line_spectrum()
        wl1d = specs.get_spectrum_range()
        self.assertEqual(sp1d.ndim, 3)
        self.assertEqual(sp1d.shape, (65 - 7 + 1, spec.shape[0], 3))
        self.assertEqual(sp1d.dtype, numpy.uint8)
        self.assertEqual(wl1d.shape, (spec.shape[0],))
        self.assertEqual(sp1d.metadata[model.MD_PIXEL_SIZE][1],
                         spec.metadata[model.MD_PIXEL_SIZE][0])

        # compare to doing it manually, by cutting the band at 3
        sp1d_raw_ex = spec[:, 0, 0, 65:6:-1, 3]
        # make it contiguous to be sure to get the fast conversion, because
        # there are (still) some minor differences with the slow conversion
        sp1d_raw_ex = numpy.ascontiguousarray(sp1d_raw_ex.swapaxes(0, 1))

        # Need to convert to RGB to compare
        hist, edges = img.histogram(sp1d_raw_ex)
        irange = img.findOptimalRange(hist, edges, 1 / 256)
        sp1d_rgb_ex = img.DataArray2RGB(sp1d_raw_ex, irange)
        numpy.testing.assert_equal(sp1d, sp1d_rgb_ex)

        # Check 1d spectrum in diagonal
        specs.selected_line.value = [(30, 65), (1, 1)]
        sp1d = specs.get_line_spectrum()
        wl1d = specs.get_spectrum_range()
        self.assertEqual(sp1d.ndim, 3)
        # There is not too much expectations on the size of the spatial axis
        self.assertTrue(29 <= sp1d.shape[0] <= (64 * 1.41))
        self.assertEqual(sp1d.shape[1], spec.shape[0])
        self.assertEqual(sp1d.shape[2], 3)
        self.assertEqual(sp1d.dtype, numpy.uint8)
        self.assertEqual(wl1d.shape, (spec.shape[0],))
        self.assertGreaterEqual(sp1d.metadata[model.MD_PIXEL_SIZE][1],
                                spec.metadata[model.MD_PIXEL_SIZE][0])


        # Check 1d with larger width
        specs.selected_line.value = [(30, 65), (5, 1)]
        specs.width.value = 12
        sp1d = specs.get_line_spectrum()
        wl1d = specs.get_spectrum_range()
        self.assertEqual(sp1d.ndim, 3)
        # There is not too much expectations on the size of the spatial axis
        self.assertTrue(29 <= sp1d.shape[0] <= (64 * 1.41))
        self.assertEqual(sp1d.shape[1], spec.shape[0])
        self.assertEqual(sp1d.shape[2], 3)
        self.assertEqual(sp1d.dtype, numpy.uint8)
        self.assertEqual(wl1d.shape, (spec.shape[0],))

        specs.selected_line.value = [(30, 65), (5, 12)]
        specs.width.value = 13 # brings bad luck?
        sp1d = specs.get_line_spectrum()
        wl1d = specs.get_spectrum_range()
        self.assertEqual(sp1d.ndim, 3)
        # There is not too much expectations on the size of the spatial axis
        self.assertTrue(29 <= sp1d.shape[0] <= (53 * 1.41))
        self.assertEqual(sp1d.shape[1], spec.shape[0])
        self.assertEqual(sp1d.shape[2], 3)
        self.assertEqual(sp1d.dtype, numpy.uint8)
        self.assertEqual(wl1d.shape, (spec.shape[0],))


    def test_spec_calib(self):
        """Test StaticSpectrumStream calibration"""
        spec = self._create_spec_data()
        specs = stream.StaticSpectrumStream("test", spec)

        # Check efficiency compensation
        prev_im2d = specs.image.value

        dbckg = numpy.ones(spec.shape, dtype=numpy.uint16)
        wl_bckg = 400e-9 + numpy.array(range(dbckg.shape[0])) * 10e-9
        obckg = model.DataArray(dbckg, metadata={model.MD_WL_LIST: wl_bckg})
        bckg = calibration.get_spectrum_data([obckg])

        dcalib = numpy.array([1, 1.3, 2, 3.5, 4, 5, 1.3, 6, 9.1], dtype=numpy.float)
        dcalib.shape = (dcalib.shape[0], 1, 1, 1, 1)
        wl_calib = 400e-9 + numpy.array(range(dcalib.shape[0])) * 10e-9
        calib = model.DataArray(dcalib, metadata={model.MD_WL_LIST: wl_calib})

        specs.efficiencyCompensation.value = calib

        specs.background.value = bckg

        # Control spatial spectrum
        im2d = specs.image.value
        # Check it's a RGB DataArray
        self.assertEqual(im2d.shape, spec.shape[-2:] + (3,))
        self.assertTrue(numpy.any(im2d != prev_im2d))



if __name__ == "__main__":
    unittest.main()
