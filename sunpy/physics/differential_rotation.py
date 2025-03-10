from copy import deepcopy

import numpy as np

import astropy.units as u
from astropy.coordinates import BaseCoordinateFrame, SkyCoord
from astropy.time import TimeDelta

import sunpy.sun.models
from sunpy.coordinates import (
    Heliocentric,
    HeliographicStonyhurst,
    Helioprojective,
    get_earth,
    transform_with_sun_center,
)
from sunpy.map import (
    contains_full_disk,
    coordinate_is_on_solar_disk,
    is_all_off_disk,
    is_all_on_disk,
    map_edges,
    on_disk_bounding_coordinates,
)
from sunpy.map.header_helper import get_observer_meta
from sunpy.time import parse_time
from sunpy.util import expand_list
from sunpy.util.decorators import deprecated
from sunpy.util.exceptions import warn_user

__all__ = ['diff_rot', 'solar_rotate_coordinate', 'differential_rotate']


@u.quantity_input
@deprecated(since="6.0", alternative="sunpy.sun.models.differential_rotation")
def diff_rot(duration: u.s, latitude: u.deg, rot_type='howard', frame_time='sidereal'):
    r"""
    This function computes the change in longitude over days in degrees.

    Parameters
    ----------
    duration : `~astropy.units.Quantity`
        Number of seconds to rotate over.
    latitude : `~astropy.units.Quantity`
        heliographic coordinate latitude in Degrees.
    rot_type : `str`
        The differential rotation model to use.

        One of:

        | ``howard`` : Use values from :cite:t:`howard_solar_1990`
        | ``snodgrass`` : Use values from :cite:t:`snodgrass_magnetic_1983`
        | ``allen`` : Use values from Allen's Astrophysical Quantities, and simpler equation.
        | ``rigid`` : Use values from `~sunpy.sun.constants.sidereal_rotation_rate`.

    frame_time : `str`
        One of : ``'sidereal'`` or  ``'synodic'``. Choose 'type of day' time reference frame.

    Returns
    -------
    longitude_delta : `~astropy.units.Quantity`
        The change in longitude over days (units=degrees)

    Notes
    -----
    The rotation rate at a heliographic latitude :math:`\theta` is given by

    .. math::

        A + B \sin^{2} \left (\theta \right ) + C \sin^{4} \left ( \theta \right )

    where :math:`A, B, C` are constants that depend on the model:

    ========= ======= ====== ====== ==========
    Model     A       B      C      Unit
    ========= ======= ====== ====== ==========
    howard    2.894   -0.428 -0.370 microrad/s
    snodgrass 2.851   -0.343 -0.474 microrad/s
    allen     14.44   -3.0   0      deg/day
    rigid     14.1844 0      0      deg/day
    ========= ======= ====== ====== ==========

    1 microrad/s is approximately 4.95 deg/day.
    See also the comparisons in :cite:t:`beck_comparison_2000`.
    """

    return sunpy.sun.models.differential_rotation(duration, latitude, model=rot_type, frame_time=frame_time)


def _validate_observer_args(initial_obstime, observer, time):
    if (observer is not None) and (time is not None):
        raise ValueError(
            "Either the 'observer' or the 'time' keyword must be specified, "
            "but not both simultaneously.")
    elif observer is not None:
        # Check that the new_observer is specified correctly.
        if not (isinstance(observer, BaseCoordinateFrame | SkyCoord)):
            raise ValueError(
                "The 'observer' must be an astropy.coordinates.BaseCoordinateFrame or an astropy.coordinates.SkyCoord.")
        if observer.obstime is None:
            raise ValueError("The observer 'obstime' property must not be None.")
    elif observer is None and time is None:
        raise ValueError("Either the 'observer' or the 'time' keyword must not be None.")


def _get_new_observer(initial_obstime, observer, time):
    """
    Helper function that interprets the possible ways of specifying the
    input to the solar coordinate rotation function.

    If the "observer" argument is not `None`, it is used to specify the location
    of the new observer in space and time.

    If the "time" argument is not `None`, it is used to calculate the duration
    over which to the amount of solar rotation is calculated. Note that using
    the "time" keyword assumes that the new observer is on the Earth. This may
    be a reasonable assumption depending on the application.

    Either the "observer" or "time" argument must be specified, but both
    cannot be specified at the same time and both cannot be None.

    Parameters
    ----------
    initial_obstime : `~astropy.time.Time`
        The initial time before solar rotation has been applied.
    observer : `~astropy.coordinates.BaseCoordinateFrame`, `~astropy.coordinates.SkyCoord`, None
        The location of the new observer in space and time (the observer must have an
        interpretable obstime property).
    time : `~astropy.time.Time`, `~astropy.time.TimeDelta`, `~astropy.units.Quantity`, None
        Used to define the duration over which the amount of solar rotation is
        calculated. If 'time' is an `~astropy.time.Time` then the time interval is
        "time - initial_obstime"; if 'time' is `~astropy.time.TimeDelta` or
        `~astropy.units.Quantity` then the calculation is "initial_obstime + time".

    Returns
    -------
    new_observer : `~astropy.coordinates.SkyCoord`, `~astropy.coordinates.BaseCoordinateFrame`
        The position of the observer in space and time. If the "time" keyword is used
        the output is an `~astropy.coordinates.SkyCoord`. If the "observer" keyword
        is not None the output has the same type as the "observer" keyword. In all cases
        the output is specified in the heliographic Stonyhurst coordinate system.
    """
    _validate_observer_args(initial_obstime, observer, time)
    # Check the input and create the new observer
    if observer is not None:
        new_observer = observer
    elif time is not None:
        warn_user("Using 'time' assumes an Earth-based observer.")
        if isinstance(time, TimeDelta) or isinstance(time, u.Quantity):
            new_observer_time = initial_obstime + time
        else:
            new_observer_time = parse_time(time)
        new_observer = get_earth(new_observer_time)
    return new_observer


def solar_rotate_coordinate(coordinate, observer=None, time=None, **diff_rot_kwargs):
    """
    Given a coordinate on the Sun, calculate where that coordinate maps to
    as seen by a new observer at some later or earlier time, given that
    the input coordinate rotates according to the solar rotation profile.

    The amount of solar rotation is based on the amount of time between the
    observation time of the input coordinate and the observation time of the
    new observer. The new observer is specified in one of two ways, either
    using the "observer" or "time" keywords.

    If the "observer" keyword is set, it is used to specify the location
    of the new observer in space and time. The difference between the
    coordinate time and the new observer time is used to calculate the amount
    of solar rotation applied, and the location of the new observer in space
    is used to calculate where the rotated coordinate is as seen from the
    new observer.

    If the "time" keyword is set, it is used to specify the number of
    seconds to rotate the coordinate by. Note that using the "time" keyword
    assumes that the new observer is on the Earth. This may be a reasonable
    assumption depending on the application.

    Either the "observer" or "time" keyword must be specified, but both
    cannot be specified at the same time.

    Parameters
    ----------
    coordinate : `~astropy.coordinates.SkyCoord`
        Any valid coordinate which is transformable to Heliographic Stonyhurst.
    observer : `~astropy.coordinates.BaseCoordinateFrame`, `~astropy.coordinates.SkyCoord`, None
        The location of the new observer in space and time (the observer must have an
        interpretable obstime property).
    time : `~astropy.time.Time`, `~astropy.time.TimeDelta`, `~astropy.units.Quantity`, None
    **diff_rot_kwargs : `dict`
        Keyword arguments are passed on as keyword arguments to `~sunpy.sun.models.differential_rotation`.
        Note that the keyword "frame_time" is automatically set to the value
        "sidereal".

    Returns
    -------
    coordinate : `~astropy.coordinates.SkyCoord`
        The locations of the input coordinates after the application of
        solar rotation as seen from the point-of-view of the new observer.

    Notes
    -----
    The translational motion of the Sun over the time interval will be ignored.
    See :func:`~sunpy.coordinates.transform_with_sun_center`.

    Examples
    --------
    >>> import astropy.units as u
    >>> from astropy.coordinates import SkyCoord
    >>> from sunpy.coordinates import Helioprojective, get_body_heliographic_stonyhurst
    >>> from sunpy.physics.differential_rotation import solar_rotate_coordinate
    >>> from sunpy.time import parse_time
    >>> start_time = parse_time('2010-09-10 12:34:56')
    >>> c = SkyCoord(-570*u.arcsec, 120*u.arcsec, obstime=start_time,
    ...              observer="earth", frame=Helioprojective)
    >>> solar_rotate_coordinate(c, time=start_time + 25*u.hr)  # doctest: +SKIP
    <SkyCoord (Helioprojective: obstime=2010-09-11T13:34:56.000, rsun=695700.0 km, observer=<HeliographicStonyhurst Coordinate (obstime=2010-09-11T13:34:56.000, rsun=695700.0 km): (lon, lat, radius) in (deg, deg, AU)
        (-5.68434189e-14, 7.24318962, 1.00669016)>): (Tx, Ty, distance) in (arcsec, arcsec, AU)
        (-378.27830452, 105.70767875, 1.00245134)>
    >>> new_observer = get_body_heliographic_stonyhurst("earth", start_time + 6*u.day)
    >>> solar_rotate_coordinate(c, observer=new_observer)
    <SkyCoord (Helioprojective: obstime=2010-09-16T12:34:56.000, rsun=695700.0 km, observer=<HeliographicStonyhurst Coordinate (obstime=2010-09-16T12:34:56.000, rsun=695700.0 km): (lon, lat, radius) in (deg, deg, AU)
        (2.65061438e-14, 7.18706547, 1.00534174)>): (Tx, Ty, distance) in (arcsec, arcsec, AU)
        (620.42567049, 126.13662663, 1.00185786)>
    """
    # Check the input and create the new observer
    new_observer = _get_new_observer(coordinate.obstime, observer, time)

    # The keyword "frame_time" must be explicitly set to "sidereal"
    # when using this function.
    diff_rot_kwargs.update({"frame_time": "sidereal"})

    # Calculate the interval between the start and end time
    interval = (new_observer.obstime - coordinate.obstime).to(u.s)

    # Compute Stonyhurst Heliographic coordinates - returns (longitude,
    # latitude). Points off the limb are returned as nan.
    heliographic_coordinate = coordinate.transform_to(HeliographicStonyhurst)

    # Compute the differential rotation
    drot = sunpy.sun.models.differential_rotation(interval, heliographic_coordinate.lat.to(u.degree), **diff_rot_kwargs)

    # Rotate the input coordinate as seen by the original observer
    heliographic_rotated = SkyCoord(heliographic_coordinate.lon + drot,
                                    heliographic_coordinate.lat,
                                    heliographic_coordinate.radius,
                                    obstime=coordinate.obstime,
                                    frame=HeliographicStonyhurst)

    # Calculate where the rotated coordinate appears as seen by new observer
    # for the coordinate system of the input coordinate. The translational
    # motion of the Sun will be ignored for the transformation.

    if "observer" in coordinate.frame.frame_attributes.keys():
        frame_newobs = coordinate.frame.replicate_without_data(observer=new_observer,
                                                           obstime=new_observer.obstime)
    else:
        frame_newobs = coordinate.frame.replicate_without_data(obstime=new_observer.obstime)
    with transform_with_sun_center():
        return heliographic_rotated.transform_to(frame_newobs)


def _rotate_submap_edge(smap, pixels, observer, **diff_rot_kwargs):
    """
    Helper function that is used to calculate where the edge of a rectangular
    map move to on rotation.

    If all the pixels passed in are not on disk and
    therefore subject to solar differential rotation, the coordinates
    corresponding to the input pixels are returned.

    Parameters
    ----------
    smap : `~sunpy.map.Map`
        The input map from which the pixel coordinates are calculated.
    pixels : `~astropy.units.Quantity`
        A Quantity array of shape (M, 2) in pixel units. Values (:, 0) are the x values of the
        pixel indices, and values ``[:, 1]`` are the "y" values of the pixel indices.
    observer : `~astropy.coordinates.SkyCoord`
        The location of the observer.
    **diff_rot_kwargs : None, `~dict`
        Keyword arguments accepted by `~sunpy.sun.models.differential_rotation`.

    Returns
    -------
    coordinates : `~astropy.coordinates.SkyCoord`
        The coordinates of a rotated edge.
    """
    # Coordinates
    c = smap.wcs.pixel_to_world(pixels[:, 0].value, pixels[:, 1].value)

    # Only apply solar rotation if all coordinates are on the disk.
    if np.all(~coordinate_is_on_solar_disk(c)):
        coordinates = deepcopy(c)
    else:
        coordinates = solar_rotate_coordinate(c, observer=observer, **diff_rot_kwargs)
    return coordinates


def _get_extreme_position(coords, axis, operator=np.nanmax):
    """
    Helper function that calculates an extreme position from a list of
    coordinates.

    Parameters
    ----------
    coords : `~list`
        Each member of the list is a `~astropy.coordinates.SkyCoord`.
    axis : 'Tx', 'Ty'
        Which helioprojective axis to examine.
    operator : numpy function
        A numpy function that finds an extreme value in an array
        of helioprojective coordinate values. Defaults to `numpy.nanmax`.

    Returns
    -------
    `float`
        An extreme position in units of arcseconds.
    """
    extreme_values = []
    for coord in coords:
        if axis == 'Tx':
            extreme_value = operator(coord.Tx.value)
        elif axis == 'Ty':
            extreme_value = operator(coord.Ty.value)
        else:
            raise ValueError('The "axis" argument must be either "Tx" or "Ty".')
        extreme_values.append(extreme_value)

    return operator(extreme_values)


def _get_bounding_coordinates(coords):
    """
    Helper function that returns the bottom left and top right coordinates
    that define a bounding box enclosing the passed in coordinates.

    Parameters
    ----------
    coords : `list`
        Each member of the list is a `~astropy.coordinates.SkyCoord`.

    Returns
    -------
    `~astropy.coordinates.SkyCoord`
        A  `~astropy.coordinates.SkyCoord` of length 2 that specifies the
        bottom left hand (first entry) and top right hand (second entry) corner
        of a bounding box that minimally encloses all the input coordinates.
    """
    rotated_x_min = _get_extreme_position(coords, "Tx", operator=np.nanmin)
    rotated_x_max = _get_extreme_position(coords, "Tx", operator=np.nanmax)
    rotated_y_min = _get_extreme_position(coords, "Ty", operator=np.nanmin)
    rotated_y_max = _get_extreme_position(coords, "Ty", operator=np.nanmax)
    return SkyCoord([rotated_x_min, rotated_x_max] * u.arcsec,
                    [rotated_y_min, rotated_y_max] * u.arcsec,
                    frame=coords[0].frame)


def _warp_sun_coordinates(xy, smap, new_observer, **diff_rot_kwargs):
    """
    This function takes pixel coordinates in the warped image (`xy`) and
    calculates the pixel locations of those pixels in the map.

    To do this it converts the input pixel coordinates to helioprojective
    coordinates as seen by new_observer, then transforms them to heliographic
    Stonyhurst, adds the differential rotation correction and then transforms
    them back to helioprojective coordinates as seen by the map observer and
    then calculates their corresponding pixel coordinates in the input map.

    This is an inverse function needed by `skimage.transform.warp`.

    Parameters
    ----------
    xy : `numpy.ndarray`
        Pixel coordinates in the warped image.
    smap : `~sunpy.map.GenericMap`
        Original map that we want to transform.

    Returns
    -------
    xy2 : `numpy.ndarray`
        Pixel coordinates in the map corresponding to the input pixels in the
        warped image.

    Notes
    -----
    The translational motion of the Sun over the time interval will be ignored.
    See :func:`~sunpy.coordinates.transform_with_sun_center`.
    """
    # Suppress NaN warnings in coordinate transforms
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')

        # The time interval between the new observer time and the map observation time.
        interval = (parse_time(new_observer.obstime) - parse_time(smap.date)).to(u.s)

        # We need to get the input pixel coordinates into the OUTPUT HPC frame.
        # To save us having to construct a WCS etc, we do the transformation
        # using the output map, and then replace the observer in place before
        # transforming to HGS. This is acceptable because the pixel -> world
        # transformation is independent of the observer.
        input_pixels = xy.T
        map_coord = smap.wcs.pixel_to_world(*input_pixels)
        output_hpc_coords = SkyCoord(map_coord.Tx,
                                     map_coord.Ty,
                                     map_coord.distance,
                                     obstime=new_observer.obstime,
                                     observer=new_observer,
                                     frame=Helioprojective)
        heliographic_coordinate = output_hpc_coords.transform_to(HeliographicStonyhurst)

        # Compute the differential rotation.
        drot = sunpy.sun.models.differential_rotation(interval, heliographic_coordinate.lat.to(u.degree), **diff_rot_kwargs)

        # The change in longitude is negative because we are mapping from the
        # new coordinates to the old.
        rotated_coord = SkyCoord(heliographic_coordinate.lon - drot,
                                 heliographic_coordinate.lat,
                                 heliographic_coordinate.radius,
                                 obstime=heliographic_coordinate.obstime,
                                 frame=HeliographicStonyhurst)

        with transform_with_sun_center():
            # As seen from the map observer, which coordinates are behind the Sun.
            where_off_disk_from_map_observer = rotated_coord.transform_to(
                Heliocentric(observer=smap.observer_coordinate)).z.value < 0

            # Re-project the pixels which are on disk back to location of the original observer
            coordinates_at_map_observer = rotated_coord.transform_to(smap.coordinate_frame)

        # Go back to pixel coordinates
        x2, y2 = smap.wcs.world_to_pixel(coordinates_at_map_observer)

    # Re-stack the data to make it correct output form
    xy2 = np.dstack([x2.T.flat, y2.T.flat])[0]
    # Set the off disk coordinates to NaN so they are not included in the output image.
    xy2[where_off_disk_from_map_observer.flat] = np.nan

    return xy2


def differential_rotate(smap, observer=None, time=None, **diff_rot_kwargs):
    """
    Warp a `~sunpy.map.GenericMap` to take into account both solar differential
    rotation and the changing location of the observer.

    .. warning::
        This function, while greatly improved in 1.0, is still experimental.
        Please validate that it gives you results you expect and report any
        discrepancies on the SunPy issue tracker.

    The function transforms the input map data pixels by first rotating each
    pixel according to solar differential rotation. The amount of solar
    differential applied is calculated by the time difference between the
    observation time of map and the new observation time, as specified by either the
    "time" keyword or the "obstime" property of the "observer" keyword.
    The location of the rotated pixels are then transformed to locations on the Sun
    as seen from the new observer position. This is desirable since in most cases
    the observer does not remain at a fixed position in space. If
    the "time" keyword is used then the new observer position is assumed to
    be based on the location of the Earth. If the "observer" keyword is used then
    this defines the new observer position.

    The function works with full disk maps and maps that contain portions of the
    solar disk (maps that are entirely off-disk will raise an error). When the
    input map contains the full disk, the output map has the same dimensions as
    the input map. When the input map images only part of the solar disk, only
    the on-disk pixels are differentially rotated and the output map can have
    a different dimensions compared to the input map. In this case any off-disk
    emission shown in the input map is not included in the output map.

    Parameters
    ----------
    smap : `~sunpy.map.GenericMap`
        Original map that we want to transform.
    observer : `~astropy.coordinates.BaseCoordinateFrame`, `~astropy.coordinates.SkyCoord`, `None`, optional
        The location of the new observer.
        Instruments in Earth orbit can be approximated by using the position
        of the Earth at the observation time of the new observer.
    time : sunpy-compatible time, `~astropy.time.TimeDelta`, `~astropy.units.Quantity`, `None`, optional
        Used to define the duration over which the amount of solar rotation is
        calculated. If 'time' is an `~astropy.time.Time` then the time interval
        is difference between 'time' and the map observation time. If 'time' is
        `~astropy.time.TimeDelta` or `~astropy.units.Quantity` then the calculation
        is "initial_obstime + time".

    Returns
    -------
    `~sunpy.map.GenericMap`
        A map with the result of applying solar differential rotation to the
        input map.

    Notes
    -----
    The translational motion of the Sun over the time interval will be ignored.
    See :func:`~sunpy.coordinates.transform_with_sun_center`.
    """
    # If the entire map is off-disk, return an error so the user is aware.
    if is_all_off_disk(smap):
        raise ValueError("The entire map is off disk. No data to differentially rotate.")

    # Get the new observer
    new_observer = _get_new_observer(smap.date, observer, time)

    # Only this function needs scikit image
    from skimage import transform

    # Check whether the input contains the full disk of the Sun
    is_sub_full_disk = not contains_full_disk(smap)
    if is_sub_full_disk:
        # Find the minimal submap of the input map that includes all the
        # on disk pixels. This is required in order to calculate how
        # much to pad the output (solar-differentially rotated) data array by
        # compared to the input map.
        # The amount of padding is dependent on the amount of solar differential
        # rotation and where the on-disk pixels are (since these pixels are the only ones
        # subject to solar differential rotation).
        if not is_all_on_disk(smap):
            # Get the bottom left and top right coordinates that are the
            # vertices that define a box that encloses the on disk pixels
            bottom_left, top_right = on_disk_bounding_coordinates(smap)

            # Create a submap that excludes the off disk emission that does
            # not need to be rotated.
            smap = smap.submap(bottom_left, top_right=top_right)
        bottom_left = smap.bottom_left_coord
        top_right = smap.top_right_coord

        # Get the edges of the minimal submap that contains all the on-disk pixels.
        edges = map_edges(smap)

        # Calculate where the output array moves to.
        # Rotate the top and bottom edges
        rotated_top = _rotate_submap_edge(smap, edges[0], observer=new_observer, **diff_rot_kwargs)
        rotated_bottom = _rotate_submap_edge(
            smap, edges[1], observer=new_observer, **diff_rot_kwargs)

        # Rotate the left and right hand edges
        rotated_lhs = _rotate_submap_edge(smap, edges[2], observer=new_observer, **diff_rot_kwargs)
        rotated_rhs = _rotate_submap_edge(smap, edges[3], observer=new_observer, **diff_rot_kwargs)

        # Calculate the bounding box of the rotated map
        rotated_bl, rotated_tr = _get_bounding_coordinates(
            [rotated_top, rotated_bottom, rotated_lhs, rotated_rhs])

        # Calculate the maximum distance in pixels the map has moved by comparing
        # how far the original and rotated bounding boxes have moved.
        diff_x = [(np.abs(rotated_bl.Tx - bottom_left.Tx)).value,
                  (np.abs(rotated_tr.Tx - top_right.Tx)).value]
        deltax = int(np.ceil(np.max(diff_x) / smap.scale.axis1).value)

        diff_y = [(np.abs(rotated_bl.Ty - bottom_left.Ty)).value,
                  (np.abs(rotated_tr.Ty - top_right.Ty)).value]
        deltay = int(np.ceil(np.max(diff_y) / smap.scale.axis2).value)

        # Create a new `smap` with the padding around it
        padded_data = np.pad(smap.data, ((deltay, deltay), (deltax, deltax)),
                             'constant', constant_values=0)
        padded_meta = deepcopy(smap.meta)
        padded_meta['naxis2'], padded_meta['naxis1'] = smap.data.shape

        padded_meta['crpix1'] += deltax
        padded_meta['crpix2'] += deltay

        # Create the padded map that will be used to create the rotated map.
        smap = smap._new_instance(padded_data, padded_meta, smap.plot_settings)

    # Check for masked maps
    if smap.mask is not None:
        smap_data = np.ma.array(smap.data, mask=smap.mask)
    else:
        smap_data = smap.data

    # Create the arguments for the warp function.
    warp_args = {'smap': smap, 'new_observer': new_observer}
    warp_args.update(diff_rot_kwargs)

    # Apply solar differential rotation as a scikit-image warp
    out_data = transform.warp(smap_data, inverse_map=_warp_sun_coordinates,
                              map_args=warp_args, preserve_range=True, cval=np.nan)

    out_meta = deepcopy(smap.meta)

    # Need to update the observer location for the output map.
    # Remove all the possible observer keys
    all_keys = expand_list([e[0] for e in smap._supported_observer_coordinates])
    for key in all_keys:
        out_meta.pop(key)

    # Add a new HGS observer
    out_meta.update(get_observer_meta(new_observer, smap.rsun_meters))

    if is_sub_full_disk:
        # Define a new reference pixel and the value at the reference pixel.
        # Note that according to the FITS convention the first pixel in the
        # image is at (1.0, 1.0).
        center_rotated = solar_rotate_coordinate(
            smap.center, observer=new_observer, **diff_rot_kwargs)
        out_meta['crval1'] = center_rotated.Tx.value
        out_meta['crval2'] = center_rotated.Ty.value
        out_meta['crpix1'] = 1 + smap.data.shape[1]/2.0 + \
            ((center_rotated.Tx - smap.center.Tx)/smap.scale.axis1).value
        out_meta['crpix2'] = 1 + smap.data.shape[0]/2.0 + \
            ((center_rotated.Ty - smap.center.Ty)/smap.scale.axis2).value

    outmap = smap._new_instance(out_data, out_meta, smap.plot_settings)

    # Update the meta information with the new date and time.
    outmap._set_date(new_observer.obstime)
    outmap._set_reference_date(new_observer.obstime)

    if is_sub_full_disk:
        return outmap.submap(rotated_bl, top_right=rotated_tr)
    return outmap
