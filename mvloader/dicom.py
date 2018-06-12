#!/usr/bin/env python
# coding: utf-8

"""
Making use of the Pydicom library [1]_, return correctly stacked and oriented DICOM volumes via ``volume.Volume``
instances.

References
----------
.. [1] https://github.com/pydicom/pydicom (20180209)
"""


try:
    import pydicom  # pydicom >= 1.0
except ImportError:
    import dicom as pydicom  # pydicom < 1.0
import numpy as np
from pathlib import Path

from mvloader.volume import Volume


def open_stack(path, verbose=True, sloppy=False):
    """
    Open a list of two-dimensional DICOM files at the specified path and build their three-dimensional volume
    representation.

    The given ``path`` may point to either of the following three cases: (1) a directory, (2) an archive file containing
    DICOM files, (3) a DICOM file.

    Case 1 (``path`` points to a directory)
        Iterate over its contents (*non-recursively*) in alphanumeric order and try to combine all present DICOM files
        that share the "Series Instance UID" (0020,000E) with the first loadable DICOM file.

    Case 2 (``path`` points to an archive file)
        Temporarily extract it, then iterate over its contents (*recursively*) in alphanumeric order and try to combine
        all present DICOM files that share the "Series Instance UID" (0020,000E) with the first loadable DICOM file.

    Case 3 (``path`` points to a DICOM file)
        Iterate over the contents of the file's base directory (*non-recursively*) and try to combine all present DICOM
        files that share the "Series Instance UID" with the given file. If ``sloppy`` is `True`, ignore the "Series
        Instance UID" in both cases and try to combine all of the directory's DICOM files.

    The given files need *not* be named according to their stacking order -- in fact, their names do not influence
    the stacking process. Instead, "Image Position (Patient)" (0020,0032) and "Image Orientation (Patient)" (0020,0037)
    are evaluated for working out the stacking order. See e.g. [2]_ and [3]_ for the necessary steps.

    Parameters
    ----------
    path : str
        The path that determines the files to be loaded (either a directory path or file path; see possibilities above).
    verbose : bool, optional
        If `True` (default), print some meta data of the loaded files to standard output.
    sloppy : bool, optional
        If `False` (default), the DICOM files' "Series Instance UID" (0020,000E) will be compared to find matching
        slices and ignore others that are in the same directory; if `True`, this comparison will not be made and thus
        files with different "Series Instance UID"s will potentially be stacked.

    Returns
    -------
    Volume
        The resulting 3D image volume, with the ``src_object`` attribute set to the respective ``SliceStacker``
        instance and the desired anatomical world coordinate system ``system`` set to "RAS".

    Raises
    ------
    IOError
        If something goes wrong.

    References
    ----------
    .. [2] http://nipy.org/nibabel/dicom/dicom_orientation.html (20180209)
    .. [3] https://itk.org/pipermail/insight-users/2003-September/004761.html (20180209)
    """
    # FIXME: add archive case
    volume = SliceStacker(path, sloppy=sloppy, recursive=False).execute().volume
    if verbose:
        print("Stack loaded:", path)
        print("Meta data (first slice):")
        print(volume.src_object.sorted_slices[0])  # Will show the first slice's header

    return volume


class SliceStacker:
    """
    SliceStacker(self, path, si_uid=None, sloppy=False, recursive=False)

    Encapsulate the slice stacking functionality.

    Parameters
    ----------
    path : str
        The path that determines the files to be loaded (either a directory path or file path). If a file path is given,
        use its base directory to find matching slices.
    si_uid : str, optional
        The "Series Instance UID" (0020,000E) to be used for non-``sloppy`` stacking. If it is not given (default), use
        (1) the one of the (alphanumerically) first DICOM file if ``path`` is a directory path or (2) the one of the
        given file if ``path`` is a file path.
    sloppy : bool, optional
        If `False` (default), ``si_uid`` (or the respective inferred "Series Instance UID" -- see ``si_uid``) will be
        compared to find matching slices and ignore others that are in the same directory; if `True`, this comparison
        will not be made and thus files with different "Series Instance UID"s will potentially be stacked.
    """
    SI_UID_TAG = (0x0020, 0x000E)  # Series Instance UID
    ORIENT_TAG = (0x0020, 0x0037)  # Image Orientation (Patient)
    POS_TAG    = (0x0020, 0x0032)  # Image Position (Patient)
    PX_SPC_TAG = (0x0028, 0x0030)  # Pixel Spacing
    ROWS_TAG   = (0x0028, 0x0010)  # Rows
    COLS_TAG   = (0x0028, 0x0011)  # Columns
    
    def __init__(self, path, si_uid=None, sloppy=False, recursive=False):

        path = Path(path)
        self.base_dir = None  # Directory containing the current slices (absolute path)
        self.si_uid = None  # The slices' common Series Instance UID (0020,000E) or None
        self.sloppy = sloppy
        self.recursive = recursive
        
        self.slices = {}
        # ^ A dictionary of all slices (sharing the determined Series Instance UID, if desired). The respective file
        # name is used as key, the value is a ``pydicom.dataset.FileDataset`` instance
        self.sorted_slices = None  # A list of all slices as ``pydicom.dataset.FileDataset`` instances after sorting
        
        self.volume = None  # The stacked image volume as a ``volume.Volume`` instance
        
        if si_uid is None and not sloppy:
            self.__find_series_instance_uid(path)
        else:
            self.si_uid = si_uid
            self.base_dir = str((path if path.is_dir() else path.parent()).resolve())

    def __find_series_instance_uid(self, path):
        """
        Find the common Series Instance UID (0020,000E) for the given ``path`` and set the ``si_uid`` attribute
        accordingly. As a by-product, set the ``base_dir`` attribute.

        Parameters
        ----------
        path : pathlib.Path
            File path or directory path
        """
        path = path.resolve()
        if path.is_dir():
            self.base_dir = str(path)
            for f in sorted(path.glob("**/*" if self.recursive else "*"), key=lambda p: str(p).lower()):
                try:
                    # Find the first DICOM file, determine its "Series Instance UID"
                    dataset = pydicom.read_file(str(f.resolve()), stop_before_pixels=True)
                    self.si_uid = dataset[SliceStacker.SI_UID_TAG].value
                    break
                except:
                    pass
        else:
            self.base_dir = str(path.parent)
            try:
                dataset = pydicom.read_file(str(path), stop_before_pixels=True)
                self.si_uid = dataset[SliceStacker.SI_UID_TAG].value
            except:
                pass
        # If the ``si_uid`` attribute has not been set so far, something went wrong
        if self.si_uid is None:
            raise IOError("No Series Instance UID could be determined for {}.".format(path))
    
    def __collect_slices(self):
        """
        Collect the slices from the ``base_dir`` sharing the ``si_uid``. Fill ``slices`` accordingly.
        """
        path = Path(self.base_dir).resolve()
        for f in path.glob("**/*" if self.recursive else "*"):
            try:
                dataset = pydicom.read_file(str(f.resolve()))
                if not self.sloppy:
                    dataset_si_uid = dataset[SliceStacker.SI_UID_TAG].value
                    if dataset_si_uid == self.si_uid:
                        self.slices[str(f)] = dataset
                else:
                    self.slices[str(f)] = dataset
            except:
                pass
        
        if not self.slices:
            if not self.sloppy:
                raise IOError("No slices could be loaded sharing the Series Instance UID {}.".format(self.si_uid))
            else:
                raise IOError("No slices could be loaded.")

    def __sort_slices(self):
        """
        Sort the collected slices and set the ``volume`` attribute, with its ``src_object`` attribute set to the
        current ``SliceStacker`` instance, i.e. ``self``. Also set the ``sorted_slices`` attribute.
        """
        # According to the DICOM specification, section C.7.6.2.1.1, the world coordinate system for DICOM images is
        # LPS for bipeds and a similar right-handed system for others.
        src_system = "LPS"
        
        slices = list(self.slices.values())  # list of ``FileDataset`` instances
        n = len(slices)
        if n <= 1:
            raise IOError("Stacking works for more than one slice only, but {} slice(s) have been found.".format(n))
        # Use the tags of an arbitrary slice for setting most of the transformation matrix values
        slice_ref = slices[0]
        
        # Create the transformation matrix, "NiBabel-style" [2]_, assuming `(r, c, s)` indices, where `(r, c)` gives row
        # and column index of the individual slices and `s` is the slice index
        mat = np.eye(4)
        # Get the directional cosines via "Image Orientation (Patient)" and flip them to have `(r, c)` indices rather
        # than the `(c, r)` order of the DICOM specification's affine matrix (see section C.7.6.2.1.1)
        cos_ref = np.asarray(slice_ref[SliceStacker.ORIENT_TAG].value)
        c = cos_ref.reshape(2,3)[::-1].T  # 3x2, flipped columns
        # Determine an orthogonal vector on the directional cosines for sorting the slices: calculate cross product
        # of them. The order of the vectors in the cross product actually doesn't matter, as the resulting vector's
        # direction and the resulting slice order cancel out with the choice of the offset of the respective
        # resulting first slice (see further down)
        stack_dir = np.cross(c[:, 0], c[:, 1])
        # Apply "Pixel Spacing". Note that no flipping is necessary here, as the first value already gives the
        # spacing between adjacent rows and the second value gives the spacing between adjacent columns (again see
        # section C.7.6.2.1.1 of the DICOM specification)
        spc_ref = np.asarray(slice_ref[SliceStacker.PX_SPC_TAG].value)
        c = c @ np.diag(spc_ref)
        mat[:3, :2] = c
        # Sort the slices along the determined stacking direction: Calculate the dot product of their "Image Position
        # (Patient)" value with the direction vector to get the position w.r.t. said direction (see [3]_)
        order = lambda s: s[SliceStacker.POS_TAG].value @ stack_dir
        slices = self.sorted_slices = sorted(slices, key=order)
        # Get the offset via "Image Position (Patient)" of the (sorted) first slice. No need to flip here as only
        # world coordinates are concerned
        pos_0 = np.asarray(slices[0][SliceStacker.POS_TAG].value)
        mat[:3, 3] = pos_0
        # Calculate the "s part" of the transformation matrix (i.e. flipping and scaling for the slice index,
        # see [2]_). The matrix is complete afterwards
        pos_end = np.asarray(slices[-1][SliceStacker.POS_TAG].value)
        s = (pos_end - pos_0) / (n - 1)
        mat[:3, 2] = s
        # Actually stack the slices, then create a new ``Volume`` instance (use `(r, c, s)` indices, see above)
        stack = np.empty((slice_ref[SliceStacker.ROWS_TAG].value, slice_ref[SliceStacker.COLS_TAG].value, n))
        for i in range(n):
            stack[:,:,i] = slices[i].pixel_array
        self.volume = Volume(src_voxel_data=stack, src_transformation=mat, src_system=src_system, system="RAS",
                             src_object=self)

    def execute(self):
        """
        Collect the appropriate slices in the current directory and stack them according to their "Image Position (
        Patient)" (0020,0032) and "Image Orientation (Patient)" (0020,0037) values.
        
        Returns
        -------
        SliceStacker
            This instance for convenience.
        """
        self.__collect_slices()
        self.__sort_slices()
        
        return self
