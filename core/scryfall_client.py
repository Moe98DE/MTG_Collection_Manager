import requests
import time
from sqlalchemy.orm import Session
from .models import OracleCard, CardPrinting

class ScryfallClient:
    """
    A client to interact with the Scryfall API, with a caching layer
    that checks our local database before making a network request.
    """
    BASE_URL = "https://api.scryfall.com"

    def __init__(self, db_session: Session):
        self.session = db_session
        print("Scryfall Client initialized.")

    def get_oracle_card_by_name(self, name: str) -> OracleCard | None:
        """
        Finds an abstract OracleCard by its name.
        Uses a 'fuzzy' search for convenience.
        """
        # First, check our local DB for an exact match
        oracle_card = self.session.query(OracleCard).filter(OracleCard.name.ilike(name)).first()
        if oracle_card:
            print(f"Found OracleCard '{name}' in local DB.")
            return oracle_card

        # If not found, query Scryfall API
        print(f"Querying Scryfall for card named '{name}'...")
        try:
            time.sleep(0.1)
            url = f"{self.BASE_URL}/cards/named"
            params = {"fuzzy": name} # Fuzzy search is more user-friendly
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            card_data = response.json()
            
            # This is tricky. The card's printing might not be in our DB yet,
            # but the oracle card might be. We use _create_from_scryfall_data
            # which intelligently handles both cases.
            # We just need to get the printing from the returned oracle card.
            printing = self.session.query(CardPrinting).filter_by(scryfall_id=card_data['id']).first()
            if printing:
                return printing.oracle_card

            # If we've never seen this printing before, create it.
            # This will also create the oracle card if needed.
            new_printing = self._create_from_scryfall_data(card_data)
            return new_printing.oracle_card

        except requests.exceptions.RequestException as e:
            print(f"Error fetching card data for '{name}': {e}")
            return None

    def _create_from_scryfall_data(self, card_data: dict) -> CardPrinting:
        """
        A helper function to process Scryfall JSON data, find/create the
        OracleCard, and create the CardPrinting.
        This is the core logic for adding new card data to our DB.
        """
        # Step 1: Find or create the OracleCard (the abstract card concept)
        oracle_id = card_data['oracle_id']
        oracle_card = self.session.query(OracleCard).filter_by(oracle_id=oracle_id).first()

        if not oracle_card:
            print(f"OracleCard not found for '{card_data['name']}'. Creating new entry.")
            oracle_card = OracleCard(
                oracle_id=oracle_id,
                name=card_data['name'],
                # Scryfall returns a list like ['W', 'B']. Join it into 'WB'.
                color_identity=''.join(card_data['color_identity'])
            )
            self.session.add(oracle_card)
            # We need to flush to get the oracle_card.id for the printing foreign key
            self.session.flush()

        # Step 2: Create the specific CardPrinting
        # Use .get() for image_uri as some cards (like Art Series) don't have it
        image_uri = card_data.get('image_uris', {}).get('normal')
        
        new_printing = CardPrinting(
            scryfall_id=card_data['id'],
            set_code=card_data['set'],
            collector_number=card_data['collector_number'],
            image_uri=image_uri,
            oracle_card_id=oracle_card.id # Link to the OracleCard
        )
        self.session.add(new_printing)
        self.session.commit()
        print(f"Successfully added printing: {card_data['name']} ({card_data['set'].upper()})")
        
        return new_printing

    def get_printing_by_set_and_number(self, set_code: str, collector_number: str) -> CardPrinting | None:
        """
        The primary method for finding a card. It's precise and efficient.
        It first checks our local database. If not found, it queries Scryfall.
        """
        # First, check our local database for this specific printing
        printing = self.session.query(CardPrinting).filter_by(
            set_code=set_code.lower(), 
            collector_number=collector_number
        ).first()
        
        if printing:
            print(f"Found '{printing.oracle_card.name} ({printing.set_code.upper()})' in local DB.")
            return printing

        # If not in our DB, query the Scryfall API
        print(f"Querying Scryfall for {set_code.upper()} #{collector_number}...")
        try:
            # Scryfall API is polite; they ask for a small delay between requests.
            time.sleep(0.1) # 100ms delay
            
            url = f"{self.BASE_URL}/cards/{set_code.lower()}/{collector_number}"
            response = requests.get(url)
            response.raise_for_status()  # This will raise an exception for 4xx/5xx errors

            card_data = response.json()
            return self._create_from_scryfall_data(card_data)

        except requests.exceptions.RequestException as e:
            print(f"Error fetching card data from Scryfall: {e}")
            return None