#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Transform between different 3D anatomical coordinate systems (RAS, LAS etc.)
"""

import numpy as np
from numpy import ma


def permutation_matrix(src, dst):
    """
    Calculate the permutation-reflection matrix that maps axes from the given source anatomical coordinate system to the
    given destination anatomical coordinate system, as well as its inverse.

    Parameters
    ----------
    src : str
        A three-character string that describes the source system (such as "LPS"). Any permutation of {A,P}, {I,S},
        {L,R} (case-insensitive) can be used.
    dst : str
        A three-character string that describes the destination system (such as "RAS").  Any permutation of {A,P},
        {I,S}, {L,R} (case-insensitive) can be used.

    Returns
    -------
    tuple
        A two-tuple ``(src2dst, dst2src)`` where ``src2dst`` holds the :math:`3x3` permutation and reflection matrix
        that maps coordinates from the ``src`` system to the ``dst`` system, and ``dst2src`` holds the :math:`3x3`
        matrix for the inverse mapping. Both matrices are Numpy arrays with a determinant of plus/minus one,
        containing only zeros, ones, and minus ones. A minus one signifies a swapped axis direction (e.g. "L" in
        ``src`` becomes "R" in ``dst``).
    """
    src = src.upper()
    dst = dst.upper()

    # Find the "R/L", "A/P", "S/I" positions
    src_pos = pos(src)
    dst_pos = pos(dst)

    ndim = 3
    dtype = np.int

    # Actually build the transformation matrix
    mat = np.zeros((ndim, ndim), dtype=dtype)
    for i in range(ndim):
        # If the character for the current axis is not the same in the source and destination string, we have to mirror
        # the respective axis (-1), otherwise not (1)
        mat[dst_pos[i], src_pos[i]] = -1 if dst[dst_pos[i]] != src[src_pos[i]] else 1

    return mat, mat.T


# def find_closest_permutation_matrix(trans):
#     """
#     Find the transformation matrix that *almost* maps voxel axes to original world coordinate axes, but does not
#     require interpolation, i.e. the permutation-reflection matrix closest to the given transformation matrix.
#
#     Parameters
#     ----------
#     trans : array_like
#         The :math:`dxd` matrix that represents the original transformations from voxel indices to world coordinates
#         (excluding offset).
#
#     Returns
#     -------
#     ndarray
#         The resulting :math:`dxd` permutation-reflection matrix (containing only integers 0, 1, and -1).
#     """
#     ndim = len(trans)
#     trans_abs = np.abs(trans)
#
#     perm = np.zeros((ndim, ndim), dtype=np.int)
#     remaining_indices = list(range(ndim))
#     # Set the maximum along each column to +/-1, keeping track of the positions already set to avoid collisions
#     for i in range(ndim):
#         m = np.argmax(trans_abs[remaining_indices, i])
#         perm[remaining_indices[m], i] = np.sign(trans[remaining_indices[m], i])
#         remaining_indices.pop(m)
#     return perm
def find_closest_permutation_matrix(trans):
    """
    Find the transformation matrix that *almost* maps voxel axes to original world coordinate axes, but does not
    require interpolation, i.e. the permutation-reflection matrix closest to the given transformation matrix.

    Parameters
    ----------
    trans : array_like
        The :math:`dxd` matrix that represents the original transformations from voxel indices to world coordinates
        (excluding offset).

    Returns
    -------
    ndarray
        The resulting :math:`dxd` permutation-reflection matrix (containing only integers 0, 1, and -1).
    """
    trans_abs = ma.masked_array(np.abs(trans) / (np.linalg.norm(trans, axis=0)[np.newaxis, :]), mask=(np.zeros_like(trans, dtype=np.bool)))

    perm = np.zeros(trans_abs.shape, dtype=np.int)
    # Set the maxima to +/-1, keeping track of rows/columns already set to avoid collisions
    while np.sum(~trans_abs.mask) > 0:
        ij_argmax = np.unravel_index(trans_abs.argmax(), trans_abs.shape)
        perm[ij_argmax] = np.sign(trans[ij_argmax])
        trans_abs.mask[ij_argmax[0], :] = True
        trans_abs.mask[:, ij_argmax[1]] = True
    return perm


def swap(volume, perm):
    """
    Swap the values in the given volume according to the given permutation-reflection matrix.

    Parameters
    ----------
    volume : array_like
        The d-dimensional array whose values are to be swapped.
    perm : array_like
        A :math:`dxd` matrix that gives the permutations and reflections for swapping. If more values are given, the
        upper left :math:`dxd` area is considered. The given array should represent a permutation-reflection matrix that
        maps the coordinate axes of one coordinate system exactly onto the axes of another coordinate system.

    Returns
    -------
    ndarray
        The d-dimensional array that results from swapping.

    See also
    --------
    matrix : Function that creates a permutation-reflection matrix.
    validate_permutation_matrix : Check if a given matrix is a valid permutation-reflection matrix.
    """

    # TODO: (1) Add a new parameter here: `copy` -- if True, keep current behaviour (i.e. the result's data is
    # independent of the given array's data); if False, make the result a view into the given array (i.e. let them share
    # their data). This needs the use of `ndarray.flip` when inverting the axis (and some more care so as not to change
    # the given array in the course of transformations). (2) Use `copy=False` when creating the `aligned_volume` in
    # the `Volume` class.

    volume = np.copy(volume)
    ndim = volume.ndim
    perm = perm[:ndim, :ndim]
    validate_permutation_matrix(perm)

    # Invert the axes as necessary: Sum the columns of the matrix. Get a three-tuple, where each element is either
    # +1, meaning the respective axis (in source coordinates) doesn't have to be inverted, or -1, meaning it has to
    # be inverted; then actually invert the axes
    inv = np.sum(perm, axis=0).astype(np.int)  # Cast to int to avoid deprecation warning in slice creation
    volume = volume[tuple([slice(None, None, i) for i in inv])]

    # Swap the axes as necessary: Transform a vector representing the axis numbers (i.e. (0, 1, 2)) by the absolute
    # value of the given matrix (as the inversions do not matter here), then permute the axes according to the result
    permutations = (np.abs(perm) @ np.arange(ndim)).astype(np.int)
    volume = np.transpose(volume, permutations)

    return volume


def pos(system):
    """
    Return a tuple `(rl, ap, si)` where `rl` holds the index of "R" or "L", `ap` holds the index of "A" or "P",
    and `si` holds the index of "S" or "I" in the given string.

    Parameters
    ----------
    system : str
        String to be processed. Any permutation of {A,P}, {I,S}, {L,R} (case-insensitive) can be used.

    Returns
    -------
    tuple
        The resulting character positions (0, 1, or 2).
    """
    return index(system, "R"), index(system, "A"), index(system, "S")


def index(system, character):
    """
    Get the index that the given character or its anatomical opposite ("A" vs. "P", "I" vs. "S", "L" vs. "R") has in
    the given string.

    Parameters
    ----------
    system : str
        String to be processed. Any permutation of {A,P}, {I,S}, {L,R} (case-insensitive) can be used.
    character : str
        Character to be found. One of "A", "P", "I", "S", "L", "R" (case insensitive).

    Returns
    -------
    int
        Index of the given character.

    Raises
    ------
    ValueError
        If the given character or its anatomical opposite cannot be found.
    """
    system = system.upper()
    character = character.upper()

    i = system.find(character)
    i = system.index(opposites()[character]) if i == -1 else i
    # ^ str.find() returns -1 for mismatch, while str.index() raises an error

    return i


def opposites():
    """
    Create a dictionary that for every uppercase letter defining an anatomical direction, when given as a key, will
    return an uppercase letter that marks the opposite direction in the same anatomical axis. As an example,
    ``opposites()["R"]`` will give "L".

    Returns
    -------
    dict
        A dictionary with each key and value being one of "A", "P", "I", "S", "L", "R" (uppercase).
    """
    return {"R": "L", "A": "P", "S": "I", "L": "R", "P": "A", "I": "S"}


def validate_permutation_matrix(perm):
    """
    Validate a permutation-reflection matrix. A matrix is considered valid if (1) its determinant is either 1 or
    -1 and (2) all of its values are either -1, 0, or 1.

    Parameters
    ----------
    perm : array_like
        The (d, d)-shaped Numpy array to be validated.

    Returns
    -------
    None
        Simply return if the matrix is valid.

    Raises
    ------
    ValueError
        If the matrix is invalid.
    """
    msg = ""
    if np.abs(np.linalg.det(perm)) != 1:
        msg = "the matrix determinant is neither -1 nor 1"
    elif not np.all(np.isin(perm, [-1, 0, 1])):
        msg = "at least one matrix element is not in {-1, 0, 1}"
    if msg:
        raise ValueError("The given matrix is not valid: {}.".format(msg))


def validate_transformation_matrix(mat, tol=1e-3):
    """
    Validate a transformation matrix. A :math:`dxd` matrix is considered valid if (1) its :math:`(d-1)x(d-1)` rotational
    part has a determinant of absolute value close to one, (2) its last row consists of zeros with a trailing one.

    Parameters
    ----------
    mat : array_like
        The (d, d)-shaped Numpy array to be validated.
    tol : float
        Tolerance for absolute value `v` of the rotational part's determinant: if :math:`(1 - tol) <= v <= (1 + tol)`,
        then `v` is considered close to one (default: 1e-3; arbitrary choice).

    Returns
    -------
    None
        Simply return if the matrix is valid.

    Raises
    ------
    ValueError
        If the matrix is invalid.
    """
    # Account for potential scaling: dividing by the column's norms leaves us with the pure rotational part
    rot_part = mat[:-1, :-1]
    scaling = np.linalg.norm(rot_part, axis=0)
    rot_part = rot_part * (1 / scaling[np.newaxis, :])

    abs_det = np.abs(np.linalg.det(rot_part))
    msg = ""
    if not ((1 - tol) <= abs_det <= (1 + tol)):
        msg = "the determinant's absolute value {} is not close to one".format(abs_det)
    elif np.any(mat[-1, :-1] != 0):
        msg = "the last row contains non-zero values"
    elif mat[-1, -1] != 1:
        msg = "the bottom right value is not one, but {}".format(mat[-1, -1])
    if msg:
        raise ValueError("the given matrix is not valid: {}.".format(msg))
