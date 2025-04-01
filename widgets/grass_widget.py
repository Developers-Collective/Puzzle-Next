import copy
import io
import json

from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QFileDialog, QLabel, QLineEdit, QHeaderView
)

import tools.grass as grass

__EMPTY__ = {"flowerfile": 0, "grassfile": 0, "entries": []}


class FlowerGrassWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._grass_data = None

        self.currentData = copy.deepcopy(__EMPTY__)
        mainLayout = QVBoxLayout(self)

        topButtonLayout = QHBoxLayout()
        self.addRowButton = QPushButton("Add Entry")
        self.removeRowButton = QPushButton("Remove Entry")

        topButtonLayout.addWidget(self.addRowButton)
        topButtonLayout.addWidget(self.removeRowButton)
        mainLayout.addLayout(topButtonLayout)

        self.addRowButton.clicked.connect(self.addRow)
        self.removeRowButton.clicked.connect(self.removeRow)

        self.table = QTableWidget()
        mainLayout.addWidget(self.table)

        self.headers = ["tilenum", "flowertype", "grasstype"]
        self.table.setColumnCount(len(self.headers))
        self.table.setHorizontalHeaderLabels(self.headers)

        # Make columns fill all width evenly, not user-resizable
        header = self.table.horizontalHeader()
        for col in range(len(self.headers)):
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        header.setSectionsClickable(False)
        header.setSectionsMovable(False)

        self.table.setEditTriggers(QTableWidget.AllEditTriggers)

        fileLayout = QHBoxLayout()
        fileLayout.addWidget(QLabel("flowerfile:"))
        self.flowerfileEdit = QLineEdit("0")
        fileLayout.addWidget(self.flowerfileEdit)

        fileLayout.addWidget(QLabel("grassfile:"))
        self.grassfileEdit = QLineEdit("0")
        fileLayout.addWidget(self.grassfileEdit)
        mainLayout.addLayout(fileLayout)

        buttonLayout = QHBoxLayout()

        self.loadJsonButton = QPushButton("Load JSON")
        self.saveJsonButton = QPushButton("Save JSON")
        self.loadBinButton = QPushButton("Load .bin")
        self.saveBinButton = QPushButton("Save .bin")

        buttonLayout.addWidget(self.loadJsonButton)
        buttonLayout.addWidget(self.saveJsonButton)
        buttonLayout.addWidget(self.loadBinButton)
        buttonLayout.addWidget(self.saveBinButton)
        mainLayout.addLayout(buttonLayout)

        self.loadJsonButton.clicked.connect(self.loadJson)
        self.saveJsonButton.clicked.connect(self.saveJson)
        self.loadBinButton.clicked.connect(self.loadBinFile)
        self.saveBinButton.clicked.connect(self.saveBinFile)

        tilesetLayout = QHBoxLayout()
        self.importTilesetButton = QPushButton("Import from Tileset")
        self.exportTilesetButton = QPushButton("Export to Tileset")
        tilesetLayout.addWidget(self.importTilesetButton)
        tilesetLayout.addWidget(self.exportTilesetButton)
        mainLayout.addLayout(tilesetLayout)

        self.importTilesetButton.clicked.connect(self.importFromTileset)
        self.exportTilesetButton.clicked.connect(self.exportToTileset)

        self.setLayout(mainLayout)

    def _load_into_table(self, data):
        self.currentData = data
        # Update line edits
        flowerVal = data.get("flowerfile", 0)
        grassVal = data.get("grassfile", 0)
        self.flowerfileEdit.setText(str(flowerVal))
        self.grassfileEdit.setText(str(grassVal))

        # Populate the table
        entries = data.get("entries", [])
        self.table.setRowCount(len(entries))

        for rowIndex, entry in enumerate(entries):
            tilenum = entry.get("tilenum", 0)
            flowertype = entry.get("flowertype", 0)
            grasstype = entry.get("grasstype", 0)

            self._setTableItem(rowIndex, 0, str(tilenum))
            self._setTableItem(rowIndex, 1, str(flowertype))
            self._setTableItem(rowIndex, 2, str(grasstype))

    def to_bytes(self) -> bytes | None:
        if self.currentData == __EMPTY__:
            return None

        if self._grass_data is None:
            self._grass_data = grass.encode(self.currentData)

        return self._grass_data

    def load_from_bin(self, data: bytes):
        self.currentData = grass.decode(io.BytesIO(data))

    # -------------------------------------------------------------------------
    # Row Management: Add/Remove
    # -------------------------------------------------------------------------
    def addRow(self):
        """Append a new row to the bottom of the table with default values."""
        rowCount = self.table.rowCount()
        self.table.insertRow(rowCount)
        # Optional: set defaults
        self._setTableItem(rowCount, 0, "0")  # tilenum
        self._setTableItem(rowCount, 1, "0")  # flowertype
        self._setTableItem(rowCount, 2, "0")  # grasstype

    def removeRow(self):
        """Remove the currently selected row (if any)."""
        selectedRow = self.table.currentRow()
        if selectedRow >= 0:
            self.table.removeRow(selectedRow)

    # -------------------------------------------------------------------------
    # Table Helper
    # -------------------------------------------------------------------------
    def _setTableItem(self, row, col, text):
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, col, item)

    # -------------------------------------------------------------------------
    # Tileset import/export
    # -------------------------------------------------------------------------
    def importFromTileset(self):
        self._load_into_table(self.currentData)

    def exportToTileset(self):
        self._grass_data = grass.encode(self.currentData)

    # -------------------------------------------------------------------------
    # Binary Load/Save
    # -------------------------------------------------------------------------
    def loadBinFile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open .bin", "", "Binary Files (*.bin)")
        if not path:
            return

        self._load_into_table(grass.decode(open(path, 'rb')))

    def saveBinFile(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save .bin", "", "Binary Files (*.bin)")
        if not path:
            return

        try:
            with open(path, "wb") as f:
                f.write(grass.encode(self.currentData))
            print(f"Saved .bin to {path}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(None, 'Error',
                                          f"Error writing .bin: {e}")

    # -------------------------------------------------------------------------
    # JSON Load/Save
    # -------------------------------------------------------------------------
    def loadJson(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open JSON", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            with open(path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            QtWidgets.QMessageBox.warning(None, 'Error',
                                          f"Error reading JSON: {e}")
            return

        self._load_into_table(data)

    def saveJson(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save JSON", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            flowerVal = int(self.flowerfileEdit.text())
        except ValueError:
            flowerVal = 0
        try:
            grassVal = int(self.grassfileEdit.text())
        except ValueError:
            grassVal = 0

        self.currentData["flowerfile"] = flowerVal
        self.currentData["grassfile"] = grassVal

        rowCount = self.table.rowCount()
        entries = []
        for rowIndex in range(rowCount):
            def textOrZero(r, c):
                item = self.table.item(r, c)
                return item.text().strip() if item else "0"

            tilenum    = int(textOrZero(rowIndex, 0))
            flowertype = int(textOrZero(rowIndex, 1))
            grasstype  = int(textOrZero(rowIndex, 2))

            entries.append({
                "tilenum": tilenum,
                "flowertype": flowertype,
                "grasstype": grasstype
            })

        self.currentData["entries"] = entries

        try:
            with open(path, 'w') as f:
                json.dump(self.currentData, f, indent=4)
            print(f"Saved JSON to {path}")
        except Exception as e:
            QtWidgets.QMessageBox.warning(None, 'Error',
                                          f"Error writing JSON: {e}")

