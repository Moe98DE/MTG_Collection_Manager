import re
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func

from .scryfall_client import ScryfallClient
from .models import CardPrinting, OracleCard, Deck, DeckStatus, BlueprintEntry, CardInstance, CardPrinting # Add new imports

class CollectionRepository:
    def __init__(self, db_session: Session, scryfall_client: ScryfallClient):
        self.session = db_session
        self.scryfall_client = scryfall_client
        print("Collection Repository initialized.")

    def _parse_card_string(self, line: str) -> dict | None:
        """
        Parses a line in the format: '1 Nalia de'Arnise (CLB) 649 *F*'
        Returns a dictionary with the parsed components or None if parsing fails.
        """
        # Regex to capture: quantity, name, set code, collector number, and foil flag
        pattern = re.compile(
            r"^(?:(\d+)\s+)?\s*(.+?)\s+\((\w+)\)\s+([\w\d]+)(?:\s+\*F\*)?$"
        )
        match = pattern.match(line.strip())

        if not match:
            print(f"Error: Could not parse line '{line}'")
            return None

        quantity, name, set_code, collector_number = match.groups()

        return {
            'quantity': int(quantity) if quantity else 1,
            'name': name.strip(),
            'set_code': set_code.lower(),
            'collector_number': collector_number,
            'is_foil': '*F*' in line
        }

    def add_card_from_string(self, line: str) -> List[CardInstance]:
        """
        High-level method to process a string, fetch card data,
        and create CardInstance objects in the database.
        """
        parsed_data = self._parse_card_string(line)
        if not parsed_data:
            return []

        # Use the Scryfall client to get the CardPrinting object
        printing = self.scryfall_client.get_printing_by_set_and_number(
            set_code=parsed_data['set_code'],
            collector_number=parsed_data['collector_number']
        )

        if not printing:
            print(f"Error: Could not find card printing for '{parsed_data['name']}'")
            return []

        # Create the specified number of CardInstance objects
        new_instances = []
        for _ in range(parsed_data['quantity']):
            instance = CardInstance(
                printing_id=printing.id,
                is_foil=parsed_data['is_foil']
            )
            self.session.add(instance)
            new_instances.append(instance)

        self.session.commit()
        print(f"Successfully added {parsed_data['quantity']}x '{printing.oracle_card.name}' to collection.")
        return new_instances
        
    def view_collection_summary(self, filters: dict = None) -> list:
        """
        Queries the collection and returns a summary, grouped by OracleCard name.
        Dynamically applies a dictionary of complex filters.
        """
        if filters is None: filters = {}

        query = (
            self.session.query(
                OracleCard.name, 
                func.count(CardInstance.id).label("total_owned")
            )
            .join(CardPrinting, OracleCard.id == CardPrinting.oracle_card_id)
            .join(CardInstance, CardPrinting.id == CardInstance.printing_id)
        )

        # --- Dynamic Filter Application ---
        if filters.get('name'):
            query = query.filter(OracleCard.name.ilike(f"%{filters['name']}%"))
        
        if filters.get('type'):
            query = query.filter(OracleCard.type_line.ilike(f"%{filters['type']}%"))
        
        selected_colors = filters.get('colors', [])
        if selected_colors:
            # This logic ensures the card's color identity is a SUBSET of the selected colors.
            # For each color in the card's identity, it must be one of the selected colors.
            # A card with identity 'W' will match if 'W' or 'WU' is selected.
            # A card with identity 'WU' will only match if BOTH 'W' and 'U' are selected.
            for color in ['W', 'U', 'B', 'R', 'G']:
                if color in selected_colors:
                    # If user selected this color, we don't care if the card has it or not.
                    continue
                else:
                    # If user did NOT select this color, the card must NOT have it.
                    query = query.filter(OracleCard.color_identity.notlike(f"%{color}%"))
            
            if 'C' in selected_colors:
                # If colorless is explicitly selected, allow cards with empty color identity
                pass # This is implicitly handled by the logic above
        
        if filters.get('available'):
            # This is the core logic: only include instances that are NOT assigned to a deck.
            query = query.filter(CardInstance.deck_id == None)

        summary = (
            query
            .group_by(OracleCard.name)
            .order_by(OracleCard.name)
            .all()
        )
        return summary
    
    def get_instances_by_oracle_name(self, name: str) -> list:
        """
        Finds all physical CardInstances for a given abstract card name.
        It also joins the Deck information to check for availability.
        """
        # We perform an outerjoin so that if a card is not in a deck (deck_id is NULL),
        # we still get the card instance back.
        query_result = (
            self.session.query(CardInstance, CardPrinting, OracleCard, Deck)
            .join(CardPrinting, CardInstance.printing_id == CardPrinting.id)
            .join(OracleCard, CardPrinting.oracle_card_id == OracleCard.id)
            .outerjoin(Deck, CardInstance.deck_id == Deck.id)
            .filter(OracleCard.name.ilike(name))
            .all()
        )
        return query_result
    
    def get_assembled_deck_contents(self, deck_id: int) -> list:
        """
        Gets a summary of cards in an assembled deck, grouped by name.
        """
        return (
            self.session.query(
                OracleCard.name,
                func.count(CardInstance.id).label("quantity")
            )
            .join(CardPrinting, OracleCard.id == CardPrinting.oracle_card_id)
            .join(CardInstance, CardPrinting.id == CardInstance.printing_id)
            .filter(CardInstance.deck_id == deck_id)
            .group_by(OracleCard.name)
            .order_by(OracleCard.name)
            .all()
        )

class DeckRepository:
    def __init__(self, db_session: Session, scryfall_client: ScryfallClient):
        self.session = db_session
        self.scryfall_client = scryfall_client
        print("Deck Repository initialized.")
    
    def create_deck(self, name: str) -> Deck:
        """Creates a new, empty deck in the Blueprint state."""
        new_deck = Deck(name=name, status=DeckStatus.BLUEPRINT)
        self.session.add(new_deck)
        self.session.commit()
        print(f"Created new blueprint deck: '{name}'")
        return new_deck

    def add_card_to_blueprint(self, deck: Deck, card_string: str) -> BlueprintEntry | None:
        """
        Adds a card to a blueprint deck from a generic string like '2 Sol Ring'.
        """
        # Basic parsing for 'Quantity Name' format
        parts = card_string.strip().split(' ', 1)
        try:
            quantity = int(parts[0])
            card_name = parts[1]
        except (ValueError, IndexError):
            quantity = 1
            card_name = parts[0]

        if deck.status != DeckStatus.BLUEPRINT:
            print(f"Error: Can only add conceptual cards to a Blueprint deck.")
            return None

        oracle_card = self.scryfall_client.get_oracle_card_by_name(card_name)
        if not oracle_card:
            print(f"Could not add '{card_name}' to deck, card not found.")
            return None

        # Check if an entry for this card already exists
        existing_entry = self.session.query(BlueprintEntry).filter_by(
            deck_id=deck.id, 
            oracle_card_id=oracle_card.id
        ).first()

        if existing_entry:
            existing_entry.quantity += quantity
            print(f"Updated quantity for '{card_name}' in '{deck.name}' to {existing_entry.quantity}.")
        else:
            new_entry = BlueprintEntry(
                deck_id=deck.id,
                oracle_card_id=oracle_card.id,
                quantity=quantity
            )
            self.session.add(new_entry)
            print(f"Added {quantity}x '{card_name}' to '{deck.name}' blueprint.")
        
        self.session.commit()
        return existing_entry or new_entry # Return the entry that was created/updated

    def update_blueprint_entry_quantity(self, deck_id: int, oracle_card_id: int, new_quantity: int) -> None:
        """Updates the quantity of a card in a blueprint. Deletes the entry if quantity is 0 or less."""
        entry = self.session.query(BlueprintEntry).filter_by(
            deck_id=deck_id,
            oracle_card_id=oracle_card_id
        ).first()

        if not entry:
            print("Error: Could not find blueprint entry to update.")
            return

        if new_quantity <= 0:
            self.session.delete(entry)
            print(f"Removed '{entry.oracle_card.name}' from blueprint.")
        else:
            entry.quantity = new_quantity
            print(f"Updated '{entry.oracle_card.name}' quantity to {new_quantity}.")
        
        self.session.commit()

    def assemble_deck(self, deck_id: int, choices: dict) -> bool:
        """
        Transitions a deck from Blueprint to Assembled.
        - Assigns chosen CardInstances to the deck.
        - Deletes the old blueprint entries.
        """
        deck = self.session.get(Deck, deck_id)
        if not deck or deck.status != DeckStatus.BLUEPRINT:
            return False

        # Assign instances
        for instance_id in choices.values():
            instance = self.session.get(CardInstance, instance_id)
            if instance:
                instance.deck_id = deck_id

        # Delete old blueprint entries
        self.session.query(BlueprintEntry).filter_by(deck_id=deck_id).delete()
        
        # Update deck status
        deck.status = DeckStatus.ASSEMBLED
        self.session.commit()
        return True

    def disassemble_deck(self, deck_id: int) -> bool:
        """
        Transitions a deck from Assembled to Blueprint.
        - Frees all associated CardInstances.
        - Re-creates the blueprint entries based on the cards that were in the deck.
        """
        deck = self.session.get(Deck, deck_id)
        if not deck or deck.status != DeckStatus.ASSEMBLED:
            return False

        # Re-create blueprint from physical cards
        card_counts = {}
        for instance in deck.cards:
            oracle_id = instance.printing.oracle_card_id
            card_counts[oracle_id] = card_counts.get(oracle_id, 0) + 1
            instance.deck_id = None # Free the card instance

        for oracle_id, quantity in card_counts.items():
            new_entry = BlueprintEntry(deck_id=deck_id, oracle_card_id=oracle_id, quantity=quantity)
            self.session.add(new_entry)

        deck.status = DeckStatus.BLUEPRINT
        self.session.commit()
        return True

    def get_all_decks(self) -> list[Deck]:
        """Returns a list of all Deck objects, ordered by name."""
        return self.session.query(Deck).order_by(Deck.name).all()
        
    def delete_deck(self, deck_id: int) -> bool:
        """Deletes a deck and its associated blueprint entries."""
        deck = self.session.get(Deck, deck_id)
        if deck:
            # The 'cascade' option we set on the model will handle deleting blueprint entries.
            self.session.delete(deck)
            self.session.commit()
            print(f"Deleted deck: '{deck.name}'")
            return True
        return False