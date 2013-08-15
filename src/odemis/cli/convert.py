# -*- coding: utf-8 -*-
'''
Created on 26 Jul 2013

@author: Éric Piel

Copyright © 2013 Éric Piel, Delmic

This file is part of Odemis.

Odemis is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License version 2 as published by the Free Software Foundation.

Odemis is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Odemis. If not, see http://www.gnu.org/licenses/.
'''

# This is a small command line utility to convert files between the different
# file formats supported by Odemis.
# Example usage:
# convert --input file-as.hdf5 --output file-as.ome.tiff

from __future__ import division
from odemis import dataio
import argparse
import logging
import numpy
import odemis
import sys
from gettext import ngettext

logging.getLogger().setLevel(logging.INFO) # use DEBUG for more messages

def open_acq(fn):
    """
    Read the content of an acquisition file
    return (list of DataArray, list of DataArray):
        list of the data in the file
        thumbnail (if available, might be empty)
    """
    fmt_mng = dataio.find_fittest_exporter(fn, default=None)
    if fmt_mng is None:
        logging.warning("Failed to find a fitting importer for file %s", fn)
        # TODO: try all the formats?
        fmt_mng = dataio.hdf5

    if not hasattr(fmt_mng, "read_data"):
        raise NotImplementedError("No support for importing format %s", fmt_mng.FORMAT)

    try:
        data = fmt_mng.read_data(fn)
    except Exception:
        logging.error("Failed to open the file '%s' as %s", fn, fmt_mng.FORMAT)
        raise

    if not data:
        logging.warning("Couldn't load any data from file '%s' as %s",
                        fn, fmt_mng.FORMAT)

    try:
        thumb = fmt_mng.read_thumbnail(fn)
    except Exception:
        logging.exception("Failed to read the thumbnail of file '%s' as %s",
                          fn, fmt_mng.FORMAT)
        # doesn't matter that much

    return data, thumb

def save_acq(fn, data, thumbs):
    """
    Saves to a file the data and thumbnail
    """
    exporter = dataio.find_fittest_exporter(fn)

    # For now the exporter supports only one thumbnail
    if thumbs:
        thumb = thumbs[0]
    else:
        thumb = None
    exporter.export(fn, data, thumb)

def da_sub(daa, dab):
    """
    subtract 2 DataArrays as cleverly as possible:
      * keep the metadata of the first DA in the result
      * ensures the result has the right type so that no underflows happen
    returns (DataArray): the result of daa - dab
    """
    rt = numpy.result_type(daa, dab) # dtype of result of daa-dab

    dt = None # default is to let numpy decide
    if rt.kind == "f":
        # float should always be fine
        pass
    elif rt.kind in "iub":
        # underflow can happen (especially if unsigned)

        # find the worse case value (could be improved, but would be longer)
        worse_val = int(daa.min()) - int(dab.max())
        dt = numpy.result_type(rt, numpy.min_scalar_type(worse_val))
    else:
        # subtracting such a data is suspicious, but try anyway
        logging.warning("Subtraction on data of type %s unsupported", rt.name)

    res = numpy.subtract(daa, dab, dtype=dt) # metadata is copied from daa
    logging.error("type = %s , %s", res.dtype.name, daa.dtype.name)
    return res

def minus(data_a, data_b):
    """
    computes data_a - data_b.
    data_a (list of DataArrays of length N)
    data_b (list of DataArrays of length 1 or N): if length is 1, all the arrays
     in data_a are subtracted from this array, otherwise, each array is subtracted
     1 to 1. 
    returns (list of DataArrays of length N)
    """
    ret = []
    if len(data_b) == 1:
        # subtract the same data from all the data_a
        b = data_b[0]
        for a in data_a:
            r = da_sub(a, b)
            ret.append(r)
    elif len(data_b) == len(data_a):
        for a, b in zip(data_a, data_b):
            r = da_sub(a, b)
            ret.append(r)
    else:
        raise ValueError("Cannot subtract %d images from %d images",
                         len(data_b), len(data_a))
    return ret

def main(args):
    """
    Handles the command line arguments
    args is the list of arguments passed
    return (int): value to return to the OS as program exit code
    """
    # arguments handling
    parser = argparse.ArgumentParser(description="File format conversion utility")

    parser.add_argument('--version', dest="version", action='store_true',
                        help="show program's version number and exit")
    parser.add_argument("--input", "-i", dest="input",
                        help="name of the input file")
    # TODO: list supported file formats for input and output
    parser.add_argument("--output", "-o", dest="output",
            help="name of the output file. The file format is derived from the extension (TIFF and HDF5 are supported).")

    parser.add_argument("--minus", "-m", dest="minus", action='append',
            help="name of an acquisition file whose data is subtracted from the input file.")

    # TODO: --range parameter to select which image to select from the input
    #      (like: 1-4,5,6-10,12)

    options = parser.parse_args(args[1:])

    # Cannot use the internal feature, because it doesn't support multi-line
    if options.version:
        print (odemis.__fullname__ + " " + odemis.__version__ + "\n" +
               odemis.__copyright__ + "\n" +
               "Licensed under the " + odemis.__license__)
        return 0

    infn = options.input
    outfn = options.output

    if not infn or not outfn:
        logging.error("--input and --output arguments must be provided.")
        return 128

    try:
        data, thumbs = open_acq(infn)
    except:
        logging.exception("Error while opening file %s.", infn)
        return 127
    logging.info("File contains %d %s (and %d %s)",
                 len(data), ngettext("image", "images", len(data)),
                 len(thumbs), ngettext("thumbnail", "thumbnails", len(thumbs)))

    if options.minus:
        if thumbs:
            logging.info("Dropping thumbnail due to subtraction")
            thumbs = []
        for fn in options.minus:
            try:
                sdata, sthumbs = open_acq(fn)
            except:
                logging.exception("Error while opening file %s.", fn)
                return 127

            try:
                data = minus(data, sdata)
            except:
                logging.exception("Error while subtracting file %s.", fn)
                return 127

    try:
        save_acq(outfn, data, thumbs)
    except:
        logging.exception("Error while saving file %s.", outfn)
        return 127

    logging.info("Successfully generated file %s", outfn)
    return 0

if __name__ == '__main__':
    ret = main(sys.argv)
    exit(ret)