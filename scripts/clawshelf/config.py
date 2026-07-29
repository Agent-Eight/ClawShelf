from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import tempfile


CONFIG_SCHEMA = "clawshelf.config"
CONFIG_NAME = "clawshelf-config.json"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AdvancedCreativitySettings:
    threshold: int = 13
    min_confidence: float = 0.65


@dataclass(frozen=True)
class CreativitySettings:
    mode: str = "auto"
    model: str = ""
    novelty_preference: float = 0.5
    candidate_limit: int = 10
    semantic_retrieval: str = "auto"
    semantic_candidate_target: int = 3
    advanced: AdvancedCreativitySettings = field(default_factory=AdvancedCreativitySettings)


@dataclass(frozen=True)
class DeliveryBinding:
    agent: str
    session: str
    channel: str
    target: str = ""
    account: str = ""


@dataclass(frozen=True)
class ShelfConfig:
    notification_policy: str = "p1_p2"
    creativity_scoring: CreativitySettings = field(default_factory=CreativitySettings)
    shelf_plan: dict[str, str] = field(default_factory=dict)
    delivery_binding: DeliveryBinding | None = None

    def to_dict(self) -> dict:
        return {
            "schema": CONFIG_SCHEMA,
            "notification_policy": self.notification_policy,
            "creativity_scoring": asdict(self.creativity_scoring),
            "shelf_plan": self.shelf_plan,
            "delivery_binding": (
                asdict(self.delivery_binding) if self.delivery_binding else None
            ),
        }

    @property
    def fingerprint(self) -> str:
        data = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    @property
    def shelf_plan_fingerprint(self) -> str:
        data = json.dumps(self.shelf_plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode("utf-8")).hexdigest()


PLAN_FIELDS = ("domain_background", "work_direction", "concrete_problem", "collection_pattern", "companion_mode")


def config_path(folder: Path) -> Path:
    return folder.resolve() / "clawshelf" / CONFIG_NAME


def infer_shelf_plan(folder: Path) -> dict[str, str]:
    root = folder.resolve()
    names = " ".join([root.name, *(path.name for path in root.rglob("*") if path.is_file() and "clawshelf" not in path.parts)]).lower()
    if any(word in names for word in {"trading", "market", "portfolio", "liquidity", "quant", "finance", "factor"}):
        domain, mode = "financial/investment research", "investment research assistant"
    elif any(word in names for word in {"product", "customer", "competitor", "roadmap"}):
        domain, mode = "industrial/product research", "product secretary"
    elif any(word in names for word in {"engineering", "architecture", "benchmark", "api", "system"}):
        domain, mode = "engineering R&D", "engineering knowledge assistant"
    elif any(word in names for word in {"draft", "essay", "chapter", "writing", "outline"}):
        domain, mode = "writing/knowledge work", "writing assistant"
    else:
        domain, mode = "unknown", "research secretary"
    direction = "idea discovery" if any(word in names for word in {"idea", "signal", "alpha", "edge", "prediction"}) else "literature review"
    problem = "find new research directions" if direction == "idea discovery" else "organize and cite sources"
    count = sum(1 for path in root.rglob("*") if path.is_file() and "clawshelf" not in path.parts)
    pattern = "steadily growing shelf" if count >= 10 else "project-by-project archive" if count >= 2 else "one-time batch"
    return {"domain_background": domain, "work_direction": direction, "concrete_problem": problem, "collection_pattern": pattern, "companion_mode": mode}


def load_or_create_config(folder: Path, shelf_plan: dict[str, str] | None = None) -> ShelfConfig:
    path = config_path(folder)
    if path.exists():
        return parse_config(path.read_text(encoding="utf-8"))
    plan = shelf_plan or infer_shelf_plan(folder)
    config = ShelfConfig(shelf_plan=_validate_plan(plan))
    _atomic_write(path, config.to_dict())
    return config


def save_config(folder: Path, config: ShelfConfig) -> None:
    _atomic_write(config_path(folder), config.to_dict())


def parse_config(text: str) -> ShelfConfig:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid {CONFIG_NAME}: {exc.msg}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != CONFIG_SCHEMA:
        raise ConfigError(f"{CONFIG_NAME} must contain schema {CONFIG_SCHEMA!r}")
    policy = payload.get("notification_policy")
    if policy not in {"p1_only", "p1_p2"}:
        raise ConfigError("notification_policy must be 'p1_only' or 'p1_p2'")
    creativity = payload.get("creativity_scoring")
    if not isinstance(creativity, dict):
        raise ConfigError("creativity_scoring must be an object")
    mode = creativity.get("mode")
    if mode not in {"auto", "off", "required"}:
        raise ConfigError("creativity_scoring.mode must be 'auto', 'off', or 'required'")
    model = creativity.get("model")
    if not isinstance(model, str):
        raise ConfigError("creativity_scoring.model must be a string")
    novelty = _number(creativity.get("novelty_preference"), "creativity_scoring.novelty_preference", 0, 1)
    candidate_limit = _integer(creativity.get("candidate_limit"), "creativity_scoring.candidate_limit", 1, 100)
    semantic_retrieval = creativity.get("semantic_retrieval", "auto")
    if semantic_retrieval not in {"auto", "off", "required"}:
        raise ConfigError(
            "creativity_scoring.semantic_retrieval must be 'auto', 'off', or 'required'"
        )
    semantic_candidate_target = _integer(
        creativity.get("semantic_candidate_target", 3),
        "creativity_scoring.semantic_candidate_target",
        1,
        20,
    )
    advanced = creativity.get("advanced")
    if not isinstance(advanced, dict):
        raise ConfigError("creativity_scoring.advanced must be an object")
    threshold = _integer(advanced.get("threshold"), "creativity_scoring.advanced.threshold", -3, 20)
    confidence = _number(advanced.get("min_confidence"), "creativity_scoring.advanced.min_confidence", 0, 1)
    binding = _validate_delivery_binding(payload.get("delivery_binding"))
    return ShelfConfig(
        policy,
        CreativitySettings(
            mode,
            model,
            novelty,
            candidate_limit,
            semantic_retrieval,
            semantic_candidate_target,
            AdvancedCreativitySettings(threshold, confidence),
        ),
        _validate_plan(payload.get("shelf_plan")),
        binding,
    )


def effective_config(config: ShelfConfig, args: object | None = None) -> ShelfConfig:
    """Apply one-run CLI/environment overrides without mutating persisted settings."""
    creativity = config.creativity_scoring
    override = lambda name, env: getattr(args, name, None) if args and getattr(args, name, None) is not None else os.environ.get(env)
    policy = override("notification_policy", "CLAWSHELF_NOTIFICATION_POLICY") or config.notification_policy
    mode = override("creativity_scorer", "CLAWSHELF_CREATIVITY_SCORER") or creativity.mode
    model = override("creativity_model", "CLAWSHELF_CREATIVITY_MODEL") or creativity.model
    novelty = _coerce_number(
        override("novelty_preference", "CLAWSHELF_NOVELTY_PREFERENCE"),
        creativity.novelty_preference,
    )
    candidate = _coerce_integer(
        override("candidate_limit", "CLAWSHELF_CANDIDATE_LIMIT"),
        creativity.candidate_limit,
    )
    semantic_retrieval = (
        override("semantic_retrieval", "CLAWSHELF_SEMANTIC_RETRIEVAL")
        or creativity.semantic_retrieval
    )
    semantic_candidate_target = _coerce_integer(
        override(
            "semantic_candidate_target",
            "CLAWSHELF_SEMANTIC_CANDIDATE_TARGET",
        ),
        creativity.semantic_candidate_target,
    )
    threshold = _coerce_integer(
        override("creativity_threshold", "CLAWSHELF_CREATIVITY_THRESHOLD"),
        creativity.advanced.threshold,
    )
    confidence = _coerce_number(
        override("creativity_min_confidence", "CLAWSHELF_CREATIVITY_MIN_CONFIDENCE"),
        creativity.advanced.min_confidence,
    )
    return parse_config(
        json.dumps(
            {
                "schema": CONFIG_SCHEMA,
                "notification_policy": policy,
                "creativity_scoring": {
                    "mode": mode,
                    "model": model,
                    "novelty_preference": novelty,
                    "candidate_limit": candidate,
                    "semantic_retrieval": semantic_retrieval,
                    "semantic_candidate_target": semantic_candidate_target,
                    "advanced": {
                        "threshold": threshold,
                        "min_confidence": confidence,
                    },
                },
                "shelf_plan": config.shelf_plan,
                "delivery_binding": (
                    asdict(config.delivery_binding)
                    if config.delivery_binding
                    else None
                ),
            }
        )
    )


def _validate_delivery_binding(value: object) -> DeliveryBinding | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigError("delivery_binding must be an object or null")
    required = ("agent", "session", "channel")
    missing = [
        field
        for field in required
        if not isinstance(value.get(field), str) or not value[field].strip()
    ]
    if missing:
        raise ConfigError(
            f"delivery_binding missing non-empty string fields: {', '.join(missing)}"
        )
    optional: dict[str, str] = {}
    for field_name in ("target", "account"):
        field_value = value.get(field_name, "")
        if not isinstance(field_value, str):
            raise ConfigError(f"delivery_binding.{field_name} must be a string")
        optional[field_name] = field_value.strip()
    agent = value["agent"].strip()
    session = value["session"].strip()
    channel = value["channel"].strip().lower()
    parts = [part.strip() for part in session.split(":")]
    if len(parts) < 4 or parts[0] != "agent":
        raise ConfigError(
            "delivery_binding.session must be canonical: agent:<agent-id>:<channel>:..."
        )
    if parts[1] != agent:
        raise ConfigError(
            "delivery_binding.agent must match the agent encoded in delivery_binding.session"
        )
    if parts[2].lower() != channel:
        raise ConfigError(
            "delivery_binding.channel must match the channel encoded in delivery_binding.session"
        )
    return DeliveryBinding(
        agent=agent,
        session=session,
        channel=channel,
        target=optional["target"],
        account=optional["account"],
    )


def _validate_plan(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ConfigError("shelf_plan must be an object")
    missing = [field for field in PLAN_FIELDS if not isinstance(value.get(field), str) or not value[field].strip()]
    if missing:
        raise ConfigError(f"shelf_plan missing non-empty string fields: {', '.join(missing)}")
    return {field: value[field].strip() for field in PLAN_FIELDS}


def _number(value: object, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ConfigError(f"{name} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if not minimum <= result <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return result


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{name} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ConfigError(f"{name} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= result <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return result


def _coerce_number(value: object, default: float) -> float:
    return default if value in {None, ""} else float(value)


def _coerce_integer(value: object, default: int) -> int:
    return default if value in {None, ""} else int(value)


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)
