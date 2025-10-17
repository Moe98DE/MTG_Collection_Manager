import os
from pprint import pprint
import pyperclip

from core.repo.database_setup import create_database_schema
from core.services import MagicCardService

# YOUR PROVIDED TEST DATA - which we now know is 100% valid.
COLLECTION_TO_ADD = """
2 Gallant Citizen (SPM) 129
1 Sun-Spider, Nimble Webber (SPM) 154
1 Spider-Man 2099 (SPM) 150
1 Wraith, Vicious Vigilante (SPM) 160
1 Prowler, Clawed Thief (SPM) 138
1 Fiendish Panda (FDN) 120 *F*
1 Karakyk Guardian (TDM) 198 *F*
1 Marshal of the Lost (TDM) 207 *F*
1 Kheru Goldkeeper (TDM) 199 *F*
1 Host of the Hereafter (TDM) 193 *F*
1 Jeskai Shrinekeeper (TDM) 197 *F*
"""

DECK_BLUEPRINT = """
1 Shadow of the Goblin
1 Shore Up
1 Sinister Concierge
1 Sol Ring
1 Spell Pierce
1 Spider-Man 2099
1 Stormcatch Mentor
1 Sulfur Falls
1 Swiftfoot Boots
1 Talisman of Creativity
1 Tavern Brawler
"""


def run_test():
    """
    An automated test script using the user's specific, valid data and
    asserting the correct, successful behavior of the application.
    """
    print("--- TEST RUNNER START ---")

    if os.path.exists('../collection.db'):
        os.remove('../collection.db')
        print("Removed existing test database.")

    print("\n--- PHASE 0: DATABASE SETUP ---")
    create_database_schema()

    service = MagicCardService()

    print("\n--- PHASE 1: POPULATING COLLECTION ---")

    print("Adding multiple cards from the provided list...")
    expected_successes = 12
    result = service.add_cards_from_list(COLLECTION_TO_ADD)
    # THIS IS THE KEY ASSERTION: We now expect 11 successes.
    assert result['success'] == expected_successes, f"Expected {expected_successes} successes, got {result['success']}"
    assert result['failure'] == 0, "There should be no failures with this valid data."
    print(f"List added successfully: {result['success']} successes.")

    print("\nVerifying collection summary...")
    summary = service.get_collection_summary()
    assert len(summary) == 11, f"Expected 11 unique cards, found {len(summary)}"

    gallant_citizen = next((c for c in summary if c.name == "Gallant Citizen"), None)
    assert gallant_citizen is not None, "Gallant Citizen not found in summary!"
    assert gallant_citizen.total_owned == 2, "Expected 2 Gallant Citizens"

    spiderman = next((c for c in summary if c.name == "Spider-Man 2099"), None)
    assert spiderman is not None, "Spider-Man 2099 not found in summary!"
    assert spiderman.total_owned == 1, "Expected 1 Spider-Man 2099"
    print("Collection summary is correct.")

    print("\n--- PHASE 2: MANAGING A DECK ---")

    DECK_NAME = "My Custom Deck"
    print(f"Creating new deck: '{DECK_NAME}'")
    service.create_deck(DECK_NAME)
    my_deck = service.get_all_decks()[0]
    deck_id = my_deck['id']
    print("Deck created successfully.")

    print("\nAdding cards to blueprint from list...")
    service.add_cards_to_blueprint_from_list(deck_id, DECK_BLUEPRINT)
    print("Blueprint populated.")

    print("\nAnalyzing blueprint against our collection...")
    analysis = service.get_deck_blueprint_analysis(deck_id)
    pprint(analysis)

    status_map = {item['card_name']: item['status'] for item in analysis}
    # We own the "Spider-Man 2099" from your list (SPM 150)
    assert status_map.get('Spider-Man 2099') == 'AVAILABLE', "Spider-Man 2099 should be AVAILABLE"
    assert status_map.get('Sol Ring') == 'MISSING', "Sol Ring should be MISSING"
    print("Blueprint analysis is correct.")

    print("\nTesting 'Export Buy List'...")
    service.export_buy_list(deck_id)
    clipboard_content = pyperclip.paste()
    print("--- CLIPBOARD CONTENT ---")
    print(clipboard_content)
    print("-------------------------")
    assert "1 Sol Ring" in clipboard_content
    assert "Spider-Man 2099" not in clipboard_content
    print("Buy list export verified successfully.")

    print("\n--- PHASE 3: ASSEMBLING THE DECK ---")

    print("Removing missing cards from blueprint to allow assembly...")
    missing_cards = [c for c in analysis if c['status'] == 'MISSING']
    for card in missing_cards:
        service.remove_card_from_blueprint(deck_id, card['oracle_card_id'])

    print("Getting assembly options for the single-card deck...")
    options = service.get_assembly_options(deck_id)

    choices_map = {}
    for option in options:
        if option['available_instances']:
            oracle_id = option['oracle_card_id']
            needed = option['quantity_needed']
            instance_ids_to_add = [inst['instance_id'] for inst in option['available_instances'][:needed]]
            choices_map[oracle_id] = instance_ids_to_add

    print("\nAttempting to assemble the deck with the owned card...")
    assembly_result = service.assemble_deck(deck_id, choices_map)
    assert assembly_result, "Deck assembly should have succeeded but it failed!"
    print("Deck assembled successfully!")

    print("\nVerifying card status after assembly...")
    spiderman_summary_after = service.get_collection_summary(filters={'name': 'Spider-Man 2099'})[0]
    assert spiderman_summary_after.total_owned == 1, "Total owned Spider-Man 2099 should still be 1."
    assert spiderman_summary_after.available_count == 0, "Available Spider-Man 2099 should now be 0."
    print("Card availability correctly updated.")

    print("\nDisassembling the deck...")
    assert service.disassemble_deck(deck_id), "Failed to disassemble deck!"
    spiderman_summary_final = service.get_collection_summary(filters={'name': 'Spider-Man 2099'})[0]
    assert spiderman_summary_final.available_count == 1, "Available Spider-Man 2099 should be back to 1."
    print("Deck disassembled and cards are available again.")

    service.close_session()
    print("\n--- TEST RUNNER FINISHED SUCCESSFULLY ---")


if __name__ == "__main__":
    run_test()