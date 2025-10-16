from core.models import Base, engine
from core.services import MagicCardService
from ui.main_window import App

def create_database():
    """Creates the database and all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    print("Database is ready.")

if __name__ == "__main__":
    create_database()

    # 1. Initialize the service layer
    service = MagicCardService()

    # 2. Create the UI, injecting the service into it
    app = App(service=service)

    # 3. Set a function to be called when the window is closed
    def on_closing():
        print("Closing application, shutting down service.")
        service.close_session()
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_closing)

    # 4. Run the application's main loop
    app.mainloop()