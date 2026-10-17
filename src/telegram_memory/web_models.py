"""Validated request contracts for the web API."""

from typing import Literal

from pydantic import BaseModel, Field


class ChannelInput(BaseModel):
    channel: str = Field(min_length=1, max_length=256, pattern=r"^[^\s#]+$")


class MessageInput(ChannelInput):
    message_id: int = Field(gt=0)


class SyncInput(BaseModel):
    channel: str | None = None
    limit: int = Field(default=1000, ge=1, le=1000000)


class RemoteSearch(SyncInput):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=50, ge=1, le=1000)


class FavoriteInput(MessageInput):
    favorite: bool


class DownloadInput(MessageInput):
    destination: Literal["server", "browser"] = "server"
