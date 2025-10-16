from typing import List, Dict

import pyperclip
from sqlalchemy import func
from .models import SessionLocal
from .models import CardPrinting, CardInstance, Deck, DeckStatus # Add missing imports
from .scryfall_client import ScryfallClient
from .repository import CollectionRepository, DeckRepository

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
            return len(instances) > 0
        except Exception as e:
            print(f"An error occurred in add_card_to_collection: {e}")
            self.db_session.rollback() # Rollback on error to keep DB clean
            return False

    def delete_card_instance(self, instance_id: int) -> bool:
        """Service layer wrapper for deleting a card instance."""
        try:
            return self.collection_repo.delete_card_instance(instance_id)
        except Exception as e:
            print(f"An error occurred during card deletion: {e}")
            self.db_session.rollback()
            return False

    def get_collection_summary(self, filters: dict = None) -> List[Dict[str, any]]:
        """
        Retrieves the collection summary, applying any specified filters.
        """
        summary_tuples = self.collection_repo.view_collection_summary(filters=filters)
        
        summary_list = [
            {"name": name, "count": total_owned} 
            for name, total_owned in summary_tuples
        ]
        return summary_list

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
        Adds multiple cards to the collection from a multi-line string.
        Each line is processed individually.
        Returns a dictionary with success and failure counts.
        """
        success_count = 0
        failure_count = 0
        
        # .splitlines() is a robust way to split a string into a list of lines
        for line in card_list_string.splitlines():
            line = line.strip()
            if not line:  # Skip empty lines
                continue
            
            # We can reuse our existing single-add logic!
            if self.add_card_to_collection(line):
                success_count += 1
            else:
                failure_count += 1
        
        return {"success": success_count, "failure": failure_count}
    
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

    def assemble_deck(self, deck_id: int, choices: dict) -> bool:
        """Service layer wrapper for assembling a deck."""
        try:
            return self.deck_repo.assemble_deck(deck_id, choices)
        except Exception as e:
            print(f"Error assembling deck: {e}")
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
        """Adds multiple cards to a blueprint from a multi-line string."""
        deck = self.deck_repo.session.get(Deck, deck_id)
        if not deck:
            return {"success": 0, "failure": -1} # Indicate deck not found

        success_count = 0
        failure_count = 0
        for line in card_list_string.splitlines():
            line = line.strip()
            if not line: continue
            
            # Reuse the existing single-add logic from the repository
            if self.deck_repo.add_card_to_blueprint(deck, line):
                success_count += 1
            else:
                failure_count += 1
        
        return {"success": success_count, "failure": failure_count}    
    
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