class ResearchAssistantError(Exception): pass
class ConfigurationError(ResearchAssistantError): pass
class ExternalServiceUnavailable(ResearchAssistantError): pass
class LLMUnavailableError(ExternalServiceUnavailable): pass
class VectorStoreUnavailableError(ExternalServiceUnavailable): pass
class VerdictParseError(ResearchAssistantError): pass
class DraftParseError(ResearchAssistantError): pass
