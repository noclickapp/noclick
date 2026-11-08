"""College Football Data reads against the provider's OpenAPI 5.33.2 contract.

The published API has no writes. Each operation makes exactly one GET; results
retain the provider JSON shape under data. No account sign-in is performed.
"""
from __future__ import annotations
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.collegefootballdata.com"
FAMILY = "college_football_data_api_key"


class CollegeFootballDataAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="College Football Data API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://collegefootballdata.com/key",
            "x-credential-instructions": "Paste your College Football Data API key. NoClick sends it as a Bearer token only to api.collegefootballdata.com. Your plan controls available data and monthly call limits.",
        },
    )
    credential_type: Literal["college_football_data_api_key"] = Field(
        FAMILY, json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API key",
        min_length=1,
        max_length=4096,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(char.isspace() for char in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, populate_by_name=True
    )

    @model_validator(mode="after")
    def ranges(self):
        for low, high in (("min_year", "max_year"), ("start_week", "end_week")):
            if (
                getattr(self, low, None) is not None
                and getattr(self, high, None) is not None
                and getattr(self, low) > getattr(self, high)
            ):
                raise ValueError("Start must not exceed end")
        if getattr(self, "latest", False) or getattr(self, "final", False):
            if self.poll != "cfp" or (self.latest and self.final):
                raise ValueError("Latest/final requires poll=cfp; choose only one")
        if (
            getattr(self, "round", None) is not None
            and getattr(self, "competition", None) is None
        ):
            raise ValueError("Playoff round requires competition")
        return self


class GetAccountInfoConfig(_Input):
    """Returns the authenticated user's Patreon level and remaining API calls."""

    operation: Literal["get_account_info"] = Field(
        "get_account_info", json_schema_extra={"ui:hidden": True}
    )


class ListGamesConfig(_Input):
    """Returns historical game data."""

    operation: Literal["list_games"] = Field(
        "list_games", json_schema_extra={"ui:hidden": True}
    )
    year: int = Field(
        ...,
        description="Season year. Required unless `id` is specified.",
        ge=1,
        le=2147483647,
    )
    week: Optional[int] = Field(None, description="Week number.", ge=1, le=2147483647)
    season_type: Optional[
        Literal[
            "regular",
            "postseason",
            "both",
            "allstar",
            "spring_regular",
            "spring_postseason",
        ]
    ] = Field(None, description="Season type.", alias="seasonType")
    classification: Optional[Literal["fbs", "fcs", "ii", "ii/iii", "iii"]] = Field(
        None, description="Division classification."
    )
    team: Optional[str] = Field(
        None,
        description="Team name on either side of the game.",
        min_length=1,
        max_length=200,
    )
    home: Optional[str] = Field(
        None, description="Home team name.", min_length=1, max_length=200
    )
    away: Optional[str] = Field(
        None, description="Away team name.", min_length=1, max_length=200
    )
    conference: Optional[str] = Field(
        None, description="Conference of either team.", min_length=1, max_length=200
    )
    id: Optional[int] = Field(
        None,
        description="Game ID. When specified, returns data for that game.",
        ge=1,
        le=2147483647,
    )
    competition: Optional[Literal["cfp"]] = Field(
        None, description="Playoff competition."
    )
    round: Optional[
        Literal["first_round", "quarterfinal", "semifinal", "championship"]
    ] = Field(None, description="Playoff round. Requires `competition`.")


class ListGameTeamStatsConfig(_Input):
    """Returns team box score statistics by game."""

    operation: Literal["list_game_team_stats"] = Field(
        "list_game_team_stats", json_schema_extra={"ui:hidden": True}
    )
    year: int = Field(
        ...,
        description="Season year. Required unless `id` is specified.",
        ge=1,
        le=2147483647,
    )
    week: int = Field(
        ...,
        description="Week number. One of `week`, `team`, or `conference` is required\nwhen filtering by year.",
        ge=1,
        le=2147483647,
    )
    team: Optional[str] = Field(
        None,
        description="Team name. One of `week`, `team`, or `conference` is required\nwhen filtering by year.",
        min_length=1,
        max_length=200,
    )
    conference: Optional[str] = Field(
        None,
        description="Conference name or abbreviation. One of `week`, `team`,\nor `conference` is required when filtering by year.",
        min_length=1,
        max_length=200,
    )
    classification: Optional[Literal["fbs", "fcs", "ii", "ii/iii", "iii"]] = Field(
        None, description="Division classification."
    )
    season_type: Optional[
        Literal[
            "regular",
            "postseason",
            "both",
            "allstar",
            "spring_regular",
            "spring_postseason",
        ]
    ] = Field(None, description="Season type.", alias="seasonType")
    id: Optional[int] = Field(
        None,
        description="Game ID. When specified, returns statistics for that game.",
        ge=1,
        le=2147483647,
    )


class ListGamePlayerStatsConfig(_Input):
    """Returns player box score statistics by game."""

    operation: Literal["list_game_player_stats"] = Field(
        "list_game_player_stats", json_schema_extra={"ui:hidden": True}
    )
    year: int = Field(
        ...,
        description="Season year. Required unless `id` is specified.",
        ge=1,
        le=2147483647,
    )
    week: int = Field(
        ...,
        description="Week number. One of `week`, `team`, or `conference` is required\nwhen filtering by year.",
        ge=1,
        le=2147483647,
    )
    team: Optional[str] = Field(
        None,
        description="Team name. One of `week`, `team`, or `conference` is required\nwhen filtering by year.",
        min_length=1,
        max_length=200,
    )
    conference: Optional[str] = Field(
        None,
        description="Conference name or abbreviation. One of `week`, `team`,\nor `conference` is required when filtering by year.",
        min_length=1,
        max_length=200,
    )
    classification: Optional[Literal["fbs", "fcs", "ii", "ii/iii", "iii"]] = Field(
        None, description="Division classification."
    )
    season_type: Optional[
        Literal[
            "regular",
            "postseason",
            "both",
            "allstar",
            "spring_regular",
            "spring_postseason",
        ]
    ] = Field(None, description="Season type.", alias="seasonType")
    category: Optional[str] = Field(
        None, description="Player statistical category.", min_length=1, max_length=200
    )
    id: Optional[int] = Field(
        None,
        description="Game ID. When specified, returns statistics for that game.",
        ge=1,
        le=2147483647,
    )


class ListCalendarConfig(_Input):
    """Returns the week-by-week season calendar."""

    operation: Literal["list_calendar"] = Field(
        "list_calendar", json_schema_extra={"ui:hidden": True}
    )
    year: int = Field(..., description="Season year.", ge=1, le=2147483647)


class ListScoreboardConfig(_Input):
    """Returns current scoreboard data."""

    operation: Literal["list_scoreboard"] = Field(
        "list_scoreboard", json_schema_extra={"ui:hidden": True}
    )
    classification: Optional[Literal["fbs", "fcs", "ii", "ii/iii", "iii"]] = Field(
        None, description="Division classification. Defaults to `fbs`."
    )
    conference: Optional[str] = Field(
        None,
        description="Conference name or abbreviation.",
        min_length=1,
        max_length=200,
    )


class ListTeamsConfig(_Input):
    """Returns team information and conference affiliations."""

    operation: Literal["list_teams"] = Field(
        "list_teams", json_schema_extra={"ui:hidden": True}
    )
    conference: Optional[str] = Field(
        None, description="Conference abbreviation.", min_length=1, max_length=200
    )
    year: Optional[int] = Field(
        None,
        description="Season year for historical conference affiliations.",
        ge=1,
        le=2147483647,
    )


class ListFbsTeamsConfig(_Input):
    """Returns Football Bowl Subdivision (FBS) teams for a season."""

    operation: Literal["list_fbs_teams"] = Field(
        "list_fbs_teams", json_schema_extra={"ui:hidden": True}
    )
    year: Optional[int] = Field(None, description="Season year.", ge=1, le=2147483647)


class GetMatchupConfig(_Input):
    """Returns historical matchup results between two teams."""

    operation: Literal["get_matchup"] = Field(
        "get_matchup", json_schema_extra={"ui:hidden": True}
    )
    team1: str = Field(
        ..., description="First team name.", min_length=1, max_length=200
    )
    team2: str = Field(
        ..., description="Second team name.", min_length=1, max_length=200
    )
    min_year: Optional[int] = Field(
        None,
        description="Earliest season year to include.",
        ge=1,
        le=2147483647,
        alias="minYear",
    )
    max_year: Optional[int] = Field(
        None,
        description="Latest season year to include.",
        ge=1,
        le=2147483647,
        alias="maxYear",
    )


class ListRosterConfig(_Input):
    """Returns historical roster data."""

    operation: Literal["list_roster"] = Field(
        "list_roster", json_schema_extra={"ui:hidden": True}
    )
    team: Optional[str] = Field(
        None, description="Team name.", min_length=1, max_length=200
    )
    year: Optional[int] = Field(
        None, description="Season year. Defaults to 2025.", ge=1, le=2147483647
    )
    classification: Optional[Literal["fbs", "fcs", "ii", "ii/iii", "iii"]] = Field(
        None, description="Division classification: `fbs` or `fcs`."
    )


class ListConferencesConfig(_Input):
    """Returns conferences and member counts."""

    operation: Literal["list_conferences"] = Field(
        "list_conferences", json_schema_extra={"ui:hidden": True}
    )
    year: Optional[int] = Field(
        None,
        description="Season year used to calculate membership.",
        ge=1,
        le=2147483647,
    )
    classification: Optional[Literal["fbs", "fcs", "ii", "ii/iii", "iii"]] = Field(
        None, description="Conference classification."
    )


class ListVenuesConfig(_Input):
    """Returns college football venues."""

    operation: Literal["list_venues"] = Field(
        "list_venues", json_schema_extra={"ui:hidden": True}
    )


class ListRecordsConfig(_Input):
    """Returns historical team records by season."""

    operation: Literal["list_records"] = Field(
        "list_records", json_schema_extra={"ui:hidden": True}
    )
    year: int = Field(
        ...,
        description="Season year. Required unless `team` is specified.",
        ge=1,
        le=2147483647,
    )
    team: Optional[str] = Field(
        None,
        description="Team name. Required unless `year` is specified.",
        min_length=1,
        max_length=200,
    )
    conference: Optional[str] = Field(
        None,
        description="Conference name or abbreviation.",
        min_length=1,
        max_length=200,
    )


class ListRankingsConfig(_Input):
    """Returns historical poll rankings."""

    operation: Literal["list_rankings"] = Field(
        "list_rankings", json_schema_extra={"ui:hidden": True}
    )
    year: int = Field(..., description="Season year.", ge=1, le=2147483647)
    season_type: Optional[
        Literal[
            "regular",
            "postseason",
            "both",
            "allstar",
            "spring_regular",
            "spring_postseason",
        ]
    ] = Field(None, description="Season type.", alias="seasonType")
    week: Optional[float] = Field(
        None, description="Poll week.", ge=0, allow_inf_nan=False
    )
    poll: Optional[Literal["cfp"]] = Field(None, description="Poll name.")
    latest: Optional[bool] = Field(
        None,
        description="Returns the latest CFP snapshot when `true`, preferring the\nsnapshot marked as final. Requires `poll=cfp` and cannot be combined with\n`final`.",
    )
    final: Optional[bool] = Field(
        None,
        description="Returns the CFP snapshot marked as final when `true`. Requires\n`poll=cfp` and cannot be combined with `latest`.",
    )


class ListRecruitsConfig(_Input):
    """Returns player recruiting rankings."""

    operation: Literal["list_recruits"] = Field(
        "list_recruits", json_schema_extra={"ui:hidden": True}
    )
    year: int = Field(
        ...,
        description="Recruiting class year. Required unless `team` is specified.",
        ge=1,
        le=2147483647,
    )
    team: Optional[str] = Field(
        None,
        description="Team name. Required unless `year` is specified.",
        min_length=1,
        max_length=200,
    )
    position: Optional[str] = Field(
        None, description="Position category.", min_length=1, max_length=200
    )
    state: Optional[str] = Field(
        None,
        description="State or province abbreviation.",
        min_length=1,
        max_length=200,
    )
    classification: Optional[Literal["JUCO", "PrepSchool", "HighSchool"]] = Field(
        None, description="Recruit classification. Defaults to `HighSchool`."
    )


class ListTeamRecruitingRankingsConfig(_Input):
    """Returns team recruiting rankings."""

    operation: Literal["list_team_recruiting_rankings"] = Field(
        "list_team_recruiting_rankings", json_schema_extra={"ui:hidden": True}
    )
    year: Optional[int] = Field(
        None, description="Recruiting class year.", ge=1, le=2147483647
    )
    team: Optional[str] = Field(
        None, description="Team name.", min_length=1, max_length=200
    )


class SearchPlayersConfig(_Input):
    """Returns up to 100 players whose names match the search term."""

    operation: Literal["search_players"] = Field(
        "search_players", json_schema_extra={"ui:hidden": True}
    )
    search_term: str = Field(
        ...,
        description="Full or partial player name.",
        min_length=1,
        max_length=200,
        alias="searchTerm",
    )
    year: Optional[int] = Field(None, description="Season year.", ge=1, le=2147483647)
    team: Optional[str] = Field(
        None, description="Team name.", min_length=1, max_length=200
    )
    position: Optional[str] = Field(
        None, description="Player position abbreviation.", min_length=1, max_length=200
    )


class ListTransferPortalConfig(_Input):
    """Returns transfer portal entries for a season."""

    operation: Literal["list_transfer_portal"] = Field(
        "list_transfer_portal", json_schema_extra={"ui:hidden": True}
    )
    year: int = Field(..., description="Season year.", ge=1, le=2147483647)


class ListPlayerSeasonStatsConfig(_Input):
    """Returns player statistics aggregated by season."""

    operation: Literal["list_player_season_stats"] = Field(
        "list_player_season_stats", json_schema_extra={"ui:hidden": True}
    )
    year: int = Field(..., description="Season year.", ge=1, le=2147483647)
    conference: Optional[str] = Field(
        None,
        description="Conference name or abbreviation.",
        min_length=1,
        max_length=200,
    )
    team: Optional[str] = Field(
        None, description="Team name.", min_length=1, max_length=200
    )
    start_week: Optional[int] = Field(
        None,
        description="Earliest week to include.",
        ge=1,
        le=2147483647,
        alias="startWeek",
    )
    end_week: Optional[int] = Field(
        None,
        description="Latest week to include.",
        ge=1,
        le=2147483647,
        alias="endWeek",
    )
    season_type: Optional[
        Literal[
            "regular",
            "postseason",
            "both",
            "allstar",
            "spring_regular",
            "spring_postseason",
        ]
    ] = Field(None, description="Season type.", alias="seasonType")
    category: Optional[str] = Field(
        None, description="Statistical category.", min_length=1, max_length=200
    )


class ListTeamSeasonStatsConfig(_Input):
    """Returns team statistics aggregated by season."""

    operation: Literal["list_team_season_stats"] = Field(
        "list_team_season_stats", json_schema_extra={"ui:hidden": True}
    )
    year: int = Field(
        ...,
        description="Season year. Required unless `team` is specified.",
        ge=1,
        le=2147483647,
    )
    team: Optional[str] = Field(
        None,
        description="Team name. Required unless `year` is specified.",
        min_length=1,
        max_length=200,
    )
    conference: Optional[str] = Field(
        None,
        description="Conference name or abbreviation.",
        min_length=1,
        max_length=200,
    )
    start_week: Optional[int] = Field(
        None,
        description="Earliest week to include.",
        ge=1,
        le=2147483647,
        alias="startWeek",
    )
    end_week: Optional[int] = Field(
        None,
        description="Latest week to include.",
        ge=1,
        le=2147483647,
        alias="endWeek",
    )
    classification: Optional[Literal["fbs", "fcs", "ii", "ii/iii", "iii"]] = Field(
        None, description="Division classification. Defaults to `fbs`."
    )


class ListBettingLinesConfig(_Input):
    """Returns historical betting lines and results."""

    operation: Literal["list_betting_lines"] = Field(
        "list_betting_lines", json_schema_extra={"ui:hidden": True}
    )
    game_id: Optional[int] = Field(
        None, description="Game ID.", ge=1, le=2147483647, alias="gameId"
    )
    year: int = Field(
        ...,
        description="Season year. Required unless `gameId` is specified.",
        ge=1,
        le=2147483647,
    )
    season_type: Optional[
        Literal[
            "regular",
            "postseason",
            "both",
            "allstar",
            "spring_regular",
            "spring_postseason",
        ]
    ] = Field(None, description="Season type.", alias="seasonType")
    week: Optional[int] = Field(None, description="Week number.", ge=1, le=2147483647)
    team: Optional[str] = Field(
        None,
        description="Team name on either side of the game.",
        min_length=1,
        max_length=200,
    )
    home: Optional[str] = Field(
        None, description="Home team name.", min_length=1, max_length=200
    )
    away: Optional[str] = Field(
        None, description="Away team name.", min_length=1, max_length=200
    )
    conference: Optional[str] = Field(
        None, description="Conference of either team.", min_length=1, max_length=200
    )
    provider: Optional[str] = Field(
        None, description="Betting line provider.", min_length=1, max_length=200
    )


class ListDrivesConfig(_Input):
    """Returns historical drive data."""

    operation: Literal["list_drives"] = Field(
        "list_drives", json_schema_extra={"ui:hidden": True}
    )
    year: int = Field(..., description="Season year.", ge=1, le=2147483647)
    season_type: Optional[
        Literal[
            "regular",
            "postseason",
            "both",
            "allstar",
            "spring_regular",
            "spring_postseason",
        ]
    ] = Field(None, description="Season type.", alias="seasonType")
    week: Optional[int] = Field(None, description="Week number.", ge=1, le=2147483647)
    team: Optional[str] = Field(
        None,
        description="Team name on either side of the drive.",
        min_length=1,
        max_length=200,
    )
    offense: Optional[str] = Field(
        None, description="Offensive team name.", min_length=1, max_length=200
    )
    defense: Optional[str] = Field(
        None, description="Defensive team name.", min_length=1, max_length=200
    )
    conference: Optional[str] = Field(
        None, description="Conference of either team.", min_length=1, max_length=200
    )
    offense_conference: Optional[str] = Field(
        None,
        description="Offensive team conference.",
        min_length=1,
        max_length=200,
        alias="offenseConference",
    )
    defense_conference: Optional[str] = Field(
        None,
        description="Defensive team conference.",
        min_length=1,
        max_length=200,
        alias="defenseConference",
    )
    classification: Optional[Literal["fbs", "fcs", "ii", "ii/iii", "iii"]] = Field(
        None, description="Division classification of either team."
    )


CollegeFootballDataConfig = Annotated[
    Union[
        GetAccountInfoConfig,
        ListGamesConfig,
        ListGameTeamStatsConfig,
        ListGamePlayerStatsConfig,
        ListCalendarConfig,
        ListScoreboardConfig,
        ListTeamsConfig,
        ListFbsTeamsConfig,
        GetMatchupConfig,
        ListRosterConfig,
        ListConferencesConfig,
        ListVenuesConfig,
        ListRecordsConfig,
        ListRankingsConfig,
        ListRecruitsConfig,
        ListTeamRecruitingRankingsConfig,
        SearchPlayersConfig,
        ListTransferPortalConfig,
        ListPlayerSeasonStatsConfig,
        ListTeamSeasonStatsConfig,
        ListBettingLinesConfig,
        ListDrivesConfig,
    ],
    Field(discriminator="operation"),
]


class CollegeFootballDataFullConfig(
    NodeConfig[CollegeFootballDataConfig, CollegeFootballDataAPIKeyCredential]
):
    pass


OPERATIONS = {
    "get_account_info": {"path": "/info", "params": {}, "object": True},
    "list_games": {
        "path": "/games",
        "params": {
            "year": "year",
            "week": "week",
            "season_type": "seasonType",
            "classification": "classification",
            "team": "team",
            "home": "home",
            "away": "away",
            "conference": "conference",
            "id": "id",
            "competition": "competition",
            "round": "round",
        },
        "object": False,
    },
    "list_game_team_stats": {
        "path": "/games/teams",
        "params": {
            "year": "year",
            "week": "week",
            "team": "team",
            "conference": "conference",
            "classification": "classification",
            "season_type": "seasonType",
            "id": "id",
        },
        "object": False,
    },
    "list_game_player_stats": {
        "path": "/games/players",
        "params": {
            "year": "year",
            "week": "week",
            "team": "team",
            "conference": "conference",
            "classification": "classification",
            "season_type": "seasonType",
            "category": "category",
            "id": "id",
        },
        "object": False,
    },
    "list_calendar": {"path": "/calendar", "params": {"year": "year"}, "object": False},
    "list_scoreboard": {
        "path": "/scoreboard",
        "params": {"classification": "classification", "conference": "conference"},
        "object": False,
    },
    "list_teams": {
        "path": "/teams",
        "params": {"conference": "conference", "year": "year"},
        "object": False,
    },
    "list_fbs_teams": {
        "path": "/teams/fbs",
        "params": {"year": "year"},
        "object": False,
    },
    "get_matchup": {
        "path": "/teams/matchup",
        "params": {
            "team1": "team1",
            "team2": "team2",
            "min_year": "minYear",
            "max_year": "maxYear",
        },
        "object": True,
    },
    "list_roster": {
        "path": "/roster",
        "params": {"team": "team", "year": "year", "classification": "classification"},
        "object": False,
    },
    "list_conferences": {
        "path": "/conferences",
        "params": {"year": "year", "classification": "classification"},
        "object": False,
    },
    "list_venues": {"path": "/venues", "params": {}, "object": False},
    "list_records": {
        "path": "/records",
        "params": {"year": "year", "team": "team", "conference": "conference"},
        "object": False,
    },
    "list_rankings": {
        "path": "/rankings",
        "params": {
            "year": "year",
            "season_type": "seasonType",
            "week": "week",
            "poll": "poll",
            "latest": "latest",
            "final": "final",
        },
        "object": False,
    },
    "list_recruits": {
        "path": "/recruiting/players",
        "params": {
            "year": "year",
            "team": "team",
            "position": "position",
            "state": "state",
            "classification": "classification",
        },
        "object": False,
    },
    "list_team_recruiting_rankings": {
        "path": "/recruiting/teams",
        "params": {"year": "year", "team": "team"},
        "object": False,
    },
    "search_players": {
        "path": "/player/search",
        "params": {
            "search_term": "searchTerm",
            "year": "year",
            "team": "team",
            "position": "position",
        },
        "object": False,
    },
    "list_transfer_portal": {
        "path": "/player/portal",
        "params": {"year": "year"},
        "object": False,
    },
    "list_player_season_stats": {
        "path": "/stats/player/season",
        "params": {
            "year": "year",
            "conference": "conference",
            "team": "team",
            "start_week": "startWeek",
            "end_week": "endWeek",
            "season_type": "seasonType",
            "category": "category",
        },
        "object": False,
    },
    "list_team_season_stats": {
        "path": "/stats/season",
        "params": {
            "year": "year",
            "team": "team",
            "conference": "conference",
            "start_week": "startWeek",
            "end_week": "endWeek",
            "classification": "classification",
        },
        "object": False,
    },
    "list_betting_lines": {
        "path": "/lines",
        "params": {
            "game_id": "gameId",
            "year": "year",
            "season_type": "seasonType",
            "week": "week",
            "team": "team",
            "home": "home",
            "away": "away",
            "conference": "conference",
            "provider": "provider",
        },
        "object": False,
    },
    "list_drives": {
        "path": "/drives",
        "params": {
            "year": "year",
            "season_type": "seasonType",
            "week": "week",
            "team": "team",
            "offense": "offense",
            "defense": "defense",
            "conference": "conference",
            "offense_conference": "offenseConference",
            "defense_conference": "defenseConference",
            "classification": "classification",
        },
        "object": False,
    },
}


class CollegeFootballDataNode(WorkflowNode):
    integration_type = "automation-college-football-data"
    connection_evidence = ConnectionEvidence(
        noun="College Football Data account", operation="get_account_info"
    )

    @classmethod
    def get_config_model(cls):
        return CollegeFootballDataFullConfig

    async def execute(self, context):
        if not self.config.credentials:
            return {
                "status": "error",
                "error": "Connect a College Football Data API key",
            }
        credential = self.config.credentials
        op = self.config.config
        endpoint = OPERATIONS[op.operation]
        params = {
            wire: getattr(op, name)
            for name, wire in endpoint["params"].items()
            if getattr(op, name) is not None
        }
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    "GET",
                    BASE + endpoint["path"],
                    params=params,
                    headers={
                        "Authorization": "Bearer " + credential.api_key,
                        "Accept": "application/json",
                    },
                )
            if response.status_code != 200:
                message = "College Football Data request failed"
                try:
                    body = response.json()
                    if isinstance(body, dict) and isinstance(body.get("message"), str):
                        message = body["message"].replace(
                            credential.api_key, "[redacted]"
                        )[:500]
                except ValueError:
                    pass
                return {
                    "status": "error",
                    "error": message,
                    "http_status": response.status_code,
                }
            body = response.json()
            if endpoint["object"]:
                if not isinstance(body, dict) or "error" in body or "message" in body:
                    raise ValueError("Expected a College Football Data object")
                if op.operation == "get_account_info" and (
                    not isinstance(body.get("tierName"), str)
                    or type(body.get("patronLevel")) not in (int, float)
                ):
                    raise ValueError(
                        "Account information was not returned; check your API key"
                    )
            elif not isinstance(body, list) or any(
                not isinstance(row, dict) for row in body
            ):
                raise ValueError("Expected a College Football Data array")
            return {"status": "success", "data": body, "http_status": 200}
        except httpx.RequestError:
            return {
                "status": "error",
                "error": "College Football Data could not be reached",
            }
        except ValueError:
            return {
                "status": "error",
                "error": "College Football Data returned an unexpected response",
            }
