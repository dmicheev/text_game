from bot_game_book.models import Chapter, Game

BOOK_PART_LIMIT = 3800


def compile_book(
    game: Game, chapters: list[Chapter], label_by_author: dict[int, str]
) -> list[str]:
    header = (
        f"📖 «{game.topic}»\n"
        f"Стиль: {game.style_label}\n"
        f"Глав: {len(chapters)}\n\n"
        "Книга написана по кругу: каждый автор видел только короткое резюме "
        "предыдущей главы. Приятного чтения!"
    )
    parts: list[str] = []
    buffer = header
    for ch in chapters:
        block = (
            f"\n\n{'—' * 24}\nГЛАВА {ch.idx}. {ch.title}\n"
            f"(автор: {label_by_author.get(ch.author_user_id, '?')})\n\n{ch.body}"
        )
        if len(buffer) + len(block) > BOOK_PART_LIMIT:
            parts.append(buffer)
            buffer = block.strip()
        else:
            buffer += block
    parts.append(buffer)
    return parts
