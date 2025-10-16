import customtkinter as ctk

class AssemblyWizardDialog(ctk.CTkToplevel):
    def __init__(self, master, service, deck_id, on_finish_callback):
        super().__init__(master)
        self.service = service
        self.deck_id = deck_id
        self.on_finish = on_finish_callback
        self.choices = {}  # To store the dropdown widgets

        self.title("Deck Assembly Wizard")
        self.geometry("600x500")
        self.transient(master)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        scroll_frame = ctk.CTkScrollableFrame(self, label_text="Select Card Printings")
        scroll_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        scroll_frame.grid_columnconfigure(0, weight=1)

        options = self.service.get_assembly_options(deck_id)
        row_counter = 0

        for card in options:
            needed = card['quantity_needed']
            available = card['available_instances']
            
            ctk.CTkLabel(scroll_frame, text=f"{needed}x {card['card_name']}", font=ctk.CTkFont(weight="bold")).grid(
                row=row_counter, column=0, columnspan=2, padx=5, pady=(10, 2), sticky="w")
            row_counter += 1

            if len(available) < needed:
                ctk.CTkLabel(scroll_frame, text=f"  ⚠️ Not enough copies available! (Need {needed}, have {len(available)})", text_color="orange").grid(
                    row=row_counter, column=0, columnspan=2, padx=15, pady=2, sticky="w")
                row_counter += 1
                continue

            self.choices[card['oracle_card_id']] = []
            for i in range(needed):
                choice_var = ctk.StringVar()
                
                # Filter out already selected choices for subsequent dropdowns
                # This prevents assigning the same physical card twice
                available_for_this_dropdown = [inst for inst in available if inst['instance_id'] not in [v.get().split(' | ')[0] for v in self.choices[card['oracle_card_id']]]]
                
                dropdown_options = [f"{inst['instance_id']} | {inst['text']}" for inst in available_for_this_dropdown]

                if not dropdown_options: continue

                dropdown = ctk.CTkOptionMenu(scroll_frame, variable=choice_var, values=dropdown_options)
                dropdown.grid(row=row_counter, column=0, columnspan=2, padx=15, pady=2, sticky="ew")
                self.choices[card['oracle_card_id']].append(choice_var)
                row_counter += 1

        confirm_button = ctk.CTkButton(self, text="Confirm Assembly", command=self.confirm)
        confirm_button.grid(row=1, column=0, padx=10, pady=10)

    def confirm(self):
        final_choices = {}
        for oracle_id, choice_vars in self.choices.items():
            for var in choice_vars:
                # The value is "instance_id | text", we just want the ID
                instance_id = int(var.get().split(' | ')[0])
                final_choices[instance_id] = instance_id # Key doesn't matter, value is the instance_id

        if self.service.assemble_deck(self.deck_id, final_choices):
            self.on_finish()
        self.destroy()