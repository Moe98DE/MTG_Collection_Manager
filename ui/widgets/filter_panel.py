import customtkinter as ctk

class FilterPanel(ctk.CTkFrame):
    def __init__(self, master, on_filter_change_callback):
        super().__init__(master)
        self.on_filter_change = on_filter_change_callback

        # --- Color Filters ---
        color_frame = ctk.CTkFrame(self)
        color_frame.pack(pady=5, padx=10, fill="x")
        ctk.CTkLabel(color_frame, text="Colors:").pack(side="left", padx=(5, 10))

        self.color_vars = {
            "W": ctk.StringVar(value="off"), "U": ctk.StringVar(value="off"),
            "B": ctk.StringVar(value="off"), "R": ctk.StringVar(value="off"),
            "G": ctk.StringVar(value="off"), "C": ctk.StringVar(value="off")
        }
        
        for color in self.color_vars:
            cb = ctk.CTkCheckBox(color_frame, text=color, variable=self.color_vars[color],
                                 onvalue="on", offvalue="off", command=self.on_filter_change, width=20)
            cb.pack(side="left", padx=5)

        # --- Type Filter ---
        type_frame = ctk.CTkFrame(self)
        type_frame.pack(pady=5, padx=10, fill="x")
        ctk.CTkLabel(type_frame, text="Type Line:").pack(side="left", padx=(5, 10))
        self.type_entry = ctk.CTkEntry(type_frame, placeholder_text="e.g., 'Creature', 'Legendary', 'Artifact'")
        self.type_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.type_entry.bind("<KeyRelease>", lambda e: self.on_filter_change())

        other_frame = ctk.CTkFrame(self)
        other_frame.pack(pady=5, padx=10, fill="x")

        # *** NEW: Available Checkbox ***
        self.available_var = ctk.StringVar(value="off")
        available_cb = ctk.CTkCheckBox(other_frame, text="Only show Available",
                                       variable=self.available_var, onvalue="on", offvalue="off",
                                       command=self.on_filter_change)
        available_cb.pack(side="left", padx=5)

    def get_filters(self) -> dict:
        """Constructs and returns the filters dictionary based on UI state."""
        filters = {}
        
        # Get selected colors
        selected_colors = [color for color, var in self.color_vars.items() if var.get() == "on"]
        if selected_colors:
            filters['colors'] = selected_colors
        
        # Get type text
        type_text = self.type_entry.get()
        if type_text:
            filters['type'] = type_text
            
        if self.available_var.get() == "on":
            filters['available'] = True
            
        return filters