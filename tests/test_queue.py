from bot_game_book.engine.queue import next_position


def test_first_player_when_none():
    assert next_position([0, 1, 2], None) == 0


def test_next_in_order():
    assert next_position([0, 1, 2], 1) == 2


def test_wrap_around():
    assert next_position([0, 1, 2], 2) == 0


def test_gaps_in_positions():
    assert next_position([0, 3, 7], 3) == 7
    assert next_position([0, 3, 7], 7) == 0
    assert next_position([0, 3, 7], 0) == 3


def test_single_player_loops():
    assert next_position([5], 5) == 5


def test_empty_raises():
    import pytest

    with pytest.raises(ValueError):
        next_position([], None)
