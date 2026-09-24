from pathlib import Path

import yaml
from sqlalchemy import select

from bot_game_book.models import StyleCard


def _normalize(text: str) -> str:
    return " ".join(text.split())


def load_seed_data(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"bad seed file: {path}")
    return data


async def seed_style_cards(session, path: Path) -> int:
    items = load_seed_data(path)
    for index, item in enumerate(items):
        result = await session.execute(
            select(StyleCard).where(StyleCard.slug == item["slug"])
        )
        card = result.scalar_one_or_none()
        fields = {
            "name_ru": item["name_ru"],
            "name_en": item["name_en"],
            "is_public_domain": bool(item.get("public_domain", False)),
            "description": _normalize(item["description"]),
            "excerpt": item.get("excerpt"),
            "temperature": float(item.get("temperature", 0.8)),
            "sort_order": int(item.get("sort_order", 100 + index)),
            "is_active": True,
        }
        if card is None:
            session.add(StyleCard(slug=item["slug"], **fields))
        else:
            for key, value in fields.items():
                setattr(card, key, value)
    await session.commit()
    return len(items)
