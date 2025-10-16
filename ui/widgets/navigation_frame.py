import customtkinter as ctk

class NavigationFrame(ctk.CTkFrame):
    def __init__(self, master, collection_callback, decks_callback):
        super().__init__(master, corner_radius=0)
        self.collection_callback = collection_callback
        self.decks_callback = decks_callback

        self.grid_columnconfigure((0, 1), weight=1) # Let buttons expand

        self.collection_button = ctk.CTkButton(
            self,
            text="Collection",
            command=self.collection_callback,
            corner_radius=0,
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.collection_button.grid(row=0, column=0, padx=0, pady=0, sticky="ew")

        self.decks_button = ctk.CTkButton(
            self,
            text="Decks",
            command=self.decks_callback,
            corner_radius=0,
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.decks_button.grid(row=0, column=1, padx=0, pady=0, sticky="ew")