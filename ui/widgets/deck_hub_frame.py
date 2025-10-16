import customtkinter as ctk
from .deck_list_frame import DeckListFrame
from .deck_contents_frame import DeckContentsFrame

class DeckHubFrame(ctk.CTkFrame):
    def __init__(self, master, service):
        """
        The main 'page' for all deck-related activities.
        Manages the layout of the DeckList and DeckContents frames.
        """
        super().__init__(master, fg_color="transparent")
        self.service = service

        self.grid_columnconfigure(1, weight=1) # The right panel (deck contents) will expand
        self.grid_rowconfigure(0, weight=1)

        # --- Left Panel: List of Decks ---
        # We pass self.on_deck_selected as the function to be called when a deck is clicked.
        self.deck_list = DeckListFrame(self, service, on_deck_select_callback=self.on_deck_selected)
        self.deck_list.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="nsew")

        # --- Right Panel: Contents of the Selected Deck ---
        # We pass self.refresh as the function to be called after a major action
        # like assembling or disassembling a deck.
        self.deck_contents = DeckContentsFrame(self, service, on_action_callback=self.refresh)
        self.deck_contents.grid(row=0, column=1, padx=(10, 0), pady=0, sticky="nsew")
        
    def on_deck_selected(self, deck_data: dict | None):
        """
        Callback function that is triggered by the DeckListFrame when a user selects a deck.
        It tells the DeckContentsFrame which deck to display.
        """
        self.deck_contents.display_deck(deck_data)
    
    def refresh(self):
        """
        Refreshes the entire deck hub. This is necessary after actions that
        could affect both the deck list and the deck contents, like assembling.
        """
        print("DeckHubFrame: Refreshing all components...")
        
        # 1. Refresh the list of decks.
        self.deck_list.refresh()
        
        # 2. Re-display the contents of the currently selected deck.
        # This ensures its status (Blueprint/Assembled) and contents are up-to-date.
        # We need to fetch the latest deck data from the service.
        selected_id = self.deck_list.selected_deck_id
        if selected_id:
            all_decks = self.service.get_all_decks()
            updated_deck_data = next((d for d in all_decks if d['id'] == selected_id), None)
            self.deck_contents.display_deck(updated_deck_data)
        else:
            self.deck_contents.display_deck(None)