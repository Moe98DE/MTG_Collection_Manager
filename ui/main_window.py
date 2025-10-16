import customtkinter as ctk
from core.services import MagicCardService

# Import our new and existing frames
from .widgets.navigation_frame import NavigationFrame
from .widgets.add_card_frame import AddCardFrame
from .widgets.collection_frame import CollectionFrame
from .widgets.deck_hub_frame import DeckHubFrame # <-- NEW IMPORT

class App(ctk.CTk):
    def __init__(self, service: MagicCardService):
        super().__init__()
        self.service = service

        # --- Window Configuration ---
        self.title("MTG Collection Manager")
        self.geometry("1000x700") # A bit bigger for the new layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1) # The main content area will expand

        # --- Create Frames/Pages ---
        
        # 1. The Add Card Frame (always visible at the top)
        self.add_card_frame = AddCardFrame(self, service, on_add_callback=self.refresh_current_view)
        self.add_card_frame.grid(row=0, column=0, padx=10, pady=10, sticky="new")

        # 2. The Navigation Frame
        self.nav_frame = NavigationFrame(self, 
                                         collection_callback=lambda: self.select_frame("collection"),
                                         decks_callback=lambda: self.select_frame("deckhub"))
        self.nav_frame.grid(row=1, column=0, padx=10, pady=0, sticky="new")

        # 3. The Main Content Container
        self.main_content_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_content_frame.grid(row=2, column=0, padx=10, pady=10, sticky="nsew")
        self.main_content_frame.grid_rowconfigure(0, weight=1)
        self.main_content_frame.grid_columnconfigure(0, weight=1)
        
        # --- Dictionary to hold our "pages" ---
        self.frames = {}

        for F in (CollectionFrame, DeckHubFrame):
            frame_name = F.__name__.lower().replace("frame", "") # e.g., 'collection', 'deckhub'
            frame = F(self.main_content_frame, self.service)
            self.frames[frame_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")
        
        self.select_frame("collection") # Start on the collection page

    def select_frame(self, page_name):
        """Shows the selected frame/page and hides the others."""
        print(f"Navigating to {page_name}")
        for name, frame in self.frames.items():
            if name == page_name:
                frame.tkraise() # Bring the frame to the front
        
        # We can also update button appearances here to show the active tab
        if page_name == "collection":
            self.nav_frame.collection_button.configure(fg_color=("#3B8ED0", "#1F6AA5"))
            self.nav_frame.decks_button.configure(fg_color=("#3a7ebf", "#1f538d")) # Revert to default
        # CHANGE THIS LINE:
        elif page_name == "deckhub": 
            self.nav_frame.decks_button.configure(fg_color=("#3B8ED0", "#1F6AA5"))
            self.nav_frame.collection_button.configure(fg_color=("#3a7ebf", "#1f538d")) # Revert to default


    def refresh_current_view(self):
        """Refreshes the currently visible frame."""
        # *** CHANGE: Make this smarter to refresh the correct page ***
        if self.frames["collection"].winfo_viewable():
            self.frames["collection"].refresh()
        if self.frames["deckhub"].winfo_viewable():
            self.frames["deckhub"].refresh()