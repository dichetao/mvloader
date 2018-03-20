#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Provide a class that represents 3D scan volumes in a desired anatomical
coordinate system.
"""

import numpy as np

import mvloader.anatomical_coords as ac


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

        # Mapping from ``src_volume``'s voxel indices to the source anatomical coordinate system
        ac.validate_transformation_matrix(src_transformation)
        self.__vsrc2csrc_4x4 = src_transformation

        self.__src_object = src_object
        self.__src_spacing = None  # Voxel spacing for ``src_volume``
        self.__src_volume = src_voxel_data  # The source voxel data
        self.__vsrc2cuser_4x4 = None
        # ^ Mapping from ``src_volume``'s voxel indices to the desired anatomical coordinate system

        self.__aligned_spacing = None
        self.__aligned_volume = None
        self.__vuser2cuser_4x4 = None
        # ^ Mapping from ``aligned_volume``'s voxel indices to the desired anatomical coordinate system

        # Mapping from ``src_volume`` voxel indices to ``aligned_volume`` voxel indices and vice versa (including offset
        # into the array)
        self.__vsrc2vuser_4x4 = None
        self.__vuser2vsrc_4x4 = None

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

        new_system = value.upper()
        if new_system != self.__user_system:
            self.__on_system_change(new_system)

    def __on_system_change(self, new_system):

        self.__user_system = new_system

        # Transform: given source array indices -> source system coordinates (known)
        vsrc2csrc_4x4 = self.__vsrc2csrc_4x4

        # Swap: given source array axes -> source system axes
        vsrc2ssrc_3x3 = ac.find_closest_permutation_matrix(vsrc2csrc_4x4[:3, :3])
        # Swap: source system axes -> user system axes
        ssrc2suser_3x3 = ac.permutation_matrix(self.__src_system, new_system)
        # Swap: given source array axes -> user system axes
        vsrc2suser_3x3 = ssrc2suser_3x3 @ vsrc2ssrc_3x3

        offset_4x4 = ac.offset(vsrc2suser_3x3, self.__src_volume.shape)
        # Transform: given source array indices -> user system aligned array indices
        self.__vsrc2vuser_4x4 = vsrc2vuser_4x4 = ac.homogeneous_matrix(vsrc2suser_3x3) @ offset_4x4
        # Transform: user system aligned array indices -> given source array indices
        self.__vuser2vsrc_4x4 = vuser2vsrc_4x4 = np.linalg.inv(vsrc2vuser_4x4)

        # Transform: given source array indices -> user system coordinates
        self.__vsrc2cuser_4x4 = vsrc2cuser_4x4 = ac.transformation_for_new_coordinate_system(trans=vsrc2csrc_4x4, sold2snew=ssrc2suser_3x3)
        # Transform: user system aligned array indices -> user system coordinates
        self.__vuser2cuser_4x4 = vuser2cuser_4x4 = ac.transformation_for_new_voxel_alignment(trans=vsrc2cuser_4x4, vnew2vold=vuser2vsrc_4x4)

        # Recalculate voxel sizes ("spacing")
        ndim = 3
        m = vsrc2csrc_4x4
        self.__src_spacing = tuple(np.linalg.norm(m[:ndim, :ndim], axis=0))
        m = vuser2cuser_4x4
        self.__aligned_spacing = tuple(np.linalg.norm(m[:ndim, :ndim], axis=0))

        # Actually swap the given source array
        self.__aligned_volume = ac.swap(self.__src_volume, vsrc2vuser_4x4)

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
        return self.__vsrc2csrc_4x4.copy()

    @property
    def aligned_transformation(self):
        """
        Returns
        -------
        ndarray
            The :math:`4x4` transformation matrix that maps from ``aligned_volume``'s voxel indices to the *desired*
            anatomical world coordinate system ``system`` (new copy).
        """
        return self.__vuser2cuser_4x4.copy()

    @property
    def src_to_aligned_transformation(self):
        """
        Returns
        -------
        ndarray
            The :math:`4x4` transformation matrix that maps from ``src_volume``'s voxel indices to the *desired*
            anatomical world coordinate system ``system`` (new copy).
        """
        return self.__vsrc2cuser_4x4.copy()

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
        sold2snew_3x3 = ac.permutation_matrix(self.__src_system, system)
        return ac.transformation_for_new_coordinate_system(trans=self.__vsrc2csrc_4x4, sold2snew=sold2snew_3x3)

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
        vsrc2csys_4x4 = self.get_src_transformation(system=system)
        return ac.transformation_for_new_voxel_alignment(trans=vsrc2csys_4x4, vnew2vold=self.__vuser2vsrc_4x4)

    def copy(self, deep=True):
        """
        Create a shallow(er) or deep(er) copy of the current instance.

        Parameters
        ----------
        deep : bool, optional
            If `True` (default), a copy of the ``src_volume`` Numpy array will be created for the new instance; if
            `False`, the array will be shared by both instances. In either case, (1) ``src_object`` will be shared by
            both instances and (2) the transformation matrices will be copies for the new instance.

        Returns
        -------
        Volume
            A copy of the current instance.
        """
        src_voxel_data = self.__src_volume.copy() if deep else self.__src_volume
        return Volume(src_voxel_data=src_voxel_data, src_transformation=self.__vsrc2csrc_4x4.copy(),
                      src_system=self.__src_system, system=self.__user_system, src_object=self.__src_object)

    def copy_like(self, template):
        """
        Create a copy of the current instance, rearranging the following data to match the respective entries of
        ``template``: (1) ``src_volume``, (2) ``src_system``, (3) ``aligned_volume``, (4) ``system``.

        To match the ``template``'s voxel order of ``src_volume``, (1) both a copy of the current instance and
        ``template`` will be aligned to the same anatomical world coordinate system and then (2) ``template``'s
        alignment process will be inverted on the copy of the current instance. The coordinate systems will only be
        adapted insofar as the direction and order of axes is copied from ``template``, but not the rotations and
        scalings. In other words, the permutations and reflections to get from the new copy's voxel indices and
        template's voxel indices -- in both of their volume representations -- to whatever world coordinate system will
        afterwards be the same, but not the parts of the rotations that deviate from pure permutation and reflection.

        Parameters
        ----------
        template : Volume
            The instance whose order of ``src_volume`` voxels and whose world coordinate systems should be adopted.

        Returns
        -------
        Volume
            A rearranged copy of the current instance.
        """
        current_instance = self.copy(deep=False)

        # Align the current instance to the same user coordinates as template
        current_instance.system = template.system
        # Get the mapping from template's aligned_volume to its src_volume, adjust for the current volume's shape,
        # then use it to rearrange the current instance's voxels and transformation matrices
        vuser2vsrc = Volume.__vsrc2vdst_4x4(template.__vuser2vsrc_4x4[:3, :3], current_instance.aligned_volume.shape)  # FIXME:
        vsrc2vuser = np.round(np.linalg.inv(vuser2vsrc)).astype(vuser2vsrc.dtype)
        src_voxel_data = ac.swap(current_instance.aligned_volume, vuser2vsrc)
        src_transformation = current_instance.get_aligned_transformation(template.src_system) @ vsrc2vuser

        return Volume(src_voxel_data=src_voxel_data, src_transformation=src_transformation,
                      src_system=template.src_system, system=template.system, src_object=current_instance.src_object)

    # TODO: Add a print method for nice output
