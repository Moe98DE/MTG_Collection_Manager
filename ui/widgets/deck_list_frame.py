import customtkinter as ctk

class DeckListFrame(ctk.CTkFrame):
    def __init__(self, master, service, on_deck_select_callback):
        super().__init__(master)
        self.service = service
        self.on_deck_select = on_deck_select_callback
        self.selected_deck_id = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- Top Control Frame ---
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.control_frame.grid_columnconfigure((0, 1), weight=1)

        self.new_button = ctk.CTkButton(self.control_frame, text="New Deck", command=self.new_deck_dialog)
        self.new_button.grid(row=0, column=0, padx=5, pady=5)

        self.delete_button = ctk.CTkButton(self.control_frame, text="Delete Deck", command=self.delete_selected_deck, state="disabled")
        self.delete_button.grid(row=0, column=1, padx=5, pady=5)
        
        # --- Deck List ---
        self.scroll_frame = ctk.CTkScrollableFrame(self, label_text="Decks")
        self.scroll_frame.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")

        self.refresh()

    def refresh(self):
        # Clear existing deck widgets
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        decks = self.service.get_all_decks()
        for deck in decks:
            btn = ctk.CTkButton(self.scroll_frame, text=deck['name'],
                                command=lambda d=deck: self.select_deck(d)) # Pass the whole dict
            btn.pack(fill="x", padx=5, pady=2)
        
        # Reset selection if the selected deck was deleted
        if self.selected_deck_id and not any(d['id'] == self.selected_deck_id for d in decks):
            self.select_deck(None)

    def select_deck(self, deck_data): # accept the whole dict
        self.selected_deck_id = deck_data['id'] if deck_data else None
        self.on_deck_select(deck_data)
        self.delete_button.configure(state="normal" if deck_data else "disabled")

    def delete_selected_deck(self):
        if self.selected_deck_id:
            # In a real app, we'd add a confirmation dialog here
            if self.service.delete_deck(self.selected_deck_id):
                self.refresh()

    def new_deck_dialog(self):
        dialog = ctk.CTkInputDialog(text="Enter new deck name:", title="Create Deck")
        deck_name = dialog.get_input()
        if deck_name and self.service.create_deck(deck_name):
            self.refresh()