from typing import List, Dict
from .models import SessionLocal
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