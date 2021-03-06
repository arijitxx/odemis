# -*- coding: utf-8 -*-
"""
Created on 18 April 2014

@author: Kimon Tsitsikas

Copyright © 2013-2014 Éric Piel & Kimon Tsitsikas, Delmic

This file is part of Odemis.

Odemis is free software: you can redistribute it and/or modify it under the
terms  of the GNU General Public License version 2 as published by the Free
Software  Foundation.

Odemis is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY;  without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR  PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
Odemis. If not, see http://www.gnu.org/licenses/.
"""

from __future__ import division

import logging
from odemis.model._metadata import MD_PIXEL_SIZE

from .autofocus import AutoFocus
from .delphi import UpdateConversion
from .find_overlay import FindOverlay
from .spot import AlignSpot, FindSpot
from odemis.dataio import hdf5


def FindEbeamCenter(ccd, detector, escan):
    """
    Locate the center of the SEM image by setting the SEM to spot mode and
    measuring the position of the spot on the CCD. It is mostly targeted at
    doing it fast. In particular it doesn’t do any focusing or multiple
    iterations with feedback loop.
    ccd (model.DigitalCamera):    The ccd
    detector (model.Detector):    The se-detector
    escan (model.Emitter):    The e-beam scanner
    return (tuple of 2 floats): x, y position of the spot relative to the
     center of the CCD.
    raise:
        LookupError: if the spot cannot be found
    """
    logging.debug("Starting ebeam spot detection...")
    # save the hw settings
    prev_exp = ccd.exposureTime.value
    prev_bin = ccd.binning.value
    prev_res = ccd.resolution.value

    try:
        # set the CCD to maximum resolution
        ccd.binning.value = (1, 1)
        ccd.resolution.value = ccd.resolution.range[1]

        # store current settings
        no_spot_settings = (escan.dwellTime.value,
                            escan.resolution.value)
        # set ebeam to spot mode
        # resolution -> translation: order matters
        escan.resolution.value = (1, 1)

        # put a not too short dwell time to avoid acquisition to keep repeating,
        # and not too long to avoid using too much memory for acquiring one point.
        escan.dwellTime.value = escan.dwellTime.range[1]  # s
        # Subscribe to actually set the spot mode
        detector.data.subscribe(discard_data)

        exp = 0.1  # start value
        prev_img = None
        while exp < 2:  # above 2 s it means something went wrong
            ccd.exposureTime.value = exp

            img = ccd.data.get(False)
            if prev_img is not None:
                img += prev_img  # accumulate, to increase the signal

            try:
                coord = FindSpot(img, sensitivity_limit=10)
            except ValueError as e:
                # if no spot just try again
                if e.args[0] == "No spot detected":
                    pass
                # if too many, stop trying, we probably need to focus
                else:
                    break
            else:
                # found a spot! => convert position to meters from center
                pxs = img.metadata[MD_PIXEL_SIZE]
                center = (img.shape[1] / 2, img.shape[0] / 2)  # shape is Y,X
                pos = (-(coord[0] - center[0]) * pxs[0],
                        (coord[1] - center[1]) * pxs[1])  # physical Y is opposite direction
                return pos
            # try longer exposure time
            prev_img = img
            exp *= 2

    finally:
        detector.data.unsubscribe(discard_data)
        # restore hw settings
        (escan.dwellTime.value,
         escan.resolution.value) = no_spot_settings
        ccd.exposureTime.value = prev_exp
        ccd.binning.value = prev_bin
        ccd.resolution.value = prev_res

    raise LookupError("Failed to locate spot after exposure time %g s", exp)


def discard_data(df, data):
    """
    Does nothing, just discard the SEM data received (for spot mode)
    """
    pass
