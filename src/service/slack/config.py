"""Immutable, environment-only Slack Socket Mode configuration with redaction."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


class SlackConfigurationError(RuntimeError):
    def __init__(self, variable: str):
        self.variable = variable
        super().__init__(f"Missing or empty required environment variable: {variable}")


@dataclass(frozen=True, repr=False)
class SlackSocketConfig:
    app_token: str
    bot_token: str
    team_id: str
    channel_ids: frozenset[str]
    approver_ids: frozenset[str]
    workspace_id: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SlackSocketConfig":
        source = os.environ if env is None else env

        def required(name: str) -> str:
            value = str(source.get(name, "")).strip()
            if not value:
                raise SlackConfigurationError(name)
            return value

        def id_set(name: str) -> frozenset[str]:
            values = frozenset(part.strip() for part in required(name).split(",") if part.strip())
            if not values:
                raise SlackConfigurationError(name)
            return values

        return cls(
            app_token=required("SARATHI_SLACK_APP_TOKEN"),
            bot_token=required("SARATHI_SLACK_BOT_TOKEN"),
            team_id=required("SARATHI_SLACK_TEAM_ID"),
            channel_ids=id_set("SARATHI_SLACK_CHANNEL_IDS"),
            approver_ids=id_set("SARATHI_SLACK_APPROVER_IDS"),
            workspace_id=required("SARATHI_SLACK_WORKSPACE_ID"),
        )

    def __repr__(self) -> str:
        return (
            "SlackSocketConfig(app_token=<redacted>, bot_token=<redacted>, "
            "team_id=<redacted>, channel_ids=<redacted>, "
            "approver_ids=<redacted>, workspace_id=<redacted>)"
        )
