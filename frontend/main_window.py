from PySide6.QtWidgets import QMainWindow
from frontend.views.collection_view import CollectionView
from core.services import MagicCardService

class MainWindow(QMainWindow):
    def __init__(self, service: MagicCardService):
        super().__init__()
        self.service = service
        self.setWindowTitle("Magic Card Manager")
        self.setGeometry(100, 100, 1024, 768) # x, y, width, height

        # Create the main view and set it as the central widget
        self.collection_view = CollectionView(self.service)
        self.setCentralWidget(self.collection_view)