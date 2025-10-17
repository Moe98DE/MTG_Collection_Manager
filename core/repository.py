import re
from collections import Counter
from typing import List, Dict
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case

from .exceptions import InvalidInputFormatError, InstanceAlreadyAllocatedError, CardNotFoundError, DeckAssemblyError
from .scryfall_client import ScryfallClient
from .models import CardPrinting, OracleCard, Deck, DeckStatus, BlueprintEntry, CardInstance, CardPrinting # Add new imports

class CollectionRepository:
    def __init__(self, db_session: Session, scryfall_client: ScryfallClient):
        self.session = db_session
        self.scryfall_client = scryfall_client
        # A list of fields that are safe for a user to update on a CardInstance
        self.updatable_instance_fields = ['is_foil', 'condition', 'purchase_price', 'deck_id']
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
            raise InvalidInputFormatError(line=line)

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
        High-level method to process a string, fetch card data, verify it,
        and create CardInstance objects in the database.
        """
        parsed_data = self._parse_card_string(line)

        # This will raise an exception if parsing fails.
        user_provided_name = parsed_data['name']

        printing = self.scryfall_client.get_printing_by_set_and_number(
            set_code=parsed_data['set_code'],
            collector_number=parsed_data['collector_number']
        )

        # Scryfall client raises CardNotFoundError if the set/number combo is invalid
        # But we still need to check if the card found is the one the user asked for.

        # --- THE CRITICAL FIX ---
        # Compare the name parsed from the user's string with the name from Scryfall.
        # We use `.lower()` and check if the user's name is a substring to allow for
        # partial names like "Sol Ring" for "Sol Ring // Sol Talisman".
        scryfall_card_name = printing.oracle_card.name.lower()
        if user_provided_name.lower() not in scryfall_card_name:
            raise CardNotFoundError(
                identifier=f"'{user_provided_name}' does not match the card found at "
                           f"{parsed_data['set_code'].upper()} #{parsed_data['collector_number']}: "
                           f"'{printing.oracle_card.name}'"
            )
        # --- END OF FIX ---

        new_instances = []
        for _ in range(parsed_data['quantity']):
            instance = CardInstance(
                printing_id=printing.id,
                is_foil=parsed_data['is_foil']
                # date_added is handled by the DB default
            )
            self.session.add(instance)
            new_instances.append(instance)

        self.session.commit()
        print(f"Successfully added {parsed_data['quantity']}x '{printing.oracle_card.name}' to collection.")
        return new_instances

    def add_cards_from_list_transactional(self, card_lines: List[str]) -> Dict[str, any]:
        """
        Processes a list of card strings, preparing them for a single transaction.
        This method does NOT commit the session.

        Returns a dictionary containing a list of successfully created CardInstance objects
        and a list of lines that failed to process.
        """
        successful_instances = []
        failed_lines = []

        for line in card_lines:
            line = line.strip()
            if not line:
                continue

            try:
                # We can reuse the single-add logic, but we must catch its exceptions locally
                # instead of letting them halt the entire process.
                parsed_data = self._parse_card_string(line)
                user_provided_name = parsed_data['name']

                printing = self.scryfall_client.get_printing_by_set_and_number(
                    set_code=parsed_data['set_code'],
                    collector_number=parsed_data['collector_number']
                )

                scryfall_card_name = printing.oracle_card.name.lower()
                if user_provided_name.lower() not in scryfall_card_name:
                    raise CardNotFoundError(
                        identifier=f"'{user_provided_name}' does not match the card found: '{printing.oracle_card.name}'"
                    )

                for _ in range(parsed_data['quantity']):
                    instance = CardInstance(
                        printing_id=printing.id,
                        is_foil=parsed_data['is_foil']
                    )
                    self.session.add(instance)
                    successful_instances.append(instance)

                print(f"Prepared {parsed_data['quantity']}x '{printing.oracle_card.name}' for addition.")

            except (InvalidInputFormatError, CardNotFoundError) as e:
                print(f"Skipping line due to error: '{line}' -> {e.message}")
                failed_lines.append(line)
            # Note: We do NOT catch generic Exception, as that might hide a real database problem.

        return {"successes": successful_instances, "failures": failed_lines}

    def view_collection_summary(self, filters: dict = None) -> list:
        """
        Queries the collection and returns a summary, grouped by OracleCard.
        Dynamically applies a dictionary of complex filters.
        Returns a list of tuples:
        (OracleCard object, total_owned, available_count, representative_image_uri)
        """
        if filters is None: filters = {}

        query = (
            self.session.query(
                OracleCard,
                func.count(CardInstance.id).label("total_owned"),
                func.sum(case((CardInstance.deck_id == None, 1), else_=0)).label("available_count"),
                # UPDATED: Add an aggregate to get one representative image URI for the group.
                # MIN() is a simple and effective way to deterministically pick one image.
                func.min(CardPrinting.image_uri_normal).label("image_uri")
            )
            .join(CardPrinting, OracleCard.id == CardPrinting.oracle_card_id)
            .join(CardInstance, CardPrinting.id == CardInstance.printing_id)
        )

        # --- Dynamic Filter Application ---
        # (All the filter logic remains exactly the same as before)
        if filters.get('name'):
            query = query.filter(OracleCard.name.ilike(f"%{filters['name']}%"))

        if filters.get('type_line'):
            query = query.filter(OracleCard.type_line.ilike(f"%{filters['type_line']}%"))

        if filters.get('oracle_text'):
            query = query.filter(OracleCard.oracle_text.ilike(f"%{filters['oracle_text']}%"))

        cmc_filter = filters.get('cmc')
        if isinstance(cmc_filter, dict) and 'op' in cmc_filter and 'value' in cmc_filter:
            op = cmc_filter['op']
            val = cmc_filter['value']
            if op == '<=':
                query = query.filter(OracleCard.cmc <= val)
            elif op == '>=':
                query = query.filter(OracleCard.cmc >= val)
            elif op == '=':
                query = query.filter(OracleCard.cmc == val)

        selected_colors = filters.get('colors', [])
        if selected_colors:
            for color in ['W', 'U', 'B', 'R', 'G']:
                if color not in selected_colors:
                    query = query.filter(OracleCard.color_identity.notlike(f"%{color}%"))

        if filters.get('set_code'):
            subquery = (
                self.session.query(CardInstance.id)
                .join(CardPrinting)
                .filter(CardPrinting.set_code.ilike(filters['set_code']))
                .subquery()
            )
            query = query.filter(CardInstance.id.in_(subquery))

        availability = filters.get('availability')
        if availability == 'Only Available':
            query = query.filter(CardInstance.deck_id == None)
        elif availability == 'Only Allocated':
            query = query.filter(CardInstance.deck_id != None)

        summary = (
            query
            .group_by(OracleCard.id)
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

    def delete_card_instance(self, instance_id: int) -> bool:
        """Deletes a single physical card instance from the database."""
        instance = self.session.get(CardInstance, instance_id)
        if instance:
            # Important check: Do not delete if it's part of an assembled deck.
            if instance.deck_id is not None:
                raise InstanceAlreadyAllocatedError(
                    instance_id=instance.id,
                    deck_name=instance.deck.name
                )
            
            self.session.delete(instance)
            self.session.commit()
            print(f"Successfully deleted card instance {instance_id}.")
            return True
        
        raise CardNotFoundError(identifier=f"Instance ID {instance_id}")

    def update_card_instance(self, instance_id: int, update_data: dict) -> CardInstance:
        """
        Updates attributes of a specific CardInstance.

        Args:
            instance_id: The primary key of the CardInstance to update.
            update_data: A dictionary where keys are field names and values are the new values.

        Returns:
            The updated CardInstance object.

        Raises:
            CardNotFoundError: If no instance with the given ID is found.
            ValueError: If an invalid field is provided in update_data.
        """
        instance = self.session.get(CardInstance, instance_id)

        if not instance:
            raise CardNotFoundError(identifier=f"Instance ID {instance_id}")

        for field, value in update_data.items():
            if field in self.updatable_instance_fields:
                setattr(instance, field, value)
            else:
                # Raise an error to prevent updating protected fields like 'id' or 'printing_id'
                raise ValueError(f"'{field}' is not an updatable field on CardInstance.")

        self.session.commit()
        self.session.refresh(instance)  # Refresh the object with the latest data from the DB
        print(f"Successfully updated card instance {instance_id}.")
        return instance

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
        
        self.session.commit()

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