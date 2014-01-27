# -*- coding: utf-8 -*-
'''
Created on 10 Jan 2014

@author: Kimon Tsitsikas

Copyright © 2014 Kimon Tsitsikas, Delmic

This file is part of Odemis.

Odemis is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License version 2 as published by the Free Software Foundation.

Odemis is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Odemis. If not, see http://www.gnu.org/licenses/.
'''
from __future__ import division
import math
from matplotlib import tri
import numpy
from odemis import model
from numpy import ma


# Functions to convert/manipulate Angle resolved image to polar projection
# Based on matlab script created by Ernst Jan Vesseur (from AMOLF)
# Variables to be used in CropMirror and AngleResolved2Polar
# These values correspond to SPARC 2014
AR_XMAX = 13.25e-3  # m, the distance between the parabola origin and the cutoff position
AR_HOLE_DIAMETER = 0.6e-3  # m, diameter the hole in the mirror
AR_FOCUS_DISTANCE = 0.5e-3  # m, the vertical mirror cutoff, iow the distance between the mirror and the sample
AR_PARABOLA_F = 2.5e-3  # m, parabola_parameter=1/4f


def AngleResolved2Polar(data, output_size, hole=True):
    """
    Converts an angle resolved image to polar representation
    data (model.DataArray): The image that was projected on the CCD after being
      relefted on the parabolic mirror. The flat line of the D shape is
      expected to be horizontal, at the top. It needs PIXEL_SIZE and AR_POLE
      metadata. Pixel size is the sensor pixel size * binning / magnification.
    output_size (int): The size of the output DataArray (assumed to be square)
    hole (boolean): Crop the pole if True
    returns (model.DataArray): converted image in polar view
    """
    assert(len(data.shape) == 2)  # => 2D with greyscale

    # Get the metadata
    try:
        pixel_size = data.metadata[model.MD_PIXEL_SIZE]
        mirror_x, mirror_y = data.metadata[model.MD_AR_POLE]
    except KeyError:
        raise ValueError("Metadata required: MD_PIXEL_SIZE, MD_AR_POLE.")

    # Crop the input image to half circle
    cropped_image = _CropHalfCircle(data, pixel_size, (mirror_x, mirror_y), hole)

    theta_data = numpy.empty(shape=cropped_image.shape)
    phi_data = numpy.empty(shape=cropped_image.shape)
    omega_data = numpy.empty(shape=cropped_image.shape)

    # For each pixel of the input ndarray, input metadata is used to
    # calculate the corresponding theta, phi and radiant intensity
    image_x, image_y = cropped_image.shape
    jj = numpy.linspace(0, image_y - 1, image_y)
    xpix = mirror_x - jj

    for i in xrange(image_x):
        ypix = (i - mirror_y) + (2 * AR_PARABOLA_F) / pixel_size[1]
        theta, phi, omega = _FindAngle(xpix, ypix, pixel_size)

        theta_data[i, :] = theta
        phi_data[i, :] = phi
        omega_data[i, :] = cropped_image[i] / omega

    # Convert into polar coordinates
    h_output_size = output_size / 2
    theta = theta_data * (h_output_size / math.pi * 2)
    phi = phi_data
    theta_data = numpy.cos(phi) * theta
    phi_data = numpy.sin(phi) * theta

    # Interpolation into 2d array
#    xi = numpy.linspace(-h_output_size, h_output_size, 2 * h_output_size + 1)
#    yi = numpy.linspace(-h_output_size, h_output_size, 2 * h_output_size + 1)
#    qz = mlab.griddata(phi_data.flat, theta_data.flat, omega_data.flat, xi, yi, interp="linear")

    # FIXME: need rotation (=swap axes), but swapping theta/phi slows down the
    # interpolation by 3 ?!
    triang = tri.delaunay.Triangulation(theta_data.flat, phi_data.flat)
    interp = triang.linear_interpolator(omega_data.flat, default_value=0)
    qz = interp[-h_output_size:h_output_size:complex(0, output_size), # Y
                - h_output_size:h_output_size:complex(0, output_size)] # X
    qz = qz.swapaxes(0, 1)[:, ::-1] # rotate by 90°
    result = model.DataArray(qz, data.metadata)

    return result


def _FindAngle(xpix, ypix, pixel_size):
    """
    For given pixels, finds the angle of the corresponding ray 
    xpix (numpy.array): x coordinates of the pixels
    ypix (float): y coordinate of the pixel
    pixel_size (2 floats): CCD pixelsize (X/Y)
    returns (3 numpy.arrays): theta, phi (the corresponding spherical coordinates for each pixel in ccd) 
                              and omega (solid angle)
    """
    y = xpix * pixel_size[0]
    z = ypix * pixel_size[1]
    r2 = y ** 2 + z ** 2
    xfocus = (1 / (4 * AR_PARABOLA_F)) * r2 - AR_PARABOLA_F
    xfocus2plusr2 = xfocus ** 2 + r2
    sqrtxfocus2plusr2 = numpy.sqrt(xfocus2plusr2)

    # theta
    theta = numpy.arccos(z / sqrtxfocus2plusr2)

    # phi
    phi = numpy.arctan2(y, xfocus) % (2 * math.pi)

    # omega
#    omega = (pixel_size[0] * pixel_size[1]) * ((1 / (2 * AR_PARABOLA_F)) * r2 - xfocus) / (sqrtxfocus2plusr2 * xfocus2plusr2)
    omega = (pixel_size[0] * pixel_size[1]) * ((1 / (4 * AR_PARABOLA_F)) * r2 + AR_PARABOLA_F) / (sqrtxfocus2plusr2 * xfocus2plusr2)

    # Note: the latest version of this function at AMOLF provides a 4th value:
    # irp, the mirror reflectivity for different emission angles.
    # However, it only has a small effect on final output and depends on the
    # wavelength and polarisation of the light, which we do not know.

    return theta, phi, omega

def ARBackgroundSubtract(data):
    """
    Substracts the "baseline" (i.e. the average intensity of the background) from the data.
    This function can be called before AngleResolved2Polar in order to take a better data output.
    data (model.DataArray): The DataArray with the data. Must be 2D. 
     Can have metadata MD_BASELINE to indicate the average 0 value. If not, 
     it must have metadata MD_PIXEL_SIZE and MD_AR_POLE
    returns (model.DataArray): Filtered data
    """
    baseline = 0
    try:
        # If available, use the baseline from the metadata, as it's much faster
        baseline = data.metadata[model.MD_BASELINE]
    except KeyError:
        # If baseline is not provided we calculate it, taking the average intensity of the
        # background (i.e. the pixels that are outside the half circle)
        try:
            pxs = data.metadata[model.MD_PIXEL_SIZE]
            pole_pos = data.metadata[model.MD_AR_POLE]
        except KeyError:
            raise ValueError("Metadata required: MD_PIXEL_SIZE, MD_AR_POLE.")
        circle_mask = _CreateMirrorMask(data, pxs, pole_pos, hole=False)
        masked_image = ma.array(data, mask=circle_mask)

        # Calculate the average value of the outside pixels
        baseline = masked_image.mean()

    # Clip values that will result to negative numbers
    # after the substraction
    ret_data = numpy.where(data < baseline, baseline, data)

    # Substract background
    ret_data -= baseline

    result = model.DataArray(ret_data, data.metadata)
    return result

def _CropHalfCircle(data, pixel_size, pole_pos, hole=True):
    """
    Crops the image to half circle shape based on AR_FOCUS_DISTANCE, AR_XMAX,
      AR_PARABOLA_F, and AR_HOLE_DIAMETER
    data (model.DataArray): The DataArray with the image
    pixel_size (float, float): effective pixel sie = sensor_pixel_size * binning / magnification
    pole_pos (float, float): x/y coordinates of the pole (MD_AR_POLE)
    hole (boolean): Crop the area around the pole if True
    returns (model.DataArray): Cropped image
    """
    # Create mirror mask and apply to the image
    circle_mask = _CreateMirrorMask(data, pixel_size, pole_pos, hole)
    image = numpy.where(circle_mask, data, 0)
    return image

def _CreateMirrorMask(data, pixel_size, pole_pos, hole=True):
    """
    Creates half circle mask (i.e. True inside half circle, False outside it) based
     AR_PARABOLA_F and AR_FOCUS_DISTANCE values.
    data (model.DataArray): The DataArray with the image
    pixel_size (float, float): effective pixel sie = sensor_pixel_size * binning / magnification
    pole_pos (float, float): x/y coordinates of the pole (MD_AR_POLE)
    hole (boolean): Crop the area around the pole if True
    returns (boolean ndarray): Mask
    """
    X, Y = data.shape
    pole_x, pole_y = pole_pos

    # Calculate the coordinates of the cutoff of half circle
    center_x = pole_x
    center_y = pole_y - ((2 * AR_PARABOLA_F - AR_FOCUS_DISTANCE) / pixel_size[1])

    # Compute the radius
    r = (2 * math.sqrt(AR_XMAX * AR_PARABOLA_F)) / pixel_size[1]
    y, x = numpy.ogrid[-center_y:X - center_y, -center_x:Y - center_x]
    circle_mask = x * x + y * y <= r * r

    # Create half circle mask
    circle_mask[:center_y, :] = False

    # Crop the pole making hole of AR_HOLE_DIAMETER
    if hole:
        r = (AR_HOLE_DIAMETER / 2) / pixel_size[1]
        y, x = numpy.ogrid[-pole_y:X - pole_y, -pole_x:Y - pole_x]
        circle_mask_hole = x * x + y * y <= r * r
        circle_mask = numpy.where(circle_mask_hole, 0, circle_mask)

    return circle_mask