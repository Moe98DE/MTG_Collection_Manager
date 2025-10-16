import os
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Boolean,
    ForeignKey,
    Enum as SQLAlchemyEnum
)
from sqlalchemy.orm import relationship, declarative_base, sessionmaker
import enum

# --- Database Setup ---

# Define the base directory for the project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_PATH = os.path.join(BASE_DIR, 'collection.db')
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# The engine is the entry point to the database.
engine = create_engine(DATABASE_URL, echo=False) # Set echo=True to see generated SQL

# A session is the primary interface for persistence operations.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# The declarative base is a factory for creating mapped classes.
Base = declarative_base()


# --- Enums for Deck Status ---

class DeckStatus(enum.Enum):
    BLUEPRINT = "blueprint"
    ASSEMBLED = "assembled"


# --- Model Definitions ---

class OracleCard(Base):
    """Represents the abstract 'idea' of a Magic card (e.g., 'Sol Ring')."""
    __tablename__ = 'oracle_cards'
    
    id = Column(Integer, primary_key=True, index=True)
    oracle_id = Column(String, unique=True, index=True) # Scryfall's unique ID for this card concept
    name = Column(String, index=True)
    color_identity = Column(String) # e.g., "WUBRG"
    
    # This card concept has many different printings
    printings = relationship("CardPrinting", back_populates="oracle_card")

    def __repr__(self):
        return f"<OracleCard(name='{self.name}')>"

class CardPrinting(Base):
    """Represents a specific printing of a card (e.g., 'Sol Ring' from Commander Legends)."""
    __tablename__ = 'card_printings'
    
    id = Column(Integer, primary_key=True, index=True)
    scryfall_id = Column(String, unique=True, index=True) # Scryfall's unique ID for this specific printing
    set_code = Column(String, index=True)
    collector_number = Column(String)
    image_uri = Column(String, nullable=True) # Store the URL for the card image
    
    # This printing belongs to one abstract card concept
    oracle_card_id = Column(Integer, ForeignKey('oracle_cards.id'))
    oracle_card = relationship("OracleCard", back_populates="printings")
    
    # You can own multiple physical instances of this specific printing
    instances = relationship("CardInstance", back_populates="printing")

    def __repr__(self):
        return f"<CardPrinting(name='{self.oracle_card.name}', set='{self.set_code}')>"

class CardInstance(Base):
    """Represents a single, physical piece of cardboard you own."""
    __tablename__ = 'card_instances'
    
    id = Column(Integer, primary_key=True, index=True)
    is_foil = Column(Boolean, default=False)
    # You could add other properties like 'condition', 'language', etc. here
    
    # This physical card is a specific printing
    printing_id = Column(Integer, ForeignKey('card_printings.id'))
    printing = relationship("CardPrinting", back_populates="instances")
    
    # ** THIS IS THE KEY FOR AVAILABILITY **
    # If deck_id is NULL, the card is 'Available'. Otherwise, it's 'Allocated'.
    deck_id = Column(Integer, ForeignKey('decks.id'), nullable=True)
    deck = relationship("Deck", back_populates="cards")

    def __repr__(self):
        foil_str = " (Foil)" if self.is_foil else ""
        return f"<CardInstance(id={self.id}, printing='{self.printing.oracle_card.name} ({self.printing.set_code})'{foil_str})>"

class Deck(Base):
    """Represents a decklist, which can be a 'Blueprint' or physically 'Assembled'."""
    __tablename__ = 'decks'
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    format = Column(String, default="Commander")
    status = Column(SQLAlchemyEnum(DeckStatus), default=DeckStatus.BLUEPRINT)
    
    # This relationship is for ASSEMBLED decks (links to physical cards)
    cards = relationship("CardInstance", back_populates="deck")
    
    # ** NEW **: This relationship is for BLUEPRINT decks (links to card concepts)
    blueprint_entries = relationship("BlueprintEntry", back_populates="deck", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Deck(name='{self.name}', status='{self.status.value}')>"
    
class BlueprintEntry(Base):
    """
    Represents a single line item in a Blueprint deck.
    e.g., 'I need 2x Sol Ring in my Zur deck blueprint'.
    """
    __tablename__ = 'blueprint_entries'

    id = Column(Integer, primary_key=True)
    quantity = Column(Integer, nullable=False)
    
    deck_id = Column(Integer, ForeignKey('decks.id'), nullable=False)
    oracle_card_id = Column(Integer, ForeignKey('oracle_cards.id'), nullable=False)
    
    # Relationships
    deck = relationship("Deck", back_populates="blueprint_entries")
    oracle_card = relationship("OracleCard")

    def __repr__(self):
        return f"<BlueprintEntry(deck='{self.deck.name}', quantity={self.quantity}, card='{self.oracle_card.name}')>"    