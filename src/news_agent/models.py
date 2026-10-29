
from datetime import datetime
from typing import Literal

#Pydantic is a Python library that validates data, converts data into the correct types when possible, and helps ensure that data follows rules you define.

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


Category = Literal[
    "World",
    "Politics",
    "Business",
    "Technology",
    "Science",
    "Health",
    "Environment",
    "Nepal",
    "India",
    "Other",
]

# str_strip_whitespace=True tells Pydantic to remove leading and trailing whitespace from string fields.

class Story(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: int | None = None
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=3000)
    source: str = Field(min_length=1, max_length=150)
    url: HttpUrl
    published_at: datetime | None = None
    collected_at: datetime
    content_hash: str = Field(min_length=1, max_length=64)


class RankedStory(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: int
    score: int = Field(ge=1, le=10)
    headline: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=1200)
    why_it_matters: str = Field(min_length=1, max_length=600)
    category: Category


class Briefing(BaseModel):
    generated_at: datetime
    stories: list[RankedStory] = Field(default_factory=list)


class RunResult(BaseModel):
    run_id: str
    status: Literal["success", "partial", "failed"]
    collected_count: int = 0
    selected_count: int = 0
    emailed: bool = False
    error: str | None = None
