from dataclasses import dataclass, field
from typing import List, Optional

from core.repo.enums import BlueprintCardStatus, DeckStatus


@dataclass
class CollectionSummaryItem:
    """Represents a grouped entry in the collection summary view."""
    oracle_id: str
    name: str
    type_line: str
    mana_cost: Optional[str]
    cmc: float
    color_identity: str
    total_owned: int
    available_count: int
    representative_image_uri: Optional[str]
    keywords: List[str] = field(default_factory=list)

@dataclass
class BlueprintAnalysisItem:
    """Represents one card's status in a blueprint deck vs. the collection."""
    oracle_card_id: str
    card_name: str
    quantity_needed: int
    total_owned: int
    available_owned: int
    status: BlueprintCardStatus
    allocated_in_decks: List[str] = field(default_factory=list)

# --- NEW DTOs to be created ---

@dataclass
class CardInstanceDetailDTO:
    """Provides full details for a single physical card instance."""
    instance_id: int
    oracle_id: str
    card_name: str
    set_code: str
    collector_number: str
    is_foil: bool
    condition: str
    purchase_price: Optional[float]
    date_added: str  # Use string for API compatibility (ISO format)
    status: str      # e.g., "Available" or "In Deck: My Commander Deck"

@dataclass
class DeckSummaryDTO:
    """Provides a brief summary of a single deck."""
    id: int
    name: str
    status: DeckStatus

@dataclass
class AssembledDeckCardDTO:
    """Represents a card and its quantity within an assembled deck."""
    card_name: str
    quantity: int

@dataclass
class AssemblyChoiceDTO:
    """Represents a single physical card instance that can be chosen for deck assembly."""
    instance_id: int
    display_text: str  # e.g., "CLB #649 (Foil) - NM"

@dataclass
class AssemblyOptionDTO:
    """Represents all available choices for a single card needed for a deck blueprint."""
    oracle_card_id: str
    card_name: str
    quantity_needed: int
    available_instances: List[AssemblyChoiceDTO]