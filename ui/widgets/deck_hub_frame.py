import customtkinter as ctk
from .deck_list_frame import DeckListFrame

class DeckHubFrame(ctk.CTkFrame):
    def __init__(self, master, service):
        super().__init__(master, fg_color="transparent")
        self.service = service

        self.grid_columnconfigure(1, weight=1) # The right panel will expand
        self.grid_rowconfigure(0, weight=1)

        # --- Left Panel: Deck List ---
        self.deck_list = DeckListFrame(self, service, self.on_deck_selected)
        self.deck_list.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="nsew")

        # --- Right Panel: Deck Contents (Placeholder for now) ---
        self.deck_contents = ctk.CTkFrame(self)
        self.deck_contents.grid(row=0, column=1, padx=(10, 0), pady=0, sticky="nsew")
        
        self.placeholder_label = ctk.CTkLabel(self.deck_contents, text="Select a deck to view its contents",
                                              font=ctk.CTkFont(size=20))
        self.placeholder_label.pack(expand=True)

    def on_deck_selected(self, deck_id):
        # This is where we will trigger the right panel to update in Milestone 3
        if deck_id:
            # For now, just update the placeholder text
            deck_name = [d['name'] for d in self.service.get_all_decks() if d['id'] == deck_id][0]
            self.placeholder_label.configure(text=f"Displaying contents for '{deck_name}'")
        else:
            self.placeholder_label.configure(text="Select a deck to view its contents")
    
    def refresh(self):
        """Passes the refresh call down to the relevant child component."""
        self.deck_list.refresh()