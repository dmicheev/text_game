def next_position(positions: list[int], current: int | None) -> int:
    if not positions:
        raise ValueError("no active players")
    if current is None or current >= positions[-1]:
        return positions[0]
    greater = [p for p in positions if p > current]
    return greater[0] if greater else positions[0]
