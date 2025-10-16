import customtkinter as ctk
from .filter_panel import FilterPanel # <-- NEW IMPORT

class CollectionFrame(ctk.CTkFrame):
    def __init__(self, master, service):
        super().__init__(master)
        self.service = service

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1) # The list is now in row 3

        self.collection_label = ctk.CTkLabel(self, text="My Collection", font=("Arial", 16))
        self.collection_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        
        self.search_entry = ctk.CTkEntry(self, placeholder_text="Filter by name...")
        self.search_entry.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.search_entry.bind("<KeyRelease>", self.on_search_change)
        
        # *** NEW: Add the filter panel ***
        self.filter_panel = FilterPanel(self, on_filter_change_callback=self.refresh)
        self.filter_panel.grid(row=2, column=0, padx=10, pady=0, sticky="ew")

        self.collection_scroll_frame = ctk.CTkScrollableFrame(self)
        self.collection_scroll_frame.grid(row=3, column=0, padx=10, pady=(0, 10), sticky="nsew")
        
        self.action_frame = ctk.CTkFrame(self)
        self.action_frame.grid(row=4, column=0, padx=10, pady=5, sticky="ew")

        self.export_button = ctk.CTkButton(self.action_frame, text="Export Visible Cards to Clipboard",
                                           command=self.export_collection_action)
        self.export_button.pack(padx=5, pady=5)

        self.refresh()

    def export_collection_action(self):
        """Gathers current filters and triggers the export service."""
        print("UI: Preparing to export collection...")
        
        # This logic is identical to the start of the refresh() method
        search_term = self.search_entry.get()
        advanced_filters = self.filter_panel.get_filters()
        all_filters = { 'name': search_term, **advanced_filters }
        
        self.service.export_collection(filters=all_filters)

    def on_search_change(self, event=None):
        self.refresh()

    def refresh(self):
        for widget in self.collection_scroll_frame.winfo_children():
            widget.destroy()

        # *** CHANGE: Get filters from both places ***
        search_term = self.search_entry.get()
        advanced_filters = self.filter_panel.get_filters()
        
        # Combine all filters into one dictionary
        all_filters = {
            'name': search_term,
            **advanced_filters # This cleverly merges the two dictionaries
        }
        
        collection_data = self.service.get_collection_summary(filters=all_filters)

        if not collection_data:
            label = ctk.CTkLabel(self.collection_scroll_frame, text="No matches found.")
            label.pack(padx=10, pady=10)
        else:
            for card in collection_data:
                card_name = card['name']
                card_count = card['count']
                
                row_frame = ctk.CTkFrame(self.collection_scroll_frame, cursor="hand2")
                row_frame.pack(fill="x", padx=5, pady=2)
                
                row_frame.bind("<Button-1>", lambda event, name=card_name: self.show_details_for_card(name))
                
                label_text = f"{card_name} (x{card_count})"
                label = ctk.CTkLabel(row_frame, text=label_text, anchor="w")
                label.pack(side="left", padx=10, pady=5)
                label.bind("<Button-1>", lambda event, name=card_name: self.show_details_for_card(name))

    def show_details_for_card(self, card_name: str):
        instances = self.service.get_instances_for_oracle_card(card_name)
        if not instances: return

        details_window = ctk.CTkToplevel(self)
        details_window.title(f"Details for {card_name}")
        details_window.geometry("500x300")
        details_window.transient(self)
        details_window.grid_columnconfigure(0, weight=1)

        scroll_frame = ctk.CTkScrollableFrame(details_window, label_text=f"Owned Copies of {card_name}")
        scroll_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        scroll_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        headers = ["Set", "Number", "Foil", "Status"]
        for i, header in enumerate(headers):
            header_label = ctk.CTkLabel(scroll_frame, text=header, font=ctk.CTkFont(weight="bold"))
            header_label.grid(row=0, column=i, padx=5, pady=5)

        for i, instance in enumerate(instances):
            ctk.CTkLabel(scroll_frame, text=instance['set_code']).grid(row=i+1, column=0, padx=5, pady=2)
            ctk.CTkLabel(scroll_frame, text=instance['collector_number']).grid(row=i+1, column=1, padx=5, pady=2)
            ctk.CTkLabel(scroll_frame, text="Yes" if instance['is_foil'] else "No").grid(row=i+1, column=2, padx=5, pady=2)
            ctk.CTkLabel(scroll_frame, text=instance['status']).grid(row=i+1, column=3, padx=5, pady=2)