from collections import Counter
from typing import List, Dict

from sqlalchemy.orm import Session, joinedload

from core.exceptions import DeckAssemblyError, CardNotFoundError
from core.models import Deck, DeckStatus, BlueprintEntry, OracleCard, CardInstance, CardPrinting
from core.api.scryfall_client import ScryfallClient
from core.repo.dtos import BlueprintAnalysisItem
from core.repo.enums import BlueprintCardStatus


class DeckRepository:
    def __init__(self, db_session: Session, scryfall_client: ScryfallClient):
        self.session = db_session
        self.scryfall_client = scryfall_client
        print("Deck Repository initialized.")

    def create_deck(self, name: str) -> Deck:
        """Creates a new, empty deck in the Blueprint state."""
        new_deck = Deck(name=name, status=DeckStatus.BLUEPRINT)
        self.session.add(new_deck)
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

        return existing_entry or new_entry # Return the entry that was created/updated

    def add_cards_to_blueprint_transactional(self, deck_id: int, card_lines: List[str]) -> Dict[str, List[str]]:
        """
        Processes a list of card strings to add to a blueprint. This method does NOT commit.
        It efficiently handles aggregating quantities for cards that appear multiple times.
        """
        deck = self.session.get(Deck, deck_id)
        if not deck or deck.status != DeckStatus.BLUEPRINT:
            raise DeckAssemblyError(f"Deck with ID {deck_id} is not a valid blueprint.")

        failed_lines = []
        # Step 1: Parse all lines and aggregate quantities in memory
        card_quantities = {}  # Key: card_name, Value: total_quantity
        for line in card_lines:
            line = line.strip()
            if not line: continue

            parts = line.split(' ', 1)
            try:
                quantity = int(parts[0])
                card_name = parts[1]
            except (ValueError, IndexError):
                quantity = 1
                card_name = parts[0]

            # Use .title() to normalize capitalization, e.g., "sol ring" becomes "Sol Ring"
            normalized_name = card_name.title()
            card_quantities[normalized_name] = card_quantities.get(normalized_name, 0) + quantity

        # Step 2: Fetch all relevant data in as few queries as possible
        all_card_names = list(card_quantities.keys())

        # Find which of these oracle cards and blueprint entries already exist
        oracle_cards_found = self.session.query(OracleCard).filter(OracleCard.name.in_(all_card_names)).all()
        oracle_card_map = {card.name: card for card in oracle_cards_found}

        existing_entries = self.session.query(BlueprintEntry).filter(
            BlueprintEntry.deck_id == deck_id,
            BlueprintEntry.oracle_card_id.in_([c.id for c in oracle_cards_found])
        ).all()
        existing_entry_map = {entry.oracle_card.name: entry for entry in existing_entries}

        # Step 3: Process the aggregated list
        for name, quantity in card_quantities.items():
            # Find the OracleCard, fetching from Scryfall if not in our DB yet
            oracle_card = oracle_card_map.get(name)
            if not oracle_card:
                try:
                    oracle_card = self.scryfall_client.get_oracle_card_by_name(name)
                    if not oracle_card: raise CardNotFoundError(name)
                except CardNotFoundError:
                    print(f"Skipping line due to error: Card not found for '{name}'")
                    failed_lines.append(name)
                    continue

            # Check if an entry for this card already exists in the deck
            if name in existing_entry_map:
                existing_entry_map[name].quantity += quantity
                print(f"Prepared update for '{name}' to total quantity {existing_entry_map[name].quantity}.")
            else:
                new_entry = BlueprintEntry(deck_id=deck_id, oracle_card_id=oracle_card.id, quantity=quantity)
                self.session.add(new_entry)
                print(f"Prepared addition of {quantity}x '{name}'.")

        return {"failures": failed_lines}

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


    # NEW: A dedicated validation method.
    def validate_assembly_choices(self, deck_id: int, chosen_instance_ids: List[int]) -> bool:
        """
        Validates if the user's chosen CardInstances are sufficient and valid for a blueprint.

        Raises:
            DeckAssemblyError: If validation fails for any reason.

        Returns:
            True if the choices are valid.
        """
        deck = self.session.query(Deck).options(
            joinedload(Deck.blueprint_entries).joinedload(BlueprintEntry.oracle_card)
        ).get(deck_id)

        if not deck or deck.status != DeckStatus.BLUEPRINT:
            raise DeckAssemblyError(f"Deck with ID {deck_id} is not a valid blueprint for assembly.")

        # 1. Get the blueprint requirements (what we need)
        blueprint_needs = {entry.oracle_card_id: entry.quantity for entry in deck.blueprint_entries}

        # 2. Get the chosen physical cards (what we have)
        chosen_instances = self.session.query(CardInstance).options(joinedload(CardInstance.printing)).filter(
            CardInstance.id.in_(chosen_instance_ids)
        ).all()

        # 3. Check for invalid or already-allocated instances
        if len(chosen_instances) != len(chosen_instance_ids):
            raise DeckAssemblyError("One or more selected card instance IDs are invalid.")

        for inst in chosen_instances:
            if inst.deck_id is not None:
                raise DeckAssemblyError(
                    f"Card '{inst.printing.oracle_card.name}' (ID: {inst.id}) is already in another deck.")

        # 4. Count the Oracle IDs of the chosen cards and compare with the blueprint
        chosen_oracle_ids = [inst.printing.oracle_card_id for inst in chosen_instances]
        chosen_counts = Counter(chosen_oracle_ids)

        for oracle_id, needed_qty in blueprint_needs.items():
            if chosen_counts.get(oracle_id, 0) < needed_qty:
                # Find card name for a better error message
                card_name = self.session.get(OracleCard, oracle_id).name
                raise DeckAssemblyError(
                    f"Not enough cards chosen for '{card_name}'. Need {needed_qty}, but only got {chosen_counts.get(oracle_id, 0)}.")

        if sum(chosen_counts.values()) != sum(blueprint_needs.values()):
            raise DeckAssemblyError(
                "The total number of chosen cards does not match the total number of cards in the blueprint.")

        return True

    def assemble_deck(self, deck_id: int, chosen_instance_ids: List[int]):
        """
        Transitions a deck from Blueprint to Assembled.
        This method does NOT commit. The calling service is responsible for transaction management.
        """
        # The 'with begin_nested()' ensures this block is atomic (creates a SAVEPOINT).
        # If anything inside fails, only these changes are rolled back.
        with self.session.begin_nested():
            deck = self.session.get(Deck, deck_id)
            if not deck or deck.status != DeckStatus.BLUEPRINT:
                # Raise an error instead of returning False to ensure transaction rollback
                raise DeckAssemblyError(f"Deck {deck_id} is not a valid blueprint.")

            # Assign instances...
            self.session.query(CardInstance).filter(
                CardInstance.id.in_(chosen_instance_ids)
            ).update({"deck_id": deck_id}, synchronize_session=False)

            # Delete blueprint...
            self.session.query(BlueprintEntry).filter_by(deck_id=deck_id).delete(synchronize_session=False)

            # Update status...
            deck.status = DeckStatus.ASSEMBLED

        print(f"Deck '{deck.name}' successfully prepared for assembly commit.")

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
            print(f"Deleted deck: '{deck.name}'")
            return True
        return False

    def analyze_blueprint_against_collection(self, deck_id: int) -> List[BlueprintAnalysisItem]:
        """
        Performs a comprehensive analysis of a blueprint deck against the user's collection.
        This is the core logic for the "buy list" and "deck check" features.

        Args:
            deck_id: The ID of the blueprint deck to analyze.

        Returns:
            A list of BlueprintAnalysisItem DTOs detailing the status of each card.
        """
        deck = self.session.get(Deck, deck_id)
        if not deck or deck.status != DeckStatus.BLUEPRINT:
            # It's better to raise an exception for an invalid deck ID or status
            # than to return an empty list, as it's an exceptional circumstance.
            raise ValueError(f"Deck with ID {deck_id} is not a valid blueprint.")

        # --- Step 1: Get all card requirements from the blueprint ---
        blueprint_requirements = {
            entry.oracle_card_id: {
                "name": entry.oracle_card.name,
                "needed": entry.quantity
            }
            for entry in deck.blueprint_entries
        }
        all_required_oracle_ids = list(blueprint_requirements.keys())

        if not all_required_oracle_ids:
            return []  # Deck is empty, nothing to analyze

        # --- Step 2: Get all owned instances of the required cards in ONE query ---
        # This is more efficient than separate queries for 'total' and 'available'.
        owned_instances = (
            self.session.query(
                CardPrinting.oracle_card_id,
                CardInstance.deck_id,
                Deck.name.label("deck_name")  # Get the deck name if it exists
            )
            .join(CardInstance, CardPrinting.id == CardInstance.printing_id)
            .outerjoin(Deck, CardInstance.deck_id == Deck.id)
            .filter(CardPrinting.oracle_card_id.in_(all_required_oracle_ids))
            .all()
        )

        # --- Step 3: Process the query results into a useful structure in memory ---
        # { oracle_id: {"total": 5, "available": 2, "allocations": ["Deck A", "Deck B"]} }
        collection_state = {
            oracle_id: {"total": 0, "available": 0, "allocations": []}
            for oracle_id in all_required_oracle_ids
        }

        for oracle_id, deck_id, deck_name in owned_instances:
            collection_state[oracle_id]["total"] += 1
            if deck_id is None:
                collection_state[oracle_id]["available"] += 1
            else:
                # Add deck name to the list if it's not already there
                if deck_name not in collection_state[oracle_id]["allocations"]:
                    collection_state[oracle_id]["allocations"].append(deck_name)

        # --- Step 4: Combine blueprint needs with collection state to generate the final analysis ---
        analysis_results = []
        for oracle_id, needs in blueprint_requirements.items():
            state = collection_state.get(oracle_id, {"total": 0, "available": 0, "allocations": []})
            needed_qty = needs['needed']
            total_owned = state['total']
            available_owned = state['available']

            status = BlueprintCardStatus.MISSING  # Default status
            if available_owned >= needed_qty:
                status = BlueprintCardStatus.OWNED_AVAILABLE
            elif total_owned >= needed_qty:
                status = BlueprintCardStatus.OWNED_ALLOCATED
            elif total_owned > 0:
                status = BlueprintCardStatus.PARTIALLY_OWNED

            analysis_results.append(BlueprintAnalysisItem(
                oracle_card_id=oracle_id,
                card_name=needs['name'],
                quantity_needed=needed_qty,
                total_owned=total_owned,
                available_owned=available_owned,
                status=status,
                allocated_in_decks=state['allocations']
            ))

        # Sort alphabetically by card name for a consistent UI presentation
        analysis_results.sort(key=lambda x: x.card_name)
        return analysis_results