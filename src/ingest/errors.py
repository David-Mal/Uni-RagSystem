"""The one error type of ingestion (plan §5.5, precedence level 1: ask for a valid export)."""


class IngestError(ValueError):
    """The file cannot be read or parsed. Nothing has been stored when this is raised."""
