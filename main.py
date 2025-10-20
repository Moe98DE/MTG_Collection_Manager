import sys
import atexit
from PySide6.QtWidgets import QApplication
from frontend.main_window import MainWindow
from core.services import MagicCardService

def main():
    # --- Application Setup ---
    app = QApplication(sys.argv)

    # --- Service Layer Initialization ---
    # Create a single service instance for the entire application lifetime
    print("Initializing service layer...")
    service_instance = MagicCardService()

    # Register the service's session closer to be called on exit
    atexit.register(service_instance.close_session)
    print("Service layer initialized. Session will be closed on exit.")

    # --- Main Window ---
    window = MainWindow(service_instance)
    window.show()

    # --- Start Event Loop ---
    sys.exit(app.exec())

if __name__ == "__main__":
    # This is a common practice to ensure the `core` module can be found
    # when running main.py directly from the `frontend` directory.
    # A better solution is a proper package installation (e.g., using setup.py).
    sys.path.append('..')
    main()