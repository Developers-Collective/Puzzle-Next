#!/usr/bin/env python

import archive
import lz77
from QCodeEditor import QCodeEditor
import json
import os, os.path
import shutil
import struct
import sys
import threading
import time
from xml.etree import ElementTree as etree

from ctypes import create_string_buffer
try:
    from PyQt5 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
Qt = QtCore.Qt

#try:
#    from PIL import Image
#except ImportError:
#    print("You have to install Pillow!")
#    os._exit(0)

try:
    import nsmblib
    HaveNSMBLib = True
except ImportError:
    HaveNSMBLib = False

SplitWindow = False

if hasattr(QtCore, 'pyqtSlot'): # PyQt
    QtCoreSlot = QtCore.pyqtSlot
    QtCoreSignal = QtCore.pyqtSignal
else: # PySide2
    QtCoreSlot = QtCore.Slot
    QtCoreSignal = QtCore.Signal


########################################################
# To Do:
#
#   - Object Editor
#       - Moving objects around
#
#   - Make UI simpler for Pop
#   - fix up conflicts with different types of parameters
#   - C speed saving
#   - quick settings for applying to mulitple slopes
#
########################################################


Tileset = None


def module_path():
    """
    This will get us the program's directory, even if we are frozen
    using PyInstaller
    """

    if hasattr(sys, 'frozen') and hasattr(sys, '_MEIPASS'):  # PyInstaller
        if sys.platform == 'darwin':  # macOS
            # sys.executable is /x/y/z/puzzle.app/Contents/MacOS/puzzle
            # We need to return /x/y/z/puzzle.app/Contents/Resources/

            macos = os.path.dirname(sys.executable)
            if os.path.basename(macos) != 'MacOS':
                return None

            return os.path.join(os.path.dirname(macos), 'Resources')

    if __name__ == '__main__':
        return os.path.dirname(os.path.abspath(sys.argv[0]))

    return None


#############################################################################################
########################## Tileset Class and Tile/Object Subclasses #########################

class TilesetClass():
    '''Contains Tileset data. Inits itself to a blank tileset.
    Methods: addTile, removeTile, addObject, removeObject, clear'''

    class Tile():
        def __init__(self, image, noalpha, bytelist):
            '''Tile Constructor'''

            self.image = image
            self.noalpha = noalpha
            self.byte0 = bytelist[0]
            self.byte1 = bytelist[1]
            self.byte2 = bytelist[2]
            self.byte3 = bytelist[3]
            self.byte4 = bytelist[4]
            self.byte5 = bytelist[5]
            self.byte6 = bytelist[6]
            self.byte7 = bytelist[7]


    class Object():

        def __init__(self, height, width, uslope, lslope, tilelist):
            '''Tile Constructor'''

            self.upperslope = uslope
            self.lowerslope = lslope

            assert (width, height) != 0

            self.height = height
            self.width = width

            self.tiles = tilelist

            self.determineRepetition()

            if self.repeatX or self.repeatY:
                height = len(self.tiles)
                if self.height != height:
                    print("WARNING: Object height mismatches with the number of rows in the object.")
                    self.height = height

                width = max(len(self.tiles[y]) for y in range(self.height))
                if self.width  != width:
                    print("WARNING: Object width mismatches with the maximum number of columns in the object.")
                    self.width = width

                if self.repeatX:
                    self.determineRepetitionFinalize()

            else:
                # Fix a bug from a previous version of Puzzle
                # where the actual width and height would
                # mismatch with the number of tiles for the object

                self.fillMissingTiles()

            self.tilingMethodIdx = self.determineTilingMethod()


        def determineRepetition(self):
            self.repeatX = []
            self.repeatY = []

            if self.upperslope[0] != 0:
                return

            #### Find X Repetition ####
            # You can have different X repetitions between rows, so we have to account for that

            for y in range(self.height):
                repeatXBn = -1
                repeatXEd = -1

                for x in range(len(self.tiles[y])):
                    if self.tiles[y][x][0] & 1 and repeatXBn == -1:
                        repeatXBn = x

                    elif not self.tiles[y][x][0] & 1 and repeatXBn != -1:
                        repeatXEd = x
                        break

                if repeatXBn != -1:
                    if repeatXEd == -1:
                        repeatXEd = len(self.tiles[y])

                    self.repeatX.append((y, repeatXBn, repeatXEd))

            #### Find Y Repetition ####

            repeatYBn = -1
            repeatYEd = -1

            for y in range(self.height):
                if len(self.tiles[y]) and self.tiles[y][0][0] & 2:
                    if repeatYBn == -1:
                        repeatYBn = y

                elif repeatYBn != -1:
                    repeatYEd = y
                    break

            if repeatYBn != -1:
                if repeatYEd == -1:
                    repeatYEd = self.height

                self.repeatY = [repeatYBn, repeatYEd]


        def determineRepetitionFinalize(self):
            if self.repeatX:
                # If any X repetition is present, fill in rows which didn't have X repetition set
                ## Should never happen, unless the tileset is broken
                ## Additionally, sort the list
                repeatX = []
                for y in range(self.height):
                    for row, start, end in self.repeatX:
                        if y == row:
                            repeatX.append([start, end])
                            break

                    else:
                        # Get the start and end X offsets for the row
                        start = 0
                        end = len(self.tiles[y])

                        repeatX.append([start, end])

                self.repeatX = repeatX


        def fillMissingTiles(self):
            realH = len(self.tiles)
            while realH > self.height:
                del self.tiles[-1]
                realH -= 1

            for row in self.tiles:
                realW = len(row)
                while realW > self.width:
                    del row[-1]
                    realW -= 1

            for row in self.tiles:
                realW = len(row)
                while realW < self.width:
                    row.append((0, 0, 0))
                    realW += 1

            while realH < self.height:
                self.tiles.append([(0, 0, 0) for _ in range(self.width)])
                realH += 1


        def createRepetitionX(self):
            self.repeatX = []

            for y in range(self.height):
                for x in range(len(self.tiles[y])):
                    self.tiles[y][x] = (self.tiles[y][x][0] | 1, self.tiles[y][x][1], self.tiles[y][x][2])

                self.repeatX.append([0, len(self.tiles[y])])


        def createRepetitionY(self, y1, y2):
            self.clearRepetitionY()

            for y in range(y1, y2):
                for x in range(len(self.tiles[y])):
                    self.tiles[y][x] = (self.tiles[y][x][0] | 2, self.tiles[y][x][1], self.tiles[y][x][2])

            self.repeatY = [y1, y2]


        def clearRepetitionX(self):
            self.fillMissingTiles()

            for y in range(self.height):
                for x in range(self.width):
                    self.tiles[y][x] = (self.tiles[y][x][0] & ~1, self.tiles[y][x][1], self.tiles[y][x][2])

            self.repeatX = []


        def clearRepetitionY(self):
            for y in range(self.height):
                for x in range(len(self.tiles[y])):
                    self.tiles[y][x] = (self.tiles[y][x][0] & ~2, self.tiles[y][x][1], self.tiles[y][x][2])

            self.repeatY = []


        def clearRepetitionXY(self):
            self.clearRepetitionX()
            self.clearRepetitionY()


        def determineTilingMethod(self):
            if self.upperslope[0] == 0x93:
                return 7

            elif self.upperslope[0] == 0x92:
                return 6

            elif self.upperslope[0] == 0x91:
                return 5

            elif self.upperslope[0] == 0x90:
                return 4

            elif self.repeatX and self.repeatY:
                return 3

            elif self.repeatY:
                return 2

            elif self.repeatX:
                return 1

            return 0


    def __init__(self):
        '''Constructor'''

        self.tiles = []
        self.objects = []
        self.animdata = {}
        self.unknownFiles = {}

        self.slot = 0
        self.placeNullChecked = False


    def addTile(self, image, noalpha, bytelist = (0, 0, 0, 0, 0, 0, 0, 0)):
        '''Adds an tile class to the tile list with the passed image or parameters'''

        self.tiles.append(self.Tile(image, noalpha, bytelist))


    def getUsedTiles(self):
        usedTiles = []

        for object in self.objects:
            for i in range(len(object.tiles)):
                for tile in object.tiles[i]:
                    if not tile[2] & 3 and Tileset.slot:  # Pa0 tile 0 used in another slot, don't count it
                        continue

                    if tile[1] not in usedTiles:
                        usedTiles.append(tile[1])

        return usedTiles


    def addObject(self, height = 1, width = 1,  uslope = [0, 0], lslope = [0, 0], tilelist = None, new = False):
        '''Adds a new object'''

        global Tileset

        if new:
            tilelist = [[(0, 0, Tileset.slot)]]

        self.objects.append(self.Object(height, width, uslope, lslope, tilelist))


    def removeObject(self, index):
        '''Removes an Object by Index number. Don't use this much, because we want objects to preserve their ID.'''

        self.objects.pop(index)


    def clear(self):
        '''Clears the tileset for a new file'''

        self.tiles = []
        self.objects = []
        self.animdata = {}
        self.unknownFiles = {}


#############################################################################################
###################################### AnimTiles Class ######################################

def readNullTerminated(data, pos):
    end = data.find(b'\0', pos)
    if end == -1:
        return data[pos:]
    return data[pos:end]


def readString(data, pos):
    return readNullTerminated(data, pos).decode('utf8')


class AnimTilesClass():
    '''Contains animation data'''

    def __init__(self):
        '''Constructor'''
        self.animations = []


    def addAnimation(self, animation):
        '''Adds animation data'''
        self.animations.append(animation)


    def clear(self):
        '''Clears everything for a new file'''
        self.animations = []


#############################################################################################
###################################### RandTiles Class ######################################

class RandTilesClass():
    '''Contains randomization data'''

    def __init__(self):
        '''Constructor'''
        self.sections = []


    def clear(self):
        '''Clears everything for a new file'''
        self.sections = []


#############################################################################################
######################### Palette for painting behaviours to tiles ##########################


class paletteWidget(QtWidgets.QWidget):

    def __init__(self, window):
        super(paletteWidget, self).__init__(window)


        # Core Types Radio Buttons and Tooltips
        self.coreType = QtWidgets.QGroupBox()
        self.coreType.setTitle('Core Type:')
        self.coreWidgets = []
        coreLayout = QtWidgets.QVBoxLayout()
        rowA = QtWidgets.QHBoxLayout()
        rowB = QtWidgets.QHBoxLayout()
        rowC = QtWidgets.QHBoxLayout()
        rowD = QtWidgets.QHBoxLayout()
        rowE = QtWidgets.QHBoxLayout()
        rowF = QtWidgets.QHBoxLayout()

        path = 'Icons/'

        self.coreTypes = [['Default', QtGui.QIcon(path + 'Core/Default.png'), 'The standard type for tiles.\n\nAny regular terrain or backgrounds\nshould be of generic type. It has no\n collision properties.'],
                     ['Slope', QtGui.QIcon(path + 'Core/Slope.png'), 'Defines a sloped tile\n\nSloped tiles have sloped collisions,\nwhich Mario can slide on.\n\nNote: Do NOT set slopes to have solid collision.'],
                     ['Reverse Slope', QtGui.QIcon(path + 'Core/RSlope.png'), 'Defines an upside-down slope.\n\nSloped tiles have sloped collisions,\nwhich Mario can slide on.\n\nNote: Do NOT set slopes to have solid collision.'],
                     ['Partial Block', QtGui.QIcon(path + 'Partial/Full.png'), 'Used for blocks with partial collisions.\n\nVery useful for Mini-Mario secret\nareas, but also for providing a more\naccurate collision map for your tiles.'],
                     ['Coin', QtGui.QIcon(path + 'Core/Coin.png'), 'Creates a coin.\n\nCoins have no solid collision,\nand when touched will disappear\nand increment the coin counter.'],
                     ['Explodable Block', QtGui.QIcon(path + 'Core/Explode.png'), 'Specifies blocks which can explode.\n\nThese blocks will shatter into componenent\npieces when hit by a bom-omb or meteor.\nThe pieces themselves may be hardcoded\nand must be included in the tileset.\nBehaviour may be sporadic.'],
                     ['Climable Grid', QtGui.QIcon(path + 'Core/Climb.png'), 'Creates terrain that can be climbed on.\n\nClimable terrain cannot be walked on.\nWhen Mario is overtop of a climable\ntile and the player presses up,\nMario will enter a climbing state.'],
                     ['Spike', QtGui.QIcon(path + 'Core/Spike.png'), 'Dangerous Spikey spikes.\n\nSpike tiles will damage Mario one hit\nwhen they are touched.'],
                     ['Pipe', QtGui.QIcon(path + 'Core/Pipe.png'), "Denotes a pipe tile.\n\nPipe tiles are specified according to\nthe part of the pipe. It's important\nto specify the right parts or\nentrances will not function correctly."],
                     ['Rails', QtGui.QIcon(path + 'Core/Rails.png'), 'Used for all types of rails.\n\nPlease note that Pa3_rail.arc is hardcoded\nto replace rails with 3D models.'],
                     ['Conveyor Belt', QtGui.QIcon(path + 'Core/Conveyor.png'), 'Defines moving tiles.\n\nMoving tiles will move Mario in one\ndirection or another. Parameters are\nlargely unknown at this time.'],
                     ['Question Block', QtGui.QIcon(path + 'Core/Qblock.png'), 'Creates question blocks.']]

        i = 0
        for item in range(len(self.coreTypes)):
            self.coreWidgets.append(QtWidgets.QRadioButton())
            if i == 0:
                self.coreWidgets[item].setText('Default')
            else:
                self.coreWidgets[item].setIcon(self.coreTypes[item][1])
            self.coreWidgets[item].setIconSize(QtCore.QSize(24, 24))
            self.coreWidgets[item].setToolTip(self.coreTypes[item][2])
            self.coreWidgets[item].clicked.connect(self.swapParams)
            if i < 2:
                rowA.addWidget(self.coreWidgets[item])
            elif i < 4:
                rowB.addWidget(self.coreWidgets[item])
            elif i < 6:
                rowC.addWidget(self.coreWidgets[item])
            elif i < 8:
                rowD.addWidget(self.coreWidgets[item])
            elif i < 10:
                rowE.addWidget(self.coreWidgets[item])
            else:
                rowF.addWidget(self.coreWidgets[item])
            i += 1

        coreLayout.addLayout(rowA)
        coreLayout.addLayout(rowB)
        coreLayout.addLayout(rowC)
        coreLayout.addLayout(rowD)
        coreLayout.addLayout(rowE)
        coreLayout.addLayout(rowF)
        self.coreType.setLayout(coreLayout)


        # Properties Buttons. I hope this works well!
        self.propertyGroup = QtWidgets.QGroupBox()
        self.propertyGroup.setTitle('Properties:')
        propertyLayout = QtWidgets.QVBoxLayout()
        self.propertyWidgets = []
        propertyList = [['Solid', QtGui.QIcon(path + 'Prop/Solid.png'), 'Tiles you can walk on.\n\nThe tiles we be a solid basic square\nthrough which Mario can not pass.'],
                        ['Block', QtGui.QIcon(path + 'Prop/Break.png'), 'This denotes breakable tiles such\nas brick blocks. It is likely that these\nare subject to the same issues as\nexplodable blocks. They emit a coin\nwhen hit.'],
                        ['Falling Block', QtGui.QIcon(path + 'Prop/Fall.png'), 'Sets the block to fall after a set period. The\nblock is sadly replaced with a donut lift model.'],
                        ['Ledge', QtGui.QIcon(path + 'Prop/Ledge.png'), 'A ledge tile with unique properties.\n\nLedges can be shimmied along or\nhung from, but not walked along\nas with normal terrain. Must have the\nledge terrain type set as well.'],
                        ['Meltable', QtGui.QIcon(path + 'Prop/Melt.png'), 'Supposedly allows melting the tile?']]

        for item in range(len(propertyList)):
            self.propertyWidgets.append(QtWidgets.QCheckBox(propertyList[item][0]))
            self.propertyWidgets[item].setIcon(propertyList[item][1])
            self.propertyWidgets[item].setIconSize(QtCore.QSize(24, 24))
            self.propertyWidgets[item].setToolTip(propertyList[item][2])
            propertyLayout.addWidget(self.propertyWidgets[item])


        self.PassThrough = QtWidgets.QRadioButton('Pass-Through')
        self.PassDown = QtWidgets.QRadioButton('Pass-Down')
        self.PassNone = QtWidgets.QRadioButton('No Passing')

        self.PassThrough.setIcon(QtGui.QIcon(path + 'Prop/Pup.png'))
        self.PassDown.setIcon(QtGui.QIcon(path + 'Prop/Pdown.png'))
        self.PassNone.setIcon(QtGui.QIcon(path + 'Prop/Pnone.png'))

        self.PassThrough.setIconSize(QtCore.QSize(24, 24))
        self.PassDown.setIconSize(QtCore.QSize(24, 24))
        self.PassNone.setIconSize(QtCore.QSize(24, 24))

        self.PassThrough.setToolTip('Allows Mario to jump through the bottom\nof the tile and land on the top.')
        self.PassDown.setToolTip("Allows Mario to fall through the tile but\nbe able to jump up through it. Doesn't seem to actually do anything, though?")
        self.PassNone.setToolTip('Default setting')

        propertyLayout.addWidget(self.PassNone)
        propertyLayout.addWidget(self.PassThrough)
        propertyLayout.addWidget(self.PassDown)

        self.propertyGroup.setLayout(propertyLayout)



        # Terrain Type ComboBox
        self.terrainType = QtWidgets.QComboBox()
        self.terrainLabel = QtWidgets.QLabel('Terrain Type')

        self.terrainTypes = [['Default', QtGui.QIcon(path + 'Core/Default.png')],
                        ['Ice', QtGui.QIcon(path + 'Terrain/Ice.png')],
                        ['Snow', QtGui.QIcon(path + 'Terrain/Snow.png')],
                        ['Quicksand', QtGui.QIcon(path + 'Terrain/Quicksand.png')],
                        ['Conveyor Belt Right', QtGui.QIcon(path + 'Core/Conveyor.png')],
                        ['Conveyor Belt Left', QtGui.QIcon(path + 'Core/Conveyor.png')],
                        ['Horiz. Climbing Rope', QtGui.QIcon(path + 'Terrain/Rope.png')],
                        ['Anti Wall Jumps', QtGui.QIcon(path + 'Terrain/Spike.png')],
                        ['Ledge', QtGui.QIcon(path + 'Terrain/Ledge.png')],
                        ['Ladder', QtGui.QIcon(path + 'Terrain/Ladder.png')],
                        ['Staircase', QtGui.QIcon(path + 'Terrain/Stairs.png')],
                        ['Carpet', QtGui.QIcon(path + 'Terrain/Carpet.png')],
                        ['Dusty', QtGui.QIcon(path + 'Terrain/Dust.png')],
                        ['Grass', QtGui.QIcon(path + 'Terrain/Grass.png')],
                        ['Muffled', QtGui.QIcon(path + 'Unknown.png')],
                        ['Beach Sand', QtGui.QIcon(path + 'Terrain/Sand.png')]]

        for item in range(len(self.terrainTypes)):
            self.terrainType.addItem(self.terrainTypes[item][1], self.terrainTypes[item][0])
            self.terrainType.setIconSize(QtCore.QSize(24, 24))
        self.terrainType.setToolTip('Set the various types of terrain.'
                                    '<ul>'
                                    '<li><b>Default:</b><br>'
                                    'Terrain with no particular properties.</li>'
                                    '<li><b>Ice:</b><br>'
                                    'Will be slippery.</li>'
                                    '<li><b>Snow:</b><br>'
                                    'Will emit puffs of snow and snow noises.</li>'
                                    '<li><b>Quicksand:</b><br>'
                                    'Will slowly swallow Mario. Required for creating the quicksand effect.</li>'
                                    '<li><b>Conveyor Belt Right:</b><br>'
                                    'Mario moves rightwards.</li>'
                                    '<li><b>Conveyor Belt Left:</b><br>'
                                    'Mario moves leftwards.</li>'
                                    '<li><b>Horiz. Rope:</b><br>'
                                    'Must be solid to function. Mario will move hand-over-hand along the rope.</li>'
                                    '<li><b>Anti Wall Jumps:</b><br>'
                                    'Mario cannot wall-jump off of the tile.</li>'
                                    '<li><b>Ledge:</b><br>'
                                    'Must have ledge property set as well.</li>'
                                    '<li><b>Ladder:</b><br>'
                                    'Acts as a pole. Mario will face right or left as he climbs.</li>'
                                    '<li><b>Staircase:</b><br>'
                                    'Does not allow Mario to slide.</li>'
                                    '<li><b>Carpet:</b><br>'
                                    'Will muffle footstep noises.</li>'
                                    '<li><b>Dusty:</b><br>'
                                    'Will emit puffs of dust.</li>'
                                    '<li><b>Muffled:</b><br>'
                                    'Mostly muffles footstep noises.</li>'
                                    '<li><b>Grass:</b><br>'
                                    'Will emit grass-like footstep noises.</li>'
                                    '<li><b>Beach Sand:</b><br>'
                                    "Will create sand tufts around Mario's feet.</li>"
                                    '</ul>'
                                   )



        # Parameters ComboBox
        self.parameters = QtWidgets.QComboBox()
        self.parameterLabel = QtWidgets.QLabel('Parameters')
        self.parameters.addItem('None')


        GenericParams = [['None', QtGui.QIcon(path + 'Core/Default.png')],
                         ['Beanstalk Stop', QtGui.QIcon(path + '/Generic/Beanstopper.png')],
                         ['Dash Coin', QtGui.QIcon(path + 'Generic/Outline.png')],
                         ['Battle Coin', QtGui.QIcon(path + 'Generic/Outline.png')],
                         ['Red Block Outline A', QtGui.QIcon(path + 'Generic/RedBlock.png')],
                         ['Red Block Outline B', QtGui.QIcon(path + 'Generic/RedBlock.png')],
                         ['Cave Entrance Right', QtGui.QIcon(path + 'Generic/Cave-Right.png')],
                         ['Cave Entrance Left', QtGui.QIcon(path + 'Generic/Cave-Left.png')],
                         ['Unknown', QtGui.QIcon(path + 'Unknown.png')],
                         ['Layer 0 Pit', QtGui.QIcon(path + 'Unknown.png')]]

        RailParams = [['None', QtGui.QIcon(path + 'Core/Default.png')],
                      ['Rail: Upslope', QtGui.QIcon(path + '')],
                      ['Rail: Downslope', QtGui.QIcon(path + '')],
                      ['Rail: 90 degree Corner Fill', QtGui.QIcon(path + '')],
                      ['Rail: 90 degree Corner', QtGui.QIcon(path + '')],
                      ['Rail: Horizontal Rail', QtGui.QIcon(path + '')],
                      ['Rail: Vertical Rail', QtGui.QIcon(path + '')],
                      ['Rail: Unknown', QtGui.QIcon(path + 'Unknown.png')],
                      ['Rail: Gentle Upslope 2', QtGui.QIcon(path + '')],
                      ['Rail: Gentle Upslope 1', QtGui.QIcon(path + '')],
                      ['Rail: Gentle Downslope 2', QtGui.QIcon(path + '')],
                      ['Rail: Gentle Downslope 1', QtGui.QIcon(path + '')],
                      ['Rail: Steep Upslope 2', QtGui.QIcon(path + '')],
                      ['Rail: Steep Upslope 1', QtGui.QIcon(path + '')],
                      ['Rail: Steep Downslope 2', QtGui.QIcon(path + '')],
                      ['Rail: Steep Downslope 1', QtGui.QIcon(path + '')],
                      ['Rail: One Panel Circle', QtGui.QIcon(path + '')],
                      ['Rail: 2x2 Circle Upper Right', QtGui.QIcon(path + '')],
                      ['Rail: 2x2 Circle Upper Left', QtGui.QIcon(path + '')],
                      ['Rail: 2x2 Circle Lower Right', QtGui.QIcon(path + '')],
                      ['Rail: 2x2 Circle Lower Left', QtGui.QIcon(path + '')],
                      ['Rail: 4x4 Circle Top Left Corner', QtGui.QIcon(path + '')],
                      ['Rail: 4x4 Circle Top Left', QtGui.QIcon(path + '')],
                      ['Rail: 4x4 Circle Top Right', QtGui.QIcon(path + '')],
                      ['Rail: 4x4 Circle Top Right Corner', QtGui.QIcon(path + '')],
                      ['Rail: 4x4 Circle Upper Left Side', QtGui.QIcon(path + '')],
                      ['Rail: 4x4 Circle Upper Right Side', QtGui.QIcon(path + '')],
                      ['Rail: 4x4 Circle Lower Left Side', QtGui.QIcon(path + '')],
                      ['Rail: 4x4 Circle Lower Right Side', QtGui.QIcon(path + '')],
                      ['Rail: 4x4 Circle Bottom Left Corner', QtGui.QIcon(path + '')],
                      ['Rail: 4x4 Circle Bottom Left', QtGui.QIcon(path + '')],
                      ['Rail: 4x4 Circle Bottom Right', QtGui.QIcon(path + '')],
                      ['Rail: 4x4 Circle Bottom Right Corner', QtGui.QIcon(path + '')],
                      ['Rail: Unknown', QtGui.QIcon(path + 'Unknown.png')],
                      ['Rail: End Stop', QtGui.QIcon(path + '')]]

        ClimableGridParams = [['None', QtGui.QIcon(path + 'Core/Default.png')],
                             ['Free Move', QtGui.QIcon(path + 'Climb/Center.png')],
                             ['Upper Left Corner', QtGui.QIcon(path + 'Climb/UpperLeft.png')],
                             ['Top', QtGui.QIcon(path + 'Climb/Top.png')],
                             ['Upper Right Corner', QtGui.QIcon(path + 'Climb/UpperRight.png')],
                             ['Left Side', QtGui.QIcon(path + 'Climb/Left.png')],
                             ['Center', QtGui.QIcon(path + 'Climb/Center.png')],
                             ['Right Side', QtGui.QIcon(path + 'Climb/Right.png')],
                             ['Lower Left Corner', QtGui.QIcon(path + 'Climb/LowerLeft.png')],
                             ['Bottom', QtGui.QIcon(path + 'Climb/Bottom.png')],
                             ['Lower Right Corner', QtGui.QIcon(path + 'Climb/LowerRight.png')]]


        CoinParams = [['Generic Coin', QtGui.QIcon(path + 'QBlock/Coin.png')],
                     ['Coin', QtGui.QIcon(path + 'Unknown.png')],
                     ['Nothing', QtGui.QIcon(path + 'Unknown.png')],
                     ['Coin', QtGui.QIcon(path + 'Unknown.png')],
                     ['Pow Block Coin', QtGui.QIcon(path + 'Coin/POW.png')]]

        ExplodableBlockParams = [['None', QtGui.QIcon(path + 'Core/Default.png')],
                                ['Stone Block', QtGui.QIcon(path + 'Explode/Stone.png')],
                                ['Wooden Block', QtGui.QIcon(path + 'Explode/Wooden.png')],
                                ['Red Block', QtGui.QIcon(path + 'Explode/Red.png')],
                                ['Unknown', QtGui.QIcon(path + 'Unknown.png')],
                                ['Unknown', QtGui.QIcon(path + 'Unknown.png')],
                                ['Unknown', QtGui.QIcon(path + 'Unknown.png')]]

        PipeParams = [['Vert. Top Entrance Left', QtGui.QIcon(path + 'Pipes/')],
                      ['Vert. Top Entrance Right', QtGui.QIcon(path + '')],
                      ['Vert. Bottom Entrance Left', QtGui.QIcon(path + '')],
                      ['Vert. Bottom Entrance Right', QtGui.QIcon(path + '')],
                      ['Vert. Center Left', QtGui.QIcon(path + '')],
                      ['Vert. Center Right', QtGui.QIcon(path + '')],
                      ['Vert. On Top Junction Left', QtGui.QIcon(path + '')],
                      ['Vert. On Top Junction Right', QtGui.QIcon(path + '')],
                      ['Horiz. Left Entrance Top', QtGui.QIcon(path + '')],
                      ['Horiz. Left Entrance Bottom', QtGui.QIcon(path + '')],
                      ['Horiz. Right Entrance Top', QtGui.QIcon(path + '')],
                      ['Horiz. Right Entrance Bottom', QtGui.QIcon(path + '')],
                      ['Horiz. Center Left', QtGui.QIcon(path + '')],
                      ['Horiz. Center Right', QtGui.QIcon(path + '')],
                      ['Horiz. On Top Junction Top', QtGui.QIcon(path + '')],
                      ['Horiz. On Top Junction Bottom', QtGui.QIcon(path + '')],
                      ['Vert. Mini Pipe Top', QtGui.QIcon(path + '')],
                      ['Unknown', QtGui.QIcon(path + 'Unknown.png')],
                      ['Vert. Mini Pipe Bottom', QtGui.QIcon(path + '')],
                      ['Unknown', QtGui.QIcon(path + 'Unknown.png')],
                      ['Unknown', QtGui.QIcon(path + 'Unknown.png')],
                      ['Unknown', QtGui.QIcon(path + 'Unknown.png')],
                      ['Vert. On Top Mini-Junction', QtGui.QIcon(path + '')],
                      ['Unknown', QtGui.QIcon(path + 'Unknown.png')],
                      ['Horiz. Mini Pipe Left', QtGui.QIcon(path + '')],
                      ['Unknown', QtGui.QIcon(path + 'Unknown.png')],
                      ['Horiz. Mini Pipe Right', QtGui.QIcon(path + '')],
                      ['Unknown', QtGui.QIcon(path + 'Unknown.png')],
                      ['Vert. Mini Pipe Center', QtGui.QIcon(path + '')],
                      ['Horiz. Mini Pipe Center', QtGui.QIcon(path + '')],
                      ['Horiz. On Top Mini-Junction', QtGui.QIcon(path + '')],
                      ['Block Covered Corner', QtGui.QIcon(path + '')]]

        PartialBlockParams = [['None', QtGui.QIcon(path + 'Core/Default.png')],
                              ['Upper Left', QtGui.QIcon(path + 'Partial/UpLeft.png')],
                              ['Upper Right', QtGui.QIcon(path + 'Partial/UpRight.png')],
                              ['Top Half', QtGui.QIcon(path + 'Partial/TopHalf.png')],
                              ['Lower Left', QtGui.QIcon(path + 'Partial/LowLeft.png')],
                              ['Left Half', QtGui.QIcon(path + 'Partial/LeftHalf.png')],
                              ['Diagonal Downwards', QtGui.QIcon(path + 'Partial/DiagDn.png')],
                              ['Upper Left 3/4', QtGui.QIcon(path + 'Partial/UpLeft3-4.png')],
                              ['Lower Right', QtGui.QIcon(path + 'Partial/LowRight.png')],
                              ['Diagonal Downwards', QtGui.QIcon(path + 'Partial/DiagDn.png')],
                              ['Right Half', QtGui.QIcon(path + 'Partial/RightHalf.png')],
                              ['Upper Right 3/4', QtGui.QIcon(path + 'Partial/UpRig3-4.png')],
                              ['Lower Half', QtGui.QIcon(path + 'Partial/LowHalf.png')],
                              ['Lower Left 3/4', QtGui.QIcon(path + 'Partial/LowLeft3-4.png')],
                              ['Lower Right 3/4', QtGui.QIcon(path + 'Partial/LowRight3-4.png')],
                              ['Full Brick', QtGui.QIcon(path + 'Partial/Full.png')]]

        SlopeParams = [['Steep Upslope', QtGui.QIcon(path + 'Slope/steepslopeleft.png')],
                       ['Steep Downslope', QtGui.QIcon(path + 'Slope/steepsloperight.png')],
                       ['Upslope 1', QtGui.QIcon(path + 'Slope/slopeleft.png')],
                       ['Upslope 2', QtGui.QIcon(path + 'Slope/slope3left.png')],
                       ['Downslope 1', QtGui.QIcon(path + 'Slope/slope3right.png')],
                       ['Downslope 2', QtGui.QIcon(path + 'Slope/sloperight.png')],
                       ['Steep Upslope 1', QtGui.QIcon(path + 'Slope/vsteepup1.png')],
                       ['Steep Upslope 2', QtGui.QIcon(path + 'Slope/vsteepup2.png')],
                       ['Steep Downslope 1', QtGui.QIcon(path + 'Slope/vsteepdown1.png')],
                       ['Steep Downslope 2', QtGui.QIcon(path + 'Slope/vsteepdown2.png')],
                       ['Slope Edge (solid)', QtGui.QIcon(path + 'Slope/edge.png')],
                       ['Gentle Upslope 1', QtGui.QIcon(path + 'Slope/gentleupslope1.png')],
                       ['Gentle Upslope 2', QtGui.QIcon(path + 'Slope/gentleupslope2.png')],
                       ['Gentle Upslope 3', QtGui.QIcon(path + 'Slope/gentleupslope3.png')],
                       ['Gentle Upslope 4', QtGui.QIcon(path + 'Slope/gentleupslope4.png')],
                       ['Gentle Downslope 1', QtGui.QIcon(path + 'Slope/gentledownslope1.png')],
                       ['Gentle Downslope 2', QtGui.QIcon(path + 'Slope/gentledownslope2.png')],
                       ['Gentle Downslope 3', QtGui.QIcon(path + 'Slope/gentledownslope3.png')],
                       ['Gentle Downslope 4', QtGui.QIcon(path + 'Slope/gentledownslope4.png')]]

        ReverseSlopeParams = [['Steep Downslope', QtGui.QIcon(path + 'Slope/Rsteepslopeleft.png')],
                              ['Steep Upslope', QtGui.QIcon(path + 'Slope/Rsteepsloperight.png')],
                              ['Downslope 1', QtGui.QIcon(path + 'Slope/Rslopeleft.png')],
                              ['Downslope 2', QtGui.QIcon(path + 'Slope/Rslope3left.png')],
                              ['Upslope 1', QtGui.QIcon(path + 'Slope/Rslope3right.png')],
                              ['Upslope 2', QtGui.QIcon(path + 'Slope/Rsloperight.png')],
                              ['Steep Downslope 1', QtGui.QIcon(path + 'Slope/Rvsteepdown1.png')],
                              ['Steep Downslope 2', QtGui.QIcon(path + 'Slope/Rvsteepdown2.png')],
                              ['Steep Upslope 1', QtGui.QIcon(path + 'Slope/Rvsteepup1.png')],
                              ['Steep Upslope 2', QtGui.QIcon(path + 'Slope/Rvsteepup2.png')],
                              ['Slope Edge (solid)', QtGui.QIcon(path + 'Slope/edge.png')],
                              ['Gentle Downslope 1', QtGui.QIcon(path + 'Slope/Rgentledownslope1.png')],
                              ['Gentle Downslope 2', QtGui.QIcon(path + 'Slope/Rgentledownslope2.png')],
                              ['Gentle Downslope 3', QtGui.QIcon(path + 'Slope/Rgentledownslope3.png')],
                              ['Gentle Downslope 4', QtGui.QIcon(path + 'Slope/Rgentledownslope4.png')],
                              ['Gentle Upslope 1', QtGui.QIcon(path + 'Slope/Rgentleupslope1.png')],
                              ['Gentle Upslope 2', QtGui.QIcon(path + 'Slope/Rgentleupslope2.png')],
                              ['Gentle Upslope 3', QtGui.QIcon(path + 'Slope/Rgentleupslope3.png')],
                              ['Gentle Upslope 4', QtGui.QIcon(path + 'Slope/Rgentleupslope4.png')]]

        SpikeParams = [['Double Left Spikes', QtGui.QIcon(path + 'Spike/Left.png')],
                       ['Double Right Spikes', QtGui.QIcon(path + 'Spike/Right.png')],
                       ['Double Upwards Spikes', QtGui.QIcon(path + 'Spike/Up.png')],
                       ['Double Downwards Spikes', QtGui.QIcon(path + 'Spike/Down.png')],
                       ['Long Spike Down 1', QtGui.QIcon(path + 'Spike/LongDown1.png')],
                       ['Long Spike Down 2', QtGui.QIcon(path + 'Spike/LongDown2.png')],
                       ['Single Downwards Spike', QtGui.QIcon(path + 'Spike/SingDown.png')],
                       ['Spike Block', QtGui.QIcon(path + 'Unknown.png')]]

        ConveyorBeltParams = [['Slow', QtGui.QIcon(path + 'Unknown.png')],
                              ['Fast', QtGui.QIcon(path + 'Unknown.png')]]

        QBlockParams = [['Fire Flower', QtGui.QIcon(path + 'Qblock/Fire.png')],
                       ['Star', QtGui.QIcon(path + 'Qblock/Star.png')],
                       ['Coin', QtGui.QIcon(path + 'Qblock/Coin.png')],
                       ['Vine', QtGui.QIcon(path + 'Qblock/Vine.png')],
                       ['1-Up', QtGui.QIcon(path + 'Qblock/1up.png')],
                       ['Mini Mushroom', QtGui.QIcon(path + 'Qblock/Mini.png')],
                       ['Propeller Suit', QtGui.QIcon(path + 'Qblock/Prop.png')],
                       ['Penguin Suit', QtGui.QIcon(path + 'Qblock/Peng.png')],
                       ['Ice Flower', QtGui.QIcon(path + 'Qblock/IceF.png')]]


        self.ParameterList = [GenericParams,
                              SlopeParams,
                              ReverseSlopeParams,
                              PartialBlockParams,
                              CoinParams,
                              ExplodableBlockParams,
                              ClimableGridParams,
                              SpikeParams,
                              PipeParams,
                              RailParams,
                              ConveyorBeltParams,
                              QBlockParams]


        layout = QtWidgets.QGridLayout()
        layout.addWidget(self.coreType, 0, 1)
        layout.addWidget(self.propertyGroup, 0, 0, 3, 1)
        layout.addWidget(self.terrainType, 2, 1)
        layout.addWidget(self.parameters, 1, 1)
        self.setLayout(layout)


    def swapParams(self):
        for item in range(len(self.ParameterList)):
            if self.coreWidgets[item].isChecked():
                self.parameters.clear()
                for option in self.ParameterList[item]:
                    self.parameters.addItem(option[1], option[0])



#############################################################################################
######################### InfoBox Custom Widget to display info to ##########################


class InfoBox(QtWidgets.QWidget):
    def __init__(self, window):
        super(InfoBox, self).__init__(window)

        # InfoBox
        superLayout = QtWidgets.QGridLayout()
        infoLayout = QtWidgets.QFormLayout()

        self.imageBox = QtWidgets.QGroupBox()
        imageLayout = QtWidgets.QHBoxLayout()

        pix = QtGui.QPixmap(24, 24)
        pix.fill(Qt.transparent)

        self.coreImage = QtWidgets.QLabel()
        self.coreImage.setPixmap(pix)
        self.terrainImage = QtWidgets.QLabel()
        self.terrainImage.setPixmap(pix)
        self.parameterImage = QtWidgets.QLabel()
        self.parameterImage.setPixmap(pix)


        def updateAllTiles():
            for i in range(256):
                window.tileDisplay.update(window.tileDisplay.model().index(i, 0))
        self.collisionOverlay = QtWidgets.QCheckBox('Overlay Collision')
        self.collisionOverlay.clicked.connect(updateAllTiles)

        self.toggleAlpha = QtWidgets.QCheckBox('Toggle Background')
        self.toggleAlpha.clicked.connect(window.toggleAlpha)

        class QScreenshot(QtWidgets.QSplashScreen):
            def __init__(self, screenshot):
                super().__init__(screenshot)

        def showScreenshot():
            self.image = window.tileDisplay.grab()
            self.image = self.image.scaled(self.image.width()*2, self.image.height()*2)
            self.screenshotWindow = QScreenshot(self.image)
            self.screenshotWindow.show()

        self.screenshotButton = QtWidgets.QPushButton('View enlarged screenshot')
        self.screenshotButton.released.connect(showScreenshot)

        self.coreInfo = QtWidgets.QLabel()
        self.terrainInfo = QtWidgets.QLabel()
        self.paramInfo = QtWidgets.QLabel()
        self.propertyBox = QtWidgets.QGroupBox()
        self.propertyInfo = QtWidgets.QLabel('Properties:\nNone             \n\n\n\n\n')
        self.propertyInfo.setWordWrap(True)
        self.propertyInfo.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Minimum)

        Font = self.font()
        Font.setPointSize(9)

        self.coreInfo.setFont(Font)
        self.propertyInfo.setFont(Font)
        self.terrainInfo.setFont(Font)
        self.paramInfo.setFont(Font)

        self.hexdata = QtWidgets.QLabel('Hex Data: 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00')
        self.hexdata.setFont(Font)
        self.numInfo = QtWidgets.QLabel('Slot: 0 Row: 0 Column: 0')
        self.numInfo.setFont(Font)

        coreLayout = QtWidgets.QVBoxLayout()
        terrLayout = QtWidgets.QVBoxLayout()
        paramLayout = QtWidgets.QVBoxLayout()

        coreLayout.setGeometry(QtCore.QRect(0,0,40,40))
        terrLayout.setGeometry(QtCore.QRect(0,0,40,40))
        paramLayout.setGeometry(QtCore.QRect(0,0,40,40))


        label = QtWidgets.QLabel('Core')
        label.setFont(Font)
        coreLayout.addWidget(label, 0, Qt.AlignCenter)

        label = QtWidgets.QLabel('Terrain')
        label.setFont(Font)
        terrLayout.addWidget(label, 0, Qt.AlignCenter)

        label = QtWidgets.QLabel('Parameters')
        label.setFont(Font)
        paramLayout.addWidget(label, 0, Qt.AlignCenter)

        coreLayout.addWidget(self.coreImage, 0, Qt.AlignCenter)
        terrLayout.addWidget(self.terrainImage, 0, Qt.AlignCenter)
        paramLayout.addWidget(self.parameterImage, 0, Qt.AlignCenter)

        coreLayout.addWidget(self.coreInfo, 0, Qt.AlignCenter)
        terrLayout.addWidget(self.terrainInfo, 0, Qt.AlignCenter)
        paramLayout.addWidget(self.paramInfo, 0, Qt.AlignCenter)

        imageLayout.setContentsMargins(0,4,4,4)
        imageLayout.addLayout(coreLayout)
        imageLayout.addStretch()
        imageLayout.addLayout(terrLayout)
        imageLayout.addStretch()
        imageLayout.addLayout(paramLayout)

        self.imageBox.setLayout(imageLayout)

        infoLayout.setContentsMargins(0,4,4,4)
        infoLayout.addRow(self.propertyInfo)
        self.propertyBox.setLayout(infoLayout)

        self.setMinimumWidth(800)
        #self.setMaximumWidth(1000)

        superLayout.addWidget(self.imageBox, 0, 2, 1, 2)
        superLayout.addWidget(self.propertyBox, 0, 0, 1, 2)
        superLayout.addWidget(self.hexdata, 1, 0, 1, 4, Qt.AlignCenter)
        superLayout.addWidget(self.numInfo, 2, 0, 1, 4, Qt.AlignCenter)
        superLayout.addWidget(self.collisionOverlay, 3, 0, 1, 1)
        superLayout.addWidget(self.toggleAlpha, 3, 1, 1, 2, Qt.AlignCenter)
        superLayout.addWidget(self.screenshotButton, 3, 3, 1, 1, Qt.AlignRight)
        self.setLayout(superLayout)


#############################################################################################
##################### Framesheet List Widget and Model Setup with Painter #######################


class framesheetList(QtWidgets.QListView):

    def __init__(self, parent=None):
        super(framesheetList, self).__init__(parent)

        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setHeight()
        self.setMovement(QtWidgets.QListView.Static)
        self.setBackgroundRole(QtGui.QPalette.BrightText)
        self.setWrapping(False)
        self.setMinimumHeight(512)

    def setHeight(self):
        height = getFramesheetGridSize()
        self.setIconSize(QtCore.QSize(32, height))
        self.setGridSize(QtCore.QSize(200,height+50))


def getFramesheetGridSize():
    global Tileset
    max = 0
    for key in list(Tileset.animdata.keys()):
        t = len(Tileset.animdata[key])//64
        if t > max:
            max = t
    return max



def SetupFramesheetModel(self, animdata):
    global Tileset
    self.framesheetList.setHeight()
    self.framesheetmodel.clear()
    self.frames = {}
    frames = []

    count = 0
    for key in list(animdata.keys()):
        height = len(animdata[key])//64

        image = QtGui.QImage(32, height, QtGui.QImage.Format_ARGB32)
        frame = QtGui.QImage(32, 32, QtGui.QImage.Format_ARGB32)

        bytes = animdata[key]
        bits = ''.join(format(byte, '08b') for byte in bytes)

        Xoffset = 0
        Yoffset = 0
        XBlock = 0
        YBlock = 0

        frames = []

        for i in range(0, len(bits), 16):
            color = RGB4A3LUT[int(bits[i:i+16], 2)]

            image.setPixel(Xoffset+XBlock, Yoffset+YBlock, color)
            frame.setPixel(Xoffset+XBlock, (Yoffset+YBlock)%32, color)

            XBlock += 1
            if XBlock >= 4:
                XBlock = 0
                YBlock += 1
                if YBlock >= 4:
                    YBlock = 0
                    Xoffset += 4
                    if Xoffset >= 32:
                        Xoffset = 0
                        Yoffset += 4
                        if (Yoffset+YBlock)%32 == 0 and not (Yoffset+YBlock) == 0:
                            frames.append(QtGui.QPixmap.fromImage(frame))
                            frame = QtGui.QImage(32, 32, QtGui.QImage.Format_ARGB32)

        self.frames[key] = frames

        tex = QtGui.QPixmap.fromImage(image)

        #fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Choose a new filename', '', '.png (*.png)')[0]
        #tex.save(fn)


        item = QtGui.QStandardItem(QtGui.QIcon(tex), '{0}'.format(key[7:-4]))
        item.setEditable(False)
        self.framesheetmodel.appendRow(item)

        count += 1


def RGB4A3FramesheetEncode(tex):
    shorts = []
    colorCache = {}

    for Yoffset in range(0, tex.height(), 4):
        for Xoffset in range(0,32,4):
            for ypixel in range(Yoffset, Yoffset + 4):
                for xpixel in range(Xoffset, Xoffset + 4):

                    pixel = tex.pixel(xpixel, ypixel)

                    a = pixel >> 24
                    r = (pixel >> 16) & 0xFF
                    g = (pixel >> 8) & 0xFF
                    b = pixel & 0xFF

                    if pixel in colorCache:
                        rgba = colorCache[pixel]

                    else:
                        if a < 238: # RGB4A3
                            alpha = ((a + 18) << 1) // 73
                            red = (r + 8) // 17
                            green = (g + 8) // 17
                            blue = (b + 8) // 17

                            # 0aaarrrrggggbbbb
                            rgba = blue | (green << 4) | (red << 8) | (alpha << 12)

                        else: # RGB555
                            red = ((r + 4) << 2) // 33
                            green = ((g + 4) << 2) // 33
                            blue = ((b + 4) << 2) // 33

                            # 1rrrrrgggggbbbbb
                            rgba = blue | (green << 5) | (red << 10) | (0x8000)

                        colorCache[pixel] = rgba

                    shorts.append(rgba)
    return struct.pack('>{0}H'.format(len(shorts)), *shorts)


class framesheetOverlord(QtWidgets.QWidget):

    def __init__(self):
        super(framesheetOverlord, self).__init__()

        self.addFramesheet = QtWidgets.QPushButton('Add')
        self.removeFramesheet = QtWidgets.QPushButton('Remove')
        self.replaceFramesheet = QtWidgets.QPushButton('Replace')
        self.renameFramesheet = QtWidgets.QPushButton('Rename')


        # Connections
        self.addFramesheet.released.connect(self.addFs)
        self.removeFramesheet.released.connect(self.removeFs)
        self.replaceFramesheet.released.connect(self.replaceFs)
        self.renameFramesheet.released.connect(self.renameFs)


        # Layout
        layout = QtWidgets.QGridLayout()

        layout.addWidget(self.addFramesheet, 0, 6, 1, 1)
        layout.addWidget(self.removeFramesheet, 0, 7, 1, 1)
        layout.addWidget(self.replaceFramesheet, 0, 8, 1, 1)
        layout.addWidget(self.renameFramesheet, 0, 9, 1, 1)

        self.setLayout(layout)


    def openFs(self, forAdding = True):
        '''Opens an framesheet from png.'''

        path = QtWidgets.QFileDialog.getOpenFileName(self, "Open framesheet", '', "Image Files (*.png)")[0]
        if not path: return (None, None)

        framesheet = QtGui.QPixmap()
        if not framesheet.load(path):
            QtWidgets.QMessageBox.warning(self, "Open framesheet",
                    "The framesheet file could not be loaded.",
                    QtWidgets.QMessageBox.Cancel)
            return (None, None)

        if forAdding and framesheet.width() != 32 or framesheet.height() % 32 != 0:
            QtWidgets.QMessageBox.warning(self, "Open framesheet",
                    "The framesheet has incorrect dimensions. "
                    "Needed sizes: 32 pixel width and a multiple of 32 height.",
                    QtWidgets.QMessageBox.Cancel)
            return (None, None)

        return (framesheet, path)


    def addFs(self):
        global Tileset

        #Tileset.addObject()

        framesheet, path = self.openFs()
        if framesheet is None: return
        #print(framesheet)
        base = os.path.basename(path)
        name = os.path.splitext(base)[0]


        while self.nameIsTaken(name):
            newName, ok = QtWidgets.QInputDialog.getText(self, 'Rename framesheet', 'The framesheet name is already taken!\nEnter a new name:')

            if not ok:
                return

            if not newName or " " in newName:
                QtWidgets.QMessageBox.warning(self, "Rename framesheet",
                        "The file name cannot be empty or contain any spaces.",
                        QtWidgets.QMessageBox.Cancel)
                continue

            name = newName

        image = framesheet.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
        data = RGB4A3FramesheetEncode(image)
        Tileset.animdata["BG_tex/{0}.bin".format(name)] = data

        frames = []
        for y in range(0, len(data)//2048):
            frame = framesheet.copy(0, 32*y, 32, 32)
            frames.append(frame)
        window.frames["BG_tex/{0}.bin".format(name)] = frames

        window.framesheetmodel.appendRow(QtGui.QStandardItem(QtGui.QIcon(framesheet), '{0}'.format(name)))
        index = window.framesheetList.currentIndex()
        window.framesheetList.setCurrentIndex(index)
        #self.setObject(index)

        window.framesheetList.setHeight()
        window.framesheetList.update()
        self.update()


    def removeFs(self):
        if not Tileset.animdata:
            return

        index = window.framesheetList.currentIndex()

        if index.row() == -1:
            return

        name = window.framesheetmodel.itemFromIndex(index).text()
        Tileset.animdata.pop("BG_tex/{0}.bin".format(name), None)
        window.frames.pop("BG_tex/{0}.bin".format(name), None)

        window.framesheetmodel.removeRow(index.row())

        index = window.framesheetList.currentIndex()
        if not index.row() == -1:
            window.framesheetList.setCurrentIndex(index)
            #self.setObject(index)

        window.framesheetList.update()
        self.update()


    def replaceFs(self):
        index = window.framesheetList.currentIndex()

        if index.row() == -1:
            return

        name = window.framesheetmodel.itemFromIndex(index).text()
        iconSize = window.framesheetmodel.itemFromIndex(index).icon().availableSizes()[0]
        framesheet, temp = self.openFs(False)

        if framesheet is None: return

        if not framesheet.width() == iconSize.width() or not framesheet.height() == iconSize.height():
            QtWidgets.QMessageBox.warning(self, "Open framesheet",
                    "The framesheet has incorrect dimensions. "
                    "Needed sizes: {0} pixel width and {1} pixel height.".format(iconSize.width(), iconSize.height()),
                    QtWidgets.QMessageBox.Cancel)
            return

        image = framesheet.toImage().convertToFormat(QtGui.QImage.Format_ARGB32);
        data = RGB4A3FramesheetEncode(image)
        Tileset.animdata["BG_tex/{0}.bin".format(name)] = data

        frames = []
        for y in range(0, len(data)//2048):
            frame = framesheet.copy(0, 32*y, 32, 32)
            frames.append(frame)
        window.frames["BG_tex/{0}.bin".format(name)] = frames

        window.framesheetmodel.itemFromIndex(index).setIcon(QtGui.QIcon(framesheet))

        window.framesheetList.update()
        self.update()


    def renameFs(self):
        index = window.framesheetList.currentIndex()

        if index.row() == -1:
            return

        oldName = window.framesheetmodel.itemFromIndex(index).text()

        name, ok = QtWidgets.QInputDialog.getText(self, 'Rename framesheet', 'Enter the new name:')
        if not ok or name == oldName:
            return

        if not name or " " in name:
            QtWidgets.QMessageBox.warning(self, "Rename framesheet",
                    "The file name cannot be empty or contain any spaces.",
                    QtWidgets.QMessageBox.Cancel)
            return

        if self.nameIsTaken(name):
            QtWidgets.QMessageBox.warning(self, "Rename framesheet",
                    "The file name is already taken by another framesheet.",
                    QtWidgets.QMessageBox.Cancel)
            return

        window.framesheetmodel.itemFromIndex(index).setText(name)

        Tileset.animdata["BG_tex/{0}.bin".format(name)] = Tileset.animdata.pop("BG_tex/{0}.bin".format(oldName))

        window.frames["BG_tex/{0}.bin".format(name)] = window.frames.pop("BG_tex/{0}.bin".format(oldName))

        window.framesheetList.update()
        self.update()


    def nameIsTaken(self, name):
        return "BG_tex/{0}.bin".format(name) in list(Tileset.animdata.keys())


#############################################################################################
################################### Frame Editor Widget #####################################


class frameEditorOverlord(QtWidgets.QWidget):

    def __init__(self):
        super(frameEditorOverlord, self).__init__()

        self.explanation = QtWidgets.QLabel('Click on a framesheet in the Framesheets tab')
        self.list = QtWidgets.QComboBox()
        self.delete = QtWidgets.QPushButton('Delete')
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Frames", "Delays"])
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)

        #self.tilenumLabel = QtWidgets.QLabel("Tilenum (int):")
        #self.tilenumLineEdit = QtWidgets.QLineEdit()
        #self.tilenumLineEdit.setMaxLength(3)
        #self.tilenumLineEdit.setValidator(QtGui.QIntValidator())
        #self.tilenumLineEdit.setPlaceholderText("slot row column (hex)")
        #self.tilenumLineEdit.setAlignment(Qt.AlignRight)




        self.opened = []

        self.coreType = QtWidgets.QGroupBox()
        self.coreType.setTitle('Animation properties:')
        self.coreWidgets = []
        coreLayout = QtWidgets.QVBoxLayout()
        self.rowA = QtWidgets.QHBoxLayout()
        self.rowB = QtWidgets.QHBoxLayout()
        self.rowC = QtWidgets.QHBoxLayout()
        self.rowD = QtWidgets.QHBoxLayout()
        self.rowE = QtWidgets.QHBoxLayout()
        self.rowF = QtWidgets.QHBoxLayout()
        self.rowG = QtWidgets.QHBoxLayout()

        self.rowA.addWidget(QtWidgets.QLabel("Texname:"))
        self.nameLabel = QtWidgets.QLabel("coin")
        self.nameLabel.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.nameLabel.setAlignment(Qt.AlignRight)
        self.rowB.addWidget(QtWidgets.QLabel("Frames:"))
        self.delayLabel = QtWidgets.QLabel("5")
        self.delayLabel.setAlignment(Qt.AlignRight)
        self.rowC.addWidget(QtWidgets.QLabel("Tilenum:"))
        self.tilenumLabel = QtWidgets.QLabel("test")
        self.tilenumLabel.setAlignment(Qt.AlignRight)

        self.spin1 = QtWidgets.QSpinBox()
        self.spin1.setDisplayIntegerBase(16)
        self.spin2 = QtWidgets.QSpinBox()
        self.spin2.setDisplayIntegerBase(16)
        self.spin3 = QtWidgets.QSpinBox()
        self.spin3.setDisplayIntegerBase(16)
        spinFont = self.spin1.font()
        spinFont.setCapitalization(QtGui.QFont.AllUppercase)
        self.spin1.setFont(spinFont)
        self.spin2.setFont(spinFont)
        self.spin3.setFont(spinFont)

        self.spin1.valueChanged.connect(self.setTilenum)
        self.spin2.valueChanged.connect(self.setTilenum)
        self.spin3.valueChanged.connect(self.setTilenum)

        self.checkBox = QtWidgets.QCheckBox('Reverse playback direction')

        self.checkBox.clicked.connect(self.setTilenum)

        self.rowA.addWidget(self.nameLabel, Qt.AlignRight)
        self.rowB.addWidget(self.delayLabel)
        self.rowC.addWidget(self.tilenumLabel)
        self.rowD.addWidget(QtWidgets.QLabel("Slot:"))
        self.rowD.addWidget(self.spin1)
        self.rowE.addWidget(QtWidgets.QLabel("Row:"))
        self.rowE.addWidget(self.spin2)
        self.rowF.addWidget(QtWidgets.QLabel("Column:"))
        self.rowF.addWidget(self.spin3)
        self.rowG.addWidget(self.checkBox)


        coreLayout.insertStretch(0)
        coreLayout.addLayout(self.rowA)
        coreLayout.insertStretch(2)
        coreLayout.addLayout(self.rowB)
        coreLayout.insertStretch(4)
        coreLayout.addLayout(self.rowC)
        coreLayout.addLayout(self.rowD)
        #coreLayout.insertStretch(5)
        coreLayout.addLayout(self.rowE)
        #coreLayout.insertStretch(7)
        coreLayout.addLayout(self.rowF)
        coreLayout.insertStretch(11)
        coreLayout.addLayout(self.rowG)
        coreLayout.setAlignment(Qt.AlignTop)
        self.coreType.setLayout(coreLayout)

        self.preview = QtWidgets.QLabel('Preview:')
        self.previewLabel = QtWidgets.QLabel(self)
        self.previewLabel.setAlignment(Qt.AlignRight)
        self.thread = threading.Thread(target = self.play, args = ())
        self.thread.start()

        self.importFramesheet = QtWidgets.QPushButton('Import framesheet info')
        self.exportFramesheet = QtWidgets.QPushButton('Export framesheet info')


        self.setupContainer()


        # Connections
        self.table.cellClicked.connect(self.tableClicked)

        self.importFramesheet.released.connect(self.importInfo)
        self.exportFramesheet.released.connect(self.exportInfo)

        self.list.activated.connect(self.setContents)
        self.delete.released.connect(self.deleteCurrentlySelectedEntry)

        # Layout
        layout = QtWidgets.QGridLayout()

        layout.addWidget(self.explanation, 0, 0, 1, 6)
        layout.addWidget(self.list, 0, 0, 1, 5)
        layout.addWidget(self.delete, 0, 5, 1, 1)

        layout.addWidget(self.table, 1, 0, 1, 3)
        
        layout.addWidget(self.coreType, 1, 3, 2, 3)

        layout.addWidget(self.preview, 2, 0, 1, 2)
        layout.addWidget(self.previewLabel, 2, 2, 1, 1)

        layout.addWidget(self.importFramesheet, 3, 0, 1, 3)
        layout.addWidget(self.exportFramesheet, 3, 3, 1, 3)


        layout.setRowMinimumHeight(1, 40)

        self.setLayout(layout)

        self.setupComboBox()
        self.list.setCurrentIndex(-1)

        self.texname = ""
        self.framenum = 0


    def tableClicked(self, row, column):
        if column != 0:
            return

        centerPoint = self.table.cellWidget(row, column).contentsRect().center()

        frameMenu = QtWidgets.QMenu(self)

        frameMenu.addAction('Export', self.exportFrame)
        frameMenu.addAction('Replace', self.replaceFrame)

        frameMenu.exec_(QtWidgets.QWidget.mapToGlobal(self.table.cellWidget(row, column), centerPoint))


    def exportFrame(self):
        i = self.table.currentRow()

        path = QtWidgets.QFileDialog.getSaveFileName(self, 'Framesheet', '{}_{}.png'.format(self.texname, i+1), 'Framesheet (*.png)')[0]
        if not path: return

        pixmap = window.frames["BG_tex/{0}.bin".format(self.texname)][i]
        pixmap.save(path, "PNG")


    def replaceFrame(self):
        frame, temp = window.framesheetWidget.openFs(False)
        if frame is None: return

        if not frame.width() == 32 or not frame.height() == 32:
            QtWidgets.QMessageBox.warning(self, "Open frame", "The frame has incorrect dimensions.\nNeeded sizes: 32x32 pixel.", QtWidgets.QMessageBox.Cancel)
            return

        i = self.table.currentRow()
        window.frames["BG_tex/{0}.bin".format(self.texname)][i] = frame
        item = window.framesheetmodel.itemFromIndex(window.framesheetList.currentIndex())
        icon = item.icon()
        pixmap = icon.pixmap(icon.availableSizes()[0])

        painter = QtGui.QPainter(pixmap)
        painter.drawPixmap(0, 32*i, frame)
        painter.end()
        del painter

        image = pixmap.toImage().convertToFormat(QtGui.QImage.Format_ARGB32);
        data = RGB4A3FramesheetEncode(image)
        Tileset.animdata["BG_tex/{0}.bin".format(self.texname)] = data
        item.setIcon(QtGui.QIcon(pixmap))

        self.table.cellWidget(i, 0).setPixmap(frame)

        window.framesheetList.update()
        self.update()




    def play(self):
        while True:
            try:
                duration = 0
                framenum = 0
                if self.checkBox.isChecked():
                    for i, image in reversed(list(enumerate(window.frames["BG_tex/{0}.bin".format(self.texname)]))):
                        self.previewLabel.setPixmap(image)
                        delay = self.table.cellWidget(i, 1).value()
                        time.sleep(delay / 60)
                        duration += delay
                        framenum += 1
                else:
                    for i, image in enumerate(window.frames["BG_tex/{0}.bin".format(self.texname)]):
                        self.previewLabel.setPixmap(image)
                        delay = self.table.cellWidget(i, 1).value()
                        time.sleep(delay / 60)
                        duration += delay
                        framenum += 1
            except:
                self.previewLabel.setPixmap(QtGui.QPixmap())
                time.sleep(2)


    def setTilenum(self, val):
        val = (self.spin1.value()<<8)+(self.spin2.value()<<4)+(self.spin3.value())
        self.tilenumLabel.setText(str(val))
        self.list.setItemText(self.list.currentIndex(), "Tilenum: {}, Reversed: {}".format(val, self.checkBox.isChecked()))
        self.saveChanges()


    def setupContainer(self, data = None):
        if data is None:
            self.nameLabel.setText("")
            self.delayLabel.setText("0")
            self.tilenumLabel.setText("0")
            self.spin1.setRange(0, 0)
            self.spin2.setRange(0, 0)
            self.spin3.setRange(0, 0)
            self.checkBox.setChecked(False)
            self.checkBox.setEnabled(False)
            self.table.setEnabled(False)
            try:
                i = 0
                while i < self.table.rowCount():
                    self.table.cellWidget(i, 1).setValue(1)
                    i += 1
            except:
                print("No cellWidgets (you can ignore this message)")

        else:
            self.nameLabel.setText(data['texname'])
            self.delayLabel.setText("{0}".format(len(data['framedelays'])))
            self.spin1.setRange(0, 3)
            self.spin2.setRange(0, 0xF)
            self.spin3.setRange(0, 0xF)
            self.spin1.setValue(data['tilenum']>>8&0xF)
            self.spin2.setValue(data['tilenum']>>4&0xF)
            self.spin3.setValue(data['tilenum']&0xF)
            self.checkBox.setEnabled(True)
            self.table.setEnabled(True)
            if 'reverse' in data:
                self.checkBox.setChecked(data['reverse'])
            else:
                self.checkBox.setChecked(False)



    def importInfo(self):
        self.popup = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout()
        self.btn1 = QtWidgets.QPushButton("Import from AnimTiles tab")
        self.btn1.released.connect(self.fromAnimTiles)

        self.btn2 = QtWidgets.QPushButton("Import from a .txt file")
        self.btn2.released.connect(self.fromTxt)

        self.info = QtWidgets.QLabel("Importing from the AnimTiles tab imports all entries with a matching texname.\n\nIt removes those entries from the AnimTiles tab!\n\nSo: don't forget to export after you finished editing!!!")
        self.info.setWordWrap(True)

        layout.addWidget(self.btn1, 0, 0, 1, 1)
        layout.addWidget(self.btn2, 0, 1, 1, 1)
        layout.addWidget(self.info, 1, 0, 1, 2)

        self.popup.setLayout(layout)
        self.popup.setWindowTitle("Import framesheet info")
        self.popup.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        self.popup.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.popup.show()


    def exportInfo(self):
        self.popup = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout()
        self.btn1 = QtWidgets.QPushButton("Export to AnimTiles tab")
        self.btn1.clicked.connect(self.toAnimTiles)

        self.btn2 = QtWidgets.QPushButton("Export to a .txt file")
        self.btn2.clicked.connect(self.toTxt)

        self.info = QtWidgets.QLabel("Exporting to the AnimTiles tab exports all entries of this tab.\n\nIt doesn't remove or overwrite entries of the AnimTiles tab!\n\nSo: don't forget to check for duplicates in the AnimTiles tab!!!")
        self.info.setWordWrap(True)

        layout.addWidget(self.btn1, 0, 0, 1, 1)
        layout.addWidget(self.btn2, 0, 1, 1, 1)
        layout.addWidget(self.info, 1, 0, 1, 2)

        self.popup.setLayout(layout)
        self.popup.setWindowTitle("Export framesheet info")
        self.popup.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        self.popup.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.popup.show()


    def fromAnimTiles(self):
        global AnimTiles
        global frameEditorData
        self.popup.hide()

        i = 0
        while i < window.framesheetmodel.rowCount():
            item = window.framesheetmodel.itemFromIndex(window.framesheetmodel.index(i, 0))
            texname = item.text()
            framenum = len(Tileset.animdata["BG_tex/{0}.bin".format(texname)])//2048
            if texname in frameEditorData.animations:
                frameEditorData.animations[texname].extend(getAllEntriesWithName(AnimTiles, texname, framenum, removeFromAnimations=True))
            else:
                frameEditorData.animations[texname] = getAllEntriesWithName(AnimTiles, texname, framenum, removeFromAnimations=True)
            i += 1

        window.animTilesEditor.text.setPlainText(animationsToText(AnimTiles))
        self.setFramesheet(3)


    def toAnimTiles(self):
        global AnimTiles
        global frameEditorData
        self.popup.hide()

        for entry in frameEditorData.animations.values():
            AnimTiles.animations.extend(entry)

        window.animTilesEditor.text.setPlainText(animationsToText(AnimTiles))
        frameEditorData.animations = {}
        self.setFramesheet(3)


    def fromTxt(self):
        self.popup.hide()

        path = QtWidgets.QFileDialog.getOpenFileName(self, "Open AnimTiles .txt file", window.animTilesTXTDialoguePath, "AnimTiles File (*.txt)")[0]
        if not path: return

        temp = type('frameEditorClass', (), {})()
        temp.animations = {}

        with open(path, 'r') as file:
            txt = file.read()

        addAnimationsFromText(temp, txt)

        i = 0
        while i < window.framesheetmodel.rowCount():
            item = window.framesheetmodel.itemFromIndex(window.framesheetmodel.index(i, 0))
            texname = item.text()
            framenum = len(Tileset.animdata["BG_tex/{0}.bin".format(texname)])//2048
            if texname in frameEditorData.animations:
                frameEditorData.animations[texname].extend(getAllEntriesWithName(temp, texname, framenum, removeFromAnimations=True))
            else:
                frameEditorData.animations[texname] = getAllEntriesWithName(temp, texname, framenum, removeFromAnimations=True)
            i += 1

        self.setFramesheet(3)

        if len(temp.animations) > 0:
            text = animationsToText(temp)
            msgBox = QtWidgets.QMessageBox()
            msgBox.setWindowTitle("Info")
            msgBox.setText("Some framesheet infos weren't imported as there were no matching framesheets!")
            msgBox.setInformativeText("Do you want to save the remaining framesheet information in a new .txt file?")
            msgBox.setStandardButtons(QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard)
            msgBox.setDefaultButton(QtWidgets.QMessageBox.Save)
            msgBox.setDetailedText(text)
            ret = msgBox.exec()
            if ret == QtWidgets.QMessageBox.Save:
                fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Save AnimTiles .txt file', window.animTilesTXTDialoguePath, 'AnimTiles File (*.txt)')[0]
                if not fn: return

                with open(fn, 'w') as f:
                    f.write(text)


    def toTxt(self):
        global frameEditorData
        self.popup.hide()

        fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Save AnimTiles .txt file', window.animTilesTXTDialoguePath, 'AnimTiles File (*.txt)')[0]
        if not fn: return

        temp = type('animTilesTemp', (), {})()
        temp.animations = []

        for entry in frameEditorData.animations.values():
            temp.animations.extend(entry)

        text = animationsToText(temp)

        with open(fn, 'w') as f:
            f.write(text)


    def setFramesheet(self, tabIndex):
        if not tabIndex == 3:
            return

        index = window.framesheetList.currentIndex()
        if not index.isValid():
            self.setEnabled(False)
            self.table.setRowCount(0)
            return
        else:
            self.setEnabled(True)

        global AnimTiles
        global frameEditorData

        self.texname = window.framesheetmodel.itemFromIndex(index).text()

        self.framenum = len(Tileset.animdata["BG_tex/{0}.bin".format(self.texname)])//2048
        self.table.setRowCount(self.framenum)

        for i, image in enumerate(window.frames["BG_tex/{0}.bin".format(self.texname)]):
            self.label = QtWidgets.QLabel(self)
            self.label.setPixmap(image)
            self.label.setAlignment(Qt.AlignCenter)
            self.table.setCellWidget(i, 0, self.label)

            self.spinBox = QtWidgets.QSpinBox(self)
            self.spinBox.setRange(1, 255)
            self.spinBox.setStyleSheet( "QSpinBox"
                                        "{"
                                        "border : 0px solid black;"
                                        "}"
                                        )
            self.spinBox.valueChanged.connect(self.saveChanges)
            self.table.setCellWidget(i, 1, self.spinBox)



        #print(window.frames)

        if self.texname in frameEditorData.animations:
            self.opened = frameEditorData.animations[self.texname]
        else:
            self.opened = []
        #print(self.opened)


        self.setupComboBox()


    def saveChanges(self):
        try:
            entry = {}
            entry['tilenum'] = (self.spin1.value()<<8)+(self.spin2.value()<<4)+(self.spin3.value())
            entry['tileset'] = self.spin1.value()                                                   #???
            entry['reverse'] = self.checkBox.isChecked()
            framedelays = []
            i = 0
            while i < self.table.rowCount():
                framedelays.append(self.table.cellWidget(i, 1).value())
                i += 1
            entry['framedelays'] = framedelays

            index = window.framesheetList.currentIndex()
            texname = window.framesheetmodel.itemFromIndex(index).text()
            entry['texname'] = "{}.bin".format(texname)

            self.opened[self.list.currentIndex()] = entry
            frameEditorData.animations[texname] = self.opened

        except:
            print("Eventually something went wrong here ... not sure though ...")


    def setEnabled(self, enabled):
        self.list.setVisible(enabled)
        self.delete.setVisible(enabled)
        self.explanation.setVisible(not enabled)
        self.importFramesheet.setEnabled(enabled)
        self.exportFramesheet.setEnabled(enabled)
        if not enabled:
            self.table.clearContents()
            self.setupContainer()
        self.table.setEnabled(enabled)


    def setupComboBox(self):
        self.list.clear()
        if not len(self.opened) == 0:
            for dict in self.opened:
                self.list.addItem("Tilenum: {}, Reversed: {}".format(dict['tilenum'], dict['reverse']))

        self.list.addItem("New ...")

        if self.list.count() <= 1:
            self.list.setCurrentIndex(-1)
            self.setupContainer()
        else:
            self.setContents(self.list.currentIndex())


    def setContents(self, index):
        #print(self.list.count())
        if index == -1: return
        if self.list.count()-1 == index:    #create new info
            animation = {}
            animation['texname'] = "{}.bin".format(self.texname)
            animation['tilenum'] = 0
            animation['framedelays'] = [0] * self.framenum
            animation['reverse'] = False
            self.opened.append(animation)
            self.setupContainer(animation)
            self.list.setCurrentIndex(-1)
            self.setupComboBox()
            self.saveChanges()
        else:                               #open selected info
            if self.opened:
                animation = self.opened[index]
                self.setupContainer(animation)
                for i, delay in enumerate(animation['framedelays']):
                    self.table.cellWidget(i, 1).setValue(delay)
            #self.setupComboBox()


    def deleteCurrentlySelectedEntry(self):
        if len(self.opened) > self.list.currentIndex() and not self.list.currentIndex() == -1:
            del self.opened[self.list.currentIndex()]
            self.setupComboBox()


#############################################################################################
#################################### randTiles Widget #######################################


class randTilesOverlord(QtWidgets.QWidget):
    global RandTiles
    
    def __init__(self):
        super(randTilesOverlord, self).__init__()

        self.isOpeningFile = False

        self.searchText = QtWidgets.QLineEdit()
        self.searchText.setPlaceholderText("Search ...")

        font = self.font()
        self.text = QCodeEditor.QCodeEditor(SyntaxHighlighter=QCodeEditor.XMLHighlighter)
        self.text.font = font

        self.importBin = QtWidgets.QPushButton('Import from .bin')
        self.importXml = QtWidgets.QPushButton('Import from .xml')
        self.exportBin = QtWidgets.QPushButton('Export to .bin')
        self.exportXml = QtWidgets.QPushButton('Export to .xml')

        self.exceptionLabel = QtWidgets.QLabel('Empty ...')

        # Connections
        self.searchText.textEdited.connect(self.updateHighlighter)
        
        self.importBin.released.connect(self.importFromBin)
        self.importXml.released.connect(self.importFromXml)
        self.exportBin.released.connect(self.exportToBin)
        self.exportXml.released.connect(self.exportToXml)

        self.text.textChanged.connect(self.updateAfterEdit)

        # Layout
        layout = QtWidgets.QGridLayout()

        layout.addWidget(self.searchText, 0, 0, 1, 4)

        layout.addWidget(self.text, 1, 0, 1, 4)

        layout.addWidget(self.exceptionLabel, 2, 0, 1, 4)

        layout.addWidget(self.importBin, 3, 0, 1, 1)
        layout.addWidget(self.importXml, 3, 1, 1, 1)
        layout.addWidget(self.exportBin, 3, 2, 1, 1)
        layout.addWidget(self.exportXml, 3, 3, 1, 1)

        layout.setRowMinimumHeight(1, 40)

        self.setLayout(layout)


    def updateHighlighter(self, text):
        self.text.highlighter.searchRules = [x for x in text.split(" ") if x]
        self.text.highlighter.rehighlight()


    def importFromBin(self, path=""):
        RandTiles.clear()

        self.isOpeningFile = True

        if not path:
            path = QtWidgets.QFileDialog.getOpenFileName(self, "Open RandTiles .bin file", window.randTilesBINDialoguePath, "RandTiles File (*.bin)")[0]
            if not path: return

        try:
            xml = addRandomizationsFromBinFile(RandTiles, path)
        except Exception as e:
            self.exceptionLabel.setText('Exception: {}'.format(str(e)))
            return
        
        self.text.setPlainText(xml)


    def importFromXml(self, path=""):
        self.isOpeningFile = True

        if not path:
            path = QtWidgets.QFileDialog.getOpenFileName(self, "Open RandTiles .xml file", window.randTilesXMLDialoguePath, "RandTiles File (*.xml)")[0]
            if not path: return

        with open(path, 'r') as file:
            xml = file.read()
        
        try:
            addRandomizationsFromXml(RandTiles, xml)
        except Exception as e:
            self.exceptionLabel.setText('Exception: {}'.format(str(e)))
            return

        self.text.setPlainText(xml)


    def updateAfterEdit(self):
        if self.isOpeningFile:
            self.isOpeningFile = False
        else:
            try:
                addRandomizationsFromXml(RandTiles, self.text.toPlainText())
                labelMessage = 'Current xml is valid!'
            except Exception as e:
                labelMessage = 'Exception: {}'.format(str(e))
                
            self.exceptionLabel.setText(labelMessage)

    def exportToBin(self):
        fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Save RandTiles .bin file', window.randTilesBINDialoguePath, 'RandTiles File (*.bin)')[0]
        if not fn: return

        encodeRandTiles(RandTiles)

        with open(fn, 'wb') as f:
            f.write(RandTiles.bin)


    def exportToXml(self):
        fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Save RandTiles .xml file', window.randTilesXMLDialoguePath, 'RandTiles File (*.xml)')[0]
        if not fn: return

        with open(fn, 'w') as f:
            f.write(self.text.toPlainText())


#############################################################################################
################################### RandTiles functions #####################################


def addRandomizationsFromBinFile(dest, bin):
    with open(bin, 'rb') as f:
        bin_ = f.read()

    header = struct.unpack('>4sI', bin_[:8])

    if header[0] != b'NwRT':
        raise ValueError("Invalid .bin file: file magic was not NwRT")

    pos = 8
    for i in range(header[1]):
        offset = struct.unpack('>I', bin_[pos : pos + 4])[0]
        pos += 4
        section = struct.unpack('>2I', bin_[offset : offset + 8])
        nameListOffset = section[0]
        nameCount = struct.unpack('>I', bin_[offset + nameListOffset : offset + 4 + nameListOffset])[0]
        nameList = []
        for j in range(nameCount):
            nameOffset = struct.unpack('>I', bin_[offset + nameListOffset + 4 + 4*j : offset + nameListOffset + 8 + 4*j])[0]
            end = bin_[offset + nameListOffset + nameOffset :]
            name = str(struct.unpack('>' + str(len(end)) + 's', end)[0]).split('\\x00', 1)[0]
            nameList.append(name[2:])

        entries = []
        entryCount = section[1]
        for j in range(entryCount):
            entry = struct.unpack('>BBBBI', bin_[offset + 8 + 8*j : offset + 16 + 8 * j])
            count = entry[2]
            tileNumOffset = entry[4]
            tiles = list(struct.unpack('>' + str(count) + 'B', bin_[offset + 8 + 8*j + tileNumOffset : offset + 8 + 8*j + tileNumOffset + count]))
            entries.append({'lowerBound' :  entry[0], 'upperBound' : entry[1], 'type' : entry[3] & 3, 'special' : entry[3] >> 2, 'tiles' : tiles})

        dest.sections.append({'nameList' : nameList, 'entries' : entries})

    types = ['none', 'horizontal', 'vertical', 'both']
    specials = [None, 'double-top', 'double-bottom']

    out = '<tilesets>\n'
    for section in dest.sections:
        out += '    <group names="' + ', '.join(section['nameList']) + '">\n'
        for entry in section['entries']:
            line = '        <random '
            if list(range(entry['lowerBound'], entry['upperBound'] + 1)) == entry['tiles']:
                line += 'range="0x%X, 0x%X" ' % (entry['lowerBound'], entry['upperBound'])
            #elif -> optimize xml
            else:
                if entry['lowerBound'] == entry['upperBound']:
                    line += 'list="0x%X" ' % (entry['lowerBound'])
                else:
                    line += 'range="0x%X, 0x%X" ' % (entry['lowerBound'], entry['upperBound'])
                tiles = ["0x%X" % tile for tile in entry['tiles']]
                line += 'values="{}" '.format(', '.join(tiles))
            line += 'direction="{}" '.format(types[entry['type']])
            if entry['special'] != 0:
                line += 'special="{}" '.format(specials[entry['special']])
            line += '/>\n'
            out += line

        out += '    </group>\n'

    out += '</tilesets>'

    return out


def randomToEntry(entries, var, numbers, direction, special):
    if isinstance(var, range):
        # Regular handling
        if numbers is None:
            numbers = var
        entries.append({'lowerBound' :  min(var), 'upperBound' : max(var), 'type' : direction , 'special' : special, 'tiles' : list(numbers)})
    elif isinstance(var, int):
        # One number
        randomToEntry(entries, range(var, var+1), numbers, direction, special)
    elif isinstance(var, list):
        # A list
        if numbers is None:
            numbers = var
        for r in var:
            randomToEntry(entries, r, numbers, direction, special)


def addRandomizationsFromXml(dest, xml):
    root = etree.fromstring(xml)
    
    sections = []
    for group in root:
        nameList = []
        for name in group.attrib['names'].split(","):
            nameList.append(name.strip())
        
        entries = []
        for random in group:
            entry = {}
            if 'name' in random.attrib:
                name = random.attrib['name']
                if name == 'regular-terrain':
                    entries.append({'lowerBound': 16, 'upperBound': 16, 'type': 2, 'special': 0, 'tiles': [16, 32, 48, 64]})
                    entries.append({'lowerBound': 32, 'upperBound': 32, 'type': 2, 'special': 0, 'tiles': [16, 32, 48, 64]})
                    entries.append({'lowerBound': 48, 'upperBound': 48, 'type': 2, 'special': 0, 'tiles': [16, 32, 48, 64]})
                    entries.append({'lowerBound': 64, 'upperBound': 64, 'type': 2, 'special': 0, 'tiles': [16, 32, 48, 64]})
                    entries.append({'lowerBound': 17, 'upperBound': 17, 'type': 2, 'special': 0, 'tiles': [17, 33, 49, 65]})
                    entries.append({'lowerBound': 33, 'upperBound': 33, 'type': 2, 'special': 0, 'tiles': [17, 33, 49, 65]})
                    entries.append({'lowerBound': 49, 'upperBound': 49, 'type': 2, 'special': 0, 'tiles': [17, 33, 49, 65]})
                    entries.append({'lowerBound': 65, 'upperBound': 65, 'type': 2, 'special': 0, 'tiles': [17, 33, 49, 65]})
                    entries.append({'lowerBound': 2, 'upperBound': 7, 'type': 1, 'special': 0, 'tiles': [2, 3, 4, 5, 6, 7]})
                    entries.append({'lowerBound': 34, 'upperBound': 39, 'type': 1, 'special': 0, 'tiles': [34, 35, 36, 37, 38, 39]})
                    entries.append({'lowerBound': 18, 'upperBound': 23, 'type': 3, 'special': 0, 'tiles': [18, 19, 20, 21, 22, 23]})
                elif name == 'sub-terrain':
                    entries.append({'lowerBound': 24, 'upperBound': 24, 'type': 2, 'special': 0, 'tiles': [24, 40, 56, 72]})
                    entries.append({'lowerBound': 40, 'upperBound': 40, 'type': 2, 'special': 0, 'tiles': [24, 40, 56, 72]})
                    entries.append({'lowerBound': 56, 'upperBound': 56, 'type': 2, 'special': 0, 'tiles': [24, 40, 56, 72]})
                    entries.append({'lowerBound': 72, 'upperBound': 72, 'type': 2, 'special': 0, 'tiles': [24, 40, 56, 72]})
                    entries.append({'lowerBound': 25, 'upperBound': 25, 'type': 2, 'special': 0, 'tiles': [25, 41, 57, 73]})
                    entries.append({'lowerBound': 41, 'upperBound': 41, 'type': 2, 'special': 0, 'tiles': [25, 41, 57, 73]})
                    entries.append({'lowerBound': 57, 'upperBound': 57, 'type': 2, 'special': 0, 'tiles': [25, 41, 57, 73]})
                    entries.append({'lowerBound': 73, 'upperBound': 73, 'type': 2, 'special': 0, 'tiles': [25, 41, 57, 73]})
                    entries.append({'lowerBound': 10, 'upperBound': 15, 'type': 1, 'special': 0, 'tiles': [10, 11, 12, 13, 14, 15]})
                    entries.append({'lowerBound': 42, 'upperBound': 47, 'type': 1, 'special': 0, 'tiles': [42, 43, 44, 45, 46, 47]})
                    entries.append({'lowerBound': 26, 'upperBound': 31, 'type': 3, 'special': 0, 'tiles': [26, 27, 28, 29, 30, 31]})
                else:
                    raise ValueError("The attribute name has to be 'regular-terrain' or 'sub-terrain'!")
                continue

            # [list | range] = input space
            if 'list' in random.attrib:
                list_ = list(map(lambda s: int(s, 0), random.attrib['list'].split(",")))
            else:
                numbers = random.attrib['range'].split(",")

                # inclusive range
                list_ = range(int(numbers[0], 0), int(numbers[1], 0) + 1)

            # values = output space [= [list | range] by default]
            if 'values' in random.attrib:
                values = list(map(lambda s: int(s, 0), random.attrib['values'].split(",")))
            else:
                values = None

            direction = 0
            if 'direction' in random.attrib:
                direction_s = random.attrib['direction']
                if direction_s in ['horizontal', 'both']:
                    direction |= 0b01
                if direction_s in ['vertical', 'both']:
                    direction |= 0b10
            else:
                direction = 0b11

            special = 0
            if 'special' in random.attrib:
                special_s = random.attrib['special']
                if special_s == 'double-top':
                    special = 0b01
                elif special_s == 'double-bottom':
                    special = 0b10

            randomToEntry(entries, list_, values, direction, special)

        sections.append({'nameList' : nameList, 'entries' : entries})

    dest.sections = sections


def unique(original):
    unique = []
    [unique.append(obj) for obj in original if obj not in unique]
    return unique


def encodeRandTiles(dest):
    currentOffset = 8 + len(dest.sections) * 4
    allEntryData = []

    for section in dest.sections:
        section['offset'] = currentOffset
        currentOffset += 8

        for entry in section['entries']:
            entry['offset'] = currentOffset
            allEntryData.append(entry['tiles'])
            currentOffset += 8

    nameListOffsets = {}
    for section in dest.sections:
        nameListOffsets[str(section['nameList'])] = currentOffset
        currentOffset += 4 + (4 * len(section['nameList']))

    dataOffsets = {}
    allEntryData = unique(allEntryData)

    for data in allEntryData:
        dataOffsets[str(data)] = currentOffset
        currentOffset += len(data)

    nameOffsets = {}
    for section in dest.sections:
        for name in section['nameList']:
            nameOffsets[name] = currentOffset
            currentOffset += len(name) + 1

    header = struct.pack('>4sI', b'NwRT', len(dest.sections))
    offsets = b''
    for section in dest.sections:
        offsets += struct.pack('>I', section['offset'])

    def getSectionData(section):
        nameListOffset = nameListOffsets[str(section['nameList'])] - section['offset']

        entryCount = len(section['entries'])

        entryData = b''
        for entry in section['entries']:
            lowerBound = entry['lowerBound']
            upperBound = entry['upperBound']

            count = len(entry['tiles'])

            type = entry['type'] | (entry['special'] << 2)

            numOffset = dataOffsets[str(entry['tiles'])] - entry['offset']

            entryData += struct.pack('>BBBBI', lowerBound, upperBound, count, type, numOffset)

        return struct.pack('>II', nameListOffset, entryCount) + entryData

    def getnameListData(section):
        count = struct.pack('>I', len(section['nameList']))
        cOffsets = b''
        for name in section['nameList']:
            cOffsets += struct.pack('>I', nameOffsets[name] - nameListOffsets[str(section['nameList'])])

        return count + cOffsets

    sectionData = []
    nameListData = []
    for section in dest.sections:
        sectionData.append(getSectionData(section))
        nameListData.append(getnameListData(section))

    output = [header, offsets]
    output += sectionData
    output += nameListData
    for entryData in allEntryData:
        output += [bytes(entryData)]

    for section in dest.sections:
        output += [bytes('\0'.join(section['nameList']), 'utf-8')]
        output += [b'\x00']

    # and save the result
    dest.bin = b''.join(output)#out#dest.bin = out + bytes(strTable, 'utf8')


#############################################################################################
#################################### animTiles Widget #######################################


class animTilesOverlord(QtWidgets.QWidget):

    def __init__(self):
        super(animTilesOverlord, self).__init__()

        self.searchText = QtWidgets.QLineEdit()
        self.searchText.setPlaceholderText("Search ...")

        self.text = QCodeEditor.QCodeEditor(SyntaxHighlighter=QCodeEditor.SearchHighlighter)

        self.importBin = QtWidgets.QPushButton('Import from .bin')
        self.importTxt = QtWidgets.QPushButton('Import from .txt')
        self.exportBin = QtWidgets.QPushButton('Export to .bin')
        self.exportTxt = QtWidgets.QPushButton('Export to .txt')


        # Connections
        self.searchText.textEdited.connect(self.updateHighlighter)

        self.importBin.released.connect(self.importFromBin)
        self.importTxt.released.connect(self.importFromTxt)
        self.exportBin.released.connect(self.exportToBin)
        self.exportTxt.released.connect(self.exportToTxt)

        self.text.textChanged.connect(self.updateAfterEdit)

        # Layout
        layout = QtWidgets.QGridLayout()

        layout.addWidget(self.searchText, 0, 0, 1, 4)

        layout.addWidget(self.text, 1, 0, 1, 4)

        layout.addWidget(self.importBin, 2, 0, 1, 1)
        layout.addWidget(self.importTxt, 2, 1, 1, 1)
        layout.addWidget(self.exportBin, 2, 2, 1, 1)
        layout.addWidget(self.exportTxt, 2, 3, 1, 1)

        layout.setRowMinimumHeight(1, 40)

        self.setLayout(layout)


    def updateHighlighter(self, text):
        self.text.highlighter.searchRules = [x for x in text.split(" ") if x]
        self.text.highlighter.rehighlight()


    def importFromBin(self, path=""):
        global AnimTiles
        AnimTiles.clear()

        if not path:
            path = QtWidgets.QFileDialog.getOpenFileName(self, "Open AnimTiles .bin file", window.animTilesBINDialoguePath, "AnimTiles File (*.bin)")[0]
            if not path: return

        addAnimationsFromBinFile(AnimTiles, path)
        txt = animationsToText(AnimTiles)

        self.text.setPlainText(txt)


    def importFromTxt(self, path=""):
        global AnimTiles
        AnimTiles.clear()

        if not path:
            path = QtWidgets.QFileDialog.getOpenFileName(self, "Open AnimTiles .txt file", window.animTilesTXTDialoguePath, "AnimTiles File (*.txt)")[0]
            if not path: return

        with open(path, 'r') as file:
            txt = file.read()

        addAnimationsFromText(AnimTiles, txt)

        with open(path, 'r') as file:
            txt = file.read()

        self.text.setPlainText(txt)


    def exportToBin(self):
        global AnimTiles

        fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Save AnimTiles .bin file', window.animTilesBINDialoguePath, 'AnimTiles File (*.bin)')[0]
        if not fn: return

        encodeAnimTiles(AnimTiles)

        with open(fn, 'wb') as f:
            f.write(AnimTiles.bin)


    def exportToTxt(self):
        fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Save AnimTiles .txt file', window.animTilesTXTDialoguePath, 'AnimTiles File (*.txt)')[0]
        if not fn: return

        with open(fn, 'w') as f:
            f.write(self.text.toPlainText())


    def updateAfterEdit(self):
        try:
            addAnimationsFromText(AnimTiles, self.text.toPlainText())
        except Exception as e:
            print('Exception: {}'.format(str(e)))


#############################################################################################
################################### AnimTiles functions #####################################


def addAnimationsFromBinFile(dest, bin):

    with open(bin, 'rb') as f:
        bin_ = f.read()

    header = struct.unpack('>4sI', bin_[:8])

    if header[0] != b'NWRa':
        print("Error: invalid .bin file: file magic was not NWRa")

    pos = 8
    for i in range(header[1]):
        # read entry
        entry = struct.unpack('>HHHBB', bin_[pos : pos + 8])
        pos += 8

        # extract name
        name = readString(bin_, entry[0])

        # extract delays
        delays = readNullTerminated(bin_, entry[1])
        delays = list(map(int, delays))

        # tilenum
        tilenum = int(entry[2])
        tileset = int(entry[3])
        reverse = int(entry[4]) == 1

        dest.addAnimation({
            'texname': name,
            'framedelays': delays,
            'tilenum': tilenum,
            'tileset': tileset,
            'reverse': reverse
        })


def animationsToText(dest):
    # write output file
    properties = ['texname', 'framedelays', 'tilenum', 'tileset', 'reverse']
    out = ""
    for animation in dest.animations:
        for prop in properties:
            if prop == 'reverse':
                if animation[prop] == True:
                    out += 'reverse = yes\n'
                continue

            elif prop == 'framedelays':
                s = ', '.join(map(str, animation[prop]))
            else:
                s = str(animation[prop])

            out += "%s = %s\n" % (str(prop), s)

        out += '\nend tile\n\n'

    # remove 1 extra newline
    out = out[:-1]
    return out


def encodeAnimTiles(dest):
    out = struct.pack('>4sI', b'NWRa', len(dest.animations))

    # first off, calculate a length for the main file
    # so we can build the string table easily
    size = len(out)
    size += len(dest.animations) * 8

    strTable = b''
    strOffset = size + len(strTable)

    # now, write tiles
    for animation in dest.animations:
        # encode the name
        texNameOffset = strOffset

        # there's only room for 56 characters
        name = animation['texname']
        if len(name) > 56:
            name = name[:56]

        strTable += bytes(name + '\0', 'utf8')
        strOffset += len(name) + 1

        # encode the delays
        frameDelays = b''
        for delay in animation['framedelays']:
            if delay >= 256:                    # max possible delay
                frameDelays += bytes([255])
                print("A framedelay had to be decreased to the maximum of 255!")
            else:
                frameDelays += bytes([delay])

        frameDelayOffset = strOffset
        strOffset += len(frameDelays) + 1
        strTable += frameDelays + b'\x00'

        tileNum = animation['tilenum']
        tilesetNum = animation['tileset']

        if 'reverse' in animation and animation['reverse']:
            reverse = 1
        else:
            reverse = 0

        out += struct.pack('>HHHBB', texNameOffset, frameDelayOffset, tileNum, tilesetNum, reverse)

    # and save the result
    dest.bin = out + strTable


def addAnimationsFromText(dest, txt):
    # strip whitespace
    lines = txt.split("\n")
    proc = []
    for line in lines:
        proc.append(line.strip())

    # dest.animations is an array of dicts
    animations = []
    currentAnimation = {}

    # parse the file
    for line in proc:
        if line == 'end tile':
            animations.append(currentAnimation)
            currentAnimation = {}
        elif line != '':
            s = line.split('=', 2)
            name = s[0].strip()
            val = s[1].strip()

            if name == 'framedelays': val = list(map(int, val.split(',')))
            if name == 'tilenum': val = int(val, 0)
            if name == 'tileset': val = int(val, 0)
            if name == 'reverse':
                if val == 'yes':
                    val = True
                else:
                    val = False

            currentAnimation[name] = val

        if not 'reverse' in currentAnimation:
            currentAnimation['reverse'] = False

        dest.animations = animations


def getAllEntriesWithName(dest, name, frames, removeFromAnimations=False):
    results = []
    if removeFromAnimations:
        newAnimations = []
    for animation in dest.animations:
        if animation['texname'] == "{}.bin".format(name) and len(animation['framedelays']) == frames:
            results.append(animation)
        elif removeFromAnimations:
            newAnimations.append(animation)
    if removeFromAnimations:
        dest.animations = newAnimations
    return results


#############################################################################################
##################### Object List Widget and Model Setup with Painter #######################


class objectList(QtWidgets.QListView):

    def __init__(self, parent=None):
        super(objectList, self).__init__(parent)

        self.noneIdx = self.currentIndex()

        self.setIconSize(QtCore.QSize(10000, 10000))
        self.setUniformItemSizes(False)
        self.setBackgroundRole(QtGui.QPalette.BrightText)
        self.setWrapping(False)
        self.setMinimumWidth(300)
        self.setMaximumWidth(300)

    def setHeight(self):
        height = getObjectMaxSize()
        self.setIconSize(QtCore.QSize(32, height))
        #self.setGridSize(QtCore.QSize(200,height+50))

    def clearCurrentIndex(self):
        self.setCurrentIndex(self.noneIdx)


def getObjectMaxSize():
    global Tileset
    max = 0
    for key in list(Tileset.animdata.keys()):
        t = len(Tileset.animdata[key])//64
        if t > max:
            max = t
    return max


def SetupObjectModel(self, objects, tiles):
    global Tileset
    self.clear()

    count = 0
    for object in objects:
        tex = QtGui.QPixmap(object.width * 24, object.height * 24)
        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        Xoffset = 0
        Yoffset = 0

        for i in range(len(object.tiles)):
            for tile in object.tiles[i]:
                if Tileset.slot == (tile[2] & 3):
                    painter.drawPixmap(Xoffset, Yoffset, tiles[tile[1]].image)
                Xoffset += 24
            Xoffset = 0
            Yoffset += 24

        painter.end()

        item = QtGui.QStandardItem(QtGui.QIcon(tex), 'Object {0}'.format(count))
        item.setEditable(False)
        self.appendRow(item)

        count += 1


#############################################################################################
######################## List Widget with custom painter/MouseEvent #########################


class displayWidget(QtWidgets.QListView):

    mouseMoved = QtCoreSignal(int, int)

    def __init__(self, parent=None):
        super(displayWidget, self).__init__(parent)

        self.setMinimumWidth(403)
        self.setMaximumWidth(403)
        self.setMinimumHeight(403)
        self.setMaximumHeight(403)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragEnabled(True)
        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setIconSize(QtCore.QSize(24,24))
        self.setGridSize(QtCore.QSize(25,25))
        self.setMovement(QtWidgets.QListView.Static)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(True)
        self.setResizeMode(QtWidgets.QListView.Adjust)
        self.setUniformItemSizes(True)
        self.setBackgroundRole(QtGui.QPalette.BrightText)
        self.setMouseTracking(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

        self.setItemDelegate(self.TileItemDelegate())


    def mouseMoveEvent(self, event):
        QtWidgets.QWidget.mouseMoveEvent(self, event)

        self.mouseMoved.emit(event.x(), event.y())


    class TileItemDelegate(QtWidgets.QAbstractItemDelegate):
        """Handles tiles and their rendering"""

        def __init__(self):
            """Initialises the delegate"""
            QtWidgets.QAbstractItemDelegate.__init__(self)

        def paint(self, painter, option, index):
            """Paints an object"""

            global Tileset
            p = index.model().data(index, Qt.DecorationRole)
            painter.drawPixmap(option.rect.x(), option.rect.y(), p.pixmap(24,24))

            x = option.rect.x()
            y = option.rect.y()


            # Collision Overlays
            info = window.infoDisplay
            if index.row() >= len(Tileset.tiles): return
            curTile = Tileset.tiles[index.row()]

            if info.collisionOverlay.isChecked():
                path = os.path.dirname(os.path.abspath(sys.argv[0])) + '/Icons/'

                # Sets the colour based on terrain type
                if curTile.byte2 & 16:      # Red
                    colour = QtGui.QColor(255, 0, 0, 120)
                elif curTile.byte5 == 1:    # Ice
                    colour = QtGui.QColor(0, 0, 255, 120)
                elif curTile.byte5 == 2:    # Snow
                    colour = QtGui.QColor(0, 0, 255, 120)
                elif curTile.byte5 == 3:    # Quicksand
                    colour = QtGui.QColor(128,64,0, 120)
                elif curTile.byte5 == 4:    # Conveyor
                    colour = QtGui.QColor(128,128,128, 120)
                elif curTile.byte5 == 5:    # Conveyor
                    colour = QtGui.QColor(128,128,128, 120)
                elif curTile.byte5 == 6:    # Rope
                    colour = QtGui.QColor(128,0,255, 120)
                elif curTile.byte5 == 7:    # Half Spike
                    colour = QtGui.QColor(128,0,255, 120)
                elif curTile.byte5 == 8:    # Ledge
                    colour = QtGui.QColor(128,0,255, 120)
                elif curTile.byte5 == 9:    # Ladder
                    colour = QtGui.QColor(128,0,255, 120)
                elif curTile.byte5 == 10:    # Staircase
                    colour = QtGui.QColor(255, 0, 0, 120)
                elif curTile.byte5 == 11:    # Carpet
                    colour = QtGui.QColor(255, 0, 0, 120)
                elif curTile.byte5 == 12:    # Dust
                    colour = QtGui.QColor(128,64,0, 120)
                elif curTile.byte5 == 13:    # Grass
                    colour = QtGui.QColor(0, 255, 0, 120)
                elif curTile.byte5 == 14:    # Unknown
                    colour = QtGui.QColor(255, 0, 0, 120)
                elif curTile.byte5 == 15:    # Beach Sand
                    colour = QtGui.QColor(128, 64, 0, 120)
                else:                       # Brown?
                    colour = QtGui.QColor(64, 30, 0, 120)


                # Sets Brush style for fills
                if curTile.byte2 & 4:        # Climbing Grid
                    style = Qt.DiagCrossPattern
                elif curTile.byte3 & 16:     # Breakable
                    style = Qt.VerPattern
                else:
                    style = Qt.SolidPattern


                brush = QtGui.QBrush(colour, style)
                painter.setBrush(brush)
                painter.setRenderHint(QtGui.QPainter.Antialiasing)


                # Paints shape based on other junk
                if curTile.byte3 & 32: # Slope
                    if curTile.byte7 == 0:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y)]))
                    elif curTile.byte7 == 1:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 2:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y + 12)]))
                    elif curTile.byte7 == 3:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x, y + 12),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 24)]))
                    elif curTile.byte7 == 4:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x + 24, y + 24)]))
                    elif curTile.byte7 == 5:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 12),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 10:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y)]))
                    elif curTile.byte7 == 11:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x + 24, y + 18),
                                                            QtCore.QPoint(x + 24, y + 24)]))
                    elif curTile.byte7 == 12:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x, y + 18),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 13:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y + 6),
                                                            QtCore.QPoint(x, y + 12),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 14:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x, y + 6),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 15:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y + 6),
                                                            QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 16:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x, y + 6),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 17:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y + 18),
                                                            QtCore.QPoint(x, y + 12),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 18:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x, y + 18),
                                                            QtCore.QPoint(x, y + 24)]))

                elif curTile.byte3 & 64: # Reverse Slope
                    if curTile.byte7 == 0:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y)]))
                    elif curTile.byte7 == 1:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y)]))
                    elif curTile.byte7 == 2:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y + 12)]))
                    elif curTile.byte7 == 3:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x, y + 12),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y)]))
                    elif curTile.byte7 == 4:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 12)]))
                    elif curTile.byte7 == 5:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 12),
                                                            QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y)]))
                    elif curTile.byte7 == 10:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y)]))
                    elif curTile.byte7 == 11:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 6)]))
                    elif curTile.byte7 == 12:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x, y + 6)]))
                    elif curTile.byte7 == 13:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 18),
                                                            QtCore.QPoint(x, y + 12)]))
                    elif curTile.byte7 == 14:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x, y + 18)]))
                    elif curTile.byte7 == 15:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 18),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 16:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x, y + 18)]))
                    elif curTile.byte7 == 17:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 6),
                                                            QtCore.QPoint(x, y + 12)]))
                    elif curTile.byte7 == 18:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x, y + 6)]))

                elif curTile.byte2 & 8: # Partial
                    if curTile.byte7 == 1:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 12, y),
                                                            QtCore.QPoint(x + 12, y + 12),
                                                            QtCore.QPoint(x, y + 12)]))
                    elif curTile.byte7 == 2:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 12, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x + 12, y + 12)]))
                    elif curTile.byte7 == 3:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x, y + 12)]))
                    elif curTile.byte7 == 4:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 12),
                                                            QtCore.QPoint(x + 12, y + 12),
                                                            QtCore.QPoint(x + 12, y + 24),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 5:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 12, y),
                                                            QtCore.QPoint(x + 12, y + 24),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 6:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x + 12, y + 24),
                                                            QtCore.QPoint(x + 12, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x, y + 12)]))
                    elif curTile.byte7 == 7:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x + 12, y + 12),
                                                            QtCore.QPoint(x + 12, y + 24),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 8:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 12, y + 12),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 12, y + 24)]))
                    elif curTile.byte7 == 9:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x, y + 12),
                                                            QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x + 12, y + 24),
                                                            QtCore.QPoint(x + 12, y)]))
                    elif curTile.byte7 == 10:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 12, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 12, y + 24)]))
                    elif curTile.byte7 == 11:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 12, y + 24),
                                                            QtCore.QPoint(x + 12, y + 12),
                                                            QtCore.QPoint(x, y + 12)]))
                    elif curTile.byte7 == 12:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 12),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 13:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 12, y),
                                                            QtCore.QPoint(x + 12, y + 12),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 14:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 12, y),
                                                            QtCore.QPoint(x + 12, y + 12),
                                                            QtCore.QPoint(x, y + 12),
                                                            QtCore.QPoint(x, y + 24)]))
                    elif curTile.byte7 == 15:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x, y + 24)]))

                elif curTile.byte2 & 0x40: # Solid-on-bottom
                    painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 24),
                                                        QtCore.QPoint(x + 24, y + 24),
                                                        QtCore.QPoint(x + 24, y + 18),
                                                        QtCore.QPoint(x, y + 18)]))

                    painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 15, y),
                                                        QtCore.QPoint(x + 15, y + 12),
                                                        QtCore.QPoint(x + 18, y + 12),
                                                        QtCore.QPoint(x + 12, y + 17),
                                                        QtCore.QPoint(x + 6, y + 12),
                                                        QtCore.QPoint(x + 9, y + 12),
                                                        QtCore.QPoint(x + 9, y)]))

                elif curTile.byte2 & 0x80: # Solid-on-top
                    painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                        QtCore.QPoint(x + 24, y),
                                                        QtCore.QPoint(x + 24, y + 6),
                                                        QtCore.QPoint(x, y + 6)]))

                    painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 15, y + 24),
                                                        QtCore.QPoint(x + 15, y + 12),
                                                        QtCore.QPoint(x + 18, y + 12),
                                                        QtCore.QPoint(x + 12, y + 7),
                                                        QtCore.QPoint(x + 6, y + 12),
                                                        QtCore.QPoint(x + 9, y + 12),
                                                        QtCore.QPoint(x + 9, y + 24)]))

                elif curTile.byte2 & 16: # Spikes
                    if curTile.byte7 == 0:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x, y + 6)]))
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 24, y + 12),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x, y + 18)]))
                    if curTile.byte7 == 1:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x, y + 12),
                                                            QtCore.QPoint(x + 24, y + 6)]))
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 12),
                                                            QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x + 24, y + 18)]))
                    if curTile.byte7 == 2:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y + 24),
                                                            QtCore.QPoint(x + 12, y + 24),
                                                            QtCore.QPoint(x + 6, y)]))
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 12, y + 24),
                                                            QtCore.QPoint(x + 24, y + 24),
                                                            QtCore.QPoint(x + 18, y)]))
                    if curTile.byte7 == 3:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 12, y),
                                                            QtCore.QPoint(x + 6, y + 24)]))
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 12, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 18, y + 24)]))
                    if curTile.byte7 == 4:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 18, y + 24),
                                                            QtCore.QPoint(x + 6, y + 24)]))
                    if curTile.byte7 == 5:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x + 6, y),
                                                            QtCore.QPoint(x + 18, y),
                                                            QtCore.QPoint(x + 12, y + 24)]))
                    if curTile.byte7 == 6:
                        painter.drawPolygon(QtGui.QPolygon([QtCore.QPoint(x, y),
                                                            QtCore.QPoint(x + 24, y),
                                                            QtCore.QPoint(x + 12, y + 24)]))

                elif curTile.byte3 & 2: # Coin
                    if curTile.byte7 == 0:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'Coin/Coin.png'))
                    if curTile.byte7 == 4:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'Coin/POW.png'))

                elif curTile.byte3 & 8: # Exploder
                    if curTile.byte7 == 1:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'Explode/Stone.png'))
                    if curTile.byte7 == 2:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'Explode/Wood.png'))
                    if curTile.byte7 == 3:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'Explode/Red.png'))

                elif curTile.byte1 & 2: # Falling
                    painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'Prop/Fall.png'))

                elif curTile.byte3 & 4: # QBlock
                    if curTile.byte7 == 0:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'QBlock/FireF.png'))
                    if curTile.byte7 == 1:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'QBlock/Star.png'))
                    if curTile.byte7 == 2:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'QBlock/Coin.png'))
                    if curTile.byte7 == 3:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'QBlock/Vine.png'))
                    if curTile.byte7 == 4:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'QBlock/1up.png'))
                    if curTile.byte7 == 5:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'QBlock/Mini.png'))
                    if curTile.byte7 == 6:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'QBlock/Prop.png'))
                    if curTile.byte7 == 7:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'QBlock/Peng.png'))
                    if curTile.byte7 == 8:
                        painter.drawPixmap(option.rect, QtGui.QPixmap(path + 'QBlock/IceF.png'))

                elif curTile.byte3 & 1: # Solid
                    painter.drawRect(option.rect)

                else: # No fill
                    pass


            # Highlight stuff.
            colour = option.palette.highlight().color()
            colour.setAlpha(80)

            if option.state & QtWidgets.QStyle.State_Selected:
                painter.fillRect(option.rect, colour)


        def sizeHint(self, option, index):
            """Returns the size for the object"""
            return QtCore.QSize(24,24)



#############################################################################################
############################ Tile widget for drag n'drop Objects ############################


class RepeatXModifiers(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setVisible(False)

        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0,0,0,0)

        self.spinboxes = []
        self.buttons = []

        self.updating = False


    def update(self):
        global Tileset

        index = window.objectList.currentIndex().row()
        if index < 0 or index >= len(Tileset.objects):
            return

        object = Tileset.objects[index]
        if not object.repeatX:
            return

        self.updating = True

        assert len(self.spinboxes) == len(self.buttons)

        height = object.height
        numRows = len(self.spinboxes)

        if numRows < height:
            for i in range(numRows, height):
                layout = QtWidgets.QHBoxLayout()
                layout.setSpacing(0)
                layout.setContentsMargins(0,0,0,0)

                spinbox1 = QtWidgets.QSpinBox()
                spinbox1.setFixedSize(50, 24)
                spinbox1.valueChanged.connect(lambda val, i=i: self.startValChanged(val, i))
                layout.addWidget(spinbox1)

                spinbox2 = QtWidgets.QSpinBox()
                spinbox2.setFixedSize(50, 24)
                spinbox2.valueChanged.connect(lambda val, i=i: self.endValChanged(val, i))
                layout.addWidget(spinbox2)

                button1 = QtWidgets.QPushButton('+')
                button1.setFixedSize(24, 24)
                button1.released.connect(lambda i=i: self.addTile(i))
                layout.addWidget(button1)

                button2 = QtWidgets.QPushButton('-')
                button2.setFixedSize(24, 24)
                button2.released.connect(lambda i=i: self.removeTile(i))
                layout.addWidget(button2)

                self.layout.addLayout(layout)
                self.spinboxes.append((spinbox1, spinbox2))
                self.buttons.append((button1, button2))

        elif height < numRows:
            for i in reversed(range(height, numRows)):
                layout = self.layout.itemAt(i).layout()
                self.layout.removeItem(layout)

                spinbox1, spinbox2 = self.spinboxes[i]
                layout.removeWidget(spinbox1)
                layout.removeWidget(spinbox2)

                spinbox1.setParent(None)
                spinbox2.setParent(None)

                del self.spinboxes[i]

                button1, button2 = self.buttons[i]
                layout.removeWidget(button1)
                layout.removeWidget(button2)

                button1.setParent(None)
                button2.setParent(None)

                del self.buttons[i]

        for y in range(height):
            spinbox1, spinbox2 = self.spinboxes[y]

            spinbox1.setRange(0, object.repeatX[y][1]-1)
            spinbox2.setRange(object.repeatX[y][0]+1, len(object.tiles[y]))

            spinbox1.setValue(object.repeatX[y][0])
            spinbox2.setValue(object.repeatX[y][1])

        self.updating = False
        self.setFixedHeight(height * 24)


    def startValChanged(self, val, y):
        if self.updating:
            return

        global Tileset

        index = window.objectList.currentIndex().row()
        if index < 0 or index >= len(Tileset.objects):
            return

        object = Tileset.objects[index]
        object.repeatX[y][0] = val

        for x in range(len(object.tiles[y])):
            if x >= val and x < object.repeatX[y][1]:
                object.tiles[y][x] = (object.tiles[y][x][0] | 1, object.tiles[y][x][1], object.tiles[y][x][2])

            else:
                object.tiles[y][x] = (object.tiles[y][x][0] & ~1, object.tiles[y][x][1], object.tiles[y][x][2])

        spinbox1, spinbox2 = self.spinboxes[y]
        spinbox1.setRange(0, object.repeatX[y][1]-1)
        spinbox2.setRange(val+1, len(object.tiles[y]))

        window.tileWidget.tiles.update()


    def endValChanged(self, val, y):
        if self.updating:
            return

        global Tileset

        index = window.objectList.currentIndex().row()
        if index < 0 or index >= len(Tileset.objects):
            return

        object = Tileset.objects[index]
        object.repeatX[y][1] = val

        for x in range(len(object.tiles[y])):
            if x >= object.repeatX[y][0] and x < val:
                object.tiles[y][x] = (object.tiles[y][x][0] | 1, object.tiles[y][x][1], object.tiles[y][x][2])

            else:
                object.tiles[y][x] = (object.tiles[y][x][0] & ~1, object.tiles[y][x][1], object.tiles[y][x][2])

        spinbox1, spinbox2 = self.spinboxes[y]
        spinbox1.setRange(0, val-1)
        spinbox2.setRange(object.repeatX[y][0]+1, len(object.tiles[y]))

        window.tileWidget.tiles.update()


    def addTile(self, y):
        if self.updating:
            return

        global Tileset

        index = window.objectList.currentIndex().row()
        if index < 0 or index >= len(Tileset.objects):
            return

        pix = QtGui.QPixmap(24,24)
        pix.fill(QtGui.QColor(0,0,0,0))

        window.tileWidget.tiles.tiles[y].append(pix)

        object = Tileset.objects[index]
        if object.repeatY and y >= object.repeatY[0] and y < object.repeatY[1]:
            object.tiles[y].append((2, 0, 0))

        else:
            object.tiles[y].append((0, 0, 0))

        object.width = max(len(object.tiles[y]), object.width)

        self.update()

        window.tileWidget.tiles.size[0] = object.width
        window.tileWidget.tiles.setMinimumSize(window.tileWidget.tiles.size[0]*24 + 12, window.tileWidget.tiles.size[1]*24 + 12)

        window.tileWidget.tiles.update()
        window.tileWidget.tiles.updateList()


    def removeTile(self, y):
        if self.updating:
            return

        if window.tileWidget.tiles.size[0] == 1:
            return

        global Tileset

        index = window.objectList.currentIndex().row()
        if index < 0 or index >= len(Tileset.objects):
            return

        object = Tileset.objects[index]

        row = window.tileWidget.tiles.tiles[y]
        if len(row) > 1:
            row.pop()
        else:
            return
                
        row = object.tiles[y]
        if len(row) > 1:
            row.pop()
        else:
            return

        start, end = object.repeatX[y]
        end = min(end, len(row))
        start = min(start, end - 1)

        if [start, end] != object.repeatX[y]:
            object.repeatX[y] = [start, end]
            for x in range(len(row)):
                if x >= start and x < end:
                    row[x] = (row[x][0] | 1, row[x][1], row[x][2])

                else:
                    row[x] = (row[x][0] & ~1, row[x][1], row[x][2])

        object.width = max(len(row) for row in object.tiles)

        self.update()

        window.tileWidget.tiles.size[0] = object.width
        window.tileWidget.tiles.setMinimumSize(window.tileWidget.tiles.size[0]*24 + 12, window.tileWidget.tiles.size[1]*24 + 12)

        window.tileWidget.tiles.update()
        window.tileWidget.tiles.updateList()


class RepeatYModifiers(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setVisible(False)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0,0,0,0)

        spinbox1 = QtWidgets.QSpinBox()
        spinbox1.setFixedSize(50, 24)
        spinbox1.valueChanged.connect(self.startValChanged)
        layout.addWidget(spinbox1)

        spinbox2 = QtWidgets.QSpinBox()
        spinbox2.setFixedSize(50, 24)
        spinbox2.valueChanged.connect(self.endValChanged)
        layout.addWidget(spinbox2)

        self.spinboxes = (spinbox1, spinbox2)
        self.updating = False

        self.setFixedWidth(102)


    def update(self):
        global Tileset

        index = window.objectList.currentIndex().row()
        if index < 0 or index >= len(Tileset.objects):
            return

        object = Tileset.objects[index]
        if not object.repeatY:
            return

        self.updating = True

        spinbox1, spinbox2 = self.spinboxes
        spinbox1.setRange(0, object.repeatY[1]-1)
        spinbox2.setRange(object.repeatY[0]+1, object.height)

        spinbox1.setValue(object.repeatY[0])
        spinbox2.setValue(object.repeatY[1])

        self.updating = False


    def startValChanged(self, val):
        if self.updating:
            return

        global Tileset

        index = window.objectList.currentIndex().row()
        if index < 0 or index >= len(Tileset.objects):
            return

        object = Tileset.objects[index]
        object.createRepetitionY(val, object.repeatY[1])

        spinbox1, spinbox2 = self.spinboxes
        spinbox1.setRange(0, object.repeatY[1]-1)
        spinbox2.setRange(object.repeatY[0]+1, object.height)

        window.tileWidget.tiles.update()


    def endValChanged(self, val):
        if self.updating:
            return

        global Tileset

        index = window.objectList.currentIndex().row()
        if index < 0 or index >= len(Tileset.objects):
            return

        object = Tileset.objects[index]
        object.createRepetitionY(object.repeatY[0], val)

        spinbox1, spinbox2 = self.spinboxes
        spinbox1.setRange(0, object.repeatY[1]-1)
        spinbox2.setRange(object.repeatY[0]+1, object.height)

        window.tileWidget.tiles.update()


class SlopeLineModifier(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.setVisible(False)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0,0,0,0)

        self.spinbox = QtWidgets.QSpinBox()
        self.spinbox.setFixedSize(50, 24)
        self.spinbox.valueChanged.connect(self.valChanged)
        layout.addWidget(self.spinbox)

        self.updating = False

        self.setFixedWidth(51)


    def update(self):
        global Tileset

        index = window.objectList.currentIndex().row()
        if index < 0 or index >= len(Tileset.objects):
            return

        object = Tileset.objects[index]
        if object.upperslope[0] == 0:
            return

        self.updating = True

        self.spinbox.setRange(1, object.height)
        self.spinbox.setValue(object.upperslope[1])

        self.updating = False


    def valChanged(self, val):
        if self.updating:
            return

        global Tileset

        index = window.objectList.currentIndex().row()
        if index < 0 or index >= len(Tileset.objects):
            return

        object = Tileset.objects[index]
        if object.height == 1:
            object.upperslope[1] = 1
            object.lowerslope = [0, 0]

        else:
            object.upperslope[1] = val
            object.lowerslope = [0x84, object.height - val]

        tiles = window.tileWidget.tiles

        if object.upperslope[0] & 2:
            tiles.slope = -object.upperslope[1]

        else:
            tiles.slope = object.upperslope[1]

        tiles.update()


class tileOverlord(QtWidgets.QWidget):

    def __init__(self):
        super(tileOverlord, self).__init__()

        # Setup Widgets
        self.tiles = tileWidget()

        self.addObject = QtWidgets.QPushButton('Add')
        self.removeObject = QtWidgets.QPushButton('Remove')

        global Tileset

        self.placeNull = QtWidgets.QPushButton('Null')
        self.placeNull.setCheckable(True)
        self.placeNull.setChecked(Tileset.placeNullChecked)

        self.addRow = QtWidgets.QPushButton('+')
        self.removeRow = QtWidgets.QPushButton('-')

        self.addColumn = QtWidgets.QPushButton('+')
        self.removeColumn = QtWidgets.QPushButton('-')

        self.tilingMethod = QtWidgets.QComboBox()
        self.tilesetType = QtWidgets.QLabel('Pa%d' % Tileset.slot)

        self.tilingMethod.addItems(['No Repetition',
                                    'Repeat X',
                                    'Repeat Y',
                                    'Repeat X and Y',
                                    'Upward slope',
                                    'Downward slope',
                                    'Downward reverse slope',
                                    'Upward reverse slope'])

        self.info = QtWidgets.QLabel("You can right click on the tiles of a object to make additional changes to it's behaivor!")
        self.info.setWordWrap(True)
        self.info.setAlignment(Qt.AlignCenter)

        # Connections
        self.addObject.released.connect(self.addObj)
        self.removeObject.released.connect(self.removeObj)
        self.placeNull.toggled.connect(self.doPlaceNull)
        self.addRow.released.connect(self.addRowHandler)
        self.removeRow.released.connect(self.removeRowHandler)
        self.addColumn.released.connect(self.addColumnHandler)
        self.removeColumn.released.connect(self.removeColumnHandler)

        self.tilingMethod.currentIndexChanged.connect(self.setTiling)


        # Layout
        self.repeatX = RepeatXModifiers()
        repeatXLyt = QtWidgets.QVBoxLayout()
        repeatXLyt.addWidget(self.repeatX)

        self.repeatY = RepeatYModifiers()
        repeatYLyt = QtWidgets.QHBoxLayout()
        repeatYLyt.addWidget(self.repeatY)

        self.slopeLine = SlopeLineModifier()
        slopeLineLyt = QtWidgets.QVBoxLayout()
        slopeLineLyt.addWidget(self.slopeLine)

        tilesLyt = QtWidgets.QGridLayout()
        tilesLyt.setSpacing(0)
        tilesLyt.setContentsMargins(0,0,0,0)

        tilesLyt.addWidget(self.tiles, 0, 0, 3, 4)
        tilesLyt.addLayout(repeatXLyt, 0, 4, 3, 1)
        tilesLyt.addLayout(repeatYLyt, 3, 0, 1, 4)
        tilesLyt.addLayout(slopeLineLyt, 0, 5, 3, 1)

        layout = QtWidgets.QGridLayout()

        layout.addWidget(self.tilesetType, 0, 0, 1, 1)
        layout.addWidget(self.tilingMethod, 0, 1, 1, 4)

        layout.addWidget(self.addObject, 0, 5, 1, 1)
        layout.addWidget(self.removeObject, 0, 6, 1, 1)

        layout.setRowMinimumHeight(1, 40)

        layout.setRowStretch(1, 1)
        layout.setRowStretch(2, 5)
        layout.setRowStretch(5, 5)

        layout.addLayout(tilesLyt, 2, 1, 4, 6)
        layout.addWidget(self.info, 6, 0, 1, 7)

        layout.addWidget(self.placeNull, 1, 0, 1, 1)

        layout.addWidget(self.addColumn, 2, 0, 1, 1)
        layout.addWidget(self.removeColumn, 3, 0, 1, 1)
        layout.addWidget(self.addRow, 1, 1, 1, 1)
        layout.addWidget(self.removeRow, 1, 2, 1, 1)

        self.setLayout(layout)




    def addObj(self):
        global Tileset

        Tileset.addObject(new=True)

        pix = QtGui.QPixmap(24, 24)
        pix.fill(Qt.transparent)

        painter = QtGui.QPainter(pix)
        painter.drawPixmap(0, 0, Tileset.tiles[0].image)
        painter.end()
        del painter

        count = len(Tileset.objects)
        item = QtGui.QStandardItem(QtGui.QIcon(pix), 'Object {0}'.format(count-1))
        item.setEditable(False)
        window.objmodel.appendRow(item)
        index = window.objectList.currentIndex()
        window.objectList.setCurrentIndex(index)
        self.setObject(index)

        window.objectList.update()
        self.update()


    def removeObj(self):
        global Tileset

        index = window.objectList.currentIndex().row()
        if index < 0 or index >= len(Tileset.objects):
            return

        Tileset.removeObject(index)
        window.objmodel.removeRow(index)
        self.tiles.clear()

        SetupObjectModel(window.objmodel, Tileset.objects, Tileset.tiles)

        window.objectList.update()
        self.update()


    def doPlaceNull(self, checked):
        global Tileset
        Tileset.placeNullChecked = checked


    def setObject(self, index):
        global Tileset

        self.tiles.object = index.row()
        if self.tiles.object < 0 or self.tiles.object >= len(Tileset.objects):
            return

        object = Tileset.objects[index.row()]

        self.tilingMethod.setCurrentIndex(object.determineTilingMethod())
        self.tiles.setObject(object)


    @QtCoreSlot(int)
    def setTiling(self, listindex):
        if listindex == 0:  # No Repetition
            self.repeatX.setVisible(False)
            self.repeatY.setVisible(False)
            self.slopeLine.setVisible(False)

        elif listindex == 1:  # Repeat X
            self.repeatX.setVisible(True)
            self.repeatY.setVisible(False)
            self.slopeLine.setVisible(False)

        elif listindex == 2:  # Repeat Y
            self.repeatX.setVisible(False)
            self.repeatY.setVisible(True)
            self.slopeLine.setVisible(False)

        elif listindex == 3:  # Repeat X and Y
            self.repeatX.setVisible(True)
            self.repeatY.setVisible(True)
            self.slopeLine.setVisible(False)

        elif listindex == 4:  # Upward Slope
            self.repeatX.setVisible(False)
            self.repeatY.setVisible(False)
            self.slopeLine.setVisible(True)

        elif listindex == 5:  # Downward Slope
            self.repeatX.setVisible(False)
            self.repeatY.setVisible(False)
            self.slopeLine.setVisible(True)

        elif listindex == 6:  # Upward Reverse Slope
            self.repeatX.setVisible(False)
            self.repeatY.setVisible(False)
            self.slopeLine.setVisible(True)

        elif listindex == 7:  # Downward Reverse Slope
            self.repeatX.setVisible(False)
            self.repeatY.setVisible(False)
            self.slopeLine.setVisible(True)

        global Tileset

        index = window.objectList.currentIndex().row()
        if index < 0 or index >= len(Tileset.objects):
            return

        object = Tileset.objects[index]
        if object.tilingMethodIdx == listindex:
            return

        object.tilingMethodIdx = listindex
        self.tiles.slope = 0

        if listindex == 0:  # No Repetition
            object.clearRepetitionXY()

            object.upperslope = [0, 0]
            object.lowerslope = [0, 0]

        elif listindex == 1:  # Repeat X
            object.clearRepetitionY()

            if not object.repeatX:
                object.createRepetitionX()
                self.repeatX.update()

            object.upperslope = [0, 0]
            object.lowerslope = [0, 0]

        elif listindex == 2:  # Repeat Y
            object.clearRepetitionX()

            if not object.repeatY:
                object.createRepetitionY(0, object.height)
                self.repeatY.update()

            object.upperslope = [0, 0]
            object.lowerslope = [0, 0]

        elif listindex == 3:  # Repeat X and Y
            if not object.repeatX:
                object.createRepetitionX()
                self.repeatX.update()

            if not object.repeatY:
                object.createRepetitionY(0, object.height)
                self.repeatY.update()

            object.upperslope = [0, 0]
            object.lowerslope = [0, 0]

        elif listindex == 4:  # Upward Slope
            object.clearRepetitionXY()

            if object.upperslope[0] != 0x90:
                object.upperslope = [0x90, 1]

                if object.height == 1:
                    object.lowerslope = [0, 0]

                else:
                    object.lowerslope = [0x84, object.height - 1]

            self.tiles.slope = object.upperslope[1]
            self.slopeLine.update()

        elif listindex == 5:  # Downward Slope
            object.clearRepetitionXY()

            if object.upperslope[0] != 0x91:
                object.upperslope = [0x91, 1]

                if object.height == 1:
                    object.lowerslope = [0, 0]

                else:
                    object.lowerslope = [0x84, object.height - 1]

            self.tiles.slope = object.upperslope[1]
            self.slopeLine.update()

        elif listindex == 6:  # Upward Reverse Slope
            object.clearRepetitionXY()

            if object.upperslope[0] != 0x92:
                object.upperslope = [0x92, 1]

                if object.height == 1:
                    object.lowerslope = [0, 0]

                else:
                    object.lowerslope = [0x84, object.height - 1]

            self.tiles.slope = -object.upperslope[1]
            self.slopeLine.update()

        elif listindex == 7:  # Downward Reverse Slope
            object.clearRepetitionXY()

            if object.upperslope[0] != 0x93:
                object.upperslope = [0x93, 1]

                if object.height == 1:
                    object.lowerslope = [0, 0]

                else:
                    object.lowerslope = [0x84, object.height - 1]

            self.tiles.slope = -object.upperslope[1]
            self.slopeLine.update()

        self.tiles.update()


    def addRowHandler(self):
        index = window.objectList.currentIndex()
        self.tiles.object = index.row()

        if self.tiles.object < 0 or self.tiles.object >= len(Tileset.objects):
            return

        self.tiles.addRow()


    def removeRowHandler(self):
        index = window.objectList.currentIndex()
        self.tiles.object = index.row()

        if self.tiles.object < 0 or self.tiles.object >= len(Tileset.objects):
            return

        self.tiles.removeRow()


    def addColumnHandler(self):
        index = window.objectList.currentIndex()
        self.tiles.object = index.row()

        if self.tiles.object < 0 or self.tiles.object >= len(Tileset.objects):
            return

        self.tiles.addColumn()


    def removeColumnHandler(self):
        index = window.objectList.currentIndex()
        self.tiles.object = index.row()

        if self.tiles.object < 0 or self.tiles.object >= len(Tileset.objects):
            return

        self.tiles.removeColumn()


class tileWidget(QtWidgets.QWidget):

    def __init__(self):
        super(tileWidget, self).__init__()

        self.tiles = []

        self.size = [1, 1]
        self.setMinimumSize(36, 36)  # (24, 24) + padding

        self.slope = 0

        self.highlightedRect = QtCore.QRect()

        self.setAcceptDrops(True)
        self.object = -1


    def clear(self):
        self.tiles = []
        self.size = [1, 1] # [width, height]

        self.slope = 0
        self.highlightedRect = QtCore.QRect()

        self.update()


    def addColumn(self):
        global Tileset

        if self.size[0] >= 24:
            return

        if self.object < 0 or self.object >= len(Tileset.objects):
            return

        self.size[0] += 1
        self.setMinimumSize(self.size[0]*24 + 12, self.size[1]*24 + 12)

        curObj = Tileset.objects[self.object]
        curObj.width += 1

        pix = QtGui.QPixmap(24,24)
        pix.fill(QtGui.QColor(0,0,0,0))

        for row in self.tiles:
            row.append(pix)

        if curObj.repeatY:
            for y, row in enumerate(curObj.tiles):
                if y >= curObj.repeatY[0] and y < curObj.repeatY[1]:
                    row.append((2, 0, 0))

                else:
                    row.append((0, 0, 0))

        else:
            for row in curObj.tiles:
                row.append((0, 0, 0))

        self.update()
        self.updateList()

        window.tileWidget.repeatX.update()


    def removeColumn(self):
        global Tileset

        if self.size[0] == 1:
            return

        if self.object < 0 or self.object >= len(Tileset.objects):
            return

        self.size[0] -= 1
        self.setMinimumSize(self.size[0]*24 + 12, self.size[1]*24 + 12)

        curObj = Tileset.objects[self.object]
        curObj.width -= 1

        for row in self.tiles:
            if len(row) > 1:
                row.pop()

        for row in curObj.tiles:
            if len(row) > 1:
                row.pop()

        if curObj.repeatX:
            for y, row in enumerate(curObj.tiles):
                start, end = curObj.repeatX[y]
                end = min(end, len(row))
                start = min(start, end - 1)

                if [start, end] != curObj.repeatX[y]:
                    curObj.repeatX[y] = [start, end]
                    for x in range(len(row)):
                        if x >= start and x < end:
                            row[x] = (row[x][0] | 1, row[x][1], row[x][2])

                        else:
                            row[x] = (row[x][0] & ~1, row[x][1], row[x][2])

        self.update()
        self.updateList()

        window.tileWidget.repeatX.update()


    def addRow(self):
        global Tileset

        if self.size[1] >= 24:
            return

        if self.object < 0 or self.object >= len(Tileset.objects):
            return

        self.size[1] += 1
        self.setMinimumSize(self.size[0]*24 + 12, self.size[1]*24 + 12)

        curObj = Tileset.objects[self.object]
        curObj.height += 1

        pix = QtGui.QPixmap(24,24)
        pix.fill(QtGui.QColor(0,0,0,0))

        self.tiles.append([pix for _ in range(curObj.width)])

        if curObj.repeatX:
            curObj.tiles.append([(1, 0, 0) for _ in range(curObj.width)])
            curObj.repeatX.append([0, curObj.width])

        else:
            curObj.tiles.append([(0, 0, 0) for _ in range(curObj.width)])

        if curObj.upperslope[0] != 0:
            curObj.lowerslope = [0x84, curObj.lowerslope[1] + 1]

        self.update()
        self.updateList()

        window.tileWidget.repeatX.update()
        window.tileWidget.repeatY.update()
        window.tileWidget.slopeLine.update()


    def removeRow(self):
        global Tileset

        if self.size[1] == 1:
            return

        if self.object < 0 or self.object >= len(Tileset.objects):
            return

        self.tiles.pop()

        self.size[1] -= 1
        self.setMinimumSize(self.size[0]*24 + 12, self.size[1]*24 + 12)

        curObj = Tileset.objects[self.object]
        curObj.tiles = list(curObj.tiles)
        curObj.height -= 1

        curObj.tiles.pop()

        if curObj.repeatX:
            curObj.repeatX.pop()

        if curObj.repeatY:
            start, end = curObj.repeatY
            end = min(end, curObj.height)
            start = min(start, end - 1)

            if [start, end] != curObj.repeatY:
                curObj.createRepetitionY(start, end)

        if curObj.upperslope[0] != 0:
            if curObj.upperslope[1] > curObj.height or curObj.height == 1:
                curObj.upperslope[1] = curObj.height
                curObj.lowerslope = [0, 0]

                if curObj.upperslope[0] & 2:
                    self.slope = -curObj.upperslope[1]
                else:
                    self.slope = curObj.upperslope[1]

            else:
                curObj.lowerslope = [0x84, curObj.lowerslope[1] - 1]

        self.update()
        self.updateList()

        window.tileWidget.repeatX.update()
        window.tileWidget.repeatY.update()
        window.tileWidget.slopeLine.update()


    def setObject(self, object):
        self.clear()

        global Tileset

        self.size = [object.width, object.height]
        self.setMinimumSize(self.size[0]*24 + 12, self.size[1]*24 + 12)

        if not object.upperslope[1] == 0:
            if object.upperslope[0] & 2:
                self.slope = -object.upperslope[1]
            else:
                self.slope = object.upperslope[1]

        x = 0
        y = 0
        for row in object.tiles:
            self.tiles.append([])
            for tile in row:
                if Tileset.slot == (tile[2] & 3):
                    self.tiles[-1].append(Tileset.tiles[tile[1]].image)
                else:
                    pix = QtGui.QPixmap(24,24)
                    pix.fill(QtGui.QColor(0,0,0,0))
                    self.tiles[-1].append(pix)
                x += 1
            y += 1
            x = 0


        self.object = window.objectList.currentIndex().row()
        self.update()
        self.updateList()

        window.tileWidget.repeatX.update()
        window.tileWidget.repeatY.update()
        window.tileWidget.slopeLine.update()


    def contextMenuEvent(self, event):
        index = window.objectList.currentIndex()
        self.object = index.row()

        if self.object < 0 or self.object >= len(Tileset.objects):
            return

        centerPoint = self.contentsRect().center()

        upperLeftX = centerPoint.x() - self.size[0]*12
        upperLeftY = centerPoint.y() - self.size[1]*12

        x = int((event.x() - upperLeftX) / 24)
        y = int((event.y() - upperLeftY) / 24)

        object = Tileset.objects[self.object]

        if y < 0 or y >= object.height or x < 0 or x >= len(object.tiles[y]):
            return

        self.contX = x
        self.contY = y

        TileMenu = QtWidgets.QMenu(self)

        TileMenu.addAction('Set tile...', self.setTile)
        TileMenu.addAction('Set item...', self.setItem)

        TileMenu.exec_(event.globalPos())


    def mousePressEvent(self, event):
        global Tileset

        if event.button() == 2:
            return

        index = window.objectList.currentIndex()
        self.object = index.row()

        if self.object < 0 or self.object >= len(Tileset.objects):
            return

        if Tileset.placeNullChecked:
            centerPoint = self.contentsRect().center()

            upperLeftX = centerPoint.x() - self.size[0]*12
            upperLeftY = centerPoint.y() - self.size[1]*12

            lowerRightX = centerPoint.x() + self.size[0]*12
            lowerRightY = centerPoint.y() + self.size[1]*12


            x = int((event.x() - upperLeftX)/24)
            y = int((event.y() - upperLeftY)/24)

            if event.x() < upperLeftX or event.y() < upperLeftY or event.x() > lowerRightX or event.y() > lowerRightY:
                return

            if Tileset.slot == 0:
                try:
                    self.tiles[y][x] = Tileset.tiles[0].image
                    Tileset.objects[self.object].tiles[y][x] = (Tileset.objects[self.object].tiles[y][x][0], 0, 0)
                except IndexError:
                    pass

            else:
                pix = QtGui.QPixmap(24,24)
                pix.fill(QtGui.QColor(0,0,0,0))

                try:
                    self.tiles[y][x] = pix
                    Tileset.objects[self.object].tiles[y][x] = (Tileset.objects[self.object].tiles[y][x][0], 0, 0)
                except IndexError:
                    pass

        else:
            if window.tileDisplay.selectedIndexes() == []:
                return

            currentSelected = window.tileDisplay.selectedIndexes()

            ix = 0
            iy = 0
            for modelItem in currentSelected:
                # Update yourself!
                centerPoint = self.contentsRect().center()

                tile = modelItem.row()
                upperLeftX = centerPoint.x() - self.size[0]*12
                upperLeftY = centerPoint.y() - self.size[1]*12

                lowerRightX = centerPoint.x() + self.size[0]*12
                lowerRightY = centerPoint.y() + self.size[1]*12


                x = int((event.x() - upperLeftX)/24 + ix)
                y = int((event.y() - upperLeftY)/24 + iy)

                if event.x() < upperLeftX or event.y() < upperLeftY or event.x() > lowerRightX or event.y() > lowerRightY:
                    return

                try:
                    self.tiles[y][x] = Tileset.tiles[tile].image
                    Tileset.objects[self.object].tiles[y][x] = (Tileset.objects[self.object].tiles[y][x][0], tile, Tileset.slot)
                except IndexError:
                    pass

                ix += 1
                if self.size[0]-1 < ix:
                    ix = 0
                    iy += 1
                if iy > self.size[1]-1:
                    break


        self.update()

        self.updateList()


    def updateList(self):
        # Update the list >.>
        object = window.objmodel.itemFromIndex(window.objectList.currentIndex())
        if not object: return


        tex = QtGui.QPixmap(self.size[0] * 24, self.size[1] * 24)
        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        Xoffset = 0
        Yoffset = 0

        for y, row in enumerate(self.tiles):
            for x, tile in enumerate(row):
                painter.drawPixmap(x*24, y*24, tile)

        painter.end()

        object.setIcon(QtGui.QIcon(tex))

        window.objectList.update()



    def setTile(self):
        global Tileset

        dlg = self.setTileDialog()
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            # Do stuff
            tile = dlg.tile.value()
            tileset = dlg.tileset.currentIndex()

            x = self.contX
            y = self.contY

            if tileset != Tileset.slot:
                tex = QtGui.QPixmap(self.size[0] * 24, self.size[1] * 24)
                tex.fill(Qt.transparent)

                self.tiles[y][x] = tex

            else:
                self.tiles[y][x] = Tileset.tiles[tile].image

            Tileset.objects[self.object].tiles[y][x] = (Tileset.objects[self.object].tiles[y][x][0], tile, tileset)

            self.update()
            self.updateList()


    class setTileDialog(QtWidgets.QDialog):

        def __init__(self):
            QtWidgets.QDialog.__init__(self)

            self.setWindowTitle('Set tiles')

            self.tileset = QtWidgets.QComboBox()
            self.tileset.addItems(['Pa0', 'Pa1', 'Pa2', 'Pa3'])

            self.tile = QtWidgets.QSpinBox()
            self.tile.setRange(0, 255)

            self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            self.buttons.accepted.connect(self.accept)
            self.buttons.rejected.connect(self.reject)

            self.layout = QtWidgets.QGridLayout()
            self.layout.addWidget(QtWidgets.QLabel('Tileset:'), 0,0,1,1, Qt.AlignLeft)
            self.layout.addWidget(QtWidgets.QLabel('Tile:'), 0,3,1,1, Qt.AlignLeft)
            self.layout.addWidget(self.tileset, 1, 0, 1, 2)
            self.layout.addWidget(self.tile, 1, 3, 1, 3)
            self.layout.addWidget(self.buttons, 2, 3)
            self.setLayout(self.layout)


    def setItem(self):
        global Tileset

        x = self.contX
        y = self.contY

        obj = Tileset.objects[self.object].tiles[y][x]

        dlg = self.setItemDialog(obj[2] >> 2)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            # Do stuff
            item = dlg.item.currentIndex()

            Tileset.objects[self.object].tiles[y][x] = (obj[0], obj[1], (obj[2] & 3) | (item << 2))

            self.update()
            self.updateList()


    class setItemDialog(QtWidgets.QDialog):

        def __init__(self, initialIndex=0):
            QtWidgets.QDialog.__init__(self)

            self.setWindowTitle('Set item')

            self.item = QtWidgets.QComboBox()
            self.item.addItems([
                'Item specified in tile behavior',
                'Fire Flower',
                'Star',
                'Coin',
                'Vine',
                'Spring',
                'Mini Mushroom',
                'Propeller Mushroom',
                'Penguin Suit',
                'Yoshi',
                'Ice Flower',
                'Unknown (11)',
                'Unknown (12)',
                'Unknown (13)',
                'Unknown (14)'])
            self.item.setCurrentIndex(initialIndex)

            self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            self.buttons.accepted.connect(self.accept)
            self.buttons.rejected.connect(self.reject)

            self.layout = QtWidgets.QHBoxLayout()
            self.vlayout = QtWidgets.QVBoxLayout()
            self.layout.addWidget(QtWidgets.QLabel('Item:'))
            self.layout.addWidget(self.item)
            self.vlayout.addLayout(self.layout)
            self.vlayout.addWidget(self.buttons)
            self.setLayout(self.vlayout)



    def paintEvent(self, event):
        painter = QtGui.QPainter()
        painter.begin(self)

        centerPoint = self.contentsRect().center()
        upperLeftX = centerPoint.x() - self.size[0]*12
        lowerRightX = centerPoint.x() + self.size[0]*12

        upperLeftY = centerPoint.y() - self.size[1]*12
        lowerRightY = centerPoint.y() + self.size[1]*12

        index = window.objectList.currentIndex()
        self.object = index.row()

        if self.object < 0 or self.object >= len(Tileset.objects):
            painter.end()
            return

        object = Tileset.objects[self.object]
        for y, row in enumerate(object.tiles):
            painter.fillRect(upperLeftX, upperLeftY + y * 24, len(row) * 24, 24, QtGui.QColor(175, 175, 175))

        for y, row in enumerate(self.tiles):
            for x, pix in enumerate(row):
                painter.drawPixmap(upperLeftX + (x * 24), upperLeftY + (y * 24), pix)

        if object.upperslope[0] & 0x80:
            pen = QtGui.QPen()
            pen.setStyle(Qt.DashLine)
            pen.setWidth(2)
            pen.setColor(QtGui.QColor(0, 255, 255))
            painter.setPen(QtGui.QPen(pen))

            slope = self.slope
            if slope < 0:
                slope += self.size[1]

            painter.drawLine(upperLeftX, upperLeftY + (slope * 24), lowerRightX, upperLeftY + (slope * 24))

            font = painter.font()
            font.setPixelSize(8)
            font.setFamily('Monaco')
            painter.setFont(font)

            if self.slope > 0:
                painter.drawText(upperLeftX+1, upperLeftY+10, 'Main')
                painter.drawText(upperLeftX+1, upperLeftY + (slope * 24) + 9, 'Sub')

            else:
                painter.drawText(upperLeftX+1, upperLeftY + self.size[1]*24 - 4, 'Main')
                painter.drawText(upperLeftX+1, upperLeftY + (slope * 24) - 3, 'Sub')

        if 0 <= self.object < len(Tileset.objects):
            object = Tileset.objects[self.object]
            if object.repeatX:
                pen = QtGui.QPen()
                pen.setStyle(Qt.DashLine)
                pen.setWidth(2)
                pen.setColor(QtGui.QColor(0, 255, 255))
                painter.setPen(QtGui.QPen(pen))

                for y in range(object.height):
                    startX, endX = object.repeatX[y]
                    painter.drawLine(upperLeftX + startX * 24, upperLeftY + y * 24, upperLeftX + startX * 24, upperLeftY + y * 24 + 24)
                    painter.drawLine(upperLeftX +   endX * 24, upperLeftY + y * 24, upperLeftX +   endX * 24, upperLeftY + y * 24 + 24)

            if object.repeatY:
                pen = QtGui.QPen()
                pen.setStyle(Qt.DashLine)
                pen.setWidth(2)
                pen.setColor(QtGui.QColor(255, 0, 255))
                painter.setPen(QtGui.QPen(pen))

                painter.drawLine(upperLeftX, upperLeftY + object.repeatY[0] * 24, lowerRightX, upperLeftY + object.repeatY[0] * 24)
                painter.drawLine(upperLeftX, upperLeftY + object.repeatY[1] * 24, lowerRightX, upperLeftY + object.repeatY[1] * 24)

        painter.end()


#############################################################################################
############################ Subclassed one dimension Item Model ############################


class PiecesModel(QtCore.QAbstractListModel):
    def __init__(self, parent=None):
        super(PiecesModel, self).__init__(parent)

        self.pixmaps = []

    def supportedDragActions(self):
        super().supportedDragActions()
        return Qt.CopyAction | Qt.MoveAction | Qt.LinkAction

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        if role == Qt.DecorationRole:
            return QtGui.QIcon(self.pixmaps[index.row()])

        if role == Qt.UserRole:
            return self.pixmaps[index.row()]

        return None

    def addPieces(self, pixmap):
        row = len(self.pixmaps)

        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        self.pixmaps.insert(row, pixmap)
        self.endInsertRows()

    def flags(self,index):
        if index.isValid():
            return (Qt.ItemIsEnabled | Qt.ItemIsSelectable |
                    Qt.ItemIsDragEnabled)

    def clear(self):
        row = len(self.pixmaps)

        del self.pixmaps[:]


    def mimeTypes(self):
        return ['image/x-tile-piece']


    def mimeData(self, indexes):
        mimeData = QtCore.QMimeData()
        encodedData = QtCore.QByteArray()

        stream = QtCore.QDataStream(encodedData, QtCore.QIODevice.WriteOnly)

        for index in indexes:
            if index.isValid():
                pixmap = QtGui.QPixmap(self.data(index, Qt.UserRole))
                stream << pixmap

        mimeData.setData('image/x-tile-piece', encodedData)
        return mimeData


    def rowCount(self, parent):
        if parent.isValid():
            return 0
        else:
            return len(self.pixmaps)

    def supportedDragActions(self):
        return Qt.CopyAction | Qt.MoveAction



#############################################################################################
################## Python-based RGB5a3 Decoding code from my BRFNT program ##################


RGB4A3LUT = []
RGB4A3LUT_NoAlpha = []
def PrepareRGB4A3LUTs():
    global RGB4A3LUT, RGB4A3LUT_NoAlpha

    RGB4A3LUT = [None] * 0x10000
    RGB4A3LUT_NoAlpha = [None] * 0x10000
    for LUT, hasA in [(RGB4A3LUT, True), (RGB4A3LUT_NoAlpha, False)]:

        # RGB4A3
        for d in range(0x8000):
            if hasA:
                alpha = d >> 12
                alpha = alpha << 5 | alpha << 2 | alpha >> 1
            else:
                alpha = 0xFF
            red = ((d >> 8) & 0xF) * 17
            green = ((d >> 4) & 0xF) * 17
            blue = (d & 0xF) * 17
            LUT[d] = blue | (green << 8) | (red << 16) | (alpha << 24)

        # RGB555
        for d in range(0x8000):
            red = d >> 10
            red = red << 3 | red >> 2
            green = (d >> 5) & 0x1F
            green = green << 3 | green >> 2
            blue = d & 0x1F
            blue = blue << 3 | blue >> 2
            LUT[d + 0x8000] = blue | (green << 8) | (red << 16) | 0xFF000000

PrepareRGB4A3LUTs()


def RGB4A3Decode(tex, useAlpha=True):
    tx = 0; ty = 0
    iter = tex.__iter__()
    dest = [0] * 262144

    LUT = RGB4A3LUT if useAlpha else RGB4A3LUT_NoAlpha

    # Loop over all texels (of which there are 16384)
    for i in range(16384):
        temp1 = (i // 256) % 8
        if temp1 == 0 or temp1 == 7:
            # Skip every row of texels that is a multiple of 8 or (a
            # multiple of 8) - 1
            # Unrolled loop for performance.
            next(iter); next(iter); next(iter); next(iter)
            next(iter); next(iter); next(iter); next(iter)
            next(iter); next(iter); next(iter); next(iter)
            next(iter); next(iter); next(iter); next(iter)
            next(iter); next(iter); next(iter); next(iter)
            next(iter); next(iter); next(iter); next(iter)
            next(iter); next(iter); next(iter); next(iter)
            next(iter); next(iter); next(iter); next(iter)
        else:
            temp2 = i % 8
            if temp2 == 0 or temp2 == 7:
                # Skip every column of texels that is a multiple of 8
                # or (a multiple of 8) - 1
                # Unrolled loop for performance.
                next(iter); next(iter); next(iter); next(iter)
                next(iter); next(iter); next(iter); next(iter)
                next(iter); next(iter); next(iter); next(iter)
                next(iter); next(iter); next(iter); next(iter)
                next(iter); next(iter); next(iter); next(iter)
                next(iter); next(iter); next(iter); next(iter)
                next(iter); next(iter); next(iter); next(iter)
                next(iter); next(iter); next(iter); next(iter)
            else:
                # Actually render this texel
                for y in range(ty, ty+4):
                    for x in range(tx, tx+4):
                        dest[x + y * 1024] = LUT[next(iter) << 8 | next(iter)]

        # Move on to the next texel
        tx += 4
        if tx >= 1024: tx = 0; ty += 4

    # Convert the list of ARGB color values into a bytes object, and
    # then convert that into a QImage
    return QtGui.QImage(struct.pack('<262144I', *dest), 1024, 256, QtGui.QImage.Format_ARGB32)


def RGB4A3Encode(tex):
    shorts = []
    colorCache = {}

    for yTile in range(0, 256, 4):
        for xTile in range(0, 1024, 4):
            for y in range(yTile, yTile + 4):
                for x in range(xTile, xTile + 4):
                    pixel = tex.pixel(x, y)

                    if pixel in colorCache:
                        rgba = colorCache[pixel]

                    else:
                        a = pixel >> 24
                        r = (pixel >> 16) & 0xFF
                        g = (pixel >> 8) & 0xFF
                        b = pixel & 0xFF

                        # See encodingTests.py for verification that these
                        # channel conversion formulas are 100% correct

                        # It'd be nice if we could do
                        # if a < 19:
                        #     rgba = 0
                        # for speed, but that defeats the purpose of the
                        # "Toggle Alpha" setting.

                        if a < 238: # RGB4A3
                            alpha = ((a + 18) << 1) // 73
                            red = (r + 8) // 17
                            green = (g + 8) // 17
                            blue = (b + 8) // 17

                            # 0aaarrrrggggbbbb
                            rgba = blue | (green << 4) | (red << 8) | (alpha << 12)

                        else: # RGB555
                            red = ((r + 4) << 2) // 33
                            green = ((g + 4) << 2) // 33
                            blue = ((b + 4) << 2) // 33

                            # 1rrrrrgggggbbbbb
                            rgba = blue | (green << 5) | (red << 10) | (0x8000)

                        colorCache[pixel] = rgba

                    shorts.append(rgba)

    return struct.pack('>262144H', *shorts)


#############################################################################################
############ Main Window Class. Takes care of menu functions and widget creation ############


class MainWindow(QtWidgets.QMainWindow):
    MaxRecentFiles = 9

    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)

        self.recentFileActs = []
        self.recentFiles = []
        self.readRececntFiles()

        self.alpha = True

        global Tileset
        Tileset = TilesetClass()

        global AnimTiles
        AnimTiles = AnimTilesClass()

        global frameEditorData
        frameEditorData = type('frameEditorClass', (), {})()
        frameEditorData.animations = {}

        global RandTiles
        RandTiles = RandTilesClass()

        self.name = ''

        self.setupMenus()
        self.updateRecentFileActions()
        self.setupWidgets()

        self.setuptile()

        self.newTileset()

        self.readIni()

        self.setSizePolicy(QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed))
        self.setWindowTitle("New Tileset")


        if self.tilesetPath:
            self.openTilesetFromPath(self.tilesetPath)

        if self.animTilesPath:
            if self.animTilesPath.endswith('.txt'):
                self.animTilesEditor.importFromTxt(path=self.animTilesPath)
            elif self.animTilesPath.endswith('.bin'):
                self.animTilesEditor.importFromBin(path=self.animTilesPath)

        if self.randTilesPath:
            if self.randTilesPath.endswith('.xml'):
                self.randTilesEditor.importFromXml(path=self.randTilesPath)
            elif self.randTilesPath.endswith('.bin'):
                self.randTilesEditor.importFromBin(path=self.randTilesPath)


    def readRececntFiles(self):
        f = open("Other/recent.txt", "r")
        self.recentFiles = f.read().splitlines()


    def saveRececntFiles(self):
        f = open("Other/recent.txt", "w")
        f.write("\n".join(self.recentFiles))


    def readIni(self):
        self.tilesetPath=""
        self.tilesetDialoguePath=""
        self.animTilesPath=""
        self.animTilesTXTDialoguePath=""
        self.animTilesBINDialoguePath=""
        self.randTilesPath=""
        self.randTilesXMLDialoguePath=""
        self.randTilesBINDialoguePath=""

        f = open("Other/settings.ini", "r")
        for line in f.read().splitlines():
            attr = line.split("=")
            if attr[0] == "tilesetPath":
                self.tilesetPath = attr[1]
            elif attr[0] == "tilesetDialoguePath":
                self.tilesetDialoguePath = attr[1]
            elif attr[0] == "animTilesPath":
                self.animTilesPath = attr[1]
            elif attr[0] == "animTilesTXTDialoguePath":
                self.animTilesTXTDialoguePath = attr[1]
            elif attr[0] == "animTilesBINDialoguePath":
                self.animTilesBINDialoguePath = attr[1]
            elif attr[0] == "randTilesPath":
                self.randTilesPath = attr[1]
            elif attr[0] == "randTilesXMLDialoguePath":
                self.randTilesXMLDialoguePath = attr[1]
            elif attr[0] == "randTilesBINDialoguePath":
                self.randTilesBINDialoguePath = attr[1]

    def saveIni(self):
        self.tilesetPath = self.tilesetPathBox.text()
        self.tilesetDialoguePath = self.tilesetDialoguePathBox.text()
        self.animTilesPath = self.animTilesPathBox.text()
        self.animTilesTXTDialoguePath = self.animTilesTXTDialoguePathBox.text()
        self.animTilesBINDialoguePath = self.animTilesBINDialoguePathBox.text()
        self.randTilesPath = self.randTilesPathBox.text()
        self.randTilesXMLDialoguePath = self.randTilesXMLDialoguePathBox.text()
        self.randTilesBINDialoguePath = self.randTilesBINDialoguePathBox.text()

        settingsText = ""
        settingsText += "tilesetPath=" + self.tilesetPath
        settingsText += "\ntilesetDialoguePath=" + self.tilesetDialoguePath
        settingsText += "\nanimTilesPath=" + self.animTilesPath
        settingsText += "\nanimTilesTXTDialoguePath=" + self.animTilesTXTDialoguePath
        settingsText += "\nanimTilesBINDialoguePath=" + self.animTilesBINDialoguePath
        settingsText += "\nrandTilesPath=" + self.randTilesPath
        settingsText += "\nrandTilesXMLDialoguePath=" + self.randTilesXMLDialoguePath
        settingsText += "\nrandTilesBINDialoguePath=" + self.randTilesBINDialoguePath

        f = open("Other/settings.ini", 'w')
        f.write(settingsText)
        self.settingsWindow.hide()


    def settings(self):
        self.settingsWindow = QtWidgets.QWidget()
        self.description = QtWidgets.QLabel('Settings')
        font = self.description.font()
        font.setPointSize(18)
        font.setBold(True)
        self.description.setFont(font)

        self.tilesetDescription = QtWidgets.QLabel('Tilesets')
        self.tilesetPathBox = QtWidgets.QLineEdit(self.tilesetPath)
        self.tilesetPathBox.setPlaceholderText('Open this tileset on start ...')
        self.tilesetPathOpen = QtWidgets.QPushButton('Select')
        self.tilesetDialoguePathBox = QtWidgets.QLineEdit(self.tilesetDialoguePath)
        self.tilesetDialoguePathBox.setPlaceholderText('Start in this directory when opening/saving a tileset ...')
        self.tilesetDialoguePathOpen = QtWidgets.QPushButton('Select')
        self.animTilesDescription = QtWidgets.QLabel('AnimTiles')
        self.animTilesPathBox = QtWidgets.QLineEdit(self.animTilesPath)
        self.animTilesPathBox.setPlaceholderText('Open this AnimTiles.bin or .txt on start ...')
        self.animTilesPathOpen = QtWidgets.QPushButton('Select')
        self.animTilesTXTDialoguePathBox = QtWidgets.QLineEdit(self.animTilesTXTDialoguePath)
        self.animTilesTXTDialoguePathBox.setPlaceholderText('Start in this directory when opening/saving a AnimTiles.txt file ...')
        self.animTilesTXTDialoguePathOpen = QtWidgets.QPushButton('Select')
        self.animTilesBINDialoguePathBox = QtWidgets.QLineEdit(self.animTilesBINDialoguePath)
        self.animTilesBINDialoguePathBox.setPlaceholderText('Start in this directory when opening/saving a AnimTiles.bin file ...')
        self.animTilesBINDialoguePathOpen = QtWidgets.QPushButton('Select')
        self.randTilesDescription = QtWidgets.QLabel('RandTiles')
        self.randTilesPathBox = QtWidgets.QLineEdit(self.randTilesPath)
        self.randTilesPathBox.setPlaceholderText('Open this RandTiles.bin or tilesetinfo.xml on start ...')
        self.randTilesPathOpen = QtWidgets.QPushButton('Select')
        self.randTilesXMLDialoguePathBox = QtWidgets.QLineEdit(self.randTilesXMLDialoguePath)
        self.randTilesXMLDialoguePathBox.setPlaceholderText('Start in this directory when opening/saving a tilesetinfo.xml file ...')
        self.randTilesXMLDialoguePathOpen = QtWidgets.QPushButton('Select')
        self.randTilesBINDialoguePathBox = QtWidgets.QLineEdit(self.randTilesBINDialoguePath)
        self.randTilesBINDialoguePathBox.setPlaceholderText('Start in this directory when opening/saving a RandTiles.bin file ...')
        self.randTilesBINDialoguePathOpen = QtWidgets.QPushButton('Select')
        self.saveSettings = QtWidgets.QPushButton('Save')

        layout = QtWidgets.QGridLayout()
        layout.addWidget(self.description, 0, 0, 1, 4, Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self.tilesetDescription, 1, 0, 1, 4, Qt.AlignCenter)
        layout.addWidget(self.tilesetPathBox, 2, 0, 1, 3)
        layout.addWidget(self.tilesetPathOpen, 2, 3, 1, 1)
        layout.addWidget(self.tilesetDialoguePathBox, 3, 0, 1, 3)
        layout.addWidget(self.tilesetDialoguePathOpen, 3, 3, 1, 1)
        layout.addWidget(self.animTilesDescription, 4, 0, 1, 4, Qt.AlignCenter)
        layout.addWidget(self.animTilesPathBox, 5, 0, 1, 3)
        layout.addWidget(self.animTilesPathOpen, 5, 3, 1, 1)
        layout.addWidget(self.animTilesTXTDialoguePathBox, 6, 0, 1, 3)
        layout.addWidget(self.animTilesTXTDialoguePathOpen, 6, 3, 1, 1)
        layout.addWidget(self.animTilesBINDialoguePathBox, 7, 0, 1, 3)
        layout.addWidget(self.animTilesBINDialoguePathOpen, 7, 3, 1, 1)
        layout.addWidget(self.randTilesDescription, 8, 0, 1, 4, Qt.AlignCenter)
        layout.addWidget(self.randTilesPathBox, 9, 0, 1, 3)
        layout.addWidget(self.randTilesPathOpen, 9, 3, 1, 1)
        layout.addWidget(self.randTilesXMLDialoguePathBox, 10, 0, 1, 3)
        layout.addWidget(self.randTilesXMLDialoguePathOpen, 10, 3, 1, 1)
        layout.addWidget(self.randTilesBINDialoguePathBox, 11, 0, 1, 3)
        layout.addWidget(self.randTilesBINDialoguePathOpen, 11, 3, 1, 1)
        layout.addWidget(self.saveSettings, 12, 3, 1, 1)
        self.settingsWindow.setLayout(layout)

        self.tilesetPathOpen.released.connect(self.getTilesetPath)
        self.tilesetDialoguePathOpen.released.connect(self.getTilesetDialoguePath)
        self.animTilesPathOpen.released.connect(self.getAnimTilesPath)
        self.animTilesTXTDialoguePathOpen.released.connect(self.getTXTAnimTilesPathOpen)
        self.animTilesBINDialoguePathOpen.released.connect(self.getBINAnimTilesPathOpen)
        self.randTilesPathOpen.released.connect(self.getRandTilesPath)
        self.randTilesXMLDialoguePathOpen.released.connect(self.getXMLRandTilesPathOpen)
        self.randTilesBINDialoguePathOpen.released.connect(self.getBINRandTilesPathOpen)
        self.saveSettings.released.connect(self.saveIni)

        self.settingsWindow.setMinimumWidth(900)
        self.settingsWindow.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        self.settingsWindow.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.settingsWindow.setWindowTitle('Settings')
        self.settingsWindow.show()


    def getTilesetPath(self):
        path = QtWidgets.QFileDialog.getOpenFileName(self, "Choose a file ...", '', "Tileset (*.arc)")[0]
        if not path: return
        self.tilesetPathBox.setText(path)

    def getTilesetDialoguePath(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose a folder ...')
        if not path: return
        self.tilesetDialoguePathBox.setText(path)

    def getAnimTilesPath(self):
        path = QtWidgets.QFileDialog.getOpenFileName(self, "Choose a file ...", '', "AnimTiles.txt (*.txt);;AnimTiles.bin (*.bin)")[0]
        if not path: return
        self.animTilesPathBox.setText(path)

    def getTXTAnimTilesPathOpen(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose a folder ...')
        if not path: return
        self.animTilesTXTDialoguePathBox.setText(path)

    def getBINAnimTilesPathOpen(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose a folder ...')
        if not path: return
        self.animTilesBINDialoguePathBox.setText(path)

    def getRandTilesPath(self):
        path = QtWidgets.QFileDialog.getOpenFileName(self, "Choose a file ...", '', "tilesetinfo.xml (*.xml);;RandTiles.bin (*.bin)")[0]
        if not path: return
        self.randTilesPathBox.setText(path)

    def getXMLRandTilesPathOpen(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose a folder ...')
        if not path: return
        self.randTilesXMLDialoguePathBox.setText(path)

    def getBINRandTilesPathOpen(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose a folder ...')
        if not path: return
        self.randTilesBINDialoguePathBox.setText(path)


    def exportAllFramesheetsAsTpl(self):
        animationKeys = list(Tileset.animdata.keys())

        if len(animationKeys) == 0:
            QtWidgets.QMessageBox.warning(self, "Export framesheets",
                    "There are no opened framesheets to be exported!",
                    QtWidgets.QMessageBox.Cancel)
            return

        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose a folder for the export ...')
        if not path: return

        for anim in animationKeys:
            #get height -> 2 bytes per pixel and 32 pixel width
            height = '%0*X' % (4, len(Tileset.animdata[anim])//64)
            header = bytearray.fromhex(f"0020AF30000000010000000C0000001400000000{height}002000000005000000400000000000000000000000010000000100000000000000000000000000000000")
            outdata = header + Tileset.animdata[anim]

            if outdata is not None:
                f = open(f"{path}/{anim[7:-4]}.tpl", 'wb')
                f.write(outdata)


    def exportAllFramesheetsAsPng(self):
        if self.framesheetmodel.rowCount() == 0:
            QtWidgets.QMessageBox.warning(self, "Export framesheets",
                    "There are no opened framesheets to be exported!",
                    QtWidgets.QMessageBox.Cancel)
            return

        path = QtWidgets.QFileDialog.getExistingDirectory(self, 'Choose a folder for the export ...')
        if not path: return

        i = 0
        while i < self.framesheetmodel.rowCount():
            item = self.framesheetmodel.itemFromIndex(self.framesheetmodel.index(i, 0))
            icon = item.icon()
            name = item.text()
            pixmap = icon.pixmap(icon.availableSizes()[0])
            pixmap.save("{}/{}.png".format(path, name), "PNG")
            i += 1


    def createClampedFramesheet(self):
        path = QtWidgets.QFileDialog.getOpenFileName(self, "Open unclamped framesheet", '', "Unclamped Framesheet (*.png)")[0]

        if path:
            framesheet = QtGui.QPixmap()
            if not framesheet.load(path):
                QtWidgets.QMessageBox.warning(self, "Open framesheet", "The framesheet file could not be loaded.", QtWidgets.QMessageBox.Cancel)
                return

            if framesheet.height() % framesheet.width() != 0:
                QtWidgets.QMessageBox.information(self, "Warning!",
                        "There seem to be some pixels missing here.\n"
                        "Make sure that the height of your framesheet is a multiple of its' width!")

            downScaledFramesheet = framesheet.scaledToWidth(24)
            downScaledImage = downScaledFramesheet.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)

            image = QtGui.QImage(32, downScaledFramesheet.height() / 24 * 32, QtGui.QImage.Format_ARGB32)
            image.fill(Qt.transparent)

            i = 0
            while i < downScaledImage.height() // 24:
                y = 0
                while y < 24:
                    x = 0
                    while x < 24:
                        color = downScaledImage.pixel(x, y + i*24)
                        image.setPixel(x + 4, i * 32 + y + 4, color)
                        x += 1
                    y += 1

                y = 0                                                   #texture clamp top
                while y < 4:
                    x = 0
                    while x < 24:
                        color = image.pixel(x + 4, i * 32 + 5)
                        image.setPixel(x + 4, i * 32 + y, color)
                        x += 1
                    y += 1

                y = 0                                                   #texture clamp bottom
                while y < 4:
                    x = 0
                    while x < 24:
                        color = image.pixel(x + 4, i * 32 + 27)
                        image.setPixel(x + 4, i * 32 + y + 28, color)
                        x += 1
                    y += 1

                x = 0                                                   #texture clamp left
                while x < 4:
                    y = 0
                    while y < 24:
                        color = image.pixel(5, i * 32 + y + 4)
                        image.setPixel(x, i * 32 + y + 4, color)
                        y += 1
                    x += 1

                x = 0                                                   #texture clamp right
                while x < 4:
                    y = 0
                    while y < 24:
                        color = image.pixel(27, i * 32 + y + 4)
                        image.setPixel(x + 28, i * 32 + y + 4, color)
                        y += 1
                    x += 1

                i += 1

            fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Save the clamped framesheet', '', 'Clamped Framesheet (*.png)')[0]
            if not fn: return

            image.save(fn)

    '''
    def convertGifToFramesheets(self):
        path = QtWidgets.QFileDialog.getOpenFileName(self, "Open a gif file", '', "Animated Image (*.gif)")[0]
        im = Image.open(path)
        try:
            shutil.rmtree("temp")
            os.mkdir("temp")
        except:
            try:
                os.mkdir("temp")
            except:
                print("Couldn't initialize temp directory!")
                return

        for i in range(0, im.n_frames):
            im.seek(i)
            print(i)
            im.save("temp/{}.png".format(i))

        self.popup = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout()
        self.btn1 = QtWidgets.QPushButton("Import from AnimTiles tab")
        #self.btn1.released.connect(self.fromAnimTiles)


        self.info = QtWidgets.QLabel("Importing from the AnimTiles tab imports all entries with a matching texname.\n\nIt removes those entries from the AnimTiles tab!\n\nSo: don't forget to export after you finished editing!!!")
        self.info.setWordWrap(True)

        layout.addWidget(self.btn1, 0, 0, 1, 1)
        layout.addWidget(self.info, 1, 0, 1, 2)

        self.popup.setLayout(layout)
        self.popup.setWindowTitle("Import framesheet info")
        self.popup.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        self.popup.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.popup.show()
    '''

    def optimizeXml(self):
        #trying to replace all entries with their abbreviated equivalents
        text = self.randTilesEditor.text.toPlainText()
        text = text.replace('        <random list="0x10" values="0x10, 0x20, 0x30, 0x40" direction="vertical" />\n        <random list="0x20" values="0x10, 0x20, 0x30, 0x40" direction="vertical" />\n        <random list="0x30" values="0x10, 0x20, 0x30, 0x40" direction="vertical" />\n        <random list="0x40" values="0x10, 0x20, 0x30, 0x40" direction="vertical" />\n        <random list="0x11" values="0x11, 0x21, 0x31, 0x41" direction="vertical" />\n        <random list="0x21" values="0x11, 0x21, 0x31, 0x41" direction="vertical" />\n        <random list="0x31" values="0x11, 0x21, 0x31, 0x41" direction="vertical" />\n        <random list="0x41" values="0x11, 0x21, 0x31, 0x41" direction="vertical" />\n        <random range="0x2, 0x7" direction="horizontal" />\n        <random range="0x22, 0x27" direction="horizontal" />\n        <random range="0x12, 0x17" direction="both" />', '        <random name="regular-terrain" />')
        text = text.replace('        <random list="0x18" values="0x18, 0x28, 0x38, 0x48" direction="vertical" />\n        <random list="0x28" values="0x18, 0x28, 0x38, 0x48" direction="vertical" />\n        <random list="0x38" values="0x18, 0x28, 0x38, 0x48" direction="vertical" />\n        <random list="0x48" values="0x18, 0x28, 0x38, 0x48" direction="vertical" />\n        <random list="0x19" values="0x19, 0x29, 0x39, 0x49" direction="vertical" />\n        <random list="0x29" values="0x19, 0x29, 0x39, 0x49" direction="vertical" />\n        <random list="0x39" values="0x19, 0x29, 0x39, 0x49" direction="vertical" />\n        <random list="0x49" values="0x19, 0x29, 0x39, 0x49" direction="vertical" />\n        <random range="0xA, 0xF" direction="horizontal" />\n        <random range="0x2A, 0x2F" direction="horizontal" />\n        <random range="0x1A, 0x1F" direction="both" />', '        <random name="sub-terrain" />')

        # unfinished vertical randomization optimizer
        #root = etree.fromstring(xml)
        #for group in root:
        #    i = 0
        #    childrenNum = len(group.getchildren())
        #    for random in group:
        #        if 'list' in random.attrib and 'values' in random.attrib:
        #            j = 0
        #            list = list(map(lambda s: int(s, 0), random.attrib['list'].split(",")))
        #            if len(list) == 1:
        #                list = list[0]
        #                values = list(map(lambda s: int(s, 0), random.attrib['values'].split(",")))
        #                if i + len(values) < childrenNum:
        #                    while j < len(values):
        #                        
        #                        j += 1
        #                else:
        #                    break
        #        i += 1

        self.randTilesEditor.text.setPlainText(text)


    def createReadme(self):
        self.readmeWindow = QtWidgets.QWidget()
        self.textEditor = QCodeEditor.QCodeEditor()
        self.textEditor.setMinimumWidth(500)
        self.textPreview = QtWidgets.QTextBrowser()
        self.textPreview.setMinimumWidth(500)
        self.textPreview.setOpenExternalLinks(True)
        self.textPreview.verticalScrollBar().setEnabled(False)
        self.tutorials = QtWidgets.QLabel('Include tutorials:')
        self.includeTilesetTutorial = QtWidgets.QCheckBox('Tilesets')
        self.includeAnimationTutorial = QtWidgets.QCheckBox('Animations')
        self.includeRandomizationTutorial = QtWidgets.QCheckBox('Randomiszations')
        self.saveBtn = QtWidgets.QPushButton('Save')
        self.saveBtn.setMaximumWidth(200)
        layout = QtWidgets.QGridLayout()
        layout.addWidget(self.textEditor, 0, 0, 1, 2)
        layout.addWidget(self.textPreview, 0, 2, 1, 2)
        layout.addWidget(self.tutorials, 1, 0, 1, 1)
        layout.addWidget(self.includeTilesetTutorial, 1, 1, 1, 1)
        layout.addWidget(self.includeAnimationTutorial, 1, 2, 1, 1)
        layout.addWidget(self.includeRandomizationTutorial, 1, 3, 1, 1)
        layout.addWidget(self.saveBtn, 2, 0, 1, 4)
        layout.setRowMinimumHeight(0, 400)

        self.textEditor.textChanged.connect(self.updateReadmePreview)
        self.textEditor.cursorPositionChanged.connect(self.updateReadmePreviewScrollBar)
        self.textEditor.verticalScrollBar().valueChanged.connect(self.updateReadmePreviewScrollBar)
        #self.textPreview.verticalScrollBar().valueChanged.connect(self.updateReadmeEditorScrollBar)
        self.saveBtn.released.connect(self.saveReadme)

        self.readmeWindow.setLayout(layout)
        self.readmeWindow.setWindowTitle('Create readme.md')
        self.readmeWindow.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        self.readmeWindow.show()


    def updateReadmePreview(self):
        self.textPreview.setMarkdown(self.textEditor.toPlainText())
        self.updateReadmePreviewScrollBar()


    def updateReadmePreviewScrollBar(self, editorValue = None):
        s1 = self.textPreview.verticalScrollBar()
        s2 = self.textEditor.verticalScrollBar()
        if s2.maximum() - s2.minimum() < 1:
            return
        if not editorValue:
            editorValue = self.textEditor.verticalScrollBar().value()
        previewValue = (editorValue / (s2.maximum() - s2.minimum())) * (s1.maximum() - s1.minimum())
        s1.setValue(previewValue)


    def saveReadme(self):
        fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Save readme.md file', 'readme.md', 'Readme (*.md)')[0]
        if not fn: return

        readmeText = self.textEditor.toPlainText()
        if self.includeTilesetTutorial.isChecked():
            f = open("Other/tilesets.md", 'r')
            readmeText += "\n<br/><br/><br/>\n" + f.read()
        if self.includeAnimationTutorial.isChecked():
            f = open("Other/animations.md", 'r')
            readmeText += "\n<br/><br/><br/>\n" + f.read()
        if self.includeRandomizationTutorial.isChecked():
            f = open("Other/randomizations.md", 'r')
            readmeText += "\n<br/><br/><br/>\n" + f.read()

        f = open(fn, 'w')
        f.write(readmeText)


    def credits(self):
        class QCreditsDialog(QtWidgets.QDialog):
            def __init__(self):
                QtWidgets.QDialog.__init__(self)
                self.setWindowTitle('Credits')

                try:
                    with open('credits.md', 'r') as f:
                        credits = f.read()
                except:
                    credits = "The file 'credits.md' is missing!"

                logo = QtGui.QPixmap('Icons/about.png')
                logoLabel = QtWidgets.QLabel()
                logoLabel.setPixmap(logo)
                logoLabel.setContentsMargins(16, 4, 32, 4)

                creditsView = QtWidgets.QTextEdit()
                creditsView.setMinimumWidth(1000)
                creditsView.setMinimumHeight(500)
                creditsView.setMarkdown(credits)
                creditsView.setReadOnly(True)

                buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
                buttonBox.accepted.connect(self.accept)

                L = QtWidgets.QGridLayout()
                L.addWidget(logoLabel, 0, 0, 3, 1)
                L.addWidget(creditsView, 0, 1, 2, 1)
                L.addWidget(buttonBox, 2, 0, 1, 2)
                L.setRowStretch(1, 1)
                L.setColumnStretch(1, 1)
                self.setLayout(L)

        QCreditsDialog().exec_()


    def help(self):
        class QHelpDialog(QtWidgets.QDialog):
            def __init__(self):
                QtWidgets.QDialog.__init__(self)
                self.setWindowTitle('Help')

                try:
                    with open('Other/help.html', 'r') as f:
                        help = f.read()
                except:
                    help = "The file 'help.html' is missing!"

                logo = QtGui.QPixmap('Icons/about.png')
                logoLabel = QtWidgets.QLabel()
                logoLabel.setPixmap(logo)
                logoLabel.setContentsMargins(16, 4, 32, 4)

                helpView = QtWidgets.QTextBrowser()
                helpView.setMinimumWidth(750)
                helpView.setMinimumHeight(500)
                helpView.setHtml(help)
                helpView.setOpenExternalLinks(True)

                buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
                buttonBox.accepted.connect(self.accept)

                L = QtWidgets.QGridLayout()
                L.addWidget(logoLabel, 0, 0, 3, 1)
                L.addWidget(helpView, 0, 1, 2, 1)
                L.addWidget(buttonBox, 2, 0, 1, 2)
                L.setRowStretch(1, 1)
                L.setColumnStretch(1, 1)
                self.setLayout(L)

        QHelpDialog().exec_()


    def setuptile(self):
        self.tileWidget.tiles.clear()
        self.model.clear()

        if self.alpha == True:
            for tile in Tileset.tiles:
                self.model.addPieces(tile.image)
        else:
            for tile in Tileset.tiles:
                self.model.addPieces(tile.noalpha)


    def newTileset(self):
        '''Creates a new, blank tileset'''

        global Tileset
        Tileset.clear()
        Tileset = TilesetClass()

        global AnimTiles
        AnimTiles.clear()
        AnimTiles = AnimTilesClass()

        global frameEditorData
        frameEditorData = type('frameEditorClass', (), {})()
        frameEditorData.animations = {}

        global RandTiles
        RandTiles.clear()
        RandTiles = RandTilesClass()

        EmptyPix = QtGui.QPixmap(24, 24)
        EmptyPix.fill(Qt.black)

        for i in range(256):
            Tileset.addTile(EmptyPix, EmptyPix)

        self.tileWidget.tilesetType.setText('Pa0')

        self.setuptile()
        self.clearObjects()

        self.setWindowTitle('New Tileset')

        index = self.framesheetList.currentIndex()
        if not index.isValid():
            self.frameEditor.setEnabled(False)
            self.frameEditor.table.setRowCount(0)


    def openTileset(self):
        '''Asks the user for a filename, then calls openTilesetFromPath().'''

        path = QtWidgets.QFileDialog.getOpenFileName(self, "Open NSMBW Tileset", window.tilesetDialoguePath, "Tileset Files (*.arc)")[0]

        if path:
            self.openTilesetFromPath(path)


    def openTilesetFromPath(self, path):
        '''Opens a Nintendo tileset arc and parses the heck out of it.'''
        if path in self.recentFiles:
            self.recentFiles.insert(0, self.recentFiles.pop(self.recentFiles.index(path)))
        else:
            self.recentFiles.insert(0, path)
            while len(self.recentFiles) > MainWindow.MaxRecentFiles:
                del self.recentFiles[9]
        self.saveRececntFiles()
        self.updateRecentFileActions()

        self.setWindowTitle(os.path.basename(path))
        Tileset.clear()

        name = path[str(path).rfind('/')+1:-4]

        with open(path,'rb') as file:
            data = file.read()

        arc = archive.U8()
        arc._load(data)

        Image = None
        behaviourdata = None
        objstrings = None
        metadata = None

        for key, value in arc.files:
            if value is None:
                continue
            elif key.startswith('BG_tex/') and key.endswith('_tex.bin.LZ'):
                Image = arc[key]
            elif key.startswith('BG_tex/') and key.endswith('.bin'):
                Tileset.animdata[key] = arc[key]
            elif key.startswith('BG_chk/d_bgchk_') and key.endswith('.bin'):
                behaviourdata = arc[key]
            elif key.startswith('BG_unt/') and key.endswith('_hd.bin'):
                metadata = arc[key]
            elif key.startswith('BG_unt/') and key.endswith('.bin'):
                objstrings = arc[key]
            else:
                Tileset.unknownFiles[key] = arc[key]

        if (Image is None) or (behaviourdata is None) or (objstrings is None) or (metadata is None):
            QtWidgets.QMessageBox.warning(None, 'Error',  'Error - the necessary files were not found.\n\nNot a valid tileset, sadly.')
            return

        # Stolen from Reggie! Loads the Image Data.
        if HaveNSMBLib:
            tiledata = nsmblib.decompress11LZS(Image)
            argbdata = nsmblib.decodeTileset(tiledata)
            dest = QtGui.QImage(argbdata, 1024, 256, 4096, QtGui.QImage.Format_ARGB32)
            if hasattr(nsmblib, 'decodeTilesetNoAlpha'):
                rgbdata = nsmblib.decodeTilesetNoAlpha(tiledata)
                noalphadest = QtGui.QImage(rgbdata, 1024, 256, 4096, QtGui.QImage.Format_ARGB32)
            else:
                noalphadest = RGB4A3Decode(tiledata, False)
        else:
            lz = lz77.LZS11()
            decomp = lz.Decompress11LZS(Image)
            dest = RGB4A3Decode(decomp)
            noalphadest = RGB4A3Decode(decomp, False)

        tileImage = QtGui.QPixmap.fromImage(dest)
        noalpha = QtGui.QPixmap.fromImage(noalphadest)

        # Loads Tile Behaviours

        behaviours = []
        for entry in range(256):
            behaviours.append(struct.unpack_from('>8B', behaviourdata, entry*8))


        # Makes us some nice Tile Classes!
        Xoffset = 4
        Yoffset = 4
        for i in range(256):
            Tileset.addTile(tileImage.copy(Xoffset,Yoffset,24,24), noalpha.copy(Xoffset,Yoffset,24,24), behaviours[i])
            Xoffset += 32
            if Xoffset >= 1024:
                Xoffset = 4
                Yoffset += 32


        # Load Objects

        meta = []
        for i in range(len(metadata) // 4):
            meta.append(struct.unpack_from('>H2B', metadata, i * 4))

        tilelist = [[]]
        upperslope = [0, 0]
        lowerslope = [0, 0]
        byte = 0

        for entry in meta:
            offset = entry[0]
            byte = struct.unpack_from('>B', objstrings, offset)[0]
            row = 0

            while byte != 0xFF:

                if byte == 0xFE:
                    tilelist.append([])

                    if (upperslope[0] != 0) and (lowerslope[0] == 0):
                        upperslope[1] = upperslope[1] + 1

                    if lowerslope[0] != 0:
                        lowerslope[1] = lowerslope[1] + 1

                    offset += 1
                    byte = struct.unpack_from('>B', objstrings, offset)[0]

                elif (byte & 0x80):

                    if upperslope[0] == 0:
                        upperslope[0] = byte
                    else:
                        lowerslope[0] = byte

                    offset += 1
                    byte = struct.unpack_from('>B', objstrings, offset)[0]

                else:
                    tilelist[-1].append(struct.unpack_from('>3B', objstrings, offset))

                    offset += 3
                    byte = struct.unpack_from('>B', objstrings, offset)[0]

            tilelist.pop()

            if (upperslope[0] & 0x80) and (upperslope[0] & 0x2):
                for i in range(lowerslope[1]):
                    pop = tilelist.pop()
                    tilelist.insert(0, pop)

            Tileset.addObject(entry[2], entry[1], upperslope, lowerslope, tilelist)

            tilelist = [[]]
            upperslope = [0, 0]
            lowerslope = [0, 0]

        if Tileset.objects:
            slots = []
            for object in Tileset.objects:
                for row in object.tiles:
                    for tile in row:
                        slot = tile[2] & 3
                        if slot != 0 or tile[1] != 0:
                            slots.append(slot)

            if not slots:
                Tileset.slot = 0
            else:
                Tileset.slot = max(slots, key=slots.count)
            del slots

            if name[:4] in ('Pa0_', 'Pa1_', 'Pa2_', 'Pa3_'):
                slot = int(name[2])
                if slot != Tileset.slot:
                    QtWidgets.QMessageBox.information(self, "Warning", "Determined tileset slot ({}) does not match with the slot in the filename ({})!".format(Tileset.slot, slot))

            else:
                print("WARNING: Tileset name does not begin with \"PaX_\". Unable to verify tileset slot.")


        else:
            Tileset.slot = 1

        self.tileWidget.tilesetType.setText('Pa{0}'.format(Tileset.slot))

        self.setuptile()
        SetupObjectModel(self.objmodel, Tileset.objects, Tileset.tiles)
        SetupFramesheetModel(self, Tileset.animdata)

        self.objectList.clearCurrentIndex()
        self.tileWidget.setObject(self.objectList.currentIndex())

        self.objectList.update()
        self.tileWidget.update()

        self.frameEditor.table.clearContents()
        self.frameEditor.table.setRowCount(0)
        modelindex = self.framesheetList.currentIndex().sibling(-1, 0)
        self.framesheetList.setCurrentIndex(modelindex)

        self.name = path




    def openImage(self):
        '''Opens an Image from png, and creates a new tileset from it.'''

        path = QtWidgets.QFileDialog.getOpenFileName(self, "Open Image", '',
                    "Image Files (*.png)")[0]

        if not path: return

        tileImage = QtGui.QPixmap()
        if not tileImage.load(path):
            QtWidgets.QMessageBox.warning(self, "Open Image",
                    "The image file could not be loaded.",
                    QtWidgets.QMessageBox.Cancel)
            return


        if tileImage.width() != 384 or tileImage.height() != 384:
            QtWidgets.QMessageBox.warning(self, "Open Image",
                    "The image has incorrect dimensions. "
                    "Please resize the image to 384x384 pixels.",
                    QtWidgets.QMessageBox.Cancel)
            return

        noalphaImage = QtGui.QPixmap(384, 384)
        noalphaImage.fill(Qt.black)
        p = QtGui.QPainter(noalphaImage)
        p.drawPixmap(0, 0, tileImage)
        p.end()
        del p

        x = 0
        y = 0
        for i in range(256):
            Tileset.tiles[i].image = tileImage.copy(x*24,y*24,24,24)
            Tileset.tiles[i].noalpha = noalphaImage.copy(x*24,y*24,24,24)
            x += 1
            if (x * 24) >= 384:
                y += 1
                x = 0

        index = self.objectList.currentIndex()

        self.setuptile()
        SetupObjectModel(self.objmodel, Tileset.objects, Tileset.tiles)

        self.objectList.setCurrentIndex(index)
        self.tileWidget.setObject(index)

        self.objectList.update()
        self.tileWidget.update()


    def saveImage(self):

        fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Choose a new filename', '', '.png (*.png)')[0]
        if not fn: return

        tex = QtGui.QPixmap(384, 384)
        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        Xoffset = 0
        Yoffset = 0

        for tile in Tileset.tiles:
            painter.drawPixmap(Xoffset, Yoffset, tile.image)
            Xoffset += 24
            if Xoffset >= 384:
                Xoffset = 0
                Yoffset += 24

        painter.end()

        tex.save(fn)


    def saveTileset(self):
        if not self.name:
            self.saveTilesetAs()
            return

        outdata = self.saving(os.path.basename(self.name)[:-4])

        if outdata is not None:
            fn = self.name
            with open(fn, 'wb') as f:
                f.write(outdata)


    def saveTilesetAs(self):

        fn = QtWidgets.QFileDialog.getSaveFileName(self, 'Choose a new filename', window.tilesetDialoguePath, '.arc (*.arc)')[0]
        if not fn: return

        outdata = self.saving(os.path.basename(str(fn))[:-4])

        if outdata is not None:
            self.name = fn
            self.setWindowTitle(os.path.basename(str(fn)))

            with open(fn, 'wb') as f:
                f.write(outdata)


    def saving(self, name):

        # Prepare tiles, objects, object metadata, and textures and stuff into buffers.

        textureBuffer = self.PackTexture()

        if textureBuffer is None:
            # The user canceled the saving process in the "use nsmblib?" dialog
            return None

        tileBuffer = self.PackTiles()
        objectBuffers = self.PackObjects()
        objectBuffer = objectBuffers[0]
        objectMetaBuffer = objectBuffers[1]


        # Make an arc and pack up the files!

        # NOTE: adding the files/folders to the U8 object in
        # alphabetical order is a simple workaround for a wii.py... bug?
        # unintuitive quirk? Whatever. Fixes one of the issues listed
        # in GitHub issue #3 (in the RoadrunnerWMC/Puzzle-Updated repo)

        arcFiles = {}
        arcFiles['BG_tex'] = None
        arcFiles['BG_tex/{0}_tex.bin.LZ'.format(name)] = textureBuffer

        arcFiles['BG_chk'] = None
        arcFiles['BG_chk/d_bgchk_{0}.bin'.format(name)] = tileBuffer

        arcFiles['BG_unt'] = None
        arcFiles['BG_unt/{0}.bin'.format(name)] = objectBuffer
        arcFiles['BG_unt/{0}_hd.bin'.format(name)] = objectMetaBuffer

        self.sortedAnimdata = sorted(Tileset.animdata.items())
        arcFiles.update(self.sortedAnimdata)

        arcFiles.update(Tileset.unknownFiles)

        arc = archive.U8()
        for name in sorted(arcFiles):
            arc[name] = arcFiles[name]
        return arc._dump()


    def PackTexture(self):

        tex = QtGui.QImage(1024, 256, QtGui.QImage.Format_ARGB32)
        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        Xoffset = 0
        Yoffset = 0

        for tile in Tileset.tiles:
            minitex = QtGui.QImage(32, 32, QtGui.QImage.Format_ARGB32)
            minitex.fill(Qt.transparent)
            minipainter = QtGui.QPainter(minitex)

            minipainter.drawPixmap(4, 4, tile.image)
            minipainter.end()

            # Read colours and DESTROY THEM (or copy them to the edges, w/e)
            for i in range(4,28):

                # Top Clamp
                colour = minitex.pixel(i, 4)
                for p in range(0,5):
                    minitex.setPixel(i, p, colour)

                # Left Clamp
                colour = minitex.pixel(4, i)
                for p in range(0,5):
                    minitex.setPixel(p, i, colour)

                # Right Clamp
                colour = minitex.pixel(i, 27)
                for p in range(27,32):
                    minitex.setPixel(i, p, colour)

                # Bottom Clamp
                colour = minitex.pixel(27, i)
                for p in range(27,32):
                    minitex.setPixel(p, i, colour)

            # UpperLeft Corner Clamp
            colour = minitex.pixel(4, 4)
            for x in range(0,5):
                for y in range(0,5):
                    minitex.setPixel(x, y, colour)

            # UpperRight Corner Clamp
            colour = minitex.pixel(27, 4)
            for x in range(27,32):
                for y in range(0,5):
                    minitex.setPixel(x, y, colour)

            # LowerLeft Corner Clamp
            colour = minitex.pixel(4, 27)
            for x in range(0,5):
                for y in range(27,32):
                    minitex.setPixel(x, y, colour)

            # LowerRight Corner Clamp
            colour = minitex.pixel(27, 27)
            for x in range(27,32):
                for y in range(27,32):
                    minitex.setPixel(x, y, colour)


            painter.drawImage(Xoffset, Yoffset, minitex)

            Xoffset += 32

            if Xoffset >= 1024:
                Xoffset = 0
                Yoffset += 32

        painter.end()

        dest = RGB4A3Encode(tex)

        useNSMBLib = HaveNSMBLib and hasattr(nsmblib, 'compress11LZS')

        if useNSMBLib:
            # There are two versions of nsmblib floating around: the original
            # one, where the compression doesn't work correctly, and a fixed one
            # with correct compression.
            # We're going to show a warning to the user if they have the broken one installed.
            # To detect which one it is, we use the following test data:
            COMPRESSION_TEST = b'\0\1\0\0\0\0\0\0\0\1\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0'

            # The original broken algorithm compresses that incorrectly.
            # So let's compress it, and then decompress it, and see if we
            # got the right output.
            compressionWorking = (nsmblib.decompress11LZS(nsmblib.compress11LZS(COMPRESSION_TEST)) == COMPRESSION_TEST)

            if not compressionWorking:
                # NSMBLib is available, but only with the broken compression algorithm,
                # so the user can choose whether to use it or not

                items = ("Slow Compression, Good Quality", "Fast Compression, but the Image gets damaged")

                item, ok = QtWidgets.QInputDialog.getItem(self, "Choose compression method",
                        "Two methods of compression are available. Choose<br />"
                        "Fast compression for rapid testing. Choose slow<br />"
                        "compression for releases.<br />"
                        "<br />"
                        "To fix the fast compression, download and install<br />"
                        "NSMBLib-Updated (\"pip uninstall nsmblib\", \"pip<br />"
                        "install nsmblib\").\n", items, 0, False)
                if not ok:
                    return None

                if item == "Slow Compression, Good Quality":
                    useNSMBLib = False
                else:
                    useNSMBLib = True

        else:
            # NSMBLib is not available, so we have to use the Python version
            useNSMBLib = False

        if useNSMBLib:
            TexBuffer = nsmblib.compress11LZS(dest)
        else:
            lz = lz77.LZS11()
            TexBuffer = lz.Compress11LZS(dest)

        return TexBuffer


    def PackTiles(self):
        offset = 0
        tilespack = struct.Struct('>8B')
        Tilebuffer = create_string_buffer(2048)
        for tile in Tileset.tiles:
            tilespack.pack_into(Tilebuffer, offset, tile.byte0, tile.byte1, tile.byte2, tile.byte3, tile.byte4, tile.byte5, tile.byte6, tile.byte7)
            offset += 8

        return Tilebuffer.raw


    def PackObjects(self):
        objectStrings = []

        o = 0
        for object in Tileset.objects:


            # Slopes
            if object.upperslope[0] != 0:

                # Reverse Slopes
                if object.upperslope[0] & 0x2:
                    a = struct.pack('>B', object.upperslope[0])

                    for row in range(object.lowerslope[1], object.height):
                        for tile in object.tiles[row]:
                            a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                        a += b'\xfe'

                    if object.height > 1 and object.lowerslope[1]:
                        a += struct.pack('>B', object.lowerslope[0])

                        for row in range(0, object.lowerslope[1]):
                            for tile in object.tiles[row]:
                                a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                            a += b'\xfe'

                    a += b'\xff'

                    objectStrings.append(a)


                # Regular Slopes
                else:
                    a = struct.pack('>B', object.upperslope[0])

                    for row in range(0, object.upperslope[1]):
                        for tile in object.tiles[row]:
                            a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                        a += b'\xfe'

                    if object.height > 1 and object.lowerslope[1]:
                        a += struct.pack('>B', object.lowerslope[0])

                        for row in range(object.upperslope[1], object.height):
                            for tile in object.tiles[row]:
                                a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                            a += b'\xfe'

                    a += b'\xff'

                    objectStrings.append(a)


            # Not slopes!
            else:
                a = b''

                for tilerow in object.tiles:
                    for tile in tilerow:
                        a += struct.pack('>BBB', tile[0], tile[1], tile[2])

                    a += b'\xfe'

                a += b'\xff'

                objectStrings.append(a)

            o += 1

        Objbuffer = b''
        Metabuffer = b''
        i = 0
        for a in objectStrings:
            Metabuffer += struct.pack('>H2B', len(Objbuffer), Tileset.objects[i].width, Tileset.objects[i].height)
            Objbuffer += a

            i += 1

        return (Objbuffer, Metabuffer)


    def setupMenus(self):
        def get(name):
            """
            Returns an icon
            """
            try:
                return QtGui.QIcon('MenuIcons/icon-' + name + '.png')
            except:
                return None

        fileMenu = self.menuBar().addMenu("&File")

        self.action = fileMenu.addAction(get('new'), "New", self.newTileset, QtGui.QKeySequence('Ctrl+N'))
        fileMenu.addAction(get('open'), "Open Tileset", self.openTileset, QtGui.QKeySequence('Ctrl+O'))
        self.recentMenu = fileMenu.addMenu(get('open'), "Open recent Tileset")
        fileMenu.addAction(get('import'), "Import Image", self.openImage, QtGui.QKeySequence('Ctrl+I'))
        fileMenu.addAction(get('export'), "Export Image", self.saveImage, QtGui.QKeySequence('Ctrl+E'))
        fileMenu.addAction(get('save'), "Save Tileset", self.saveTileset, QtGui.QKeySequence('Ctrl+S'))
        fileMenu.addAction(get('saveas'), "Save Tileset as", self.saveTilesetAs, QtGui.QKeySequence('Ctrl+Shift+S'))
        fileMenu.addAction(get('exit'), "Quit", self.close, QtGui.QKeySequence('Ctrl+Q'))
        fileMenu.addAction(get('settings'), "Settings", self.settings, QtGui.QKeySequence('Ctrl+P'))

        fileMenu.addSeparator()
        nsmblibAct = fileMenu.addAction('Using NSMBLib' if HaveNSMBLib else 'Not using NSMBLib')
        nsmblibAct.setEnabled(False)

        taskMenu = self.menuBar().addMenu("&Tasks")

        taskMenu.addAction("Set Tileset Slot", self.setSlot, QtGui.QKeySequence('Ctrl+T'))
        taskMenu.addAction("Clear Collision Data", self.clearCollisions, QtGui.QKeySequence('Ctrl+Shift+Backspace'))
        taskMenu.addAction("Clear Object Data", self.clearObjects, QtGui.QKeySequence('Ctrl+Alt+Backspace'))
        taskMenu.addAction("Export all objects", self.saveAllObjects)
        taskMenu.addAction("Switch objects", self.switchObjects)

        animMenu = self.menuBar().addMenu("&Animations")
        animMenu.addAction("Export all framesheets as .tpl", self.exportAllFramesheetsAsTpl, QtGui.QKeySequence('Ctrl+F'))
        animMenu.addAction("Export all framesheets as .png", self.exportAllFramesheetsAsPng, QtGui.QKeySequence('Ctrl+Shift+F'))
        animMenu.addAction("Create clamped framesheet", self.createClampedFramesheet, QtGui.QKeySequence('Ctrl+Shift+C'))
        #animMenu.addAction("Convert gif to framesheet(s)", self.convertGifToFramesheets, QtGui.QKeySequence('Ctrl+G'))

        randMenu = self.menuBar().addMenu("&Randomizations")
        randMenu.addAction("Optimize opened xml", self.optimizeXml)

        otherMenu = self.menuBar().addMenu("&Other")
        otherMenu.addAction("Create readme.md", self.createReadme)
        otherMenu.addAction("Help", self.help)
        #otherMenu.addSeparator()
        #otherMenu.addAction("Credits", self.credits)

        for i in range(MainWindow.MaxRecentFiles):
            self.recentFileActs.append(QtWidgets.QAction(self, visible=False, triggered=self.openRecentFile))

        for i in range(MainWindow.MaxRecentFiles):
            self.recentMenu.addAction(self.recentFileActs[i])


    def updateRecentFileActions(self):
        numRecentFiles = min(len(self.recentFiles), MainWindow.MaxRecentFiles)

        if numRecentFiles == 0:
            self.recentMenu.setEnabled(False)
        else:
            self.recentMenu.setEnabled(True)

        for i in range(numRecentFiles):
            text = "&%d %s" % (i + 1, self.strippedName(self.recentFiles[i]))
            self.recentFileActs[i].setText(text)
            self.recentFileActs[i].setData(self.recentFiles[i])
            self.recentFileActs[i].setVisible(True)

        for j in range(numRecentFiles, MainWindow.MaxRecentFiles):
            self.recentFileActs[j].setVisible(False)


    def openRecentFile(self):
        action = self.sender()
        if action:
            self.openTilesetFromPath(action.data())


    def strippedName(self, fullFileName):
        return QtCore.QFileInfo(fullFileName).fileName()


    def setSlot(self):
        global Tileset

        items = ("Pa0", "Pa1", "Pa2", "Pa3")

        item, ok = QtWidgets.QInputDialog.getItem(self, "Set Tileset Slot",
                "Warning: \n    Setting the tileset slot will override any \n    tiles set to draw from other tilesets.\n\nCurrent slot is Pa%d" % Tileset.slot, items, 0, False)
        if ok and item:
            Tileset.slot = int(item[2])
            self.tileWidget.tilesetType.setText(item)

            self.updateInfo(0, 0)

            cobj = 0
            crow = 0
            ctile = 0
            for object in Tileset.objects:
                for row in object.tiles:
                    for tile in row:
                        if (tile[2] & 3) != 0 or tile[1] != 0:
                            Tileset.objects[cobj].tiles[crow][ctile] = (tile[0], tile[1], (tile[2] & 0xFC) | int(str(item[2])))
                        ctile += 1
                    crow += 1
                    ctile = 0
                cobj += 1
                crow = 0
                ctile = 0


    def toggleAlpha(self):
        # Replace Alpha Image with non-Alpha images in model
        self.alpha = not self.alpha

        self.setuptile()

        self.tileWidget.setObject(self.objectList.currentIndex())
        self.tileWidget.update()


    def importObjFromFile(self):
        usedTiles = Tileset.getUsedTiles()
        if len(usedTiles) >= 256:  # It can't be more than 256, oh well
            QtWidgets.QMessageBox.warning(self, "Open Object",
                    "There isn't enough room in the Tileset.",
                    QtWidgets.QMessageBox.Cancel)
            return

        file = QtWidgets.QFileDialog.getOpenFileName(self, "Open Object", '',
                    "Object files (*.json)")[0]

        if not file: return

        with open(file) as inf:
            jsonData = json.load(inf)

        dir = os.path.dirname(file)

        tilelist = [[]]
        upperslope = [0, 0]
        lowerslope = [0, 0]

        metaData = open(dir + "/" + jsonData["meta"], "rb").read()
        objstrings = open(dir + "/" + jsonData["objlyt"], "rb").read()
        colls = open(dir + "/" + jsonData["colls"], "rb").read()

        tilesUsed = []

        pos = 0
        while objstrings[pos] != 0xFF:
            if objstrings[pos] & 0x80:
                pos += 1
                continue

            tile = objstrings[pos:pos+3]
            if tile != b'\0\0\0':
                if tile[1] not in tilesUsed:
                    tilesUsed.append(tile[1])

            pos += 3

        numTiles = len(tilesUsed)

        if numTiles + len(usedTiles) > 256:
            QtWidgets.QMessageBox.warning(self, "Open Object",
                    "There isn't enough room for the object.",
                    QtWidgets.QMessageBox.Cancel)
            return

        freeTiles = [i for i in range(256) if i not in usedTiles]

        tilesUsed = {}

        offset = 0
        byte = struct.unpack_from('>B', objstrings, offset)[0]
        i = 0
        row = 0

        while byte != 0xFF:

            if byte == 0xFE:
                tilelist.append([])

                if (upperslope[0] != 0) and (lowerslope[0] == 0):
                    upperslope[1] = upperslope[1] + 1

                if lowerslope[0] != 0:
                    lowerslope[1] = lowerslope[1] + 1

                offset += 1
                byte = struct.unpack_from('>B', objstrings, offset)[0]

            elif (byte & 0x80):

                if upperslope[0] == 0:
                    upperslope[0] = byte
                else:
                    lowerslope[0] = byte

                offset += 1
                byte = struct.unpack_from('>B', objstrings, offset)[0]

            else:
                tileBytes = objstrings[offset:offset + 3]
                if tileBytes == b'\0\0\0':
                    tile = [0, 0, 0]

                else:
                    tile = []
                    tile.append(byte)

                    if tileBytes[1] not in tilesUsed:
                        tilesUsed[tileBytes[1]] = i
                        tile.append(freeTiles[i])
                        i += 1
                    else:
                        tile.append(freeTiles[tilesUsed[tileBytes[1]]])

                    byte2 = (struct.unpack_from('>B', objstrings, offset + 2)[0]) & 0xFC
                    byte2 |= Tileset.slot
                    tile.append(byte2)

                tilelist[-1].append(tile)

                offset += 3
                byte = struct.unpack_from('>B', objstrings, offset)[0]

        tilelist.pop()

        if (upperslope[0] & 0x80) and (upperslope[0] & 0x2):
            for i in range(lowerslope[1]):
                pop = tilelist.pop()
                tilelist.insert(0, pop)

        Tileset.addObject(metaData[3], metaData[2], upperslope, lowerslope, tilelist)

        count = len(Tileset.objects)

        object = Tileset.objects[count-1]

        tileImage = QtGui.QPixmap(dir + "/" + jsonData["img"])

        tex = QtGui.QPixmap(object.width * 24, object.height * 24)
        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        Xoffset = 0
        Yoffset = 0

        colls_off = 0

        tilesReplaced = []

        for row in object.tiles:
            for tile in row:
                if tile[2] & 3 or not Tileset.slot:
                    if tile[1] not in tilesReplaced:
                        tilesReplaced.append(tile[1])

                        Tileset.tiles[tile[1]].image = tileImage.copy(Xoffset,Yoffset,24,24)
                        Tileset.tiles[tile[1]].byte0 = colls[colls_off]
                        colls_off += 1
                        Tileset.tiles[tile[1]].byte1 = colls[colls_off]
                        colls_off += 1
                        Tileset.tiles[tile[1]].byte2 = colls[colls_off]
                        colls_off += 1
                        Tileset.tiles[tile[1]].byte3 = colls[colls_off]
                        colls_off += 1
                        Tileset.tiles[tile[1]].byte4 = colls[colls_off]
                        colls_off += 1
                        Tileset.tiles[tile[1]].byte5 = colls[colls_off]
                        colls_off += 1
                        Tileset.tiles[tile[1]].byte6 = colls[colls_off]
                        colls_off += 1
                        Tileset.tiles[tile[1]].byte7 = colls[colls_off]
                        colls_off += 1

                    painter.drawPixmap(Xoffset, Yoffset, Tileset.tiles[tile[1]].image)
                Xoffset += 24
            Xoffset = 0
            Yoffset += 24

        painter.end()

        self.setuptile()

        self.objmodel.appendRow(QtGui.QStandardItem(QtGui.QIcon(tex), 'Object {0}'.format(count-1)))

        index = self.objectList.currentIndex()
        self.objectList.setCurrentIndex(index)
        self.objectList.setCurrentIndex(index)
        self.tileWidget.setObject(index)

        self.objectList.update()
        self.tileWidget.update()


    def switchObjects(self):
        self.switchObjectsWindow = QtWidgets.QWidget()
        self.object1label = QtWidgets.QLabel("1st Object:")
        self.object1spin = QtWidgets.QSpinBox()
        self.object1spin.setRange(0, len(Tileset.objects)-1)
        self.object2label = QtWidgets.QLabel("2nd Object:")
        self.object2spin = QtWidgets.QSpinBox()
        self.object2spin.setRange(0, len(Tileset.objects)-1)
        self.objectOkButton = QtWidgets.QPushButton("Switch")

        layout = QtWidgets.QGridLayout()
        layout.addWidget(self.object1label, 0, 0, 1, 1)
        layout.addWidget(self.object1spin, 0, 1, 1, 1)
        layout.addWidget(self.object2label, 0, 2, 1, 1)
        layout.addWidget(self.object2spin, 0, 3, 1, 1)
        layout.addWidget(self.objectOkButton, 1, 0, 1, 4)
        self.switchObjectsWindow.setLayout(layout)

        self.objectOkButton.released.connect(self.actuallySwitchObjects)

        self.switchObjectsWindow.setWindowTitle('Switch Objects')
        self.switchObjectsWindow.setFixedSize(self.switchObjectsWindow.sizeHint())
        self.switchObjectsWindow.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
        self.switchObjectsWindow.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.switchObjectsWindow.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.switchObjectsWindow.show()


    def actuallySwitchObjects(self):
        self.switchObjectsWindow.hide()
        temp = Tileset.objects[self.object1spin.value()]
        Tileset.objects[self.object1spin.value()] = Tileset.objects[self.object2spin.value()]
        Tileset.objects[self.object2spin.value()] = temp

        index = self.objectList.currentIndex()
        self.objectList.clearCurrentIndex()
        SetupObjectModel(self.objmodel, Tileset.objects, Tileset.tiles)
        self.objectList.setCurrentIndex(self.objmodel.index(index.row(), index.column()))
        self.objectList.update()


    def saveAllObjects(self):
        tile_name = (os.path.basename(self.name) if self.name else 'NewTileset')

        save_path = QtWidgets.QFileDialog.getExistingDirectory(None, "Choose where to save the Object folder")
        if not save_path: return

        for object in Tileset.objects:
            object.jsonData = {}

        count = 0
        for object in Tileset.objects:
            tex = QtGui.QPixmap(object.width * 24, object.height * 24)
            tex.fill(Qt.transparent)
            painter = QtGui.QPainter(tex)

            Xoffset = 0
            Yoffset = 0

            Tilebuffer = b''

            for i in range(len(object.tiles)):
                for tile in object.tiles[i]:
                    if (Tileset.slot == 0) or ((tile[2] & 3) != 0):
                        painter.drawPixmap(Xoffset, Yoffset, Tileset.tiles[tile[1]].image)
                    Tilebuffer += (Tileset.tiles[tile[1]].byte0).to_bytes(1, 'big')
                    Tilebuffer += (Tileset.tiles[tile[1]].byte1).to_bytes(1, 'big')
                    Tilebuffer += (Tileset.tiles[tile[1]].byte2).to_bytes(1, 'big')
                    Tilebuffer += (Tileset.tiles[tile[1]].byte3).to_bytes(1, 'big')
                    Tilebuffer += (Tileset.tiles[tile[1]].byte4).to_bytes(1, 'big')
                    Tilebuffer += (Tileset.tiles[tile[1]].byte5).to_bytes(1, 'big')
                    Tilebuffer += (Tileset.tiles[tile[1]].byte6).to_bytes(1, 'big')
                    Tilebuffer += (Tileset.tiles[tile[1]].byte7).to_bytes(1, 'big')
                    Xoffset += 24
                Xoffset = 0
                Yoffset += 24

            painter.end()

            # Slopes
            if object.upperslope[0] != 0:

                # Reverse Slopes
                if object.upperslope[0] & 0x2:
                    a = struct.pack('>B', object.upperslope[0])

                    if object.height == 1:
                        iterationsA = 0
                        iterationsB = 1
                    else:
                        iterationsA = object.upperslope[1]
                        iterationsB = object.lowerslope[1] + object.upperslope[1]

                    for row in range(iterationsA, iterationsB):
                        for tile in object.tiles[row]:
                            a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                        a += b'\xfe'

                    if object.height > 1:
                        a += struct.pack('>B', object.lowerslope[0])

                        for row in range(0, object.upperslope[1]):
                            for tile in object.tiles[row]:
                                a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                            a += b'\xfe'

                    a += b'\xff'


                # Regular Slopes
                else:
                    a = struct.pack('>B', object.upperslope[0])

                    #for row in range(0, object.upperslope[1]):
                    #    for tile in object.tiles[row]:
                    #        a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                    #    a += b'\xfe'

                    if object.height > 1:
                        a += struct.pack('>B', object.lowerslope[0])

                        for row in range(object.upperslope[1], object.height):
                            for tile in object.tiles[row]:
                                a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                            a += b'\xfe'

                    a += b'\xff'


            # Not slopes!
            else:
                a = b''

                for tilerow in object.tiles:
                    for tile in tilerow:
                        a += struct.pack('>BBB', tile[0], tile[1], tile[2])

                    a += b'\xfe'

                a += b'\xff'

            Objbuffer = a
            Metabuffer = struct.pack('>HBB', (0 if count == 0 else len(Objbuffer)), object.width, object.height)

            if not os.path.isdir(save_path + "/" + tile_name + "_objects"):
                os.mkdir(save_path + "/" + tile_name + "_objects")

            tex.save(save_path + "/" + tile_name + "_objects" + "/" + tile_name + "_object_" + str(count) + ".png", "PNG")

            object.jsonData['img'] = tile_name + "_object_" + str(count) + ".png"

            with open(save_path + "/" + tile_name + "_objects" + "/" + tile_name + "_object_" + str(count) + ".colls", "wb+") as colls:
                colls.write(Tilebuffer)

            object.jsonData['colls'] = tile_name + "_object_" + str(count) + ".colls"

            with open(save_path + "/" + tile_name + "_objects" + "/" + tile_name + "_object_" + str(count) + ".objlyt", "wb+") as objlyt:
                objlyt.write(Objbuffer)

            object.jsonData['objlyt'] = tile_name + "_object_" + str(count) + ".objlyt"

            with open(save_path + "/" + tile_name + "_objects" + "/" + tile_name + "_object_" + str(count) + ".meta", "wb+") as meta:
                meta.write(Metabuffer)

            object.jsonData['meta'] = tile_name + "_object_" + str(count) + ".meta"

            count += 1

        count = 0
        for object in Tileset.objects:
            with open(save_path + "/" + tile_name + "_objects" + "/" + tile_name + "_object_" + str(count) + ".json", 'w+') as outfile:
                json.dump(object.jsonData, outfile)

            count += 1


    def saveFramesheet(self, index):
        item = self.framesheetmodel.itemFromIndex(index)
        icon = item.icon()
        name = item.text()

        path = QtWidgets.QFileDialog.getSaveFileName(self, 'Framesheet', '{}.png'.format(name), 'Framesheet (*.png)')[0]
        if not path: return


        pixmap = icon.pixmap(icon.availableSizes()[0])
        pixmap.save(path, "PNG")



    def saveObject(self, index):
        if len(Tileset.objects) == 0: return

        tile_name = (os.path.basename(self.name) if self.name else 'NewTileset')

        save_path = QtWidgets.QFileDialog.getExistingDirectory(None, "Choose where to save the Object folder")
        if not save_path: return

        n = index.row()

        object = Tileset.objects[n]

        object.jsonData = {}

        tex = QtGui.QPixmap(object.width * 24, object.height * 24)
        tex.fill(Qt.transparent)
        painter = QtGui.QPainter(tex)

        Xoffset = 0
        Yoffset = 0

        Tilebuffer = b''

        for i in range(len(object.tiles)):
            for tile in object.tiles[i]:
                if (Tileset.slot == 0) or ((tile[2] & 3) != 0):
                    painter.drawPixmap(Xoffset, Yoffset, Tileset.tiles[tile[1]].image)
                Tilebuffer += (Tileset.tiles[tile[1]].byte0).to_bytes(1, 'big')
                Tilebuffer += (Tileset.tiles[tile[1]].byte1).to_bytes(1, 'big')
                Tilebuffer += (Tileset.tiles[tile[1]].byte2).to_bytes(1, 'big')
                Tilebuffer += (Tileset.tiles[tile[1]].byte3).to_bytes(1, 'big')
                Tilebuffer += (Tileset.tiles[tile[1]].byte4).to_bytes(1, 'big')
                Tilebuffer += (Tileset.tiles[tile[1]].byte5).to_bytes(1, 'big')
                Tilebuffer += (Tileset.tiles[tile[1]].byte6).to_bytes(1, 'big')
                Tilebuffer += (Tileset.tiles[tile[1]].byte7).to_bytes(1, 'big')
                Xoffset += 24
            Xoffset = 0
            Yoffset += 24

        painter.end()

        # Slopes
        if object.upperslope[0] != 0:

            # Reverse Slopes
            if object.upperslope[0] & 0x2:
                a = struct.pack('>B', object.upperslope[0])

                if object.height == 1:
                    iterationsA = 0
                    iterationsB = 1
                else:
                    iterationsA = object.upperslope[1]
                    iterationsB = object.lowerslope[1] + object.upperslope[1]

                for row in range(iterationsA, iterationsB):
                    for tile in object.tiles[row]:
                        a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                    a += b'\xfe'

                if object.height > 1:
                    a += struct.pack('>B', object.lowerslope[0])

                    for row in range(0, object.upperslope[1]):
                        for tile in object.tiles[row]:
                            a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                        a += b'\xfe'

                a += b'\xff'


            # Regular Slopes
            else:
                a = struct.pack('>B', object.upperslope[0])

                for row in range(0, object.upperslope[1]):
                    for tile in object.tiles[row]:
                        a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                    a += b'\xfe'

                if object.height > 1:
                    a += struct.pack('>B', object.lowerslope[0])

                    for row in range(object.upperslope[1], object.height):
                        for tile in object.tiles[row]:
                            a += struct.pack('>BBB', tile[0], tile[1], tile[2])
                        a += b'\xfe'

                a += b'\xff'


        # Not slopes!
        else:
            a = b''

            for tilerow in object.tiles:
                for tile in tilerow:
                    a += struct.pack('>BBB', tile[0], tile[1], tile[2])

                a += b'\xfe'

            a += b'\xff'

        Objbuffer = a
        Metabuffer = struct.pack('>HBB', (0 if n == 0 else len(Objbuffer)), object.width, object.height)

        if not os.path.isdir(save_path + "/" + tile_name + "_objects"):
            os.mkdir(save_path + "/" + tile_name + "_objects")

        tex.save(save_path + "/" + tile_name + "_objects" + "/" + tile_name + "_object_" + str(n) + ".png", "PNG")

        object.jsonData['img'] = tile_name + "_object_" + str(n) + ".png"

        with open(save_path + "/" + tile_name + "_objects" + "/" + tile_name + "_object_" + str(n) + ".colls", "wb+") as colls:
            colls.write(Tilebuffer)

        object.jsonData['colls'] = tile_name + "_object_" + str(n) + ".colls"

        with open(save_path + "/" + tile_name + "_objects" + "/" + tile_name + "_object_" + str(n) + ".objlyt", "wb+") as objlyt:
            objlyt.write(Objbuffer)

        object.jsonData['objlyt'] = tile_name + "_object_" + str(n) + ".objlyt"

        with open(save_path + "/" + tile_name + "_objects" + "/" + tile_name + "_object_" + str(n) + ".meta", "wb+") as meta:
            meta.write(Metabuffer)

        object.jsonData['meta'] = tile_name + "_object_" + str(n) + ".meta"

        if not os.path.isdir(save_path + "/" + tile_name + "_objects"):
            os.mkdir(save_path + "/" + tile_name + "_objects")

        with open(save_path + "/" + tile_name + "_objects" + "/" + tile_name + "_object_" + str(n) + ".json", 'w+') as outfile:
            json.dump(object.jsonData, outfile)


    def clearObjects(self):
        '''Clears the object data'''

        Tileset.objects = []
        Tileset.animdata = {}

        SetupObjectModel(self.objmodel, Tileset.objects, Tileset.tiles)
        SetupFramesheetModel(self, Tileset.animdata)


        self.objectList.update()
        self.framesheetList.update()
        self.tileWidget.update()


    def clearCollisions(self):
        '''Clears the collisions data'''

        for tile in Tileset.tiles:
            tile.byte0 = 0
            tile.byte1 = 0
            tile.byte2 = 0
            tile.byte3 = 0
            tile.byte4 = 0
            tile.byte5 = 0
            tile.byte6 = 0
            tile.byte7 = 0

        self.updateInfo(0, 0)
        self.tileDisplay.update()


    def setupWidgets(self):
        frame = QtWidgets.QFrame()
        frameLayout = QtWidgets.QGridLayout(frame)

        # Displays the tiles
        self.tileDisplay = displayWidget()

        # Info Box for tile information
        self.infoDisplay = InfoBox(self)

        # Sets up the model for the tile pieces
        self.model = PiecesModel(self)
        self.tileDisplay.setModel(self.model)

        # Object List
        self.objectList = objectList()
        self.objmodel = QtGui.QStandardItemModel()
        SetupObjectModel(self.objmodel, Tileset.objects, Tileset.tiles)
        self.objectList.setModel(self.objmodel)

        self.importObject = QtWidgets.QPushButton('Import Object')

        # Creates the Tab Widget for behaviours and objects
        self.tabWidget = QtWidgets.QTabWidget()
        self.tabWidget.setUsesScrollButtons(False)
        self.framesheetWidget = framesheetOverlord()
        self.tileWidget = tileOverlord()
        self.paletteWidget = paletteWidget(self)

        # Second Tab
        self.container = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout()
        layout.addWidget(self.objectList, 0, 0, 1, 1)
        layout.addWidget(self.importObject, 1, 0, 1, 1)
        layout.addWidget(self.tileWidget, 0, 1, 2, 1)
        self.container.setLayout(layout)

        # Framesheet List
        self.framesheetList = framesheetList()
        self.framesheetmodel = QtGui.QStandardItemModel()
        self.frames = {}
        SetupFramesheetModel(self, Tileset.animdata)
        self.framesheetList.setModel(self.framesheetmodel)

        # Third Tab
        self.framesheetContainer = QtWidgets.QWidget()
        animationLayout = QtWidgets.QVBoxLayout()
        animationLayout.addWidget(self.framesheetList)
        animationLayout.addWidget(self.framesheetWidget)
        self.framesheetContainer.setLayout(animationLayout)

        # Fourth Tab
        self.frameEditor = frameEditorOverlord()

        # Fifth Tab
        self.animTilesEditor = animTilesOverlord()

        #Sixth Tab
        self.randTilesEditor = randTilesOverlord()


        # Sets the Tabs
        self.tabWidget.addTab(self.paletteWidget, 'Behaviors')
        self.tabWidget.addTab(self.container, 'Objects')
        self.tabWidget.addTab(self.framesheetContainer, 'Framesheets')
        self.tabWidget.addTab(self.frameEditor, 'Animation Editor')
        self.tabWidget.addTab(self.animTilesEditor, 'AnimTiles')
        self.tabWidget.addTab(self.randTilesEditor, 'RandTiles')

        # Connections do things!
        self.tileDisplay.clicked.connect(self.paintFormat)
        self.tileDisplay.mouseMoved.connect(self.updateInfo)
        self.objectList.selectionModel().currentChanged.connect(self.tileWidget.setObject)
        self.objectList.doubleClicked.connect(self.saveObject)
        self.importObject.released.connect(self.importObjFromFile)

        self.framesheetList.doubleClicked.connect(self.saveFramesheet)
        self.tabWidget.tabBarClicked.connect(self.frameEditor.setFramesheet)

        # Layout
        if SplitWindow:
            frameLayout.addWidget(self.infoDisplay, 0, 0, 1, 3, Qt.AlignTop)
            frameLayout.addWidget(self.tileDisplay, 1, 0, 1, 3, Qt.AlignTop | Qt.AlignCenter)
            self.anotherWidget = QtWidgets.QWidget()
            anotherLayout = QtWidgets.QGridLayout()
            anotherLayout.addWidget(self.tabWidget, 0, 3, 2, 3)
            anotherLayout.setMenuBar(QtWidgets.QWidget(self.menuBar()))
            self.anotherWidget.setLayout(anotherLayout)
            self.anotherWidget.setWindowTitle (" ")
            self.anotherWidget.setWindowFlags(Qt.WindowStaysOnTopHint)
            self.anotherWidget.setAttribute(Qt.WA_DeleteOnClose)
            self.anotherWidget.destroyed.connect(osExit)
            self.anotherWidget.show()
        else:
            frameLayout.addWidget(self.infoDisplay, 0, 0, 1, 3, Qt.AlignTop)
            frameLayout.addWidget(self.tileDisplay, 1, 0, 1, 3, Qt.AlignTop | Qt.AlignCenter)
            frameLayout.addWidget(self.tabWidget, 0, 3, 2, 3)
        self.setCentralWidget(frame)


    def updateInfo(self, x, y):

        index = [self.tileDisplay.indexAt(QtCore.QPoint(x, y))]
        curTile = Tileset.tiles[index[0].row()]
        info = self.infoDisplay
        palette = self.paletteWidget

        propertyList = []
        propertyText = ''
        coreType = 0

        if curTile.byte3 & 32:
            coreType = 1
        elif curTile.byte3 & 64:
            coreType = 2
        elif curTile.byte2 & 8:
            coreType = 3
        elif curTile.byte3 & 2:
            coreType = 4
        elif curTile.byte3 & 8:
            coreType = 5
        elif curTile.byte2 & 4:
            coreType = 6
        elif curTile.byte2 & 16:
            coreType = 7
        elif curTile.byte1 & 1:
            coreType = 8
        elif 0 > curTile.byte7 > 0x23:
            coretype = 9
        elif curTile.byte5 == 4 or 5:
            coretype = 10
        elif curTile.byte3 & 4:
            coreType = 11

        if curTile.byte3 & 1:
            propertyList.append('Solid')
        if curTile.byte3 & 16:
            propertyList.append('Breakable')
        if curTile.byte2 & 128:
            propertyList.append('Pass-Through')
        if curTile.byte2 & 64:
            propertyList.append('Pass-Down')
        if curTile.byte1 & 2:
            propertyList.append('Falling')
        if curTile.byte1 & 8:
            propertyList.append('Ledge')
        if curTile.byte0 & 2:
            propertyList.append('Meltable')


        if len(propertyList) == 0:
            propertyText = 'None'
        elif len(propertyList) == 1:
            propertyText = propertyList[0]
        else:
            propertyText = propertyList.pop(0)
            for string in propertyList:
                propertyText = propertyText + ', ' + string

        if coreType == 0:
            if curTile.byte7 == 0x23:
                parameter = palette.ParameterList[coreType][1]
            elif curTile.byte7 == 0x28:
                parameter = palette.ParameterList[coreType][2]
            elif curTile.byte7 >= 0x35:
                parameter = palette.ParameterList[coreType][curTile.byte7 - 0x32]
            else:
                parameter = palette.ParameterList[coreType][0]
        else:
            parameter = palette.ParameterList[coreType][curTile.byte7]


        info.coreImage.setPixmap(palette.coreTypes[coreType][1].pixmap(24,24))
        info.terrainImage.setPixmap(palette.terrainTypes[curTile.byte5][1].pixmap(24,24))
        info.parameterImage.setPixmap(parameter[1].pixmap(24,24))

        info.coreInfo.setText(palette.coreTypes[coreType][0])
        info.propertyInfo.setText("Properties:\n{0}".format(propertyText))
        info.terrainInfo.setText(palette.terrainTypes[curTile.byte5][0])
        info.paramInfo.setText(parameter[0])

        info.hexdata.setText('Hex Data: {0} {1} {2} {3} {4} {5} {6} {7}'.format(
                                hex(curTile.byte0), hex(curTile.byte1), hex(curTile.byte2), hex(curTile.byte3),
                                hex(curTile.byte4), hex(curTile.byte5), hex(curTile.byte6), hex(curTile.byte7)))

        row = index[0].row() % 16
        column = index[0].row() // 16
        if 0 <= row <= 15 and 0 <= column <= 15:
            info.numInfo.setText('Slot: %X Row: 0x%X Column: 0x%X' % (Tileset.slot, row, column))


    def paintFormat(self, index):
        if self.tabWidget.currentIndex() == 1:
            return

        curTile = Tileset.tiles[index.row()]
        palette = self.paletteWidget

        if palette.coreWidgets[8].isChecked() == 1 or palette.propertyWidgets[0].isChecked() == 1:
            solid = 1
        else:
            solid = 0

        if palette.coreWidgets[1].isChecked() == 1 or palette.coreWidgets[2].isChecked() == 1:
            solid = 0


        curTile.byte0 = ((palette.propertyWidgets[4].isChecked() << 1))
        curTile.byte1 = ((palette.coreWidgets[8].isChecked()) +
                        (palette.propertyWidgets[2].isChecked() << 1) +
                        (palette.propertyWidgets[3].isChecked() << 3))
        curTile.byte2 = ((palette.coreWidgets[6].isChecked() << 2) +
                        (palette.coreWidgets[3].isChecked() << 3) +
                        (palette.coreWidgets[7].isChecked() << 4) +
                        (palette.PassDown.isChecked() << 6) +
                        (palette.PassThrough.isChecked() << 7))
        curTile.byte3 = ((solid) +
                        (palette.coreWidgets[4].isChecked() << 1) +
                        (palette.coreWidgets[5].isChecked() << 3) +
                        (palette.propertyWidgets[1].isChecked() << 4) +
                        (palette.coreWidgets[1].isChecked() << 5) +
                        (palette.coreWidgets[2].isChecked() << 6) +
                        (palette.coreWidgets[11].isChecked() << 2))
        curTile.byte4 = 0
        if palette.coreWidgets[2].isChecked():
            curTile.byte5 = 4
        curTile.byte5 = palette.terrainType.currentIndex()

        if palette.coreWidgets[0].isChecked():
            params = palette.parameters.currentIndex()
            if params == 0:
                curTile.byte7 = 0
            elif params == 1:
                curTile.byte7 = 0x23
            elif params == 2:
                curTile.byte7 = 0x28
            elif params >= 3:
                curTile.byte7 = params + 0x32
        else:
            curTile.byte7 = palette.parameters.currentIndex()

        self.updateInfo(0, 0)
        self.tileDisplay.update()



#############################################################################################
####################################### Main Function #######################################

def osExit(self):
    os._exit(0)


if '-nolib' in sys.argv:
    HaveNSMBLib = False
    sys.argv.remove('-nolib')

if '-split' in sys.argv:
    SplitWindow = True
    sys.argv.remove('-split')


if __name__ == '__main__':

    import sys

    app = QtWidgets.QApplication(sys.argv)
    app.setAttribute(Qt.AA_DisableWindowContextHelpButton)
    app.setWindowIcon(QtGui.QIcon("Icons/about.png"));

    # go to the script path
    path = module_path()
    if path is not None:
        os.chdir(path)

    with open("dark.qss", 'r') as file:
        qss = file.read()
    app.setStyleSheet(qss)

    window = MainWindow()

    window.setAttribute(Qt.WA_DeleteOnClose)
    window.destroyed.connect(osExit)

    if len(sys.argv) > 1:
        window.openTilesetFromPath(sys.argv[1])
    window.show()

    sys.exit(app.exec_())
    app.deleteLater()
