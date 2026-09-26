import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class GameStatus(str, enum.Enum):
    configuring = "configuring"
    running = "running"
    paused = "paused"
    finished = "finished"
    cancelled = "cancelled"


class PlayerStatus(str, enum.Enum):
    active = "active"
    kicked = "kicked"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("platform", "platform_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), default="telegram", index=True)
    platform_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StyleCard(Base):
    __tablename__ = "style_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name_ru: Mapped[str] = mapped_column(String(128))
    name_en: Mapped[str] = mapped_column(String(128))
    is_public_domain: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    temperature: Mapped[float] = mapped_column(default=0.8)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    host_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    style_card_id: Mapped[int | None] = mapped_column(ForeignKey("style_cards.id"), nullable=True)
    style_label: Mapped[str] = mapped_column(String(128))
    style_card_text: Mapped[str] = mapped_column(Text)
    style_temperature: Mapped[float | None] = mapped_column(nullable=True)
    topic: Mapped[str] = mapped_column(Text)
    chapters_total: Mapped[int] = mapped_column(Integer)
    words_target: Mapped[int] = mapped_column(Integer)
    summary_words: Mapped[int] = mapped_column(Integer)
    turn_timeout_hours: Mapped[int] = mapped_column(Integer)
    status: Mapped[GameStatus] = mapped_column(SAEnum(GameStatus), default=GameStatus.configuring)
    current_chapter_idx: Mapped[int] = mapped_column(Integer, default=1)
    current_player_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    player_cursor: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_skips: Mapped[int] = mapped_column(Integer, default=0)
    turn_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    turn_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    turn_reminded: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dashboard_platform: Mapped[str | None] = mapped_column(String(16), nullable=True)
    dashboard_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dashboard_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    players: Mapped[list["GamePlayer"]] = relationship(
        back_populates="game",
        order_by="GamePlayer.position",
        lazy="selectin",
    )


class GamePlayer(Base):
    __tablename__ = "game_players"
    __table_args__ = (UniqueConstraint("game_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[PlayerStatus] = mapped_column(SAEnum(PlayerStatus), default=PlayerStatus.active)

    game: Mapped[Game] = relationship(back_populates="players")
    user: Mapped[User] = relationship(lazy="joined")


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("game_id", "idx"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    idx: Mapped[int] = mapped_column(Integer)
    author_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    memory: Mapped[str | None] = mapped_column(Text, nullable=True)
    illustration: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    illustration_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GameEvent(Base):
    __tablename__ = "game_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
