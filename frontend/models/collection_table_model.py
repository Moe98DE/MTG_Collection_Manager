from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from typing import List, Any
from core.repo.dtos import CollectionSummaryItem


class CollectionTableModel(QAbstractTableModel):
    """
    A table model to represent the collection summary data.
    """
    def __init__(self, data: List[CollectionSummaryItem] = None):
        super().__init__()
        self._data = data or []
        self._headers = ["Name", "Total", "Available", "Type", "Mana Cost", "CMC"]

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            item = self._data[index.row()]
            col = index.column()

            if col == 0:
                return item.name
            elif col == 1:
                return item.total_owned
            elif col == 2:
                return item.available_count
            elif col == 3:
                return item.type_line
            elif col == 4:
                return item.mana_cost
            elif col == 5:
                return item.cmc
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._headers)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._headers[section]
        return None

    def set_data(self, data: List[CollectionSummaryItem]):
        """Updates the model's data and refreshes the view."""
        self.beginResetModel()
        self._data = data
        self.endResetModel()