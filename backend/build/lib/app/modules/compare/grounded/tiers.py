"""Model tiers. Tiers change interpretation quality, never the evidence rules."""

from dataclasses import asdict, dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class TierConfig:
    tier: str
    text_model: str
    vision_model: str
    embed_model: str
    alt_model: str | None
    seed: int
    num_ctx: int
    think: bool
    final_evidence_authority: bool
    capability_note: str
    limitation_note: str

    def as_dict(self) -> dict:
        return asdict(self)


TIER_NOTES = {
    "weak": (
        "Weak-laptop fallback (4B models): produces summaries and candidate findings only.",
        "Not a final evidence authority: expect more abstention and more 'Insufficient evidence' results.",
    ),
    "student": (
        "Student-laptop default (8B models): typed extraction, source-limited validation and candidate comparison.",
        "Interpretive findings remain candidates until the faculty-reviewed evaluation thresholds are met.",
    ),
    "deep": (
        "University deep-review tier (30B/32B thinking models): stronger interpretation of methods, tables and figures.",
        "Improves interpretation only; the same evidence rules, suppression and evaluation gates apply.",
    ),
}


def tier_config(settings: Settings, tier: str | None = None) -> TierConfig:
    name = tier or settings.grounded_tier
    if name == "weak":
        text, vision, alt = settings.grounded_weak_text_model, settings.grounded_weak_vision_model, None
    elif name == "deep":
        text, vision, alt = settings.grounded_deep_text_model, settings.grounded_deep_vision_model, settings.grounded_deep_alt_model
    elif name == "student":
        text, vision, alt = settings.grounded_text_model, settings.grounded_vision_model, None
    else:
        raise ValueError(f"unknown grounded tier: {name}")
    capability, limitation = TIER_NOTES[name]
    return TierConfig(
        tier=name,
        text_model=text,
        vision_model=vision,
        embed_model=settings.grounded_embed_model,
        alt_model=alt,
        seed=settings.grounded_seed,
        num_ctx=settings.grounded_num_ctx,
        # Thinking models reason internally; smaller tiers answer directly for latency.
        think=name == "deep",
        final_evidence_authority=name != "weak",
        capability_note=capability,
        limitation_note=limitation,
    )


def all_tiers(settings: Settings) -> list[dict]:
    return [tier_config(settings, name).as_dict() for name in ("weak", "student", "deep")]
