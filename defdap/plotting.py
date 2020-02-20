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
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
from matplotlib.collections import LineCollection
from matplotlib_scalebar.scalebar import ScaleBar


from skimage import morphology as mph

from defdap import quat
# TODO: add plot parameter to add to current figure


class Plot(object):
    def __init__(self, ax, fig=None, makeInteractive=False):

        self.interactive = makeInteractive
        if makeInteractive:
            if fig is not None and ax is not None:
                self.fig = fig
                self.ax = ax
            else:
                self.fig, self.ax = plt.subplots()
            self.btnStore = []
        else:
            self.fig = fig
            # TODO: flag for new figure
            if ax is None:
                self.fig, self.ax = plt.subplots()
            else:
                self.ax = ax
        self.colourBar = None

    def checkInteractive(self):
        if not self.interactive:
            raise Exception("Plot must be interactive")

    def addEventHandler(self, eventName, eventHandler):
        self.checkInteractive()

        self.fig.canvas.mpl_connect(eventName, lambda e: eventHandler(e, self))

    def addButton(self, label, clickHandler, loc=(0.8, 0.0, 0.1, 0.07), **kwargs):
        self.checkInteractive()

        btnAx = self.fig.add_axes(loc)
        btn = Button(btnAx, label, **kwargs)
        btn.on_clicked(lambda e: clickHandler(e, self))

        self.btnStore.append(btn)

    @property
    def exists(self):
        self.checkInteractive()

        return plt.fignum_exists(self.fig.number)

    def clear(self):
        self.checkInteractive()

        self.ax.clear()
        if self.colourBar is not None:
            self.colourBar.remove()
        self.draw()

    def draw(self):
        self.fig.canvas.draw()


class MapPlot(Plot):
    def __init__(self, callingMap, fig=None, ax=None, makeInteractive=False):
        super(MapPlot, self).__init__(ax, fig=fig, makeInteractive=makeInteractive)

        self.callingMap = callingMap
        self.imgLayers = []
        self.highlightsLayerID = None
        self.pointsLayerIDs = []

        self.ax.set_xticks([])
        self.ax.set_yticks([])

    def addMap(self, mapData, vmin=None, vmax=None, cmap='viridis', **kwargs):

        img = self.ax.imshow(mapData, vmin=vmin, vmax=vmax,
                             interpolation='None', cmap=cmap, **kwargs)
        self.draw()

        self.imgLayers.append(img)

        return img

    def addColourBar(self, label, layer=0, **kwargs):
        img = self.imgLayers[layer]
        self.colourBar = plt.colorbar(img, ax=self.ax, label=label, **kwargs)

    def addScaleBar(self, scale=None):
        if scale is None:
            scale = self.callingMap.scale * 1e-6
        self.ax.add_artist(ScaleBar(scale))

    def addGrainBoundaries(self, colour=None, dilate=False, kind="pixel", **kwargs):
        if colour is None:
            colour = "white"

        if kind == "line":
            lc = LineCollection(self.callingMap.boundaryLines,
                                colors=mpl.colors.to_rgba(colour), **kwargs)

            self.ax.add_collection(lc)
            # ax.autoscale()

            self.draw()
        else:
            boundariesImage = -self.callingMap.boundaries

            if dilate:
                boundariesImage = mph.binary_dilation(boundariesImage)

            # create colourmap for boundaries going from transparent to
            # opaque of the given colour
            boundariesCmap = mpl.colors.LinearSegmentedColormap.from_list(
                'my_cmap', ['white', colour], 256
            )
            boundariesCmap._init()
            boundariesCmap._lut[:, -1] = np.linspace(0, 1, boundariesCmap.N + 3)

            img = self.ax.imshow(boundariesImage, cmap=boundariesCmap,
                                 interpolation='None', vmin=0, vmax=1)
            self.draw()

            self.imgLayers.append(img)

            return img

    def addGrainHighlights(self, grainIds, grainColours=None, alpha=None,
                           newLayer=False):
        if grainColours is None:
            grainColours = ['white']
        if alpha is None:
            alpha = self.callingMap.highlightAlpha

        xDim = self.callingMap.xDim
        yDim = self.callingMap.yDim

        outline = np.zeros((yDim, xDim), dtype=int)
        for i, grainId in enumerate(grainIds, start=1):
            if i > len(grainColours):
                i = len(grainColours)

            # outline of highlighted grain
            grain = self.callingMap.grainList[grainId]
            grainOutline = grain.grainOutline(bg=0, fg=i)
            x0, y0, xmax, ymax = grain.extremeCoords

            # add to highlight image
            outline[y0:ymax + 1, x0:xmax + 1] += grainOutline

        # Custom colour map where 0 is transparent white for bg and
        # then a patch for each grain colour
        grainColours.insert(0, 'white')
        hightlightsCmap = mpl.colors.ListedColormap(grainColours)
        hightlightsCmap._init()
        alphaMap = np.full(hightlightsCmap.N + 3, alpha)
        alphaMap[0] = 0
        hightlightsCmap._lut[:, -1] = alphaMap

        if self.highlightsLayerID is None or newLayer:
            img = self.ax.imshow(outline, interpolation='none',
                                 cmap=hightlightsCmap)
            if self.highlightsLayerID is None:
                self.highlightsLayerID = len(self.imgLayers)
            self.imgLayers.append(img)
        else:
            img = self.imgLayers[self.highlightsLayerID]
            img.set_data(outline)
            img.set_cmap(hightlightsCmap)
            img.autoscale()

        self.draw()

        return img

    def addGrainNumbers(self, fontsize=10, **kwargs):
        for grainID, grain in enumerate(self.callingMap):
            xCentre, yCentre = grain.centreCoords(centreType="com",
                                                  grainCoords=False)

            self.ax.text(xCentre, yCentre, grainID,
                         fontsize=fontsize, **kwargs)
        self.draw()

    def addLegend(self, values, lables, layer=0, **kwargs):
        # Find colour values for given values
        img = self.imgLayers[layer]
        colors = [img.cmap(img.norm(value)) for value in values]

        # Get colour patches for each phase and make legend
        patches = [mpl.patches.Patch(
            color=colors[i], label=lables[i]
        ) for i in range(len(values))]

        self.ax.legend(handles=patches, **kwargs)

    def addPoints(self, x, y, updateLayer=None, **kwargs):
        x, y = np.array(x), np.array(y)
        if len(self.pointsLayerIDs) == 0 or updateLayer is None:
            points = self.ax.scatter(x, y, **kwargs)
            self.pointsLayerIDs.append(len(self.imgLayers))
            self.imgLayers.append(points)
        else:
            points = self.imgLayers[self.pointsLayerIDs[updateLayer]]
            points.set_offsets(np.hstack((x[:, np.newaxis], y[:, np.newaxis])))

        self.draw()

        return points

    @classmethod
    def create(
        cls, callingMap, mapData,
        fig=None, ax=None, plot=None, makeInteractive=False,
        plotColourBar=False, vmin=None, vmax=None, cmap=None, cLabel="",
        plotGBs=False, dilateBoundaries=False, boundaryColour=None,
        plotScaleBar=False, scale=None,
        highlightGrains=None, highlightColours=None, highlightAlpha=None,
        **kwargs
    ):
        if plot is None:
            plot = cls(callingMap, fig=fig, ax=ax, makeInteractive=makeInteractive)
        if mapData is not None:
            plot.addMap(mapData, cmap=cmap, vmin=vmin, vmax=vmax, **kwargs)

        if plotColourBar:
            plot.addColourBar(cLabel)

        if plotGBs:
            plot.addGrainBoundaries(
                colour=boundaryColour, dilate=dilateBoundaries, kind=plotGBs
            )

        if highlightGrains is not None:
            plot.addGrainHighlights(
                highlightGrains,
                grainColours=highlightColours, alpha=highlightAlpha
            )

        if plotScaleBar:
            plot.addScaleBar(scale=scale)

        return plot


class GrainPlot(Plot):
    def __init__(self, callingGrain, fig=None, ax=None, makeInteractive=False):
        super(GrainPlot, self).__init__(ax, fig=fig, makeInteractive=makeInteractive)

        self.callingGrain = callingGrain
        self.imgLayers = []

        self.ax.set_xticks([])
        self.ax.set_yticks([])

    def addMap(self, mapData, vmin=None, vmax=None, cmap='viridis', **kwargs):
        img = self.ax.imshow(mapData, vmin=vmin, vmax=vmax,
                             interpolation='None', cmap=cmap, **kwargs)
        self.draw()

        self.imgLayers.append(img)

        return img

    def addColourBar(self, label, layer=0, **kwargs):
        img = self.imgLayers[layer]
        self.colourBar = plt.colorbar(img, ax=self.ax, label=label, **kwargs)

    def addScaleBar(self, scale=None):
        if scale is None:
            scale = self.callingGrain.ownerMap.scale * 1e-6
        self.ax.add_artist(ScaleBar(scale))

    def addTraces(self, angles, colours, pos=None, **kwargs):
        if pos is None:
            pos = self.callingGrain.centreCoords()

        traces = np.array((-np.sin(angles), np.cos(angles)))
        for i, trace in enumerate(traces.T):
            colour = colours[len(colours) - 1] if i >= len(colours) else colours[i]
            self.ax.quiver(
                pos[0], pos[1],
                trace[0], trace[1],
                scale=1, pivot="middle",
                color=colour, headwidth=1,
                headlength=0, **kwargs
            )
            self.draw()

    def addSlipTraces(self, colours=None, pos=None, **kwargs):
        if colours is None:
            colours = self.callingGrain.ebsdMap.slipTraceColours
        slipTraceAngles = self.callingGrain.slipTraces

        self.addTraces(slipTraceAngles, colours, pos=pos, **kwargs)

    def addSlipBands(self, grainMapData, pos=None, thres=None, min_dist=None, **kwargs):
        slipBandAngles = self.callingGrain.calcSlipBands(grainMapData,
                                                         thres=thres,
                                                         min_dist=min_dist)

        self.addTraces(slipBandAngles, ["yellow"], pos=pos, **kwargs)

    @classmethod
    def create(
        cls, callingGrain, mapData,
        fig=None, ax=None, plot=None, makeInteractive=False,
        plotColourBar=False, vmin=None, vmax=None, cmap=None, cLabel="",
        plotScaleBar=False, scale=None,
        plotSlipTraces=False, plotSlipBands=False, **kwargs
    ):
        if plot is None:
            plot = cls(callingGrain, fig=fig, ax=ax, makeInteractive=makeInteractive)
        plot.addMap(mapData, cmap=cmap, vmin=vmin, vmax=vmax, **kwargs)

        if plotColourBar:
            plot.addColourBar(cLabel)

        if plotScaleBar:
            plot.addScaleBar(scale=scale)

        if plotSlipTraces:
            plot.addSlipTraces()

        if plotSlipBands:
            plot.addSlipBands(mapData)

        return plot


class PolePlot(Plot):
    defaultProjection = "stereographic"

    def __init__(self, plotType, crystalSym, projection=None,
                 fig=None, ax=None, makeInteractive=False):
        super(PolePlot, self).__init__(ax, fig=fig, makeInteractive=makeInteractive)

        self.plotType = plotType
        self.crystalSym = crystalSym
        self.projection = self._validateProjection(projection)

        self.imgLayers = []

        self.addAxis()

    def addAxis(self):
        if self.plotType == "IPF" and self.crystalSym == "cubic":
            # line between [001] and [111]
            self.addLine([0, 0, 1], [1, 1, 1], c='k', lw=2)

            # line between [001] and [101]
            self.addLine([0, 0, 1], [1, 0, 1], c='k', lw=2)

            # line between [101] and [111]
            self.addLine([1, 0, 1], [1, 1, 1], c='k', lw=2)

            # label poles
            self.labelPoint([0, 0, 1], '001',
                            padY=-0.005, va='top', ha='center')
            self.labelPoint([1, 0, 1], '101',
                            padY=-0.005, va='top', ha='center')
            self.labelPoint([1, 1, 1], '111',
                            padY=0.005, va='bottom', ha='center')

        elif self.plotType == "IPF" and self.crystalSym == "hexagonal":
            # line between [0001] and [10-10] ([001] and [210])
            # converted to cubic axes
            self.addLine([0, 0, 1], [np.sqrt(3), 1, 0], c='k', lw=2)

            # line between [0001] and [2-1-10] ([001] and [100])
            self.addLine([0, 0, 1], [1, 0, 0], c='k', lw=2)

            # line between [2-1-10] and [10-10] ([100] and [210])
            self.addLine([1, 0, 0], [np.sqrt(3), 1, 0], c='k', lw=2)

            # label poles
            self.labelPoint([0, 0, 1], '0001',
                            padY=-0.008, va='top', ha='center')
            self.labelPoint([1, 0, 0], '2-1-10',
                            padY=-0.008, va='top', ha='center')
            self.labelPoint([np.sqrt(3), 1, 0], '10-10',
                            padY=0.008, va='bottom', ha='center')

        else:
            raise NotImplementedError("Only works for cubic and hexagonal IPFs")

        self.ax.axis('equal')
        self.ax.axis('off')

    def addLine(self, startPoint, endPoint, plotSyms=False, res=100, **kwargs):
        lines = [(startPoint, endPoint)]
        if plotSyms:
            for symm in quat.Quat.symEqv(self.crystalSym)[1:]:
                startPointSymm = symm.transformVector(startPoint).astype(int)
                endPointSymm = symm.transformVector(endPoint).astype(int)

                if startPointSymm[2] < 0:
                    startPointSymm *= -1
                if endPointSymm[2] < 0:
                    endPointSymm *= -1

                lines.append((startPointSymm, endPointSymm))

        linePoints = np.zeros((3, res), dtype=float)
        for line in lines:
            for i in range(3):
                if line[0][i] == line[1][i]:
                    linePoints[i] = np.full(res, line[0][i])
                else:
                    linePoints[i] = np.linspace(line[0][i], line[1][i], res)

            xp, yp = self.projection(linePoints[0], linePoints[1], linePoints[2])
            self.ax.plot(xp, yp, **kwargs)

    def labelPoint(self, point, label, padX=0, padY=0, **kwargs):
        xp, yp = self.projection(*point)
        self.ax.text(xp + padX, yp + padY, label, **kwargs)

    def addPoints(self, alphaAng, betaAng, markerColour=None, markerSize=None, **kwargs):
        # project onto equatorial plane
        xp, yp = self.projection(alphaAng, betaAng)

        # plot poles
        # plot markers with 'half and half' colour
        if type(markerColour) is str:
            markerColour = [markerColour]

        if markerColour is None:
            points = self.ax.scatter(xp, yp, **kwargs)
            self.imgLayers.append(points)
        elif len(markerColour) == 2:
            pos = (xp, yp)
            r1 = 0.5
            r2 = r1 + 0.5
            markerSize = np.sqrt(markerSize)

            x = [0] + np.cos(np.linspace(0, 2 * np.pi * r1, 10)).tolist()
            y = [0] + np.sin(np.linspace(0, 2 * np.pi * r1, 10)).tolist()
            xy1 = list(zip(x, y))

            x = [0] + np.cos(np.linspace(2 * np.pi * r1, 2 * np.pi * r2, 10)).tolist()
            y = [0] + np.sin(np.linspace(2 * np.pi * r1, 2 * np.pi * r2, 10)).tolist()
            xy2 = list(zip(x, y))

            points = self.ax.scatter(
                pos[0], pos[1], marker=(xy1, 0),
                s=markerSize, c=markerColour[0], **kwargs
            )
            self.imgLayers.append(points)
            points = self.ax.scatter(
                pos[0], pos[1], marker=(xy2, 0),
                s=markerSize, c=markerColour[1], **kwargs
            )
            self.imgLayers.append(points)
        else:
            raise Exception("specify one colour for solid markers or list two for 'half and half'")

    def addColourBar(self, label, layer=0, **kwargs):
        img = self.imgLayers[layer]
        self.colourBar = plt.colorbar(img, ax=self.ax, label=label, **kwargs)

    @staticmethod
    def _validateProjection(projectionIn, validateDefault=False):
        if validateDefault:
            defaultProjection = None
        else:
            defaultProjection = PolePlot._validateProjection(
                PolePlot.defaultProjection, validateDefault=True
            )

        if projectionIn is None:
            projection = defaultProjection

        elif type(projectionIn) is str:
            projectionName = projectionIn.replace(" ", "").lower()
            if projectionName in ["lambert", "equalarea"]:
                projection = PolePlot.lambertProject
            elif projectionName in ["stereographic", "stereo", "equalangle"]:
                projection = PolePlot.stereoProject
            else:
                print("Unknown projection name, using default")
                projection = defaultProjection

        elif callable(projectionIn):
            projection = projectionIn

        else:
            print("Unknown projection, using default")
            projection = defaultProjection

        if projection is None:
            raise Exception("Problem with default projection.")

        return projection

    @staticmethod
    def stereoProject(*args):
        if len(args) == 3:
            alpha, beta = quat.Quat.polarAngles(args[0], args[1], args[2])
        elif len(args) == 2:
            alpha, beta = args
        else:
            raise Exception("3 arguments for pole directions and 2 for polar angles.")

        alphaComp = np.tan(alpha / 2)
        xp = alphaComp * np.cos(beta)
        yp = alphaComp * np.sin(beta)

        return xp, yp

    @staticmethod
    def lambertProject(*args):
        if len(args) == 3:
            alpha, beta = quat.Quat.polarAngles(args[0], args[1], args[2])
        elif len(args) == 2:
            alpha, beta = args
        else:
            raise Exception("3 arguments for pole directions and 2 for polar angles.")

        alphaComp = np.sqrt(2 * (1 - np.cos(alpha)))
        xp = alphaComp * np.cos(beta)
        yp = alphaComp * np.sin(beta)

        return xp, yp


class HistPlot(Plot):
    def __init__(self, plotType="linear", density=True,
                 fig=None, ax=None, makeInteractive=False):
        super(HistPlot, self).__init__(ax, fig=fig, makeInteractive=makeInteractive)

        plotType = plotType.lower()
        if plotType in ["linear", "log"]:
            self.plotType = plotType
        else:
            raise ValueError("plotType must be linear or log.")

        self.density = bool(density)

        # set y-axis label
        yLabel = "Normalised frequency" if self.density else "Frequency"
        if self.plotType is "log":
            yLabel = "ln({})".format(yLabel)
        self.ax.set_ylabel(yLabel)

    def addHist(self, histData, bins=10, range=None, line='o',
                label=None, **kwargs):

        hist = np.histogram(histData.flatten(), bins=bins, range=range,
                            density=self.density)

        yVals = hist[0]
        if self.plotType is "log":
            yVals = np.log(yVals)
        xVals = 0.5 * (hist[1][1:] + hist[1][:-1])

        self.ax.plot(xVals, yVals, line, label=label, **kwargs)

    def addLegend(self, **kwargs):
        self.ax.legend(**kwargs)

    @classmethod
    def create(
        cls, histData, fig=None, ax=None, plot=None, makeInteractive=False,
        plotType="linear", density=True, bins=10, range=None,
        line='o', label=None, **kwargs
    ):
        if plot is None:
            plot = cls(plotType=plotType, density=density, fig=fig, ax=ax,
                       makeInteractive=makeInteractive)
        plot.addHist(histData, bins=bins, range=range, line=line,
                     label=label, **kwargs)

        return plot
