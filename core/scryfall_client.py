import requests
import time
from sqlalchemy.orm import Session, joinedload

from .exceptions import CardNotFoundError
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
        # First, check our local DB for an exact match. We use ilike for case-insensitivity.
        oracle_card = self.session.query(OracleCard).filter(OracleCard.name.ilike(name)).first()
        if oracle_card:
            print(f"Found OracleCard '{name}' in local DB.")
            return oracle_card

        # If not found, query Scryfall API
        print(f"Querying Scryfall for card named '{name}'...")
        try:
            # Scryfall API is polite; they ask for a small delay between requests.
            time.sleep(0.1)  # 100ms delay

            url = f"{self.BASE_URL}/cards/named"
            params = {"fuzzy": name}
            response = requests.get(url, params=params)
            response.raise_for_status()  # Raise an exception for 4xx/5xx errors

            card_data = response.json()

            # UPDATED: Use the new centralized caching method
            # This method will find/create the OracleCard and the CardPrinting
            # and returns the fully populated CardPrinting object.
            new_printing = self._cache_card_data(card_data)
            return new_printing.oracle_card

        except requests.exceptions.RequestException as e:
            # This will catch 404 Not Found errors as well
            print(f"Error fetching card data for '{name}': {e}")
            raise CardNotFoundError(identifier=name) from e

    # UPDATED: This method is now the primary entry point for finding a specific printing
    def get_printing_by_set_and_number(self, set_code: str, collector_number: str) -> CardPrinting | None:
        """
        The primary method for finding a specific card printing.
        It first checks the local database. If not found, it queries Scryfall.
        """
        # First, check our local database for this specific printing
        # Using joinedload tells SQLAlchemy to fetch the related OracleCard in the same query,
        # which is more efficient than loading it later.
        printing = self.session.query(CardPrinting).options(joinedload(CardPrinting.oracle_card)).filter_by(
            set_code=set_code.lower(),
            collector_number=collector_number
        ).first()

        if printing:
            print(f"Found '{printing.oracle_card.name} ({printing.set_code.upper()})' in local DB.")
            return printing

        # If not in our DB, query the Scryfall API
        print(f"Querying Scryfall for {set_code.upper()} #{collector_number}...")
        try:
            time.sleep(0.1)

            url = f"{self.BASE_URL}/cards/{set_code.lower()}/{collector_number}"
            response = requests.get(url)
            response.raise_for_status()

            card_data = response.json()
            # UPDATED: Use the new centralized caching method
            return self._cache_card_data(card_data)

        except requests.exceptions.RequestException as e:
            identifier = f"{set_code.upper()} #{collector_number}"
            print(f"Scryfall API error for '{identifier}': {e}")
            raise CardNotFoundError(identifier=identifier) from e

    # NEW: This method replaces the old '_create_from_scryfall_data'
    def _cache_card_data(self, card_data: dict) -> CardPrinting:
        """
        Processes Scryfall JSON data. Finds/creates the OracleCard and the
        CardPrinting, populating all fields from the TRS. This is the core
        caching logic.
        """
        # Use a transaction block to ensure this is an atomic operation
        with self.session.begin_nested():
            # Step 1: Find or create the OracleCard
            oracle_id = card_data['oracle_id']
            oracle_card = self.session.get(OracleCard, oracle_id)

            if not oracle_card:
                print(f"OracleCard not found for '{card_data['name']}'. Creating new entry.")
                oracle_card = OracleCard(
                    id=oracle_id,
                    name=card_data['name'],
                    mana_cost=card_data.get('mana_cost', ''),
                    cmc=card_data.get('cmc', 0.0),
                    color_identity="".join(card_data.get('color_identity', [])),
                    type_line=card_data.get('type_line', ''),
                    oracle_text=card_data.get('oracle_text', ''),
                    power=card_data.get('power'),  # .get() handles missing keys gracefully
                    toughness=card_data.get('toughness'),
                    loyalty=card_data.get('loyalty'),
                    keywords=", ".join(card_data.get('keywords', []))  # Store as string
                )
                self.session.add(oracle_card)

            # Step 2: Find or create the CardPrinting
            printing_id = card_data['id']
            printing = self.session.get(CardPrinting, printing_id)

            if not printing:
                print(f"Printing not found for '{card_data['name']} ({card_data['set'].upper()})'. Creating new entry.")
                printing = CardPrinting(
                    id=printing_id,
                    oracle_card_id=oracle_id,
                    set_code=card_data['set'],
                    collector_number=card_data['collector_number'],
                    rarity=card_data['rarity'],
                    artist=card_data.get('artist'),
                    image_uri_normal=card_data.get('image_uris', {}).get('normal'),
                    image_uri_large=card_data.get('image_uris', {}).get('large'),
                    price_usd=card_data.get('prices', {}).get('usd'),
                    price_usd_foil=card_data.get('prices', {}).get('usd_foil')
                )
                self.session.add(printing)

        # The main session commit will be handled by the calling function in the repository
        # or we can commit here if this client is used independently. Let's commit for safety.
        self.session.commit()

        # After commit, the 'printing' object is fully attached to the session and its relationships are loaded
        return printing