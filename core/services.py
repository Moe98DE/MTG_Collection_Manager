from dataclasses import field, dataclass
from typing import List, Dict, Optional

import pyperclip
from sqlalchemy import func

from .exceptions import InvalidInputFormatError, CardNotFoundError, CoreLogicError, DeckAssemblyError
from .models import SessionLocal
from .models import CardPrinting, CardInstance, Deck, DeckStatus # Add missing imports
from core.api.scryfall_client import ScryfallClient
from core.repo.collection_repository import CollectionRepository
from core.repo.deck_repository import DeckRepository


# NEW: A fully fleshed-out Data Transfer Object for collection summary views
@dataclass
class CollectionSummaryItem:
    """
    Represents a single, grouped entry in the user's collection view.
    This is a Data Transfer Object (DTO) designed to provide all necessary
    information for a rich UI display in a single object.
    """
    # Core identifying information
    oracle_id: str
    name: str

    # Key gameplay attributes for sorting and display
    type_line: str
    mana_cost: Optional[str]
    cmc: float
    color_identity: str

    # User's collection statistics
    total_owned: int
    available_count: int

    # Display and aesthetic information
    # We'll pick the image from the first printing we find for this card.
    # It provides a good visual representation without complex logic.
    representative_image_uri: Optional[str]

    # Making keywords a list is much nicer for a frontend to consume than a raw string.
    keywords: List[str] = field(default_factory=list)

    @staticmethod
    def from_repository_tuple(repo_tuple) -> 'CollectionSummaryItem':
        """
        A factory method to create an instance from the data structure
        returned by the CollectionRepository.
        """
        oracle_card, total, available, image_uri = repo_tuple

        # Split the comma-separated string from the DB back into a list
        keywords_list = [k.strip() for k in oracle_card.keywords.split(',') if k.strip()]

        return CollectionSummaryItem(
            oracle_id=oracle_card.id,
            name=oracle_card.name,
            type_line=oracle_card.type_line,
            mana_cost=oracle_card.mana_cost,
            cmc=oracle_card.cmc,
            color_identity=oracle_card.color_identity,
            total_owned=total,
            available_count=available,
            representative_image_uri=image_uri,
            keywords=keywords_list
        )

class MagicCardService:
    def __init__(self):
        """
        Initializes the service and all its underlying components.
        This class is the single entry point for the UI.
        """
        self.db_session = SessionLocal()
        self.scryfall_client = ScryfallClient(db_session=self.db_session)
        self.collection_repo = CollectionRepository(db_session=self.db_session, scryfall_client=self.scryfall_client)
        self.deck_repo = DeckRepository(db_session=self.db_session, scryfall_client=self.scryfall_client)
        print("MagicCardService initialized.")

    def add_card_to_collection(self, card_string: str) -> bool:
        """
        Adds one or more card instances to the collection from a string.
        Returns True on success, False on failure.
        """
        # UPDATED: Catch specific exceptions and provide context
        try:
            instances = self.collection_repo.add_card_from_string(card_string)
            return len(instances) > 0
        except InvalidInputFormatError as e:
            print(f"SERVICE LAYER ERROR: {e.message}")
            self.db_session.rollback()
            return False
        except CardNotFoundError as e:
            print(f"SERVICE LAYER ERROR: {e.message}")
            self.db_session.rollback()
            return False
        except Exception as e:
            # A general catch-all for unexpected errors
            print(f"An unexpected error occurred in add_card_to_collection: {e}")
            self.db_session.rollback()
            return False

    def delete_card_instance(self, instance_id: int) -> bool:
        """Service layer wrapper for deleting a card instance."""
        # UPDATED: Catch our new exceptions
        try:
            return self.collection_repo.delete_card_instance(instance_id)
        except CoreLogicError as e:  # Catches our custom base exception and its children
            print(f"SERVICE LAYER ERROR: {e.message}")
            self.db_session.rollback()
            return False
        except Exception as e:
            print(f"An unexpected error occurred during card deletion: {e}")
            self.db_session.rollback()
            return False

    def update_card_instance(self, instance_id: int, update_data: dict) -> CardInstance | None:
        """
        Service layer wrapper for updating a card instance.
        Returns the updated CardInstance on success, None on failure.
        """
        try:
            # Basic validation: ensure update_data is a non-empty dictionary
            if not isinstance(update_data, dict) or not update_data:
                print("SERVICE LAYER ERROR: update_data must be a non-empty dictionary.")
                return None

            return self.collection_repo.update_card_instance(instance_id, update_data)
        except (CoreLogicError, ValueError) as e:
            print(f"SERVICE LAYER ERROR: {e}")
            self.db_session.rollback()
            return None
        except Exception as e:
            print(f"An unexpected error occurred during card update: {e}")
            self.db_session.rollback()
            return None

    def get_collection_summary(self, filters: dict = None) -> List[CollectionSummaryItem]:
        """
        Retrieves the collection summary, applying any specified filters.
        Returns a list of structured CollectionSummaryItem objects.
        """
        # The repository now returns tuples in the format our DTO expects.
        summary_tuples = self.collection_repo.view_collection_summary(filters=filters)

        # UPDATED: Use the clean factory method for conversion.
        return [CollectionSummaryItem.from_repository_tuple(t) for t in summary_tuples]

    def close_session(self):
        """Closes the database session. Should be called on application exit."""
        self.db_session.close()

    def get_instances_for_oracle_card(self, name: str) -> List[Dict[str, any]]:
        """
        Gets detailed information for every physical instance of a card.
        This is for the 'Drill-Down' view.
        """
        instances_data = []
        # Get raw data from the repository
        results = self.collection_repo.get_instances_by_oracle_name(name)

        for instance, printing, oracle, deck in results:
            status = "✅ Available"
            if deck:
                status = f"⚠️ In '{deck.name}'"
            
            instances_data.append({
                "instance_id": instance.id,
                "set_code": printing.set_code.upper(),
                "collector_number": printing.collector_number,
                "is_foil": instance.is_foil,
                "status": status,
            })
        
        return instances_data
    
    def add_cards_from_list(self, card_list_string: str) -> dict:
        """
                Adds multiple cards from a multi-line string in a single, atomic transaction.
                If any card causes a database-level error, the entire batch is rolled back.
                Parsing and card-not-found errors for individual lines are skipped and reported.

                Returns a dictionary with success and failure counts.
                """
        lines = card_list_string.splitlines()

        try:
            # The repository method prepares all objects in the session
            result = self.collection_repo.add_cards_from_list_transactional(lines)

            # If there are any successful objects to add, commit them all at once.
            if result["successes"]:
                self.db_session.commit()
                print(f"Successfully committed {len(result['successes'])} new card instances to the database.")

            return {
                "success": len(result["successes"]),
                "failure": len(result["failures"])
            }

        except Exception as e:
            # This will catch unexpected errors, like a database connection failure.
            # It will NOT catch the CardNotFoundError, which is handled inside the repo method.
            print(f"A critical error occurred during bulk add. Rolling back transaction. Error: {e}")
            self.db_session.rollback()
            return {"success": 0, "failure": len(lines)}
    
    def get_all_decks(self) -> List[Dict[str, any]]:
        """Returns a UI-friendly list of all decks."""
        decks = self.deck_repo.get_all_decks()
        return [
            {"id": deck.id, "name": deck.name, "status": deck.status.value}
            for deck in decks
        ]
        
    def create_deck(self, name: str) -> bool:
        """Creates a new deck."""
        if not name or len(name.strip()) == 0:
            return False
        try:
            self.deck_repo.create_deck(name)
            return True
        except Exception as e:
            print(f"Error creating deck: {e}")
            self.db_session.rollback()
            return False

    def delete_deck(self, deck_id: int) -> bool:
        """Deletes a deck by its ID."""
        try:
            return self.deck_repo.delete_deck(deck_id)
        except Exception as e:
            print(f"Error deleting deck: {e}")
            self.db_session.rollback()
            return False
        
    def get_deck_blueprint_analysis(self, deck_id: int) -> list:
        """
        Analyzes a blueprint deck against the user's collection.
        Returns a UI-friendly list of cards with their status.
        """
        deck = self.deck_repo.session.get(Deck, deck_id)
        if not deck or deck.status != DeckStatus.BLUEPRINT:
            return []

        # Get available and total owned cards (efficiently)
        available_cards = self.db_session.query(CardPrinting.oracle_card_id, func.count(CardInstance.id)).join(CardInstance).filter(CardInstance.deck_id == None).group_by(CardPrinting.oracle_card_id).all()
        available_map = dict(available_cards)
        total_owned_cards = self.db_session.query(CardPrinting.oracle_card_id, func.count(CardInstance.id)).join(CardInstance).group_by(CardPrinting.oracle_card_id).all()
        total_owned_map = dict(total_owned_cards)

        analysis = []
        for entry in deck.blueprint_entries:
            needed = entry.quantity
            available = available_map.get(entry.oracle_card_id, 0)
            total_owned = total_owned_map.get(entry.oracle_card_id, 0)

            status = "MISSING"
            if available >= needed:
                status = "AVAILABLE"
            elif total_owned >= needed:
                status = "ALLOCATED"
            elif total_owned > 0:
                status = "PARTIAL"

            analysis.append({
                "oracle_card_id": entry.oracle_card_id,
                "card_name": entry.oracle_card.name,
                "quantity": needed,
                "status": status,
                "owned": total_owned,
            })
        
        # Sort by card name
        analysis.sort(key=lambda x: x['card_name'])
        return analysis
    
    def remove_card_from_blueprint(self, deck_id: int, oracle_card_id: int) -> bool:
        """Removes a card entry completely from a blueprint."""
        try:
            self.deck_repo.update_blueprint_entry_quantity(deck_id, oracle_card_id, 0)
            return True
        except Exception as e:
            print(f"Error removing card from blueprint: {e}")
            self.db_session.rollback()
            return False

    def export_buy_list(self, deck_id: int):
        """Generates a buy list for a deck and copies it to the clipboard."""
        analysis = self.get_deck_blueprint_analysis(deck_id)
        buy_list = []
        for card in analysis:
            if card['status'] in ['MISSING', 'PARTIAL']:
                to_buy = card['quantity'] - card['owned']
                buy_list.append(f"{to_buy} {card['card_name']}")
        
        if buy_list:
            buy_list_str = "\n".join(buy_list)
            pyperclip.copy(buy_list_str)
            print("Buy list copied to clipboard.")
        else:
            print("No cards to buy for this deck.")    

    def get_assembly_options(self, deck_id: int) -> list:
        """
        For a given blueprint, finds all required cards and the available
        physical instances for each. This powers the Assembly Wizard.
        """
        blueprint_analysis = self.get_deck_blueprint_analysis(deck_id)
        options = []

        for card in blueprint_analysis:
            # Find all available physical instances for this oracle card
            available_instances = (
                self.db_session.query(CardInstance)
                .join(CardPrinting)
                .filter(CardPrinting.oracle_card_id == card['oracle_card_id'])
                .filter(CardInstance.deck_id == None) # Must be available
                .all()
            )
            
            instance_choices = []
            for inst in available_instances:
                instance_choices.append({
                    "instance_id": inst.id,
                    "text": f"{inst.printing.set_code.upper()} #{inst.printing.collector_number}{' (Foil)' if inst.is_foil else ''}"
                })

            options.append({
                "oracle_card_id": card['oracle_card_id'],
                "card_name": card['card_name'],
                "quantity_needed": card['quantity'],
                "available_instances": instance_choices
            })
        return options

    # UPDATED: The service method now orchestrates validation and assembly.
    # The 'choices' dict from the UI needs to be flattened into a list of instance IDs.
    def assemble_deck(self, deck_id: int, choices_map: Dict[str, List[int]]) -> bool:
        """
        Service layer wrapper for validating and assembling a deck.

        Args:
            deck_id: The ID of the blueprint deck to assemble.
            choices_map: A dictionary from the UI, e.g.,
                         {'oracle_id_1': [instance_id_A, instance_id_B], 'oracle_id_2': [instance_id_C]}

        Returns:
            True on success, False on failure.
        """
        try:
            # 1. Flatten the list of chosen instance IDs from the UI's data structure
            if not isinstance(choices_map, dict):
                print("SERVICE LAYER ERROR: Choices must be provided in a dictionary.")
                return False

            all_chosen_instance_ids = [
                instance_id for instance_list in choices_map.values() for instance_id in instance_list
            ]

            if not all_chosen_instance_ids:
                print("SERVICE LAYER ERROR: No card instances were chosen for assembly.")
                return False

            # 2. Perform validation BEFORE attempting the database transaction
            self.deck_repo.validate_assembly_choices(deck_id, all_chosen_instance_ids)

            # 3. If validation passes, proceed with the atomic assembly operation
            self.deck_repo.assemble_deck(deck_id, all_chosen_instance_ids)

            # The service layer is responsible for the final commit
            self.db_session.commit()
            print("Assembly transaction committed successfully.")
            return True

        except DeckAssemblyError as e:
            # Catch our specific, expected errors from the validation/assembly process
            print(f"SERVICE LAYER ERROR: Could not assemble deck. Reason: {e.message}")
            self.db_session.rollback()  # Ensure rollback just in case
            return False
        except Exception as e:
            # Catch any other unexpected errors
            print(f"An unexpected error occurred assembling deck: {e}")
            self.db_session.rollback()
            return False

    def disassemble_deck(self, deck_id: int) -> bool:
        """Service layer wrapper for disassembling a deck."""
        try:
            return self.deck_repo.disassemble_deck(deck_id)
        except Exception as e:
            print(f"Error disassembling deck: {e}")
            self.db_session.rollback()
            return False        
        
    def get_assembled_deck_contents(self, deck_id: int) -> List[Dict[str, any]]:
        """Returns a UI-friendly list of cards in an assembled deck."""
        results = self.collection_repo.get_assembled_deck_contents(deck_id)
        return [{"name": name, "quantity": qty} for name, qty in results]

    def add_cards_to_blueprint_from_list(self, deck_id: int, card_list_string: str) -> dict:
        """
                Adds multiple cards to a blueprint from a multi-line string in a single transaction.
                """
        lines = card_list_string.splitlines()

        try:
            # The repository method prepares all the changes in the session
            result = self.deck_repo.add_cards_to_blueprint_transactional(deck_id, lines)

            # The service layer commits the entire transaction
            self.db_session.commit()

            success_count = len(lines) - len(result["failures"])
            print(f"Successfully committed {success_count} blueprint changes.")

            return {
                "success": success_count,
                "failure": len(result["failures"])
            }

        except (DeckAssemblyError, CardNotFoundError) as e:
            print(f"SERVICE LAYER ERROR: {e.message}")
            self.db_session.rollback()
            return {"success": 0, "failure": len(lines)}
        except Exception as e:
            print(f"A critical error occurred during blueprint update. Rolling back transaction. Error: {e}")
            self.db_session.rollback()
            return {"success": 0, "failure": len(lines)}
    
    def export_collection(self, filters: dict = None):
        """
        Gets the filtered collection summary, formats it as a list,
        and copies it to the clipboard.
        """
        # We can reuse our existing summary logic!
        summary_tuples = self.collection_repo.view_collection_summary(filters=filters)
        
        if not summary_tuples:
            print("No cards to export for the current filter.")
            return

        # Format as "Count Card Name"
        export_list = [f"{count} {name}" for name, count in summary_tuples]
        export_string = "\n".join(export_list)
        
        try:
            pyperclip.copy(export_string)
            print("Filtered collection list copied to clipboard.")
        except pyperclip.PyperclipException as e:
            print(f"Error: Could not copy to clipboard. Is a clipboard tool installed? Error: {e}")