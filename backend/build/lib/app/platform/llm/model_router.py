from enum import StrEnum
from app.core.config import Settings
class ModelTier(StrEnum): SMALL='small'; MEDIUM='medium'; LARGE='large'; VERIFY='verify'; EMBED='embed'
class ModelRouter:
    def __init__(self,settings:Settings): self.settings=settings
    def model_for(self,tier:ModelTier|str)->str:
        tier=ModelTier(tier); return {ModelTier.SMALL:self.settings.ollama_model_small,ModelTier.MEDIUM:self.settings.ollama_model_medium,ModelTier.LARGE:self.settings.ollama_model_large,ModelTier.VERIFY:self.settings.ollama_model_verify,ModelTier.EMBED:self.settings.ollama_model_embed}[tier]
