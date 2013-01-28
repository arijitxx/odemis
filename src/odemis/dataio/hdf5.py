# -*- coding: utf-8 -*-
'''
Created on 14 Jan 2013

@author: Éric Piel

Copyright © 2013 Éric Piel, Delmic

This file is part of Odemis.

Odemis is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 2 of the License, or (at your option) any later version.

Odemis is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Odemis. If not, see http://www.gnu.org/licenses/.
'''
from __future__ import division
from odemis import model
from datetime import datetime
import h5py
import numpy
import os
import time
# User-friendly name
FORMAT = "HDF5"
# list of file-name extensions possible, the first one is the default when saving a file 
EXTENSIONS = [".h5", ".hdf5"]

# We are trying to follow the same format as SVI, as defined here:
# http://www.svi.nl/HDF5
# A file follows this structure:
# + /
#   + Preview (this our extension, to contain thumbnails)
#     + RGB image (*) (HDF5 Image with Dimension Scales)
#     + DimensionScale*
#     + *Offset (position on the axis)
#   + AcquisitionName (one per set of emitter/detector) 
#     + ImageData
#       + Image (HDF5 Image with Dimension Scales CTZXY)
#       + DimensionScale*
#       + *Offset (position on the axis)
#     + PhysicalData
#     + SVIData (Not necessary for us)


# Image is an official extension to HDF5:
# http://www.hdfgroup.org/HDF5/doc/ADGuide/ImageSpec.html


# h5py doesn't implement explicitly HDF5 image, and is not willing to cf:
# http://code.google.com/p/h5py/issues/detail?id=157
def _create_image_dataset(group, dataset_name, image, **kwargs):
    """
    Create a dataset respecting the HDF5 image specification
    http://www.hdfgroup.org/HDF5/doc/ADGuide/ImageSpec.html
   
    group (HDF group): the group that will contain the dataset
    dataset_name (string): name of the dataset
    image (numpy.ndimage): the image to create. It should have at least 2 dimensions
    returns the new dataset
    """
    assert(len(image.shape) >= 2)
    image_dataset = group.create_dataset(dataset_name, data=image, **kwargs)
       
    # numpy.string_ is to force fixed-length string (necessary for compatibility)
    image_dataset.attrs["CLASS"] = numpy.string_("IMAGE")
    # Colour image?
    if len(image.shape) == 3 and (image.shape[0] == 3 or image.shape[2] == 3):
        # TODO: check dtype is int?
        image_dataset.attrs["IMAGE_SUBCLASS"] = numpy.string_("IMAGE_TRUECOLOR")
        image_dataset.attrs["IMAGE_COLORMODEL"] = numpy.string_("RGB")
        if image.shape[0] == 3:
            # Stored as [pixel components][height][width]
            image_dataset.attrs["INTERLACE_MODE"] = numpy.string_("INTERLACE_PLANE")
        else: # This is the numpy standard
            # Stored as [height][width][pixel components]
            image_dataset.attrs["INTERLACE_MODE"] = numpy.string_("INTERLACE_PIXEL")
    else:
        image_dataset.attrs["IMAGE_SUBCLASS"] = numpy.string_("IMAGE_GRAYSCALE")
        image_dataset.attrs["IMAGE_WHITE_IS_ZERO"] = numpy.array(0, dtype="uint8")
        idtype = numpy.iinfo(image.dtype)
        image_dataset.attrs["IMAGE_MINMAXRANGE"] = [image.min(), image.max()]
    
    image_dataset.attrs["DISPLAY_ORIGIN"] = numpy.string_("UL") # not rotated
    image_dataset.attrs["IMAGE_VERSION"] = numpy.string_("1.2")
   
    return image_dataset

def _add_image_info(group, dataset, image):
    """
    Adds the basic metadata information about an image (scale and offset)
    group (HDF Group): the group that contains the dataset
    dataset (HDF Dataset): the image dataset
    image (DataArray >= 2D): image with metadata, the last 2 dimensions are Y and X (H,W)
    """

    # Note: DimensionScale support is only part of h5py since v2.1
    # Dimensions
    # The order of the dimension is reversed (the slowest changing is last)
    l = len(dataset.dims)
    dataset.dims[l-1].label = "X"
    dataset.dims[l-2].label = "Y"
    # support more dimensions if available:
    if l >= 3:
        dataset.dims[l-3].label = "Z"
    if l >= 4:
        dataset.dims[l-4].label = "T"
    if l >= 5:
        dataset.dims[l-5].label = "C"
    
    # Offset
    if model.MD_POS in image.metadata:
        pos = image.metadata[model.MD_POS]
        group["XOffset"] = pos[0]
        _h5svi_set_state(group["XOffset"], ST_REPORTED)
        group["XOffset"].attrs["UNIT"] = "m" # our extension
        group["YOffset"] = pos[1]
        _h5svi_set_state(group["YOffset"], ST_REPORTED)
        group["YOffset"].attrs["UNIT"] = "m" # our extension
    
    # Time
    # TODO: is this correct? strange that it's a string? Is there a special type?
    # Surprisingly (for such a usual type), time storage is a mess in HDF5.
    # The documentation states that you can use H5T_TIME, but it is 
    # "is not supported. If H5T_TIME is used, the resulting data will be readable
    # and modifiable only on the originating computing platform; it will not be
    # portable to other platforms.". It appears many format are allowed.
    # In addition in h5py, it's indicated as "deprecated" (although it seems
    # it was added in the latest version of HDF5. 
    # Moreover, the only types available are 32 and 64 bits integers as number
    # of seconds since epoch. No past, no milliseconds, no time-zone. 
    # So there are other proposals like in in F5 
    # (http://sciviz.cct.lsu.edu/papers/2007/F5TimeSemantics.pdf) to represent
    # time with a float, a unit and an offset.
    # KNMI uses a string like this: DD-MON-YYYY;HH:MM:SS.sss. 
    # (cf http://www.knmi.nl/~beekhuis/documents/publicdocs/ir2009-01_hdftag36.pdf)
    # So, to not solve anything, we save the date as a float representing the 
    # Unix time. At least it make Huygens happy.
    if model.MD_ACQ_DATE in image.metadata:
        # For a ISO 8601 string:
#        ad = datetime.utcfromtimestamp(image.metadata[model.MD_ACQ_DATE])
#        adstr = ad.strftime("%Y-%m-%dT%H:%M:%S.%f")
#        group["TOffset"] = adstr
        group["TOffset"] = image.metadata[model.MD_ACQ_DATE]
        _h5svi_set_state(group["TOffset"], ST_REPORTED)
    else:
        group["TOffset"] = 0.0
        _h5svi_set_state(group["TOffset"], ST_DEFAULT)
        
    # Scale
    if model.MD_PIXEL_SIZE in image.metadata:
        # DimensionScales are not clearly explained in the specification to 
        # understand what they are supposed to represent. Surprisingly, there
        # is no official way to attach a unit.
        # Huygens seems to consider it's in m
        pxs = image.metadata[model.MD_PIXEL_SIZE]
        group["DimensionScaleX"] = pxs[0]
        group["DimensionScaleX"].attrs["UNIT"] = "m" # our extension
        _h5svi_set_state(group["DimensionScaleX"], ST_REPORTED)
        group["DimensionScaleY"] = pxs[1]
        group["DimensionScaleY"].attrs["UNIT"] = "m"
        _h5svi_set_state(group["DimensionScaleY"], ST_REPORTED)
        # No clear what's the relation between this name and the label
        dataset.dims.create_scale(group["DimensionScaleX"], "X")
        dataset.dims.create_scale(group["DimensionScaleY"], "Y")
        dataset.dims[l-1].attach_scale(group["DimensionScaleX"])
        dataset.dims[l-2].attach_scale(group["DimensionScaleY"])

        # Unknown data, but SVI needs them to take the scales into consideration
        if l >= 4:
            group["ZOffset"] = 0.0
            _h5svi_set_state(group["ZOffset"], ST_DEFAULT)
            group["DimensionScaleZ"] = 1e-3 # m
            group["DimensionScaleZ"].attrs["UNIT"] = "m"
            group["DimensionScaleT"] = 1.0 # s
            group["DimensionScaleT"].attrs["UNIT"] = "s"
            # No clear what's the relation between this name and the label
            dataset.dims.create_scale(group["DimensionScaleZ"], "Z")
            _h5svi_set_state(group["DimensionScaleZ"], ST_DEFAULT)
            dataset.dims.create_scale(group["DimensionScaleT"], "T")
            _h5svi_set_state(group["DimensionScaleT"], ST_DEFAULT)
            dataset.dims[l-3].attach_scale(group["DimensionScaleZ"])
            dataset.dims[l-4].attach_scale(group["DimensionScaleT"])
            
            # Put here to please Huygens
            # Seems to be the coverslip position, ie, the lower and upper glass of
            # the sample. Not clear what's the relation with ZOffset. 
            group["PrimaryGlassMediumInterfacePosition"] = 0.0 # m?
            _h5svi_set_state(group["PrimaryGlassMediumInterfacePosition"], ST_DEFAULT)        
            group["SecondaryGlassMediumInterfacePosition"] = 1.0 # m?
            _h5svi_set_state(group["SecondaryGlassMediumInterfacePosition"], ST_DEFAULT)

            # TODO: extension for Rotation:
#            RotationAngle (scalar): angle in radian
#            RotationAxis (3-scalar): X,Y,Z of the rotation vector 
            

ST_INVALID=111
ST_DEFAULT=112
ST_ESTIMATED=113
ST_REPORTED=114
ST_VERIFIED=115
_dtstate = h5py.special_dtype(enum=('i', {
     "Invalid":ST_INVALID, "Default":ST_DEFAULT, "Estimated":ST_ESTIMATED,
     "Reported":ST_REPORTED, "Verified":ST_VERIFIED}))
def _h5svi_set_state(dataset, state):
    """
    Set the "State" of a dataset: the confidence that can be put in the value
    dataset (Dataset): the dataset
    state (int or list of int): the state value (ST_*) which will be duplicated
     as many times as the shape of the dataset. If it's a list, it will be directly
     used, as is.
    """
    
    # the state should be the same shape as the dataset
    if isinstance(state, int):
        fullstate = numpy.empty(shape=dataset.shape, dtype=_dtstate)
        fullstate.fill(state)
    else:
        fullstate = numpy.array(state, dtype=_dtstate)

    dataset.attrs["State"] = fullstate

def _h5py_enum_commit(group, name, dtype):
    """
    Commit (=save under a name) a enum to a group
    group (h5py.Group)
    name (string)
    dtype (dtype)
    """
    enum_type = h5py.h5t.py_create(dtype, logical=True)
    enum_type.commit(group.id, name)
    #TODO: return the TypeEnumID created?
        
def _add_image_metadata(group, images):
    """
    Adds the basic metadata information about an image (scale and offset)
    group (HDF Group): the group that will contain the metadata (named "PhysicalData")
    images (list of DataArray): list of images with metadata
    """
    gp = group.create_group("PhysicalData")
    
    dtvlen_str = h5py.special_dtype(vlen=str)
    # TODO indicate correctly the State of the information (especially if it's unknown)
    
    # All values are duplicated by channel, excepted for Title
    gdesc = [i.metadata.get(model.MD_DESCRIPTION, "") for i in images]
    gp["Title"] = ", ".join(gdesc)
    
    cdesc = [i.metadata.get(model.MD_DESCRIPTION, "") for i in images]
    gp["ChannelDescription"] = numpy.array(cdesc, dtype=dtvlen_str)
    _h5svi_set_state(gp["ChannelDescription"], ST_ESTIMATED)
    
    # TODO: if it takes the default value, the state should be ST_DEFAULT
    xwls = [numpy.mean(i.metadata.get(model.MD_IN_WL, 1e-9)) for i in images]
    gp["ExcitationWavelength"] = xwls # in m
    _h5svi_set_state(gp["ExcitationWavelength"], ST_REPORTED)
    
    ewls = [numpy.mean(i.metadata.get(model.MD_OUT_WL, 1e-9)) for i in images]
    gp["EmissionWavelength"] = ewls # in m
    _h5svi_set_state(gp["EmissionWavelength"], ST_REPORTED)

    mags = [i.metadata.get(model.MD_LENS_MAG, 1.0) for i in images]
    gp["Magnification"] = mags
    _h5svi_set_state(gp["Magnification"], ST_REPORTED)

    # MicroscopeMode
    dtmm = h5py.special_dtype(enum=('i', {
         "None":0, "Transmission":1 ,"Reflection":2, "Fluorescence":3}))
    _h5py_enum_commit(gp, "MicroscopeModeEnumeration", dtmm)
    # MicroscopeType
    dtmt = h5py.special_dtype(enum=('i', {
            "None":111, "WideField":112, "Confocal":113, "4PiExcitation":114,
            "NipkowDiskConfocal":115, "GenericSensor":118}))
    _h5py_enum_commit(gp, "MicroscopeTypeEnumeration", dtmt)
    # ImagingDirection
    dtid = h5py.special_dtype(enum=('i', {
            "Upward":0, "Downward":1, "Both":2  
            }))
    _h5py_enum_commit(gp, "ImagingDirectionEnumeration", dtid)
    mm, mt, id = [], [], []
    # MicroscopeMode: if IN_WL => fluorescence/brightfield, otherwise SEM (=Reflection?)
    for i in images:
        # FIXME: this is true only for the SECOM
        if model.MD_IN_WL in i.metadata:
            iwl = i.metadata[model.MD_IN_WL]
            if abs(iwl[1] - iwl[0]) < 100e-9:
                mm.append("Fluorescence")
                mt.append("WideField")
                id.append("Downward")
            else:
                mm.append("Transmission")  # Brightfield
                mt.append("WideField")
                id.append("Downward")
        else:
            mm.append("Reflection")  # SEM
            mt.append("GenericSensor") # ScanningElectron?
            id.append("Upward")
    # Microscope* is the old format, Microscope*Str is new format
    dictmm = h5py.check_dtype(enum=dtmm)
    # FIXME: it seems h5py doesn't allow to directly set the dataset type to a
    # named type (it always creates a new transient type), unless you redo
    # all make_new_dset() by hand.
    gp["MicroscopeMode"] = numpy.array([dictmm[m] for m in mm], dtype=dtmm)
    _h5svi_set_state(gp["MicroscopeMode"], ST_REPORTED)
    # For the *Str, Huygens expects a space separated string (scalar), _but_ 
    # still wants an array for the state of each channel.
    gp["MicroscopeModeStr"] = " ".join([m.lower() for m in mm])
    _h5svi_set_state(gp["MicroscopeModeStr"], numpy.array([ST_REPORTED] * len(images), dtype=_dtstate))
    dictmt = h5py.check_dtype(enum=dtmt)
    gp["MicroscopeType"] = numpy.array([dictmt[t] for t in mt], dtype=dtmt)
    _h5svi_set_state(gp["MicroscopeType"], ST_REPORTED)
    gp["MicroscopeTypeStr"] = " ".join([t.lower() for t in mt])
    _h5svi_set_state(gp["MicroscopeTypeStr"], numpy.array([ST_REPORTED] * len(images), dtype=_dtstate))
    dictid = h5py.check_dtype(enum=dtid)
    gp["ImagingDirection"] = numpy.array([dictid[d] for d in id], dtype=dtid)
    _h5svi_set_state(gp["ImagingDirection"], ST_REPORTED)
    gp["ImagingDirectionStr"] = " ".join([d.lower() for d in id])
    _h5svi_set_state(gp["ImagingDirectionStr"], numpy.array([ST_REPORTED] * len(images), dtype=_dtstate)) 
    
    # Below are almost entirely made-up values, present just to please Huygens
    # TODO: should allow the user to specify it in the preferences: 1=>vacuum, 1.5 => glass/oil
    gp["RefractiveIndexLensImmersionMedium"] = [1.515] * len(images) # ratio (no unit)
    _h5svi_set_state(gp["RefractiveIndexLensImmersionMedium"], ST_DEFAULT)
    gp["RefractiveIndexSpecimenEmbeddingMedium"] = [1.515] * len(images) # ratio (no unit)
    _h5svi_set_state(gp["RefractiveIndexSpecimenEmbeddingMedium"], ST_DEFAULT)
    
    # Only for confocal microscopes
    gp["BackprojectedIlluminationPinholeSpacing"] = [2.53e-6] * len(images) # unit? m?
    _h5svi_set_state(gp["BackprojectedIlluminationPinholeSpacing"], ST_DEFAULT)
    gp["BackprojectedIlluminationPinholeRadius"] = [280e-9] * len(images) # unit? m?
    _h5svi_set_state(gp["BackprojectedIlluminationPinholeRadius"], ST_DEFAULT)
    gp["BackprojectedPinholeRadius"] = [280e-9] * len(images) # unit? m?
    _h5svi_set_state(gp["BackprojectedPinholeRadius"], ST_DEFAULT)
    
    # TODO: should come from the microscope model?
    gp["NumericalAperture"] = [1.4] * len(images) # ratio (no unit)
    _h5svi_set_state(gp["NumericalAperture"], ST_DEFAULT)
    gp["ObjectiveQuality"] = [80] * len(images) # unit? int [0->100] = percentage of respect to the theory?
    _h5svi_set_state(gp["ObjectiveQuality"], ST_DEFAULT)
    
    # Only for confocal microscopes?
    gp["ExcitationBeamOverfillFactor"] = [2.0] * len(images) # unit?
    _h5svi_set_state(gp["ExcitationBeamOverfillFactor"], ST_DEFAULT)
    
    # Only for fluorescence acquisitions. Almost always 1, excepted for super fancy techniques.
    # Number of simultaneously absorbed photons by a fluorophore in a fluorescence event
    gp["ExcitationPhotonCount"] = [1] * len(images) # photons
    _h5svi_set_state(gp["ExcitationPhotonCount"], ST_DEFAULT) 
    
def _add_svi_info(group):
    """
    Adds the information to indicate this file follows the SVI format
    group (HDF Group): the group that will contain the information
    """
    gi = group.create_group("SVIData")
    gi["Company"] = "Delmic"
    gi["FileSpecificationCompatibility"] = "0.01p0"
    gi["FileSpecificationVersion"] = "0.01d8"
    gi["ImageHistory"] = ""
    gi["URL"] = "www.delmic.com"

def _add_acquistion_svi(group, images, **kwargs):
    """
    Adds the acquisition data according to the sub-format by SVI
    group (HDF Group): the group that will contain the metadata (named "PhysicalData")
    images (list of 2D DataArray): set of images with metadata
    """
    gi = group.create_group("ImageData")
    # one of the main thing is that data must always be with 5 dimensions,
    # in this order: CTZYX => so we add dimensions to data if needed
    # In the C dimension we put the different images
    images4d = []
    for d in images:
        if len(d.shape) < 4:
            shape4d = [1] * (4-len(d.shape)) + list(d.shape)
            d = d.reshape(shape4d)
        images4d.append(d)
    gdata = numpy.array(images4d) # convert to a 5D array
       
    # StateEnumeration
    # FIXME: should be done by _h5svi_set_state (and used)
    dtstate = h5py.special_dtype(enum=('i', {
         "Invalid":111, "Default":112, "Estimated":113, "Reported":114, "Verified":115}))
    _h5py_enum_commit(group, "StateEnumeration", dtstate)
    
    ids = _create_image_dataset(gi, "Image", gdata, **kwargs)
    _add_image_info(gi, ids, images[0]) # all images should have the same info (but channel)
    _add_image_metadata(group, images)
    _add_svi_info(group)


def _findImageGroups(das):
    """
    Find groups of images which should be considered part of the same acquisition
    (be a channel of an Image in HDF5 SVI).
    das (list of DataArray): all the images
    returns (list of list of int): a set of "groups", each group is represented
      by a set of indexes (of the images being part of the group)
    Note: it's a slightly different function from tiff._findImageGroups()
    """
    # We consider images to be part of the same group if they have:
    # * same shape
    # * metadata that show they were acquired by the same instrument
    # * same position
    # * same density (MPP)
    
    groups = []
    
    for i, da in enumerate(das):
        # try to find a matching group (compare just to the first picture)
        found = False
        for g in groups:
            da0 = das[g[0]]
            if da0.shape != da.shape:
                continue
            if (da0.metadata.get(model.MD_HW_NAME, None) != da.metadata.get(model.MD_HW_NAME, None) or
                da0.metadata.get(model.MD_HW_VERSION, None) != da.metadata.get(model.MD_HW_VERSION, None)):
                continue
            if (da0.metadata.get(model.MD_PIXEL_SIZE, None) != da.metadata.get(model.MD_PIXEL_SIZE, None) or
                da0.metadata.get(model.MD_POS, None) != da.metadata.get(model.MD_POS, None)):
                continue
            g.append(i)
            found = True
            break
        
        if not found:
            # if not, create a new group
            groups.append([i])
    
    return groups

def _saveAsHDF5(filename, ldata, thumbnail, compressed=True):
    """
    Saves a list of DataArray as a HDF5 (SVI) file.
    filename (string): name of the file to save
    ldata (list of DataArray): list of 2D data of int or float. Should have at least one array
    thumbnail (None or DataArray): see export
    compressed (boolean): whether the file is compressed or not.
    """
    # TODO check what is the format in Odemis if image is 3D (ex: each pixel has
    # a spectrum associated, or there is a Z axis as well) and convert to CTZYX.
    
    # h5py will extend the current file by default, so we want to make sure
    # there is no file at all.
    try:
        os.remove(filename)
    except OSError:
        pass
    f = h5py.File(filename, "w") # w will fail if file exists 
    if compressed:
        # szip is not free for commercial usage and lzf doesn't seem to be 
        # well supported yet 
        compression = "gzip"
    else:
        compression = None
    
    if thumbnail is not None:
        # Save the image as-is in a special group "Preview"
        prevg = f.create_group("Preview")
        ids = _create_image_dataset(prevg, "Image", thumbnail, compression=compression)
        _add_image_info(prevg, ids, thumbnail)
        _add_svi_info(prevg)
        
    # for each set of images from the same instrument, add them
    groups = _findImageGroups(ldata)
    
    for g in groups:
        ga = f.create_group("Acquisition%d" % min(g)) # smallest ID of the images
        gdata = [ldata[i] for i in g]
        _add_acquistion_svi(ga, gdata, compression=compression)
    
    f.close()

def export(filename, data, thumbnail=None):
    '''
    Write a HDF5 file with the given image and metadata
    filename (string): filename of the file to create (including path)
    data (list of model.DataArray, or model.DataArray): the data to export, 
        must be 2D of int or float. Metadata is taken directly from the data 
        object. If it's a list, a multiple page file is created.
    thumbnail (None or model.DataArray): Image used as thumbnail for the file. Can be of any
      (reasonable) size. Must be either 2D array (greyscale) or 3D with last 
      dimension of length 3 (RGB). If the exporter doesn't support it, it will
      be dropped silently.
    '''
    if isinstance(data, list):
        _saveAsHDF5(filename, data, thumbnail)
    else:
        # TODO should probably not enforce it: respect duck typing
        assert(isinstance(data, model.DataArray))
        _saveAsHDF5(filename, [data], thumbnail)