import customtkinter as ctk

class AssemblyWizardDialog(ctk.CTkToplevel):
    def __init__(self, master, service, deck_id, on_finish_callback):
        super().__init__(master)
        self.service = service
        self.deck_id = deck_id
        self.on_finish = on_finish_callback
        self.choices = {}  # To store the dropdown widgets
        self.card_widgets = [] # To store the created card widgets for filtering

        self.title("Deck Assembly Wizard")
        self.geometry("600x500")
        self.transient(master)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1) # The scroll frame is now in row 2

        # --- NEW: Search Entry ---
        self.search_entry = ctk.CTkEntry(self, placeholder_text="Filter cards...")
        self.search_entry.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.search_entry.bind("<KeyRelease>", self.filter_cards)
        
        # This frame will hold the confirm button
        self.bottom_frame = ctk.CTkFrame(self)
        self.bottom_frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")

        self.confirm_button = ctk.CTkButton(self.bottom_frame, text="Confirm Assembly", command=self.confirm)
        self.confirm_button.pack(pady=5)

        self.scroll_frame = ctk.CTkScrollableFrame(self, label_text="Select Card Printings")
        self.scroll_frame.grid(row=1, column=0, rowspan=2, padx=10, pady=0, sticky="nsew")
        self.scroll_frame.grid_columnconfigure(0, weight=1)

        self.options = self.service.get_assembly_options(deck_id)
        self.populate_options()

    def populate_options(self):
        """Creates the widgets for all card selection options."""
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self.choices.clear()

        for card in self.options:
            needed = card['quantity_needed']
            available = card['available_instances']
            
            # This frame will hold all widgets for one card, for easy filtering
            card_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            card_frame.pack(fill="x", pady=(5,0))
            card_frame.grid_columnconfigure(0, weight=1)
            self.card_widgets.append((card['card_name'], card_frame))

            ctk.CTkLabel(card_frame, text=f"{needed}x {card['card_name']}", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=5)

            if len(available) < needed:
                ctk.CTkLabel(card_frame, text=f"⚠️ Not enough copies available! (Need {needed}, have {len(available)})", text_color="orange").pack(anchor="w", padx=15)
                continue

            self.choices[card['oracle_card_id']] = []
            used_instance_ids = []
            for i in range(needed):
                choice_var = ctk.StringVar()
                
                # Filter out already selected choices for subsequent dropdowns
                available_for_this_dropdown = [inst for inst in available if inst['instance_id'] not in used_instance_ids]
                dropdown_options = [f"{inst['instance_id']} | {inst['text']}" for inst in available_for_this_dropdown]

                if not dropdown_options: continue
                
                # *** CHANGE 1: AUTO-SELECTION ***
                choice_var.set(dropdown_options[0])
                used_instance_ids.append(int(dropdown_options[0].split(' | ')[0]))

                dropdown = ctk.CTkOptionMenu(card_frame, variable=choice_var, values=dropdown_options)
                dropdown.pack(fill="x", padx=15, pady=2)
                self.choices[card['oracle_card_id']].append(choice_var)

    def filter_cards(self, event=None):
        """Shows/hides card frames based on the search term."""
        search_term = self.search_entry.get().lower()
        for card_name, frame in self.card_widgets:
            if search_term in card_name.lower():
                frame.pack(fill="x", pady=(5,0)) # Show it
            else:
                frame.pack_forget() # Hide it
    
    def confirm(self):
        # ... (confirm method is unchanged) ...
        final_choices = {}
        for oracle_id, choice_vars in self.choices.items():
            for var in choice_vars:
                if not var.get(): continue # Skip if somehow empty
                instance_id = int(var.get().split(' | ')[0])
                final_choices[instance_id] = instance_id

        if self.service.assemble_deck(self.deck_id, final_choices):
            self.on_finish()
        self.destroy()