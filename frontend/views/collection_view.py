from PySide6.QtWidgets import QWidget, QVBoxLayout, QTableView, QLabel, QAbstractItemView
from PySide6.QtCore import QThread, Slot

from core.repo.dtos import CollectionSummaryItem
from frontend.models.collection_table_model import CollectionTableModel
from frontend.workers import CollectionLoaderWorker
from core.services import MagicCardService
from typing import List


class CollectionView(QWidget):
    """
    A widget that displays the card collection summary in a table.
    """

    def __init__(self, service: MagicCardService):
        super().__init__()
        self.service = service
        self.setWindowTitle("My Collection")

        # --- Layout ---
        self.layout = QVBoxLayout(self)

        # --- Widgets ---
        self.status_label = QLabel("Loading collection...")
        self.table_view = QTableView()
        self.table_view.setSortingEnabled(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_view.verticalHeader().setVisible(False)

        # --- Model ---
        self.table_model = CollectionTableModel()
        self.table_view.setModel(self.table_model)

        # --- Add widgets to layout ---
        self.layout.addWidget(self.status_label)
        self.layout.addWidget(self.table_view)

        # --- Load data in background ---
        self.load_collection_data()

    def load_collection_data(self):
        """
        Sets up a background thread to load collection data without freezing the UI.
        """
        self.thread = QThread()
        self.worker = CollectionLoaderWorker(self.service)
        self.worker.moveToThread(self.thread)

        # Connect signals and slots
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_loading_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        # Start the thread
        self.thread.start()
        print("Main thread: Started collection loader thread.")

    @Slot(list)
    def on_loading_finished(self, summary_data: List[CollectionSummaryItem]):
        """Slot to handle the data once the worker is finished."""
        print("Main thread: Received data from worker.")
        self.table_model.set_data(summary_data)
        self.status_label.setText(f"Displaying {len(summary_data)} unique cards.")

        # Optional: Resize columns to fit content
        self.table_view.resizeColumnsToContents()