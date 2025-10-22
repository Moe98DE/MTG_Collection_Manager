# main.py
import uvicorn
from typing import List, Optional, Dict

from fastapi import FastAPI, HTTPException, Query, Body, Response, Path
from pydantic import BaseModel, Field

# Assuming your provided code is in a 'core' directory
# Make sure your project structure allows this import
from core.services import MagicCardService
from core.repo.enums import BlueprintCardStatus, DeckStatus

# =============================================================================
# 1. Initialize FastAPI App and Service Layer
# =============================================================================

app = FastAPI(
    title="Magic Card Collection API",
    description="API for managing a Magic: The Gathering card collection and decks.",
    version="1.0.0",
)

# Create a single, shared instance of the service for the application's lifetime
service = MagicCardService()


# =============================================================================
# 2. Define Pydantic Models for API Data Contracts
# (Translating your dataclasses to Pydantic models)
# =============================================================================

# --- Collection Models ---

class CollectionSummaryItemModel(BaseModel):
    oracle_id: str
    name: str
    type_line: str
    mana_cost: Optional[str]
    cmc: float
    color_identity: str
    total_owned: int
    available_count: int
    representative_image_uri: Optional[str]
    keywords: List[str]


class CardInstanceDetailModel(BaseModel):
    instance_id: int
    oracle_id: str
    card_name: str
    set_code: str
    collector_number: str
    is_foil: bool
    condition: str
    purchase_price: Optional[float]
    date_added: str
    status: str


class CardAddRequest(BaseModel):
    card_string: str = Field(..., example="1x Sol Ring (CMM) #729")


class CardListAddRequest(BaseModel):
    card_list: str = Field(..., example="1x Sol Ring (CMM) #729\n2x Counterspell (DMC)")


class CardUpdateModel(BaseModel):
    # Define fields that are allowed to be updated
    condition: Optional[str] = Field(None, example="NM")
    purchase_price: Optional[float] = Field(None, example=4.99)
    is_foil: Optional[bool] = Field(None, example=True)


class BulkAddResponse(BaseModel):
    success: int
    failure: int


class CollectionExportResponse(BaseModel):
    export_list: str


# --- Deck Models ---

class DeckSummaryModel(BaseModel):
    id: int
    name: str
    status: DeckStatus


class AssembledDeckCardModel(BaseModel):
    card_name: str
    quantity: int


class BlueprintAnalysisItemModel(BaseModel):
    oracle_card_id: str
    card_name: str
    quantity_needed: int
    total_owned: int
    available_owned: int
    status: BlueprintCardStatus
    allocated_in_decks: List[str]


class AssemblyChoiceModel(BaseModel):
    instance_id: int
    display_text: str


class AssemblyOptionModel(BaseModel):
    oracle_card_id: str
    card_name: str
    quantity_needed: int
    available_instances: List[AssemblyChoiceModel]


class DeckCreateModel(BaseModel):
    name: str = Field(..., min_length=1, example="My Awesome Commander Deck")


class DeckAssemblyRequest(BaseModel):
    choices: Dict[str, List[int]] = Field(
        ...,
        example={
            "c0b395b8-522b-44df-91a7-59a1d1d81c13": [101, 102],
            "9c05514c-5353-48ee-a093-2396b4ce74a3": [205]
        }
    )


class BuyListResponse(BaseModel):
    buy_list: str


# =============================================================================
# 3. Define API Endpoints
# =============================================================================

# --- Root Endpoint ---

@app.get("/", tags=["General"])
def read_root():
    """A simple welcome message to confirm the API is running."""
    return {"message": "Welcome to the Magic Card Collection API"}


# --- Collection Endpoints ---

@app.get(
    "/collection/summary",
    response_model=List[CollectionSummaryItemModel],
    tags=["Collection"]
)
def get_collection_summary(
        name: Optional[str] = Query(None, description="Filter by card name (case-insensitive, partial match)."),
        type_line: Optional[str] = Query(None, description="Filter by card type line (e.g., 'Creature')."),
        color_identity: Optional[str] = Query(None,
                                              description="Filter by color identity (e.g., 'WUBRG'). Exact match."),
        cmc: Optional[float] = Query(None, description="Filter by Converted Mana Cost (CMC).")
):
    """
    Retrieves a summarized view of all unique cards in the collection.
    Each item represents one unique card (by Oracle ID) and its counts.
    Supports filtering by various card attributes.
    """
    filters = {
        "name": name,
        "type_line": type_line,
        "color_identity": color_identity,
        "cmc": cmc
    }
    # Remove None values so the service layer doesn't process them
    active_filters = {k: v for k, v in filters.items() if v is not None}
    return service.get_collection_summary(filters=active_filters)


@app.get(
    "/collection/instances",
    response_model=List[CardInstanceDetailModel],
    tags=["Collection"]
)
def get_all_card_instances():
    """Retrieves a detailed list of every single physical card instance in the collection."""
    return service.get_all_card_instances()


@app.get(
    "/collection/instances/search",
    response_model=List[CardInstanceDetailModel],
    tags=["Collection"]
)
def search_instances_by_name(name: str = Query(..., description="The exact Oracle card name to search for.")):
    """Finds all physical instances of a specific card by its name."""
    instances = service.get_instances_for_oracle_card(name)
    if not instances:
        raise HTTPException(
            status_code=404,
            detail=f"No instances found for card named '{name}'."
        )
    return instances


@app.post(
    "/collection/cards",
    status_code=201,
    tags=["Collection"],
    response_model=BulkAddResponse
)
def add_card_to_collection(request: CardAddRequest):
    """
    Adds a single card instance to the collection from a formatted string.
    Example: '1x Sol Ring (CMM) #729'
    """
    # Re-use the bulk add logic for simplicity
    result = service.add_cards_from_list(request.card_string)
    if result["success"] == 0:
        raise HTTPException(
            status_code=400,
            detail="Failed to add card. Check format or if card exists."
        )
    return result


@app.post(
    "/collection/cards/bulk-add",
    response_model=BulkAddResponse,
    tags=["Collection"]
)
def add_cards_from_list(request: CardListAddRequest):
    """
    Adds multiple cards to the collection from a multi-line string.
    Each line should be a valid card string.
    The operation is transactional; if a critical error occurs, nothing is added.
    """
    result = service.add_cards_from_list(request.card_list)
    if result["success"] == 0 and result["failure"] > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to add any cards. {result['failure']} lines could not be processed."
        )
    return result


@app.patch(
    "/collection/instances/{instance_id}",
    response_model=CardInstanceDetailModel,
    tags=["Collection"]
)
def update_card_instance(
        instance_id: int = Path(..., description="The unique ID of the card instance to update."),
        update_data: CardUpdateModel = Body(...)
):
    """Updates the details of a specific physical card instance."""
    # .dict(exclude_unset=True) is crucial to only send fields the user provided
    updated_card = service.update_card_instance(instance_id, update_data.dict(exclude_unset=True))
    if not updated_card:
        raise HTTPException(
            status_code=404,
            detail=f"Card instance with ID {instance_id} not found or update failed."
        )
    return updated_card


@app.delete(
    "/collection/instances/{instance_id}",
    status_code=204,
    tags=["Collection"]
)
def delete_card_instance(instance_id: int = Path(..., description="The unique ID of the card instance to delete.")):
    """
    Deletes a specific physical card instance from the collection.
    Fails if the card is currently part of an assembled deck.
    """
    deleted = service.delete_card_instance(instance_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Could not delete instance with ID {instance_id}. It may not exist or may be in an assembled deck."
        )
    # A 204 response should not have a body
    return Response(status_code=204)


@app.get(
    "/collection/export",
    response_model=CollectionExportResponse,
    tags=["Collection"]
)
def export_collection(
        name: Optional[str] = Query(None, description="Filter by card name (case-insensitive, partial match)."),
        type_line: Optional[str] = Query(None, description="Filter by card type line (e.g., 'Creature')."),
        color_identity: Optional[str] = Query(None,
                                              description="Filter by color identity (e.g., 'WUBRG'). Exact match."),
        cmc: Optional[float] = Query(None, description="Filter by Converted Mana Cost (CMC).")
):
    """
    Generates a text list of the collection for export, formatted as 'Count Card Name'.
    The frontend can then copy this text to the user's clipboard.
    """
    filters = {
        "name": name,
        "type_line": type_line,
        "color_identity": color_identity,
        "cmc": cmc
    }
    active_filters = {k: v for k, v in filters.items() if v is not None}

    # This logic is adapted from your service's export_collection method
    summary_items = service.get_collection_summary(filters=active_filters)
    if not summary_items:
        return CollectionExportResponse(export_list="")

    export_list = [f"{item.total_owned} {item.name}" for item in summary_items]
    return CollectionExportResponse(export_list="\n".join(export_list))


# --- Deck Endpoints ---

@app.get("/decks", response_model=List[DeckSummaryModel], tags=["Decks"])
def get_all_decks():
    """Retrieves a summary list of all decks."""
    return service.get_all_decks()


@app.post("/decks", response_model=DeckSummaryModel, status_code=201, tags=["Decks"])
def create_deck(deck_data: DeckCreateModel):
    """Creates a new, empty deck."""
    new_deck = service.create_deck(deck_data.name)
    if not new_deck:
        raise HTTPException(status_code=400,
                            detail="Deck could not be created. The name might be invalid or already exist.")
    # Convert DB model to DTO for response
    return DeckSummaryModel(id=new_deck.id, name=new_deck.name, status=new_deck.status)


@app.delete("/decks/{deck_id}", status_code=204, tags=["Decks"])
def delete_deck(deck_id: int = Path(..., description="The ID of the deck to delete.")):
    """Deletes a deck. This action cannot be undone."""
    success = service.delete_deck(deck_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Deck with ID {deck_id} not found.")
    return Response(status_code=204)


@app.get(
    "/decks/{deck_id}/blueprint/analysis",
    response_model=List[BlueprintAnalysisItemModel],
    tags=["Decks"]
)
def get_deck_blueprint_analysis(deck_id: int = Path(..., description="The ID of the deck to analyze.")):
    """
    Analyzes a deck's blueprint against the collection to see which cards are
    owned, missing, or already used in other decks.
    """
    analysis = service.get_deck_blueprint_analysis(deck_id)
    # The service returns [] for not found, which is fine for the API to return as well.
    return analysis


@app.post(
    "/decks/{deck_id}/blueprint/cards/bulk-add",
    response_model=BulkAddResponse,
    tags=["Decks"]
)
def add_cards_to_blueprint(
        deck_id: int = Path(..., description="The ID of the deck blueprint to modify."),
        request: CardListAddRequest = Body(...)
):
    """Adds cards from a list to a deck's blueprint."""
    result = service.add_cards_to_blueprint_from_list(deck_id, request.card_list)
    if result["success"] == 0 and result["failure"] > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to add any cards to blueprint. {result['failure']} lines could not be processed."
        )
    return result


@app.delete(
    "/decks/{deck_id}/blueprint/cards/{oracle_card_id}",
    status_code=204,
    tags=["Decks"]
)
def remove_card_from_blueprint(
        deck_id: int = Path(..., description="The ID of the deck."),
        oracle_card_id: str = Path(..., description="The Scryfall Oracle ID of the card to remove.")
):
    """Removes a card entry entirely from a deck's blueprint."""
    success = service.remove_card_from_blueprint(deck_id, oracle_card_id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Could not remove card {oracle_card_id} from deck {deck_id}. Deck or card may not exist in blueprint."
        )
    return Response(status_code=204)


@app.get(
    "/decks/{deck_id}/cards",
    response_model=List[AssembledDeckCardModel],
    tags=["Decks"]
)
def get_assembled_deck_contents(deck_id: int = Path(..., description="The ID of the assembled deck.")):
    """Retrieves the list of cards for a deck that is currently assembled."""
    return service.get_assembled_deck_contents(deck_id)


@app.get(
    "/decks/{deck_id}/assembly-options",
    response_model=List[AssemblyOptionModel],
    tags=["Decks"]
)
def get_assembly_options(deck_id: int = Path(..., description="The ID of the deck blueprint.")):
    """
    For a given deck blueprint, retrieves all available physical card instances
    that can be used to assemble it. Powers the 'Assembly Wizard' UI.
    """
    return service.get_assembly_options(deck_id)


@app.post("/decks/{deck_id}/assemble", tags=["Decks"])
def assemble_deck(
        deck_id: int = Path(..., description="The ID of the deck to assemble."),
        request: DeckAssemblyRequest = Body(...)
):
    """
    Assembles a deck using specific physical card instances.
    Validates choices and performs the assembly in a single transaction.
    """
    success = service.assemble_deck(deck_id, request.choices)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Deck assembly failed. Choices might be invalid (e.g., cards not available, wrong counts)."
        )
    return {"message": "Deck assembled successfully."}


@app.post("/decks/{deck_id}/disassemble", tags=["Decks"])
def disassemble_deck(deck_id: int = Path(..., description="The ID of the deck to disassemble.")):
    """Disassembles a deck, making all its physical cards available again."""
    success = service.disassemble_deck(deck_id)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Could not disassemble deck {deck_id}. It may not exist or is not assembled."
        )
    return {"message": "Deck disassembled successfully."}


@app.get(
    "/decks/{deck_id}/buy-list",
    response_model=BuyListResponse,
    tags=["Decks"]
)
def get_deck_buy_list(deck_id: int = Path(..., description="The ID of the deck.")):
    """
    Generates a text buy-list for cards missing from the collection for this deck.
    The frontend can then copy this text to the user's clipboard.
    """
    # This logic is adapted from your service's export_buy_list method
    analysis = service.get_deck_blueprint_analysis(deck_id)
    buy_list = []
    for card in analysis:
        if card.status in [BlueprintCardStatus.MISSING, BlueprintCardStatus.PARTIALLY_OWNED]:
            to_buy = card.quantity_needed - card.available_owned
            if to_buy > 0:
                buy_list.append(f"{to_buy} {card.card_name}")

    return BuyListResponse(buy_list="\n".join(buy_list))


# =============================================================================
# 4. Run the Application
# =============================================================================

if __name__ == "__main__":
    # This block allows you to run the API directly for testing
    # For production, use a process manager like Gunicorn:
    # gunicorn main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)