#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Provide a class that represents 3D scan volumes in a desired anatomical
coordinate system.
"""

import numpy as np

from . import anatomical_coords


class Volume:
    """
    Volume(src_voxel_data, src_transformation, src_system, system="RAS", src_object=None)

    Return an object that represents 3D image volumes in a desired anatomical world coordinate system (``system``;
    default is "RAS"), based on (1) an array that holds the voxels (``src_voxel_data``) and (2) a transformation matrix
    (``src_transformation``) that holds the mapping from voxel indices to (3) some potentially different given
    anatomical world coordinate system (``src_system``). The class is meant to serve as a layer on top of specific
    image formats (with different coordinate system conventions).

    It is also meant to make dealing with the voxel data a little simpler: when accessing voxels via the field
    ``aligned_volume``, the voxel data axes are aligned with the anatomical world coordinate system axes as closely as
    is possible without reinterpolating the image.

    Parameters
    ----------
    src_voxel_data : array_like
        A three-dimensional array that contains the image voxels, arranged to match the coordinate transformation
        matrix ``src_transformation``.
    src_transformation : array_like
        A :math:`4x4` matrix that describes the mapping from voxel indices in ``src_voxel_data`` to the given anatomical
        world coordinate system ``src_system``.
    src_system : str
        A three-character string that describes the anatomical world coordinate system for the provided
        ``src_transformation`` matrix. Any permutation of {A,P}, {I,S}, {L,R} (case-insensitive) can be used. For
        example, for voxels and a transformation matrix provided by a DICOM loading library, this should usually be
        "LPS", as this is the assumed world coordinate system of the DICOM standard.
    system : str, optional
        A three-character string similar to ``src_system``. However, ``system`` should describe the anatomical world
        coordinate system that the *user* assumes/desires. It will also determine the arrangement of the voxel data for
        the ``aligned_volume`` representation (default: "RAS").
    src_object : object, optional
        The original object that was created by the image loading library (nibabel, pydicom, ...) to get the provided
        ``src_voxel_data`` and ``src_transformation`` -- for debugging, for example (default: None).
    """

    def __init__(self, src_voxel_data, src_transformation, src_system, system="RAS", src_object=None):

        self.__src_system = src_system
        self.__user_system = None

        # Mapping from ``src_volume``'s voxel indices to the source anatomical coordinate system (4x4 matrix)
        self.__vsrc2csrc = src_transformation

        self.__src_object = src_object
        self.__src_spacing = None  # Voxel spacing for ``src_volume``
        self.__src_volume = src_voxel_data  # The source voxel data
        self.__vsrc2cuser = None
        # ^ Mapping from ``src_volume``'s voxel indices to the desired anatomical coordinate system

        self.__aligned_spacing = None
        self.__aligned_volume = None
        self.__vuser2cuser = None
        # ^ Mapping from ``aligned_volume``'s voxel indices to the desired anatomical coordinate system

        # Mapping from the source anatomical coordinate system to the user's anatomical coordinate system and vice
        # versa (3x3; only the permutation-reflection matrices)
        self.__csrc2cuser = None
        self.__cuser2csrc = None

        # Mapping from ``src_volume`` voxel indices to ``aligned_volume`` voxel indices and vice versa (4x4; including
        # offset into the array)
        self.__vsrc2vuser = None
        self.__vuser2vsrc = None

        self.system = system  # Initialize the remaining empty fields

    @property
    def system(self):
        """
        Returns
        -------
        str
            The desired anatomical world coordinate system as a three-character string. Any permutation of {A,P}, {I,S},
            {L,R} (case-insensitive) can be used. When being set, fields like ``aligned_volume``, ``aligned_spacing``,
            ``aligned_transformation``, and ``src_to_aligned_transformation`` will be adjusted accordingly.
        """
        return self.__user_system

    @system.setter
    def system(self, value):

        value = value.upper()
        if value != self.__user_system:
            self.__user_system = value
            self.__init_system_mapping()
            self.__init_aligned_volume()
            self.__init_voxel_mapping()
            self.__init_spacing()

    def __init_system_mapping(self):
        """
        Calculate the mapping from the source anatomical coordinate system to the user desired anatomical coordinate
        system and vice versa (3x3 permutation-reflection matrices).
        """
        self.__csrc2cuser, self.__cuser2csrc = anatomical_coords.permutation_matrix(self.__src_system, self.__user_system)

    def __init_aligned_volume(self):
        """
        Calculate ``aligned_volume``: swap the ``src_volume`` to match the currently desired anatomical world coordinate
        system ``user_system``. Also calculate the voxel swapping matrices in the process.
        """
        ndim = 3

        # First map the voxels to lie parallel to the *original* coordinate system's axes, then map to the *desired*
        # coordinate system. This results in the mapping from the ``src_volume`` voxel coordinates to ``aligned_volume``
        # voxel coordinates (3x3)
        perm = anatomical_coords.find_closest_permutation_matrix(self.__vsrc2csrc[:ndim, :ndim])
        vsrc2vuser3 = self.__csrc2cuser @ perm
        # Make it a 4x4 matrix: Add offset of (dimension size - 1) for the inverted dimensions (in this way account
        # for the inverted and thus negative voxel indices)
        offset = (vsrc2vuser3 @ (np.asarray(self.src_volume.shape) - 1)).clip(max=0)
        vsrc2vuser4 = np.eye(ndim + 1, dtype=np.int)
        vsrc2vuser4[:ndim, :ndim] = vsrc2vuser3
        vsrc2vuser4[:ndim, ndim] = -offset
        vuser2vsrc4 = np.round(np.linalg.inv(vsrc2vuser4)).astype(np.int)

        anatomical_coords.validate_permutation_matrix(vsrc2vuser4[:ndim, :ndim])  # Just to be sure ...
        anatomical_coords.validate_permutation_matrix(vuser2vsrc4[:ndim, :ndim])

        self.__vuser2vsrc = vuser2vsrc4
        self.__vsrc2vuser = vsrc2vuser4

        # Actually swap the volume
        self.__aligned_volume = anatomical_coords.swap(self.__src_volume, vsrc2vuser4)

    def __init_voxel_mapping(self):
        """
        Calculate ``vsrc2cuser`` and ``vuser2cuser``, i.e. the mappings from ``src_volume``'s and ``aligned_volume``'s
        voxel indices to the currently desired anatomical world coordinate system ``system``.
        """
        self.__vsrc2cuser = self.get_src_transformation(system=self.__user_system)
        self.__vuser2cuser = self.get_aligned_transformation(system=self.__user_system)

    def __init_spacing(self):
        """
        Calculate ``src_spacing`` and ``aligned_spacing``, i.e. the voxel spacings for ``src_volume`` and
        ``aligned_volume``.
        """
        ndim = 3
        m = self.__vsrc2csrc
        self.__src_spacing = tuple(np.linalg.norm(m[:ndim, :ndim], axis=0))
        m = self.__vuser2cuser
        self.__aligned_spacing = tuple(np.linalg.norm(m[:ndim, :ndim], axis=0))

    @property
    def src_system(self):
        """
        Returns
        -------
        str
            The original anatomical world coordinate system as a three-character string.
        """
        return self.__src_system

    @property
    def src_object(self):
        """
        Returns
        -------
        object
            The object that originally was returned by the image loading library (or None).
        """
        return self.__src_object

    @property
    def src_transformation(self):
        """
        Returns
        -------
        ndarray
            The :math:`4x4` transformation matrix that maps from ``src_volume``'s voxel indices to the *original*
            anatomical world coordinate system ``src_system`` (new copy).
        """
        return self.__vsrc2csrc.copy()

    @property
    def aligned_transformation(self):
        """
        Returns
        -------
        ndarray
            The :math:`4x4` transformation matrix that maps from ``aligned_volume``'s voxel indices to the *desired*
            anatomical world coordinate system ``system`` (new copy).
        """
        return self.__vuser2cuser.copy()

    @property
    def src_to_aligned_transformation(self):
        """
        Returns
        -------
        ndarray
            The :math:`4x4` transformation matrix that maps from ``src_volume``'s voxel indices to the *desired*
            anatomical world coordinate system ``system`` (new copy).
        """
        return self.__vsrc2cuser.copy()

    @property
    def src_volume(self):
        """
        Returns
        -------
        ndarray
            The 3-dimensional Numpy array that contains the original voxel data.
        """
        return self.__src_volume

    @property
    def aligned_volume(self):
        """
        Returns
        -------
        ndarray
            The 3-dimensional Numpy array that contains the image information with the voxel data axes aligned to the
            desired anatomical world coordinate system ``system`` as closely as is possible without reinterpolation.
            This means, for example, if ``system`` is "RAS", then ``aligned_volume`` will hold an array where
            increasing the index on axis 0 will reach a voxel coordinate that is typically more to the right side of
            the imaged subject, increasing the index on axis 1 will reach a voxel coordinate that is more anterior,
            and increasing the index on axis 2 will reach a voxel coordinate that is more superior.
        """
        return self.__aligned_volume

    @property
    def src_spacing(self):
        """
        Returns
        -------
        tuple
            The spacing of ``src_volume`` as a three-tuple in world coordinate system units per voxel.
        """
        return self.__src_spacing

    @property
    def aligned_spacing(self):
        """
        Returns
        -------
        tuple
            The spacing of ``aligned_volume`` as a three-tuple in world coordinate system units per voxel.
        """
        return self.__aligned_spacing

    def get_src_transformation(self, system):
        """
        Get a transformation matrix that maps from ``src_volume``'s voxel indices to the given anatomical world
        coordinate system.

        Parameters
        ----------
        system : str
            A three-character string that describes the anatomical world coordinate system. Any permutation of {A,P},
            {I,S}, {L,R} (case-insensitive) can be used.

        Returns
        -------
        ndarray
            The resulting :math:`4x4` transformation matrix.

        See also
        --------
        get_aligned_transformation : Same transformation, but for ``aligned_volume``.
        """
        csrc2csys = np.eye(4)
        csrc2csys[:-1, :-1] = anatomical_coords.permutation_matrix(self.__src_system, system)[0]
        result = csrc2csys @ self.__vsrc2csrc
        return result

    def get_aligned_transformation(self, system):
        """
        Get a transformation matrix that maps from ``aligned_volume``'s voxel indices to the given anatomical world
        coordinate system.

        Parameters
        ----------
        system : str
            A three-character string that describes the anatomical world coordinate system. Any permutation of {A,P},
            {I,S}, {L,R} (case-insensitive) can be used.

        Returns
        -------
        ndarray
            The resulting :math:`4x4` transformation matrix.

        See also
        --------
        get_src_transformation : Same transformation, but for ``src_volume``.
        """
        vsrc2csys = self.get_src_transformation(system=system)
        result = vsrc2csys @ self.__vuser2vsrc
        return result

    def copy(self):
        """
        Returns
        -------
        Volume
            A copy of the current instance.
        """
        return Volume(src_voxel_data=self.__src_volume.copy(), src_transformation=self.__vsrc2csrc.copy(),
                      src_system=self.__src_system, system=self.__user_system, src_object=self.__src_object)