from dataclasses import dataclass, field
from typing import List

from core.repo.enums import BlueprintCardStatus


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