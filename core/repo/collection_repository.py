import re
from typing import List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from core.exceptions import InvalidInputFormatError, InstanceAlreadyAllocatedError, CardNotFoundError
from core.api.scryfall_client import ScryfallClient
from core.models import OracleCard, Deck, CardInstance, CardPrinting # Add new imports

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
