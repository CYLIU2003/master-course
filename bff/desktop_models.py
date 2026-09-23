"""Public desktop contracts, shared with the generated TypeScript client."""

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from typing import Literal


class ScenarioSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    status: str | None = None
    updatedAt: str | None = None
    routeGroup: Literal["shibu24", "shibu21_24", "shibu21_23", "other"] = "other"


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


class DesktopConfiguration(BaseModel):
    values: dict[str, JsonValue]
    revision: str


class DesktopConfigurationEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    changes: dict[str, JsonValue]
    revision: str


class DesktopWeatherAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["inspect", "historical", "pv_proxy", "representative", "typical_proxy"]
    source_path: str = ""
    service_date: str = ""
    station_id: str = ""
    station_name: str = ""
    depot_id: str = ""
    issue_date: str = ""
    weather_class: Literal["auto", "sunny", "cloudy", "rainy"] = "auto"
    random_seed: int = 42


class DesktopTimetableImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(max_length=20_000_000)
    apply: bool = False
    revision: str = ""


class DesktopWeatherSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(max_length=200)
    content: str = Field(max_length=20_000_000)


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
