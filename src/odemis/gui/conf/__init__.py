# -*- coding: utf-8 -*-
"""
Created on 14 Jan 2013

@author: Rinze de Laat

Copyright © 2013 Rinze de Laat, Delmic

This file is part of Odemis.

Odemis is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License version 2 as published by the Free
Software Foundation.

Odemis is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
Odemis. If not, see http://www.gnu.org/licenses/.


### Purpose ###

This module contains all code needed for the access to and management of GUI
related configuration files.

"""

from ConfigParser import NoOptionError
import ConfigParser
from abc import ABCMeta, abstractproperty
import logging
import math
from odemis.dataio import tiff
from odemis.gui.util import get_picture_folder, get_home_folder
import os.path


CONF_PATH = os.path.join(get_home_folder(), u".config/odemis")
ACQUI_PATH = get_picture_folder()

CONF_GENERAL = None
def get_general_conf():
    global CONF_GENERAL

    if not CONF_GENERAL:
        CONF_GENERAL = GeneralConfig()

    return CONF_GENERAL

CONF_ACQUI = None
def get_acqui_conf():
    """ Return the Acquisition config object and create/read it first if it does
        not yet exist.
    """
    global CONF_ACQUI

    if not CONF_ACQUI:
        CONF_ACQUI = AcquisitionConfig()

    return CONF_ACQUI

CONF_CALIB = None
def get_calib_conf():
    """ Return the calibration config object and create/read it first if it does
        not yet exist.
    """
    global CONF_CALIB

    if not CONF_CALIB:
        CONF_CALIB = CalibrationConfig()

    return CONF_CALIB


class Config(object):
    """ Configuration super class

        Configurations are built around the
        :py:class:`ConfigParser.SafeConfigParser` class.

        The main difference is that the filename is fixed, and changes are
        automatically saved.
    """
    __metaclass__ = ABCMeta
    @abstractproperty
    def file_name(self):
        """Name of the configuration file"""
        pass

    def __init__(self):
        # Absolute path to the configuration file
        self.file_path = os.path.abspath(os.path.join(CONF_PATH, self.file_name))
        # Attribute that contains the actual configuration
        self.config = ConfigParser.SafeConfigParser()

        # Note: the defaults argument of ConfigParser doesn't do enough, because
        # it only allows to specify default options values, independent of the
        # section.

        # Default configuration used to check for completeness
        self.default = ConfigParser.SafeConfigParser()

        self.read()

    def read(self):
        """ Will try to read the configuration file and will use the default.
            values when it fails.
        """
        if os.path.exists(self.file_path):
            self.config.read(self.file_path)
        else:
            logging.warn(u"Using default %s configuration",
                         self.__class__.__name__)
            self.use_default()

            # Create the file and save the default configuration, so the user
            # will be able to see the option exists. The drawback is that if we
            # change the default settings later on, the old installs will not
            # catch them up automatically.
            # TODO: => save the default settings as comments?
            self.write()

    def write(self):
        """
        Write the configuration file
        """
        # Create directory structure if it doesn't exist.
        if not os.path.exists(CONF_PATH):
            logging.debug(u"Creating path '%s'", CONF_PATH)
            os.makedirs(CONF_PATH)

        logging.debug(u"Writing configuration file '%s'", self.file_path)
        f = open(self.file_path, "w")
        self.config.write(f)
        f.close()

    def use_default(self):
        """ Assign the default configuration to the main one """
        self.config = self.default

    def set(self, section, option, value):
        """ Set the value of an option """
        if not self.config.has_section(section):
            logging.warn("Section %s not found, creating...", section)
            self.config.add_section(section)
        self.config.set(section, option, value)
        self.write()

    def get(self, section, option):
        """ Get the value of an option """
        try:
            return self.config.get(section, option)
        except (ConfigParser.NoOptionError, ConfigParser.NoSectionError):
            return self.default.get(section, option)

class GeneralConfig(Config):
    """ General configuration values """

    file_name = "odemis.config"
    def __init__(self):

        super(GeneralConfig, self).__init__()

        # Define the default settings
        self.default.add_section("help")

        self.default.set("help",
                         "manual_base_name",
                         u"user-guide.pdf"
                        )

        self.default.set("help",
                         "manual_path",
                         u"/usr/share/doc/odemis/"
                        )

        # For the calibration files (used in analysis tab)
        self.default.add_section("calibration")
        self.default.set("calibration", "ar_file", u"")
        self.default.set("calibration", "spec_file", u"")
        self.default.set("calibration", "spec_bck_file", u"")

    def get_manual(self, role=None):
        """ This method returns the path to the user manual

        First, it will look for a specific manual if a role is defined. If no
        role is defined or it does not exists, it will try and find the general
        user manual and return its path. If that also fails, None is returned.
        """
        manual_path = self.get("help", "manual_path")
        manual_base_name = self.get("help", "manual_base_name")

        if role:
            full_path = os.path.join(
                                manual_path,
                                u"%s-%s" % (role, manual_base_name)
                        )
            if os.path.exists(full_path):
                return full_path
            else:
                logging.info("%s manual not found, will use default one.", role)

        full_path = os.path.join(manual_path, manual_base_name)
        if os.path.exists(full_path):
            return full_path
        else:
            return None

    def get_dev_manual(self):
        """
        Returns (unicode): the path to the developer manual (or None)
        """
        manual_path = self.get("help", "manual_path")
        full_path = os.path.join(manual_path, u"odemis-develop.pdf")
        if os.path.exists(full_path):
            return full_path
        return None

class AcquisitionConfig(Config):

    file_name = "acquisition.config"
    def __init__(self):
        super(AcquisitionConfig, self).__init__()

        # Define the default settings
        self.default.add_section("acquisition")
        self.default.set("acquisition", "last_path", ACQUI_PATH)
        self.default.set("acquisition", "last_format", tiff.FORMAT)
        self.default.set("acquisition", "last_extension", tiff.EXTENSIONS[0])

    @property
    def last_path(self):
        lp = self.get("acquisition", "last_path")
        # Check that it (still) exists, and if not, fallback to the default
        if not os.path.isdir(lp):
            lp = ACQUI_PATH
        return lp

    @last_path.setter
    def last_path(self, last_path):
        self.set("acquisition", "last_path", last_path)

    @property
    def last_format(self):
        return self.get("acquisition", "last_format")

    @last_format.setter
    def last_format(self, value):
        self.set("acquisition", "last_format", value)

    @property
    def last_extension(self):
        return self.get("acquisition", "last_extension")

    @last_extension.setter
    def last_extension(self, last_extension):
        self.set("acquisition", "last_extension", last_extension)

class CalibrationConfig(Config):
    """
    For saving/restoring sample holder calibration data in the Delphi
    """

    file_name = "calibration.config"

    def _get_section_name(self, shid):
        return "delphi-%x" % shid

    def set_sh_calib(self, shid, htop, hbot, strans, sscale, srot, iscale, irot,
                     resa, resb, hfwa, spotshift):
        """
        Store the calibration data for a given sample holder
        shid (int): the sample holder ID
        htop (2 floats): position of the top hole
        hbot (2 floats): position of the bottom hole
        strans (2 floats): stage translation
        sscale (2 floats > 0): stage scaling
        srot (float): stage rotation (rad)
        iscale (2 floats > 0): image scaling
        irot (float): image rotation (rad)
        resa (2 floats): resolution related SEM image shift, slope of linear fit
        resb (2 floats): resolution related SEM image shift, intercept of linear fit
        hfwa (2 floats): hfw related SEM image shift, slope of linear fit
        spotshift (2 floats): SEM spot shift in percentage of HFW
        """
        sec = self._get_section_name(shid)
        if self.config.has_section(sec):
            logging.info("ID %s already exists, overwriting...", sec)
        else:
            self.config.add_section(sec)

        # Don't use self.set() to avoid checking the section/writing every time
        self.config.set(sec, "top_hole_x", "%.15f" % htop[0])
        self.config.set(sec, "top_hole_y", "%.15f" % htop[1])
        self.config.set(sec, "bottom_hole_x", "%.15f" % hbot[0])
        self.config.set(sec, "bottom_hole_y", "%.15f" % hbot[1])
        self.config.set(sec, "stage_trans_x", "%.15f" % strans[0])
        self.config.set(sec, "stage_trans_y", "%.15f" % strans[1])
        self.config.set(sec, "stage_scaling_x", "%.15f" % sscale[0])
        self.config.set(sec, "stage_scaling_y", "%.15f" % sscale[1])
        self.config.set(sec, "stage_rotation", "%.15f" % srot)
        self.config.set(sec, "image_scaling_x", "%.15f" % iscale[0])
        self.config.set(sec, "image_scaling_y", "%.15f" % iscale[1])
        self.config.set(sec, "image_rotation", "%.15f" % irot)
        self.config.set(sec, "resolution_a_x", "%.15f" % resa[0])
        self.config.set(sec, "resolution_a_y", "%.15f" % resa[1])
        self.config.set(sec, "resolution_b_x", "%.15f" % resb[0])
        self.config.set(sec, "resolution_b_y", "%.15f" % resb[1])
        self.config.set(sec, "hfw_a_x", "%.15f" % hfwa[0])
        self.config.set(sec, "hfw_a_y", "%.15f" % hfwa[1])
        self.config.set(sec, "spot_shift_x", "%.15f" % spotshift[0])
        self.config.set(sec, "spot_shift_y", "%.15f" % spotshift[1])
        self.write()

    def _get_tuple(self, section, option):
        """
        Reads a tuple of float with the option name + _x and _y
        return (2 floats)
        raises:
            ValueError: if the config file doesn't contain floats
            NoOptionError: if not all the options are present
        """
        x = self.config.getfloat(section, option + "_x")
        y = self.config.getfloat(section, option + "_y")
        return x, y

    def get_sh_calib(self, shid):
        """
        Reads the calibration of a given sample holder
        shid (int): the sample holder ID
        returns None (if no calibration data available), or :
            htop (2 floats): position of the top hole
            hbot (2 floats): position of the bottom hole
            strans (2 floats): stage translation
            sscale (2 floats > 0): stage scaling
            srot (float): stage rotation
            iscale (2 floats > 0): image scaling
            irot (float): image rotation
            resa (2 floats): resolution related SEM image shift, slope of linear fit
            resb (2 floats): resolution related SEM image shift, intercept of linear fit
            hfwa (2 floats): hfw related SEM image shift, slope of linear fit
            spotshift (2 floats): SEM spot shift in percentage of HFW
        """
        sec = self._get_section_name(shid)
        if self.config.has_section(sec):
            try:
                htop = self._get_tuple(sec, "top_hole")
                hbot = self._get_tuple(sec, "bottom_hole")
                strans = self._get_tuple(sec, "stage_trans")

                sscale = self._get_tuple(sec, "stage_scaling")
                if not (sscale[0] > 0 and sscale[1] > 0):
                    raise ValueError("stage_scaling %s must be > 0", sscale)

                srot = self.config.getfloat(sec, "stage_rotation")
                if not 0 <= srot <= (2 * math.pi):
                    raise ValueError("stage_rotation %f out of range", srot)

                iscale = self._get_tuple(sec, "image_scaling")
                if not (iscale[0] > 0 and iscale[1] > 0):
                    raise ValueError("image_scaling %s must be > 0", iscale)

                irot = self.config.getfloat(sec, "image_rotation")
                if not 0 <= irot <= (2 * math.pi):
                    raise ValueError("image_rotation %f out of range", irot)

                resa = self._get_tuple(sec, "resolution_a")
                resb = self._get_tuple(sec, "resolution_b")
                hfwa = self._get_tuple(sec, "hfw_a")
                spotshift = self._get_tuple(sec, "spot_shift")
                return htop, hbot, strans, sscale, srot, iscale, irot, resa, resb, hfwa, spotshift
            except (ValueError, NoOptionError):
                logging.info("Not all calibration data readable, new calibration is required",
                             exc_info=True)
            except Exception:
                logging.exception("Failed to read calibration data")

        return None

