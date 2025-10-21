import re
from typing import List, Dict
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case, tuple_

from core.exceptions import InvalidInputFormatError, InstanceAlreadyAllocatedError, CardNotFoundError
from core.api.scryfall_client import ScryfallClient
from core.models import OracleCard, Deck, CardInstance, CardPrinting  # Add new imports


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
        Checks local cache before calling Scryfall API.
        """
        parsed_data = self._parse_card_string(line)
        user_provided_name = parsed_data['name']

        # --- MODIFICATION ---
        # First, try to find the printing in our local database to avoid an API call.
        printing = self.session.query(CardPrinting).options(
            joinedload(CardPrinting.oracle_card)  # Eager load for the name check later
        ).filter_by(
            set_code=parsed_data['set_code'],
            collector_number=parsed_data['collector_number']
        ).first()

        if printing:
            print(f"Found '{printing.oracle_card.name}' ({parsed_data['set_code'].upper()}) in local cache.")
        else:
            # If not found locally, then call the Scryfall client.
            print(
                f"Card {parsed_data['set_code'].upper()} #{parsed_data['collector_number']} not in cache, fetching from Scryfall...")
            printing = self.scryfall_client.get_printing_by_set_and_number(
                set_code=parsed_data['set_code'],
                collector_number=parsed_data['collector_number']
            )
        # --- END MODIFICATION ---

        # Scryfall client raises CardNotFoundError if the set/number combo is invalid
        # But we still need to check if the card found is the one the user asked for.
        scryfall_card_name = printing.oracle_card.name.lower()
        if user_provided_name.lower() not in scryfall_card_name:
            raise CardNotFoundError(
                identifier=f"'{user_provided_name}' does not match the card found at "
                           f"{parsed_data['set_code'].upper()} #{parsed_data['collector_number']}: "
                           f"'{printing.oracle_card.name}'"
            )

        new_instances = []
        for _ in range(parsed_data['quantity']):
            instance = CardInstance(
                printing_id=printing.id,
                is_foil=parsed_data['is_foil']
                # date_added is handled by the DB default
            )
            self.session.add(instance)
            new_instances.append(instance)

        print(f"Successfully prepared {parsed_data['quantity']}x '{printing.oracle_card.name}' for addition.")
        return new_instances

    def add_cards_from_list_transactional(self, card_lines: List[str]) -> Dict[str, any]:
        """
        Processes a list of card strings, preparing them for a single transaction.
        This method does NOT commit the session. It has been optimized to check the local
        cache for all cards first before making any API calls to Scryfall.

        Returns a dictionary containing a list of successfully created CardInstance objects
        and a list of lines that failed to process.
        """
        successful_instances = []
        failed_lines = []

        # 1. Parse all lines and identify the unique printings we need to find.
        parsed_data_map = {}  # Maps original line -> parsed data dict
        unique_printings_to_find = set()

        for line in card_lines:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = self._parse_card_string(line)
                parsed_data_map[line] = parsed
                # Store a tuple of (set_code, collector_number) for lookup
                unique_printings_to_find.add(
                    (parsed['set_code'], parsed['collector_number'])
                )
            except InvalidInputFormatError as e:
                print(f"Skipping line due to parsing error: '{line}' -> {e.message}")
                failed_lines.append(line)

        if not unique_printings_to_find:
            return {"successes": [], "failures": failed_lines}

        # --- REFACTOR START: Query the DB in chunks to avoid SQLite variable limits ---

        # 2. Perform bulk queries in chunks to get all existing printings from our DB cache.
        printings_cache = {}
        keys_to_query = list(unique_printings_to_find)
        # SQLite's default variable limit is 999. Each tuple uses 2 variables.
        # A chunk size of 400 (800 variables) is safely under this limit.
        CHUNK_SIZE = 400

        print(f"Preparing to query the local cache for {len(keys_to_query)} unique printings...")

        for i in range(0, len(keys_to_query), CHUNK_SIZE):
            chunk = keys_to_query[i:i + CHUNK_SIZE]

            found_printings_query = self.session.query(CardPrinting).options(
                joinedload(CardPrinting.oracle_card)
            ).filter(
                tuple_(CardPrinting.set_code, CardPrinting.collector_number).in_(chunk)
            )

            # Update the main cache with the results from this chunk
            for p in found_printings_query.all():
                printings_cache[(p.set_code, p.collector_number)] = p

        # --- REFACTOR END ---

        print(f"Found {len(printings_cache)} of {len(unique_printings_to_find)} required printings in local cache.")

        # 3. Identify which printings are missing and fetch only those from Scryfall.
        missing_printings_keys = unique_printings_to_find - set(printings_cache.keys())

        if missing_printings_keys:
            print(f"Fetching {len(missing_printings_keys)} missing printings from Scryfall...")
            for set_code, collector_number in missing_printings_keys:
                try:
                    printing = self.scryfall_client.get_printing_by_set_and_number(
                        set_code=set_code,
                        collector_number=collector_number
                    )
                    # Add newly fetched printing to our cache for the next step
                    printings_cache[(set_code, collector_number)] = printing
                except CardNotFoundError as e:
                    # This specific printing could not be found by Scryfall.
                    # We'll mark all lines that needed it as failed in the next step.
                    print(
                        f"Scryfall API Error: Could not find printing for {set_code.upper()} #{collector_number}: {e.message}")
                    pass  # The printing will simply be absent from the cache

        # 4. Re-iterate through the successfully parsed lines, validate, and create instances.
        for line, parsed in parsed_data_map.items():
            if line in failed_lines:  # Skip lines that already failed parsing
                continue

            lookup_key = (parsed['set_code'], parsed['collector_number'])
            printing = printings_cache.get(lookup_key)

            if not printing:
                print(
                    f"Skipping line due to error: '{line}' -> Card data could not be found for {lookup_key[0].upper()} #{lookup_key[1]}")
                failed_lines.append(line)
                continue

            # Robustness Check: Ensure the printing is linked to an oracle card.
            if not printing.oracle_card:
                print(
                    f"Skipping line due to data integrity error: '{line}' -> Printing {lookup_key[0].upper()} #{lookup_key[1]} exists but is not linked to a parent card.")
                failed_lines.append(line)
                continue

            # Perform the name validation.
            user_provided_name = parsed['name']
            scryfall_card_name = printing.oracle_card.name.lower()
            if user_provided_name.lower() not in scryfall_card_name:
                print(
                    f"Skipping line due to name mismatch: '{line}' -> User name '{user_provided_name}' does not match found card '{printing.oracle_card.name}'")
                failed_lines.append(line)
                continue

            # If all checks pass, create the instances.
            for _ in range(parsed['quantity']):
                instance = CardInstance(
                    printing_id=printing.id,
                    is_foil=parsed['is_foil']
                )
                self.session.add(instance)
                successful_instances.append(instance)

            print(f"Prepared {parsed['quantity']}x '{printing.oracle_card.name}' for addition.")

        return {"successes": successful_instances, "failures": sorted(list(set(failed_lines)))}

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

    def get_all_card_instances(self) -> List[CardInstance]:
        """Retrieves all card instances, correctly joined for sorting."""
        return (
            self.session.query(CardInstance)
            .join(CardInstance.printing)  # Explicit join from CardInstance to CardPrinting
            .join(CardPrinting.oracle_card)  # <-- ADD THIS JOIN
            .order_by(
                CardInstance.date_added.desc(),
                OracleCard.name,  # <-- FIX THIS REFERENCE
                CardPrinting.set_code,
                CardPrinting.collector_number
            )
            .all()
        )

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

        self.session.refresh(instance)  # Refresh the object with the latest data from the DB
        print(f"Successfully updated card instance {instance_id}.")
        return instance