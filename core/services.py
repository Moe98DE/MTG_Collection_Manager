from dataclasses import field, dataclass
from typing import List, Dict, Optional

import pyperclip
from sqlalchemy import func

from .exceptions import InvalidInputFormatError, CardNotFoundError, CoreLogicError, DeckAssemblyError
from .models import SessionLocal
from .models import CardPrinting, CardInstance, Deck  # Add missing imports
from .repo.enums import DeckStatus, BlueprintCardStatus
from core.api.scryfall_client import ScryfallClient
from core.repo.collection_repository import CollectionRepository
from core.repo.deck_repository import DeckRepository
from .repo.dtos import BlueprintAnalysisItem, AssemblyChoiceDTO, AssemblyOptionDTO, AssembledDeckCardDTO, \
    DeckSummaryDTO, CardInstanceDetailDTO, CollectionSummaryItem


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
        try:
            instances = self.collection_repo.add_card_from_string(card_string)
            if instances:
                self.db_session.commit()  # COMMIT ON SUCCESS
                return True
            return False  # This case might not be reachable if repo raises exception, but it's safe
        except (InvalidInputFormatError, CardNotFoundError) as e:
            print(f"SERVICE LAYER ERROR: {e.message}")
            self.db_session.rollback()
            return False
        except Exception as e:
            print(f"An unexpected error occurred in add_card_to_collection: {e}")
            self.db_session.rollback()
            return False

    def delete_card_instance(self, instance_id: int) -> bool:
        """Service layer wrapper for deleting a card instance."""
        try:
            deleted = self.collection_repo.delete_card_instance(instance_id)
            if deleted:
                self.db_session.commit()  # COMMIT ON SUCCESS
            return deleted
        except CoreLogicError as e:
            print(f"SERVICE LAYER ERROR: {e.message}")
            self.db_session.rollback()
            return False
        except Exception as e:
            print(f"An unexpected error occurred during card deletion: {e}")
            self.db_session.rollback()
            return False

    def update_card_instance(self, instance_id: int, update_data: dict) -> CardInstanceDetailDTO | None:
        """
        Service layer wrapper for updating a card instance.
        Returns the updated CardInstance on success, None on failure.
        """
        try:
            if not isinstance(update_data, dict) or not update_data:
                raise ValueError("update_data must be a non-empty dictionary.")

            instance = self.collection_repo.update_card_instance(instance_id, update_data)
            self.db_session.commit()

            # --- DTO Translation Logic ---
            status = "✅ Available"
            if instance.deck:
                status = f"⚠️ In '{instance.deck.name}'"

            return CardInstanceDetailDTO(
                instance_id=instance.id,
                oracle_id=instance.printing.oracle_card.id,
                card_name=instance.printing.oracle_card.name,
                set_code=instance.printing.set_code.upper(),
                collector_number=instance.printing.collector_number,
                is_foil=instance.is_foil,
                condition=instance.condition,
                purchase_price=instance.purchase_price,
                date_added=instance.date_added.isoformat(),
                status=status
            )
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
        Translates the repository's output into a list of DTOs.
        """
        # The repository still returns tuples: (OracleCard, total, available, image_uri)
        summary_tuples = self.collection_repo.view_collection_summary(filters=filters)

        results = []
        for repo_tuple in summary_tuples:
            # --- The translation logic now lives here, in the service layer ---
            oracle_card, total, available, image_uri = repo_tuple

            keywords_list = [k.strip() for k in oracle_card.keywords.split(',') if k.strip()]

            item = CollectionSummaryItem(
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
            results.append(item)
            # --- End of translation logic ---

        return results

    def close_session(self):
        """Closes the database session. Should be called on application exit."""
        self.db_session.close()

    def get_instances_for_oracle_card(self, name: str) -> List[CardInstanceDetailDTO]:
        """
        Gets detailed information for every physical instance of a card,
        returning a list of DTOs.
        """
        instances_data = []
        results = self.collection_repo.get_instances_by_oracle_name(name)

        for instance, printing, oracle, deck in results:
            status = "✅ Available"
            if deck:
                status = f"⚠️ In '{deck.name}'"

            instances_data.append(CardInstanceDetailDTO(
                instance_id=instance.id,
                oracle_id=oracle.id,
                card_name=oracle.name,
                set_code=printing.set_code.upper(),
                collector_number=printing.collector_number,
                is_foil=instance.is_foil,
                condition=instance.condition,
                purchase_price=instance.purchase_price,
                date_added=instance.date_added.isoformat(),
                status=status
            ))

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

    def get_all_decks(self) -> List[DeckSummaryDTO]:
        """Returns a UI-friendly list of all decks as DTOs."""
        decks = self.deck_repo.get_all_decks()
        return [
            DeckSummaryDTO(id=deck.id, name=deck.name, status=deck.status)
            for deck in decks
        ]
        
    def create_deck(self, name: str) -> bool:
        """Creates a new deck."""
        if not name or not name.strip():
            print("SERVICE LAYER ERROR: Deck name cannot be empty.")
            return None
        try:
            new_deck = self.deck_repo.create_deck(name.strip())
            self.db_session.commit()  # COMMIT ON SUCCESS
            return new_deck
        except Exception as e:
            print(f"Error creating deck: {e}")
            self.db_session.rollback()
            return None

    def delete_deck(self, deck_id: int) -> bool:
        """Deletes a deck by its ID."""
        try:
            deleted = self.deck_repo.delete_deck(deck_id)
            if deleted:
                self.db_session.commit()  # COMMIT ON SUCCESS
            return deleted
        except Exception as e:
            print(f"Error deleting deck: {e}")
            self.db_session.rollback()
            return False
        
    def get_deck_blueprint_analysis(self, deck_id: int) -> List[BlueprintAnalysisItem]:
        """
        Analyzes a blueprint deck against the user's collection by delegating
        to the deck repository.

        Returns a list of structured BlueprintAnalysisItem objects, ready for the UI.
        """
        try:
            return self.deck_repo.analyze_blueprint_against_collection(deck_id)
        except ValueError as e:
            # Handle the case where the repo raises an error for an invalid deck
            print(f"SERVICE LAYER ERROR: {e}")
            return []
        except Exception as e:
            # Catch any other unexpected errors
            print(f"An unexpected error occurred during deck analysis: {e}")
            return []
    
    def remove_card_from_blueprint(self, deck_id: int, oracle_card_id: int) -> bool:
        """Removes a card entry completely from a blueprint."""
        try:
            # Note: the repo method returns nothing, it just modifies the session
            self.deck_repo.update_blueprint_entry_quantity(deck_id, oracle_card_id, 0)
            self.db_session.commit()  # COMMIT ON SUCCESS
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
            # We only need to find options for cards we actually own and can use.
            if card.status not in [BlueprintCardStatus.OWNED_AVAILABLE, BlueprintCardStatus.OWNED_ALLOCATED]:
                continue

            available_instances = (
                self.db_session.query(CardInstance)
                .join(CardPrinting)
                .filter(CardPrinting.oracle_card_id == card.oracle_card_id)
                .filter(CardInstance.deck_id == None)  # Must be available
                .all()
            )

            instance_choices = []
            for inst in available_instances:
                foil_str = ' (Foil)' if inst.is_foil else ''
                display = (f"{inst.printing.set_code.upper()} #{inst.printing.collector_number}{foil_str}"
                           f" - {inst.condition}")
                instance_choices.append(AssemblyChoiceDTO(
                    instance_id=inst.id,
                    display_text=display
                ))

            options.append(AssemblyOptionDTO(
                oracle_card_id=card.oracle_card_id,
                card_name=card.card_name,
                quantity_needed=card.quantity_needed,
                available_instances=instance_choices
            ))

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
            success = self.deck_repo.disassemble_deck(deck_id)
            if success:
                self.db_session.commit()  # COMMIT ON SUCCESS
            return success
        except Exception as e:
            print(f"Error disassembling deck: {e}")
            self.db_session.rollback()
            return False

    def get_assembled_deck_contents(self, deck_id: int) -> List[AssembledDeckCardDTO]:
        """Returns a UI-friendly list of cards in an assembled deck."""
        results = self.collection_repo.get_assembled_deck_contents(deck_id)
        return [AssembledDeckCardDTO(name=name, quantity=qty) for name, qty in results]

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