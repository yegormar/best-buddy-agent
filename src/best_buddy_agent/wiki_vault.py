"""No-op wiki vault hooks for extracted best_buddy_agent project."""

def is_enabled() -> bool:
    return False

def export_entity(entity: dict) -> None:
    return None

def delete_entity_md(entity: dict) -> None:
    return None

def clear_wiki_folder() -> None:
    return None

def rebuild_vault() -> None:
    return None
