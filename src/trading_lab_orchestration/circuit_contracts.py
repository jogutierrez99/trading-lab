"""New technical integration card; bounded connections, not an economic protocol."""

from typing import Literal

from pydantic import model_validator

from .contracts import HypothesisManifest, Identifier, Model
from .implementation_contracts import ImplementationPlan

TARGET = "integration_candle_pulse_v1"
ACCEPTANCE_TARGET = "integration_candle_pair_v1"
ACCEPTANCE_RESEARCHER = "technical_acceptance_v1"
FLOW1_RESEARCHER = "openai-research-v1"
FLOW1_ID = "flow1_seq_v1"
FLOW1_FINGERPRINT = "771cb627739fb17eeabf139b92b14a074929327cc334ce9391b4cbde3ff51151"
PROFILES = {
    "technical_circuit_v1": (TARGET, "CANDLE_PULSE_V1", "circuit46_pulse_technical"),
    ACCEPTANCE_RESEARCHER: (ACCEPTANCE_TARGET, "CANDLE_PAIR_V1", "circuit46_pair_technical"),
}


def technical_profile(manifest):
    if manifest.researcher_version == FLOW1_RESEARCHER:
        if manifest.fingerprint() == FLOW1_FINGERPRINT:
            return PROFILES["technical_circuit_v1"]
        return None
    return PROFILES.get(manifest.researcher_version)


class CircuitRequest(Model):
    schema_version: Literal["1.0"] = "1.0"
    circuit_id: Identifier
    manifest: HypothesisManifest
    implementation: ImplementationPlan
    initial_attempts: Literal[1] = 1
    technical_repairs: Literal[2] = 2
    fixture: Literal["CANDLE_PULSE_V1", "CANDLE_PAIR_V1"] = "CANDLE_PULSE_V1"
    audit_mode: Literal["DETERMINISTIC_ONLY"] = "DETERMINISTIC_ONLY"
    telegram: Literal["PREVIEW_ONLY"] = "PREVIEW_ONLY"
    max_invocation_seconds: Literal[1500] = 1500
    max_backtests: Literal[6] = 6
    max_candles: Literal[328] = 328
    max_dataset_bytes: Literal[2000000] = 2000000

    @model_validator(mode="after")
    def technical_scope(self):
        p, m = self.implementation, self.manifest
        profile = technical_profile(m)
        if (
            p.operation != "NEW_STRATEGY"
            or profile is None
            or (p.target, self.fixture) != profile[:2]
            or p.max_wall_seconds != 300
            or p.check_timeout_seconds != 45
            or m.data_requirements.timeframe != "1h"
            or m.data_requirements.warmup_bars != 20
            or m.execution_assumptions.market_mode != "spot"
            or m.parameter_space.parameters
            or m.parameter_space.combination_limit != 1
            or not m.requires_new_strategy_code
            or "manual_engulfing" in m.hypothesis_id.lower()
            or (m.researcher_version == FLOW1_RESEARCHER and self.circuit_id != FLOW1_ID)
        ):
            raise ValueError(
                "Circuit4.6 requires the distinct frozen bounded technical integration profile"
            )
        return self
