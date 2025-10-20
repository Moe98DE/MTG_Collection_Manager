from PySide6.QtCore import QObject, Signal, Slot
from typing import List
from core.repo.dtos import CollectionSummaryItem
from core.services import MagicCardService


class CollectionLoaderWorker(QObject):
    """
    Worker object to fetch the collection summary in a background thread.
    """
    # Signal to emit the result. The 'list' part is the type of the argument.
    finished = Signal(list)

    def __init__(self, service: MagicCardService):
        super().__init__()
        self.service = service

    @Slot()
    def run(self):
        """Fetches data and emits the 'finished' signal with the result."""
        print("Worker thread: Fetching collection summary...")
        summary_data: List[CollectionSummaryItem] = self.service.get_collection_summary()
        print(f"Worker thread: Found {len(summary_data)} items. Emitting signal.")
        self.finished.emit(summary_data)