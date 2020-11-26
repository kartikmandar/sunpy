"""
=====================================================
Retrieving and analyzing GOES X-Ray Sensor (XRS) data
=====================================================

The X-ray Sensor (XRS) on board the GOES series of satellites
have provided soft X-ray measurements in two broadband energy
ranges 0.5-4 and 1-8 angstrom since 1975. The GOES 16 and 17
satellites are the latest in line. The flux levels in the GOES
0.1-8 angstrom channel are used to report flares and determine
their size (i.e. their GOES class).

In this example we are going to look at how you can query and
retrieve the GOES XRS data using `~sunpy.net.Fido` and load it
into a `~sunpy.timeseries.TimeSeries`.

Some things are to note. NOAA have recently re-processed the GOES 13,
14 and 15 XRS science quality data, such that the SWPC scaling factor
has been removed. This means that the fluxes will have a different values,
and so will flare peak fluxes. See
`here <https://satdat.ngdc.noaa.gov/sem/goes/data/science/xrs/GOES_13-15_XRS_Science-Quality_Data_Readme.pdf>`__
for more details. The sunpy GOES XRS client for Fido now provides this
new re-processed data. We now also provide the data for GOES 16 and 17.

Another thing to note is that the GOES XRS client `~sunpy.net.Fido` now
returns all available GOES data for the specific timerange queried. For
example, there are times when GOES 13, 14 and 15 overlap and such data is
available from each satellite. Similarly there are times when GOES 16 and 17 overlap.

Lets query the GOES XRS data over a specified timerange:
"""
import matplotlib.pyplot as plt
import numpy as np

from sunpy import timeseries as ts
from sunpy.net import Fido
from sunpy.net import attrs as a

#############################################################
# Lets first define our start and end times and query using the
# `~sunpy.net.Fido`.
tstart = "2015-06-21 01:00"
tend = "2015-06-21 23:00"
result = Fido.search(a.Time(tstart, tend), a.Instrument("XRS"))
print(result)

#############################################################
# As we can see this now returns three results, one file for GOES
# 13, one for GOES 14 and one for GOES 15, which can be identfied
# by the `SatelliteNumber` column. However, we probably will only want
# one of these files for our analysis, so we can query by the `attrs`:
# `a.goes.SatelliteNumber` to specify what GOES satellite number we want
# to use.
result_goes15 = Fido.search(a.Time(tstart, tend), a.Instrument("XRS"), a.goes.SatelliteNumber(15))
print(result_goes15)

#############################################################
# Now we can see that this returns just one file for the GOES 15 data.
# Lets now download this data using `~sunpy.net.Fido.fetch`.
file_goes15 = Fido.fetch(result_goes15)

#############################################################
# Also just to note, if this will download the file to the
# `~/sunpy/data/` directory on your local machine. You can also
# define where you want this to download to using the `path` keyword
# argument in .fetch (e.g. Fido.fetch(result, path=".\")).

#############################################################
# Lets now load this data into a `~sunpy.timeseries.TimeSeries`,
# and inspect the data using `.peek()`
goes_15 = ts.TimeSeries(file_goes15)
goes_15.peek()

###############################################################
# We can also pull out the individual GOES chanels and plot. The 0.5-4 angstrom
# channel is known as the "xrsa" channel and the 1-8 angstrom channel is known
# as the "xrsb" channel.
fig, ax = plt.subplots()
ax.plot(goes_15.index, goes_15.quantity("xrsb"))
ax.set_ylabel("Flux (Wm$^{-2}$)")
ax.set_xlabel("Time")
fig.autofmt_xdate()
plt.show()

###############################################################
# We can also truncate the data for the time of the large flare,
# and analyze the different channels. For example, we can plot the
# derivative which is useful in terms of the Neupert effect when analyzing
# flares
goes_flare = goes_15.truncate("2015-06-21 09:35", "2015-06-21 10:30")
fig, ax = plt.subplots()
ax.plot(goes_flare.index, np.gradient(goes_flare.quantity("xrsb")))
ax.set_ylabel("Flux (Wm$^{-2}$$s^{-1}$)")
fig.autofmt_xdate()
plt.show()
