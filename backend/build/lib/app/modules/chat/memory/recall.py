import re
from app.modules.chat.orm.turn import Turn
from app.modules.chat.schemas.chat import ConversationTurnDTO


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def keyword_recall(older_turns: list[Turn], recent_turns: list[Turn], limit: int = 4) -> list[ConversationTurnDTO]:
    query_terms = set()
    for turn in recent_turns:
        query_terms |= tokens(turn.content)
    if not query_terms:
        return []
    scored = []
    for turn in older_turns:
        score = len(query_terms & tokens(turn.content))
        if score > 0:
            scored.append((score, turn))
    scored.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
    return [ConversationTurnDTO(role=t.role, content=t.content, created_at=t.created_at.isoformat() if t.created_at else None) for _, t in scored[:limit]]
