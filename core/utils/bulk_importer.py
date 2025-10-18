import requests
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any

from sqlalchemy.orm import sessionmaker
from tqdm import tqdm  # A library for progress bars. Install with: pip install tqdm

# We need to configure the path to import from the parent `core` directory
import sys

# This adds the project root to the Python path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.models import engine, OracleCard, CardPrinting

# --- Configuration ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Scryfall API endpoint for bulk data information
BULK_DATA_API_URL = "https://api.scryfall.com/bulk-data"

# Directory to store the downloaded JSON files temporarily
DOWNLOAD_DIR = Path(__file__).parent / "temp_bulk_data"

# Create a sessionmaker for database operations
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _get_bulk_data_url(data_type: str) -> str:
    """
    Fetches the Scryfall bulk data manifest and returns the download URL
    for the specified data type (e.g., 'oracle_cards', 'default_cards').
    """
    logging.info(f"Fetching bulk data manifest to find '{data_type}'...")
    try:
        response = requests.get(BULK_DATA_API_URL)
        response.raise_for_status()
        all_bulk_data = response.json()['data']

        for item in all_bulk_data:
            if item.get("type") == data_type:
                url = item["download_uri"]
                logging.info(f"Found download URL for '{data_type}'.")
                return url

        raise RuntimeError(f"Could not find bulk data of type '{data_type}' in the manifest.")
    except requests.RequestException as e:
        logging.error(f"Failed to fetch bulk data manifest: {e}")
        raise


def _download_file(url: str, dest_path: Path) -> None:
    """
    Downloads a large file from a URL to a destination path with a progress bar.
    """
    logging.info(f"Downloading data from {url} to {dest_path}...")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            total_size_in_bytes = int(r.headers.get('content-length', 0))
            block_size = 8192  # 8KB

            progress_bar = tqdm(total=total_size_in_bytes, unit='iB', unit_scale=True, desc=dest_path.name)
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=block_size):
                    progress_bar.update(len(chunk))
                    f.write(chunk)
            progress_bar.close()

            if total_size_in_bytes != 0 and progress_bar.n != total_size_in_bytes:
                raise RuntimeError("Download failed: Incomplete file.")
        logging.info(f"Successfully downloaded {dest_path.name}.")
    except requests.RequestException as e:
        logging.error(f"Failed to download file: {e}")
        raise

def _prepare_data_for_bulk_insert(card_data: List[Dict[str, Any]], model_type: str) -> List[Dict[str, Any]]:
    """
    Transforms the raw Scryfall JSON data for a list of cards into a list of
    dictionaries that match our database model schemas.

    UPDATED: This function now de-duplicates data to prevent UNIQUE constraint errors.
    """
    mappings = []

    if model_type == 'oracle':
        # Use a set for highly efficient tracking of names we've already processed
        seen_names = set()
        for card in tqdm(card_data, desc="Deduplicating Oracle Cards"):
            name = card.get('name')
            # Skip non-game cards, cards without names, or names we've already added
            if 'oracle_id' not in card or not name or name in seen_names:
                continue

            mappings.append({
                'id': card['oracle_id'],
                'name': name,
                'mana_cost': card.get('mana_cost'),
                'cmc': card.get('cmc', 0.0),
                'color_identity': "".join(card.get('color_identity', [])),
                'type_line': card.get('type_line'),
                'oracle_text': card.get('oracle_text'),
                'power': card.get('power'),
                'toughness': card.get('toughness'),
                'loyalty': card.get('loyalty'),
                'keywords': ", ".join(card.get('keywords', []))
            })
            # Add the name to our set so we can skip future duplicates
            seen_names.add(name)

    elif model_type == 'printing':
        # No de-duplication needed for printings as their Scryfall ID is unique
        for card in card_data:
            # Skip digital-only cards or those without an oracle_id (e.g. reversible cards)
            if not card.get('digital', False) and 'oracle_id' in card:
                mappings.append({
                    'id': card['id'],
                    'oracle_card_id': card['oracle_id'],
                    'set_code': card['set'],
                    'collector_number': card['collector_number'],
                    'rarity': card['rarity'],
                    'artist': card.get('artist'),
                    'image_uri_normal': card.get('image_uris', {}).get('normal'),
                    'image_uri_large': card.get('image_uris', {}).get('large'),
                    'price_usd': card.get('prices', {}).get('usd'),
                    'price_usd_foil': card.get('prices', {}).get('usd_foil')
                })
    return mappings


def run_bulk_import():
    """
    Orchestrates the entire bulk import process:
    1. Clears existing card data.
    2. Downloads Oracle and Default card files from Scryfall.
    3. Processes and inserts the data into the database.
    4. Cleans up downloaded files.
    """
    db_session = SessionLocal()
    start_time = time.time()

    try:
        # --- 1. Clear existing static card data ---
        # The order is important due to foreign key constraints.
        # CardPrinting must be deleted before OracleCard.
        logging.info("Clearing existing static card data (OracleCards and CardPrintings)...")
        db_session.query(CardPrinting).delete(synchronize_session=False)
        db_session.query(OracleCard).delete(synchronize_session=False)
        db_session.commit()
        logging.info("Existing data cleared.")

        # --- 2. Download files ---
        oracle_url = _get_bulk_data_url("oracle_cards")
        default_cards_url = _get_bulk_data_url("default_cards")

        oracle_file_path = DOWNLOAD_DIR / "oracle_cards.json"
        default_cards_file_path = DOWNLOAD_DIR / "default_cards.json"

        _download_file(oracle_url, oracle_file_path)
        _download_file(default_cards_url, default_cards_file_path)

        # --- 3. Process and Insert Oracle Cards ---
        logging.info("Loading Oracle Cards JSON file into memory...")
        with open(oracle_file_path, 'r', encoding='utf-8') as f:
            oracle_json_data = json.load(f)

        logging.info("Preparing Oracle Card data for insertion...")
        oracle_mappings = _prepare_data_for_bulk_insert(oracle_json_data, 'oracle')

        logging.info(f"Starting bulk insert of {len(oracle_mappings)} Oracle Cards...")
        db_session.bulk_insert_mappings(OracleCard, oracle_mappings)
        db_session.commit()
        logging.info("Oracle Cards successfully inserted.")

        # --- 4. Process and Insert Default Cards (Printings) ---
        logging.info("Loading Default Cards JSON file into memory...")
        # NOTE: This file is large (~500MB). For memory-constrained systems,
        # a streaming JSON parser like `ijson` would be a better choice.
        with open(default_cards_file_path, 'r', encoding='utf-8') as f:
            default_cards_json_data = json.load(f)

        logging.info("Preparing Card Printing data for insertion...")
        printing_mappings = _prepare_data_for_bulk_insert(default_cards_json_data, 'printing')

        logging.info(f"Starting bulk insert of {len(printing_mappings)} Card Printings...")
        db_session.bulk_insert_mappings(CardPrinting, printing_mappings)
        db_session.commit()
        logging.info("Card Printings successfully inserted.")

    except Exception as e:
        logging.error(f"A critical error occurred during the bulk import process: {e}")
        logging.info("Rolling back any partial changes to the database.")
        db_session.rollback()
    finally:
        # --- 5. Clean up ---
        logging.info("Cleaning up downloaded files...")
        if oracle_file_path.exists():
            oracle_file_path.unlink()
        if default_cards_file_path.exists():
            default_cards_file_path.unlink()
        if DOWNLOAD_DIR.exists():
            DOWNLOAD_DIR.rmdir()

        db_session.close()
        end_time = time.time()
        logging.info(f"Bulk import process finished in {end_time - start_time:.2f} seconds.")


if __name__ == '__main__':
    print("====================================================================")
    print(" Magic: The Gathering Collection Manager - Bulk Data Importer")
    print("====================================================================")
    print("\nThis script will download the latest card data from Scryfall and")
    print("populate your local database. This may take several minutes.")
    print("\nWARNING: This is a destructive operation. It will completely")
    print("         erase and replace all existing canonical card data")
    print("         (Oracle cards and Printings). Your personal collection")
    print("         and decks will NOT be affected.")
    print("--------------------------------------------------------------------")

    # Prompt the user to confirm
    answer = input("Do you want to proceed? (yes/no): ").lower()

    if answer in ['yes', 'y']:
        run_bulk_import()
    else:
        print("Operation cancelled by user.")