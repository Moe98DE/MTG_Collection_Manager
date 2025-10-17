import os
import enum
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Boolean,
    ForeignKey,
    Enum as SQLAlchemyEnum,
    Float,  # NEW: For prices and CMC
    TIMESTAMP,  # NEW: For date_added
    UniqueConstraint,  # NEW: For CardPrinting uniqueness
    Text  # NEW: For long text like oracle_text
)
from sqlalchemy.orm import relationship, declarative_base, sessionmaker
from sqlalchemy.sql import func  # NEW: To get the current time for defaults

# --- Database Setup ---

# Define the base directory for the project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_PATH = os.path.join(BASE_DIR, 'collection.db')
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# The engine is the entry point to the database.
engine = create_engine(DATABASE_URL, echo=False)

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

    # OLD Fields - A few are updated
    id = Column(String, primary_key=True)  # UPDATED: Using Scryfall Oracle ID as primary key is more robust.
    name = Column(String, unique=True, index=True)
    color_identity = Column(String)  # Stored as a string, e.g., "WUBRG"
    type_line = Column(String)

    # NEW Fields from TRS 3.1
    mana_cost = Column(String, nullable=True)
    cmc = Column(Float, nullable=False)
    oracle_text = Column(Text, nullable=True)
    power = Column(String, nullable=True)
    toughness = Column(String, nullable=True)
    loyalty = Column(String, nullable=True)
    keywords = Column(String, default="")  # Stored as a comma-separated string

    # This card concept has many different printings
    printings = relationship("CardPrinting", back_populates="oracle_card")

    def __repr__(self):
        return f"<OracleCard(name='{self.name}')>"


class CardPrinting(Base):
    """Represents a specific printing of a card (e.g., 'Sol Ring' from Commander Legends)."""
    __tablename__ = 'card_printings'

    # OLD Fields - A few are updated
    id = Column(String, primary_key=True)  # UPDATED: Using Scryfall Card ID as primary key is more robust.
    set_code = Column(String, index=True)
    collector_number = Column(String)

    # NEW fields from TRS 3.2
    rarity = Column(String)
    artist = Column(String, nullable=True)
    image_uri_normal = Column(String, nullable=True)

    # NEW: The spec asks for multiple image sizes, let's add the large one.
    image_uri_large = Column(String, nullable=True)
    price_usd = Column(Float, nullable=True)
    price_usd_foil = Column(Float, nullable=True)

    # This printing belongs to one abstract card concept
    oracle_card_id = Column(String, ForeignKey('oracle_cards.id'))
    oracle_card = relationship("OracleCard", back_populates="printings")

    # You can own multiple physical instances of this specific printing
    instances = relationship("CardInstance", back_populates="printing")

    # NEW: Unique constraint from TRS 3.2
    __table_args__ = (UniqueConstraint('set_code', 'collector_number', name='_set_collector_uc'),)

    def __repr__(self):
        return f"<CardPrinting(name='{self.oracle_card.name}', set='{self.set_code}')>"


class CardInstance(Base):
    """Represents a single, physical piece of cardboard you own."""
    __tablename__ = 'card_instances'

    id = Column(Integer, primary_key=True, index=True)
    is_foil = Column(Boolean, default=False)

    # NEW fields from TRS 3.3
    condition = Column(String, default="Near Mint")
    purchase_price = Column(Float, nullable=True)
    date_added = Column(TIMESTAMP, server_default=func.now())

    # This physical card is a specific printing
    printing_id = Column(String, ForeignKey('card_printings.id'))
    printing = relationship("CardPrinting", back_populates="instances")

    # This is the key for availability
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

    # NEW field from TRS 3.4
    # Note: Storing the printing ID allows showing the exact art for the commander.
    commander_id = Column(String, ForeignKey('card_printings.id'), nullable=True)
    commander = relationship("CardPrinting")

    # This relationship is for ASSEMBLED decks (links to physical cards)
    cards = relationship("CardInstance", back_populates="deck")

    # This relationship is for BLUEPRINT decks (links to card concepts)
    blueprint_entries = relationship("BlueprintEntry", back_populates="deck", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Deck(name='{self.name}', status='{self.status.value}')>"


class BlueprintEntry(Base):
    """
    Represents a single line item in a Blueprint deck.
    This corresponds to the 'DeckCardBlueprint' table in the TRS.
    """
    __tablename__ = 'blueprint_entries'

    id = Column(Integer, primary_key=True)
    quantity = Column(Integer, nullable=False)

    deck_id = Column(Integer, ForeignKey('decks.id'), nullable=False)
    oracle_card_id = Column(String, ForeignKey('oracle_cards.id'), nullable=False)

    # Relationships
    deck = relationship("Deck", back_populates="blueprint_entries")
    oracle_card = relationship("OracleCard")

    def __repr__(self):
        return f"<BlueprintEntry(deck='{self.deck.name}', quantity={self.quantity}, card='{self.oracle_card.name}')>"