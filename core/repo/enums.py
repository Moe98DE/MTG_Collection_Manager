# In core/models.py (alongside DeckStatus)
import enum

class BlueprintCardStatus(enum.Enum):
    """
    Defines the status of a card in a blueprint relative to the user's collection.
    Corresponds to TRS 4.2.5.
    """
    # Using descriptive names for the enum members is good practice.
    # The value is what will be serialized (e.g., sent as JSON to a frontend).
    OWNED_AVAILABLE = "OWNED_AVAILABLE"    # Quantity owned and available >= quantity in deck
    OWNED_ALLOCATED = "OWNED_ALLOCATED"    # Not enough available, but total owned is sufficient
    PARTIALLY_OWNED = "PARTIALLY_OWNED"    # Total owned > 0 but < quantity in deck
    MISSING = "MISSING"                    # Total owned = 0

    def __str__(self):
        # This makes it easy to print the enum or use it in f-strings
        return self.value