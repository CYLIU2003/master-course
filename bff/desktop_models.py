"""Public desktop contracts, shared with the generated TypeScript client."""

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ScenarioSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    status: str | None = None
    updatedAt: str | None = None


class DesktopPage(BaseModel):
    items: list[dict[str, JsonValue]]
    total: int
    offset: int
    limit: int
    warnings: list[str] = Field(default_factory=list)


class ScenarioPage(BaseModel):
    items: list[ScenarioSummary]
    total: int
    offset: int
    limit: int
    warnings: list[str] = Field(default_factory=list)


class ResultSummary(BaseModel):
    available: bool
    source: str | None
    values: dict[str, JsonValue]


class ScenarioOverview(BaseModel):
    meta: ScenarioSummary
    stats: dict[str, JsonValue]
    scope: dict[str, JsonValue]
    settings: dict[str, JsonValue]
    result: ResultSummary


class PrepareReply(BaseModel):
    # Preserve existing fields consumed by Tkinter and research runners.
    model_config = ConfigDict(extra="allow")
    ready: bool
    preparedInputId: str
    tripCount: int
    vehicleCount: int
    planningDays: int
    warnings: list[str]
    message: str | None = None
    errorCode: str | None = None


class JobReply(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    status: str
    progress: int
    message: str
    error: str | None
