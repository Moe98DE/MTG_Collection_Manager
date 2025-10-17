class CoreLogicError(Exception):
    """Base exception for all custom errors in the core logic module."""
    def __init__(self, message="An error occurred in the core logic."):
        self.message = message
        super().__init__(self.message)

class CardNotFoundError(CoreLogicError):
    """Raised when a card cannot be found via the Scryfall API or in the local cache."""
    def __init__(self, identifier: str):
        message = f"Card with identifier '{identifier}' could not be found."
        super().__init__(message)
        self.identifier = identifier

class InvalidInputFormatError(CoreLogicError):
    """Raised when a user-provided string for a card cannot be parsed."""
    def __init__(self, line: str):
        message = f"The input line '{line}' could not be parsed. Expected format: '1 Card Name (SET) 123 *F*'."
        super().__init__(message)
        self.line = line

class InstanceAlreadyAllocatedError(CoreLogicError):
    """Raised when an operation is attempted on a CardInstance that is part of an assembled deck."""
    def __init__(self, instance_id: int, deck_name: str):
        message = f"CardInstance ID {instance_id} is already allocated to the deck '{deck_name}' and cannot be modified."
        super().__init__(message)
        self.instance_id = instance_id
        self.deck_name = deck_name

class DeckAssemblyError(CoreLogicError):
    """Raised during the deck assembly process for various validation failures."""
    def __init__(self, message="An error occurred while assembling the deck."):
        super().__init__(message)