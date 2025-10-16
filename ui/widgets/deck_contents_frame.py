import customtkinter as ctk
from .assembly_wizard_dialog import AssemblyWizardDialog
from core.models import Deck # Import Deck model for type hinting

class DeckContentsFrame(ctk.CTkFrame):
    def __init__(self, master, service, on_action_callback):
        super().__init__(master)
        self.service = service
        self.on_action_callback = on_action_callback # To refresh the whole hub
        self.current_deck = None
        self.status_map = {"AVAILABLE": "✅", "ALLOCATED": "⚠️", "PARTIAL": "🟠", "MISSING": "❌"}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.title_label = ctk.CTkLabel(self, text="Select a Deck", font=ctk.CTkFont(size=20, weight="bold"))
        self.title_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")

        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self.scroll_frame.grid_columnconfigure(1, weight=1)

        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")
        self.control_frame.grid_columnconfigure(0, weight=1)
        
        # --- Blueprint Controls ---
        self.add_entry = ctk.CTkEntry(self.control_frame, placeholder_text="Add card by name...")
        self.add_button = ctk.CTkButton(self.control_frame, text="Add", command=self.add_card_action, width=60)
        self.import_button = ctk.CTkButton(self.control_frame, text="Import List", command=self.show_blueprint_import_dialog)
        self.export_button = ctk.CTkButton(self.control_frame, text="Export Buy List", command=self.export_action)
        self.assemble_button = ctk.CTkButton(self.control_frame, text="Assemble Deck", command=self.launch_wizard)
        
        # --- Assembled Controls ---
        self.disassemble_button = ctk.CTkButton(self.control_frame, text="Disassemble Deck", command=self.disassemble_action)

    def show_blueprint_import_dialog(self):
        """Creates a pop-up window for pasting a list of cards for the blueprint."""
        if not self.current_deck: return
        
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Import to {self.current_deck['name']}")
        dialog.geometry("500x400")
        dialog.transient(self)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(dialog, text="Paste card list below (e.g., '2 Sol Ring'):").grid(row=0, column=0, padx=10, pady=10)
        textbox = ctk.CTkTextbox(dialog)
        textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        def submit_action():
            card_list_string = textbox.get("1.0", "end")
            if not card_list_string.strip():
                dialog.destroy()
                return

            self.service.add_cards_to_blueprint_from_list(self.current_deck['id'], card_list_string)
            self.display_deck(self.current_deck) # Refresh view
            dialog.destroy()

        ctk.CTkButton(dialog, text="Submit", command=submit_action).grid(row=2, column=0, padx=10, pady=10)

    def display_deck(self, deck_data: dict):
        self.current_deck = deck_data
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        # Hide all controls initially
        for w in self.control_frame.winfo_children(): w.grid_forget()

        if not self.current_deck:
            self.title_label.configure(text="Select a Deck")
            return
        
        if self.current_deck['status'] == 'blueprint':
            self.title_label.configure(text=f"Blueprint: {self.current_deck['name']}")
            self.display_blueprint_contents()
            # Show blueprint controls
            self.add_entry.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
            self.add_button.grid(row=0, column=1, padx=5, pady=5)
            self.import_button.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
            self.export_button.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
            self.assemble_button.grid(row=3, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
        else: # Assembled
            self.title_label.configure(text=f"Assembled: {self.current_deck['name']}", text_color="cyan")
            self.display_assembled_contents()
            # Show assembled controls
            self.disassemble_button.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

    def display_blueprint_contents(self):
        analysis = self.service.get_deck_blueprint_analysis(self.current_deck['id'])
        for i, card in enumerate(analysis):
            status_icon = self.status_map.get(card['status'], "❓")
            ctk.CTkLabel(self.scroll_frame, text=f"{status_icon}  {card['quantity']}x {card['card_name']}").grid(row=i, column=1, padx=5, pady=2, sticky="w")
            ctk.CTkButton(self.scroll_frame, text=" X ", width=30, command=lambda o_id=card['oracle_card_id']: self.remove_card_action(o_id)).grid(row=i, column=2, padx=5, pady=2)

    def display_assembled_contents(self):
        # *** CHANGE 2: SHOW THE LIST ***
        contents = self.service.get_assembled_deck_contents(self.current_deck['id'])
        if not contents:
            ctk.CTkLabel(self.scroll_frame, text="This deck is empty.").pack(pady=20)
            return
        
        for i, card in enumerate(contents):
            label_text = f"{card['quantity']}x {card['name']}"
            ctk.CTkLabel(self.scroll_frame, text=label_text).grid(row=i, column=0, padx=5, pady=2, sticky="w")

    def add_card_action(self, event=None):
        card_string = self.add_entry.get()
        if not self.current_deck or not card_string: return
        deck = self.service.deck_repo.session.get(Deck, self.current_deck['id'])
        if deck:
            self.service.deck_repo.add_card_to_blueprint(deck, card_string)
            self.add_entry.delete(0, 'end')
            self.display_deck(self.current_deck) # Refresh view
            
    def remove_card_action(self, oracle_card_id: int):
        if self.service.remove_card_from_blueprint(self.current_deck['id'], oracle_card_id):
            self.display_deck(self.current_deck)

    def export_action(self):
        if self.current_deck: self.service.export_buy_list(self.current_deck['id'])
        
    def launch_wizard(self):
        if self.current_deck:
            AssemblyWizardDialog(self, self.service, self.current_deck['id'], on_finish_callback=self.on_action_callback)
            
    def disassemble_action(self):
        if self.current_deck and self.service.disassemble_deck(self.current_deck['id']):
            self.on_action_callback()