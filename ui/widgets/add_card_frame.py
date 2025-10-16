import customtkinter as ctk

class AddCardFrame(ctk.CTkFrame):
    def __init__(self, master, service, on_add_callback):
        super().__init__(master)
        self.service = service
        # This callback allows this component to trigger a refresh in the main app
        self.on_add_callback = on_add_callback

        self.grid_columnconfigure(1, weight=1)

        # --- Widgets ---
        self.add_card_label = ctk.CTkLabel(self, text="Add Card:")
        self.add_card_label.grid(row=0, column=0, padx=10, pady=10)

        self.add_card_entry = ctk.CTkEntry(self, placeholder_text="e.g., 2 Sol Ring (LTC) 289 *F*")
        self.add_card_entry.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.add_card_entry.bind("<Return>", self.add_card_action)

        self.add_card_button = ctk.CTkButton(self, text="Add", command=self.add_card_action)
        self.add_card_button.grid(row=0, column=2, padx=10, pady=10)
        
        self.import_list_button = ctk.CTkButton(self, text="Import List", command=self.show_import_dialog)
        self.import_list_button.grid(row=0, column=3, padx=10, pady=10)

    def add_card_action(self, event=None):
        card_string = self.add_card_entry.get()
        if not card_string: return
        
        success = self.service.add_card_to_collection(card_string)
        if success:
            self.add_card_entry.delete(0, 'end')
            self.on_add_callback() # Call the refresh function in the main app
        else:
            print("UI: Failed to add card. Check console.")

    def show_import_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Import Card List")
        dialog.geometry("500x400")
        dialog.transient(self)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)

        dialog_label = ctk.CTkLabel(dialog, text="Paste your card list below (one per line):")
        dialog_label.grid(row=0, column=0, padx=10, pady=10)

        textbox = ctk.CTkTextbox(dialog)
        textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        def submit_action():
            card_list_string = textbox.get("1.0", "end")
            if not card_list_string.strip():
                dialog.destroy()
                return

            result = self.service.add_cards_from_list(card_list_string)
            print(f"UI: Import complete. Success: {result['success']}, Failed: {result['failure']}")
            
            if result['success'] > 0:
                self.on_add_callback() # Call the refresh function
            
            dialog.destroy()

        submit_button = ctk.CTkButton(dialog, text="Submit", command=submit_action)
        submit_button.grid(row=2, column=0, padx=10, pady=10)