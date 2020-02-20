# Copyright 2019 Mechanics of Microstructures Group
#    at The University of Manchester
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import numpy as np
from matplotlib.pyplot import imread
import inspect

from skimage import transform as tf
from skimage import morphology as mph

from scipy.stats import mode

import peakutils

from defdap.file_readers import DICDataLoader
from defdap import base
from defdap.quat import Quat
from defdap import plotting

from defdap.plotting import MapPlot, GrainPlot


class Map(base.Map):

    def __init__(self, path, fname, dataType=None):
        """Initialise class and import DIC data from file

        Args:
            path(str): Path to file
            fname(str): Name of file including extension
        """

        # Call base class constructor
        super(Map, self).__init__()

        print("\rLoading DIC data...", end="")

        # Initialise variables
        self.format = None      # Software name
        self.version = None     # Software version
        self.binning = None     # Sub-window size in pixels
        self.xdim = None        # size of map along x (from header)
        self.ydim = None        # size of map along y (from header)

        self.xc = None          # x coordinates
        self.yc = None          # y coordinates
        self.xd = None          # x displacement
        self.yd = None          # y displacement

        self.ebsdMap = None                 # EBSD map linked to DIC map
        self.ebsdTransform = None           # Transform from EBSD to DIC coordinates
        self.ebsdTransformInv = None        # Transform from DIC to EBSD coordinates
        self.currGrainId = None             # ID of last selected grain
        self.ebsdGrainIds = None
        self.patternImPath = None           # Path to BSE image of map
        self.plotHomog = self.plotMaxShear  # Use max shear map for defining homologous points
        self.highlightAlpha = 0.6
        self.bseScale = None                # size of a pixel in the correlated images
        self.patScale = None                # size of pixel in loaded
        # pattern relative to pixel size of dic data i.e 1 means they
        # are the same size and 2 means the pixels in the pattern are
        # half the size of the dic data.
        self.path = path                    # file path
        self.fname = fname                  # file name

        self.loadData(path, fname, dataType=dataType)
  
        # *dim are full size of data. *Dim are size after cropping
        self.xDim = self.xdim
        self.yDim = self.ydim
        
        self.x_map = self._map(self.xd)     # u (displacement component along x)
        self.y_map = self._map(self.yd)     # v (displacement component along x)
        xDispGrad = self._grad(self.x_map)
        yDispGrad = self._grad(self.y_map)
        self.f11 = xDispGrad[1] + 1         # f11
        self.f22 = yDispGrad[0] + 1         # f22
        self.f12 = xDispGrad[0]             # f12
        self.f21 = yDispGrad[1]             # f21

        self.max_shear = np.sqrt((((self.f11 - self.f22) / 2.)**2) +
                                 ((self.f12 + self.f21) / 2.)**2)   # max shear component

        self.cropDists = np.array(((0, 0), (0, 0)), dtype=int)      # crop distances (default all zeros)

        print("\rLoaded {0} {1} data (dimensions: {2} x {3} pixels, sub-window size: {4} x {4} pixels)".
              format(self.format, self.version, self.xdim, self.ydim, self.binning))

    @property
    def plotDefault(self):
        # return self.plotMaxShear(plotGBs=True, *args, **kwargs)
        return lambda *args, **kwargs: self.plotMaxShear(plotGBs=True, *args, **kwargs)

    @property
    def crystalSym(self):
        return self.ebsdMap.crystalSym

    def loadData(self, fileDir, fileName, dataType=None):
        dataType = "DavisText" if dataType is None else dataType

        dataLoader = DICDataLoader()
        if dataType == "DavisText":
            metadataDict = dataLoader.loadDavisMetadata(fileName, fileDir)
            dataDict = dataLoader.loadDavisData(fileName, fileDir)
        else:
            raise Exception("No loader found for this DIC data.")

        self.format = metadataDict['format']      # Software name
        self.version = metadataDict['version']    # Software version
        self.binning = metadataDict['binning']    # Sub-window width in pixels
        self.xdim = metadataDict['xDim']          # size of map along x (from header)
        self.ydim = metadataDict['yDim']          # size of map along y (from header)

        self.xc = dataDict['xc']    # x coordinates
        self.yc = dataDict['yc']    # y coordinates
        self.xd = dataDict['xd']    # x displacement
        self.yd = dataDict['yd']    # y displacement

    def _map(self, data_col):
        data_map = np.reshape(np.array(data_col), (self.ydim, self.xdim))
        return data_map

    def _grad(self, data_map):
        grad_step = min(abs((np.diff(self.xc))))
        data_grad = np.gradient(data_map, grad_step, grad_step)
        return data_grad

    def retrieveName(self):
        """
        Gets the first name assigned to the a map, as a string

        var(obj) variable to get name of
        """
        for fi in reversed(inspect.stack()):
            names = [var_name for var_name, var_val in fi.frame.f_locals.items() if var_val is self]
            if len(names) > 0:
                return names[0]

    def setScale(self, micrometrePerPixel):
        """
        Sets the scale of the map

        micrometrePerPixel(float) length of pixel in original BSE image in micrometres
        """
        self.bseScale = micrometrePerPixel

    @property
    def scale(self):
        if self.bseScale is None:
            raise ValueError("Map scale not set. Set with setScale()")

        return self.bseScale * self.binning

    def printStatsTable(self, percentiles, components):
        """
        Print out statistics table for a DIC map

        percentiles(list) list of percentiles to print (number, Min, Mean or Max)
        components(list of str) lis of map components to print i.e. f11, mss
        """

        # Print map info
        print('\033[1m', end='')    # START BOLD
        print("{0} (dimensions: {1} x {2} pixels, sub-window size: {3} "
              "x {3} pixels, number of points: {4})\n".format(
            self.retrieveName(),
            self.xDim,
            self.yDim,
            self.binning,
            self.xDim * self.yDim
        ))

        # Print table header
        print("Component\t".format(), end="")
        for x in percentiles:
            if x == 'Min' or x == 'Mean' or x == 'Max':
                print("{0}\t".format(x), end='')
            else:
                print("P{0}\t".format(x), end='')
        print('\033[0m', end='')    # END BOLD
        print()

        # Print table
        for c in components:
            selmap = []
            if c == 'mss':
                selmap = self.crop(self.max_shear) * 100
            if c == 'f11':
                selmap = (self.crop(self.f11) - 1) * 100
            if c == 'f12':
                selmap = self.crop(self.f12) * 100
            if c == 'f21':
                selmap = self.crop(self.f21) * 100
            if c == 'f22':
                selmap = (self.crop(self.f22) - 1) * 100
            plist = []
            for p in percentiles:
                if p == 'Min':
                    plist.append(np.min(selmap))
                elif p == 'Mean':
                    plist.append(np.mean(selmap))
                elif p == 'Max':
                    plist.append(np.max(selmap))
                else:
                    plist.append(np.percentile(selmap, p))
            print("{0}\t\t".format(c), end="")
            for l in plist:
                print("{0:.2f}\t".format(l), end='')
            print()
        print()

    def setCrop(self, xMin=None, xMax=None, yMin=None, yMax=None, updateHomogPoints=False):
        """Set a crop for the DIC map

        Args:
            xMin(int): Distance to crop from left in pixels
            xMax(int): Distance to crop from right in pixels
            yMin(int): Distance to crop from top in pixels
            yMax(int): Distance to crop from bottom in pixels
            updateHomogPoints (bool, optional): Change homologous points to reflect crop
        """
        # changes in homog points
        dx = 0
        dy = 0

        # update crop distances
        if xMin is not None:
            if updateHomogPoints:
                dx = self.cropDists[0, 0] - int(xMin)
            self.cropDists[0, 0] = int(xMin)
        if xMax is not None:
            self.cropDists[0, 1] = int(xMax)
        if yMin is not None:
            if updateHomogPoints:
                dy = self.cropDists[1, 0] - int(yMin)
            self.cropDists[1, 0] = int(yMin)
        if yMax is not None:
            self.cropDists[1, 1] = int(yMax)

        # update homogo points if required
        if updateHomogPoints and (dx != 0 or dy != 0):
            self.updateHomogPoint(homogID=-1, delta=(dx, dy))

        # set new cropped dimensions
        self.xDim = self.xdim - self.cropDists[0, 0] - self.cropDists[0, 1]
        self.yDim = self.ydim - self.cropDists[1, 0] - self.cropDists[1, 1]

    def crop(self, mapData, binned=True):
        if binned:
            multiplier = 1
        else:
            multiplier = self.patScale

        minY = int(self.cropDists[1, 0] * multiplier)
        maxY = int((self.ydim - self.cropDists[1, 1]) * multiplier)

        minX = int(self.cropDists[0, 0] * multiplier)
        maxX = int((self.xdim - self.cropDists[0, 1]) * multiplier)

        return mapData[minY:maxY, minX:maxX]

    def setHomogPoint(self, points=None, display=None):
        
        if points is not None:
            self.homogPoints = points
            
        if points is None:
            if display is None:
                display = "maxshear"

            # Set plot dafault to display selected image
            display = display.lower().replace(" ", "")
            if display == "bse" or display == "pattern":
                self.plotHomog = self.plotPattern
                binSize = self.patScale
            else:
                self.plotHomog = self.plotMaxShear
                binSize = 1

            # Call set homog points from base class setting the bin size
            super(type(self), self).setHomogPoint(binSize=binSize, points=points)

    def linkEbsdMap(self, ebsdMap, transformType="affine", order=2):
        """Calculates the transformation required to align EBSD dataset to DIC

        Args:
            ebsdMap(ebsd.Map): EBSD map object to link
            transformType(string, optional): affine, piecewiseAffine or polynomial
            order(int, optional): Order of polynomial transform to apply
        """

        self.ebsdMap = ebsdMap
        if transformType == "piecewiseAffine":
            self.ebsdTransform = tf.PiecewiseAffineTransform()
            self.ebsdTransformInv = self.ebsdTransform.inverse
        elif transformType == "polynomial":
            self.ebsdTransform = tf.PolynomialTransform()
            # You can't calculate the inverse of a polynomial transform
            # so have to estimate by swapping source and destination
            # homog points
            self.ebsdTransformInv = tf.PolynomialTransform()
            self.ebsdTransformInv.estimate(
                np.array(self.ebsdMap.homogPoints),
                np.array(self.homogPoints),
                order=order
            )
            # calculate transform from EBSD to DIC frame
            self.ebsdTransform.estimate(
                np.array(self.homogPoints),
                np.array(self.ebsdMap.homogPoints),
                order=order
            )
            return
        else:
            self.ebsdTransform = tf.AffineTransform()
            self.ebsdTransformInv = self.ebsdTransform.inverse

        # calculate transform from EBSD to DIC frame
        self.ebsdTransform.estimate(
            np.array(self.homogPoints),
            np.array(self.ebsdMap.homogPoints)
        )

    def checkEbsdLinked(self):
        """Check if an EBSD map has been linked.

        Returns:
            bool: Returns True if EBSD map linked

        Raises:
            Exception: if EBSD map not linked
        """
        if self.ebsdMap is None:
            raise Exception("No EBSD map linked.")
        return True

    def warpToDicFrame(self, mapData, cropImage=True, order=1, preserve_range=False):
        """Warps a map to the DIC frame

        Returns:
            warpedMap: Map (i.e. EBSD map) warped to the DIC frame

        Args:
            mapData(map): data to warp
            cropImage(bool, optional):
            order(int, optional): order of interpolation (0: Nearest-neighbor, 1: Bi-linear...)
            preserve_range(bool, optional): keep the original range of values
        """
        # Check a EBSD map is linked
        self.checkEbsdLinked()

        if (cropImage or type(self.ebsdTransform) is not tf.AffineTransform):
            # crop to size of DIC map
            outputShape = (self.yDim, self.xDim)
            # warp the map
            warpedMap = tf.warp(
                mapData, self.ebsdTransform,
                output_shape=outputShape,
                order=order, preserve_range=preserve_range
            )
        else:
            # copy ebsd transform and change translation to give an extra
            # 5% border to show the entire image after rotation/shearing
            tempEbsdTransform = tf.AffineTransform(matrix=np.copy(self.ebsdTransform.params))
            tempEbsdTransform.params[0:2, 2] = -0.05 * np.array(mapData.shape)

            # output the entire warped image with 5% border (add some
            # extra to fix a bug)
            outputShape = np.array(mapData.shape) * 1.4 / tempEbsdTransform.scale

            # warp the map
            warpedMap = tf.warp(
                mapData, tempEbsdTransform,
                output_shape=outputShape.astype(int),
                order=order, preserve_range=preserve_range
            )

        # return map
        return warpedMap

    @property
    def boundaries(self):
        # Check a EBSD map is linked
        self.checkEbsdLinked()

        # image is returned cropped if a piecewise transform is being used
        boundaries = self.warpToDicFrame(-self.ebsdMap.boundaries.astype(float), cropImage=False) > 0.1

        boundaries = mph.skeletonize(boundaries)
        mph.remove_small_objects(boundaries, min_size=10, in_place=True, connectivity=2)

        # crop image if it is a simple affine transform
        if type(self.ebsdTransform) is tf.AffineTransform:
            # need to apply the translation of ebsd transform and remove 5% border
            crop = np.copy(self.ebsdTransform.params[0:2, 2])
            crop += 0.05 * np.array(self.ebsdMap.boundaries.shape)
            # the crop is defined in EBSD coords so need to transform it
            transformMatrix = np.copy(self.ebsdTransform.params[0:2, 0:2])
            crop = np.matmul(np.linalg.inv(transformMatrix), crop)
            crop = crop.round().astype(int)

            boundaries = boundaries[crop[1]:crop[1] + self.yDim,
                                    crop[0]:crop[0] + self.xDim]

        boundaries = -boundaries.astype(int)

        return boundaries

    def setPatternPath(self, filePath, windowSize):
        """Set path of BSE image of pattern. filePath is relative to
        the path set when constructing."""

        self.patternImPath = self.path + filePath
        self.patScale = windowSize

    def plotPattern(self, **kwargs):
        """Plot BSE image of Map. For use with setting homog points"""
        # Set default plot parameters then update with any input
        plotParams = {
            'cmap': 'gray'
        }
        try:
            plotParams['scale'] = self.scale / self.patScale * 1e-6
        except(ValueError):
            pass
        plotParams.update(kwargs)

        # Check image path is set
        if self.patternImPath is None:
            raise Exception("First set path to pattern image.")

        bseImage = imread(self.patternImPath)
        bseImage = self.crop(bseImage, binned=False)

        plot = MapPlot.create(self, bseImage, **plotParams)

        return plot

    def plotMaxShear(self, **kwargs):
        """
        Plot a map of maximum shear strain

        Parameters
        ----------
        plotColourBar : bool, optional
            Add a colourbar to plot
        vmin : float, optional
            Minimum value for colour scale, default is max value of data
        vmax : float, optional
            Maximum value for colour scale, default is min value of data
        cmap
        plotGBs : bool, optional
            Add grain boundaries to the plot
        dilateBoundaries : bool, optional
        boundaryColour
        plotScaleBar : bool, optional
            Add scale bar to plot
        highlightGrains

        highlightColours
        ax
        updateCurrent : bool, optional
        """
        # Set default plot parameters then update with any input
        plotParams = {
            'plotColourBar': True,
            'cLabel': "Effective shear strain"
        }
        plotParams.update(kwargs)

        plot = MapPlot.create(self, self.crop(self.max_shear), **plotParams)

        return plot

    def plotGrainAvMaxShear(self, **kwargs):
        """Plot grain map with grains filled with average value of max shear.
        This uses the max shear values stored in grain objects, to plot other data
        use plotGrainAv().

        Args:
            plotGBs (bool, optional): Set to True to draw grain boundaries
            plotColourBar (bool, optional): Set to Flase to exclude the colour bar
            vmin (float, optional): Minimum value of colour scale
            vmax (float, optional): Maximum value for colour scale
            cLabel (str, optional): Colour bar label text
        """
        # Set default plot parameters then update with any input
        plotParams = {
            'cLabel': "Effective shear strain"
        }
        plotParams.update(kwargs)

        plot = self.plotGrainDataMap(
            mapData=self.crop(self.max_shear), **plotParams
        )

        return plot

    def findGrains(self, minGrainSize=10):
        print("\rFinding grains in DIC map...", end="")

        # Check a EBSD map is linked
        self.checkEbsdLinked()

        # Initialise the grain map
        self.grains = np.copy(self.boundaries)

        self.grainList = []

        # List of points where no grain has been set yet
        unknownPoints = np.where(self.grains == 0)
        # Start counter for grains
        grainIndex = 1

        # Loop until all points (except boundaries) have been assigned
        # to a grain or ignored
        while unknownPoints[0].shape[0] > 0:
            # Flood fill first unknown point and return grain object
            currentGrain = self.floodFill(unknownPoints[1][0], unknownPoints[0][0], grainIndex)

            grainSize = len(currentGrain)
            if grainSize < minGrainSize:
                # if grain size less than minimum, ignore grain and set
                # values in grain map to -2
                for coord in currentGrain.coordList:
                    self.grains[coord[1], coord[0]] = -2
            else:
                # add grain and size to lists and increment grain label
                self.grainList.append(currentGrain)
                grainIndex += 1

            # update unknown points
            unknownPoints = np.where(self.grains == 0)

        # Now link grains to those in ebsd Map
        # Warp DIC grain map to EBSD frame
        dicGrains = self.grains
        warpedDicGrains = tf.warp(np.ascontiguousarray(dicGrains.astype(float)), self.ebsdTransformInv,
                                  output_shape=(self.ebsdMap.yDim, self.ebsdMap.xDim), order=0).astype(int)

        # Initalise list to store ID of corresponding grain in EBSD map.
        # Also stored in grain objects
        self.ebsdGrainIds = []

        for i in range(len(self.grainList)):
            # Find grain by masking the native ebsd grain image with
            # selected grain from the warped dic grain image. The modal
            # value is the EBSD grain label.
            modeId, _ = mode(self.ebsdMap.grains[warpedDicGrains == i + 1])

            self.ebsdGrainIds.append(modeId[0] - 1)
            self.grainList[i].ebsdGrainId = modeId[0] - 1
            self.grainList[i].ebsdGrain = self.ebsdMap.grainList[modeId[0] - 1]
            self.grainList[i].ebsdMap = self.ebsdMap

        print("\rDone                                               ", end="")

    def floodFill(self, x, y, grainIndex):
        currentGrain = Grain(self)

        currentGrain.addPoint((x, y), self.max_shear[y + self.cropDists[1, 0], x + self.cropDists[0, 0]])

        edge = [(x, y)]
        grain = [(x, y)]

        self.grains[y, x] = grainIndex
        while edge:
            newedge = []

            for (x, y) in edge:
                moves = np.array([(x + 1, y),
                                  (x - 1, y),
                                  (x, y + 1),
                                  (x, y - 1)])

                movesIndexShift = 0
                if x <= 0:
                    moves = np.delete(moves, 1, 0)
                    movesIndexShift = 1
                elif x >= self.xDim - 1:
                    moves = np.delete(moves, 0, 0)
                    movesIndexShift = 1

                if y <= 0:
                    moves = np.delete(moves, 3 - movesIndexShift, 0)
                elif y >= self.yDim - 1:
                    moves = np.delete(moves, 2 - movesIndexShift, 0)

                for (s, t) in moves:
                    if self.grains[t, s] == 0:
                        currentGrain.addPoint((s, t), self.max_shear[y + self.cropDists[1, 0],
                                                                     x + self.cropDists[0, 0]])
                        newedge.append((s, t))
                        grain.append((s, t))
                        self.grains[t, s] = grainIndex
                    elif self.grains[t, s] == -1 and (s > x or t > y):
                        currentGrain.addPoint((s, t), self.max_shear[y + self.cropDists[1, 0],
                                                                     x + self.cropDists[0, 0]])
                        grain.append((s, t))
                        self.grains[t, s] = grainIndex

            if newedge == []:
                return currentGrain
            else:
                edge = newedge


class Grain(base.Grain):

    def __init__(self, dicMap):
        # Call base class constructor
        super(Grain, self).__init__()

        self.dicMap = dicMap       # dic map this grain is a member of
        self.ownerMap = dicMap
        self.maxShearList = []
        self.ebsdGrain = None
        self.ebsdMap = None

    @property
    def plotDefault(self):
        return lambda *args, **kwargs: self.plotMaxShear(
            plotColourBar=True, plotScaleBar=True, plotSlipTraces=True,
            plotSlipBands=True, *args, **kwargs
        )

    # coord is a tuple (x, y)
    def addPoint(self, coord, maxShear):
        self.coordList.append(coord)
        self.maxShearList.append(maxShear)

    def plotMaxShear(self, **kwargs):
        # Set default plot parameters then update with any input
        plotParams = {
            'plotColourBar': True,
            'cLabel': "Effective shear strain"
        }
        plotParams.update(kwargs)

        plot = self.plotGrainData(grainData=self.maxShearList, **plotParams)

        return plot

    @property
    def refOri(self):
        return self.ebsdGrain.refOri

    @property
    def slipTraces(self):
        return self.ebsdGrain.slipTraces

    def calcSlipTraces(self, slipSystems=None):
        self.ebsdGrain.calcSlipTraces(slipSystems=slipSystems)

    def calcSlipBands(self, grainMapData, thres=None, min_dist=None):
        """Use Radon transform to detect slip band angles

        Args:
            grainMapData (numpy.array): Data to find bands in
            thres (float, optional): Normalised threshold for peaks
            min_dist (int, optional): Minimum angle between bands

        Returns:
            list(float): Detected slip band angles
        """
        if thres is None:
            thres = 0.3
        if min_dist is None:
            min_dist = 30
        grainMapData = np.nan_to_num(grainMapData)

        if grainMapData.min() < 0:
            print("Negative values in data, taking absolute value.")
            # grainMapData = grainMapData**2
            grainMapData = np.abs(grainMapData)
        suppGMD = np.zeros(grainMapData.shape) #array to hold shape / support of grain
        suppGMD[grainMapData!=0]=1
        sin_map = tf.radon(grainMapData, circle=False)
        #profile = np.max(sin_map, axis=0) # old method
        supp_map = tf.radon(suppGMD, circle=False)
        supp_1 = np.zeros(supp_map.shape)
        supp_1[supp_map>0]=1
        mindiam = np.min(np.sum(supp_1, axis=0), axis=0) # minimum diameter of grain
        crop_map = np.zeros(sin_map.shape)
        # only consider radon rays that cut grain with mindiam*2/3 or more, and scale by length of the cut
        crop_map[supp_map>mindiam*2/3] = sin_map[supp_map>mindiam*2/3]/supp_map[supp_map>mindiam*2/3] 
        supp_crop = np.zeros(crop_map.shape)
        supp_crop[crop_map>0] = 1
        profile = np.sum(crop_map**4, axis=0) / np.sum(supp_crop, axis=0) # raise to power to accentuate local peaks

        x = np.arange(180)

        # indexes = peakutils.indexes(profile, thres=thres, min_dist=min_dist, thres_abs=False)
        indexes = peakutils.indexes(profile, thres=thres, min_dist=min_dist)
        peaks = x[indexes]
        # peaks = peakutils.interpolate(x, profile, ind=indexes)
        print("Number of bands detected: {:}".format(len(peaks)))

        slipBandAngles = peaks
        slipBandAngles = slipBandAngles * np.pi / 180
        return slipBandAngles
