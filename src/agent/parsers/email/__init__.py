"""
Email Parser Module

This module contains the email parser and its supporting components.
Components are imported lazily to avoid circular dependencies.
"""

# Lazy loading to avoid circular imports and reduce initial load time
def __getattr__(name):
    if name == "EmailSemanticPatternMatcher":
        from .semantic_matcher import EmailSemanticPatternMatcher
        return EmailSemanticPatternMatcher
    elif name == "EmailLearningSystem":
        from .learning_system import EmailLearningSystem
        return EmailLearningSystem
    elif name == "EmailSearchHandlers":
        from .search_handlers import EmailSearchHandlers
        return EmailSearchHandlers
    elif name == "EmailCompositionHandlers":
        from .composition_handlers import EmailCompositionHandlers
        return EmailCompositionHandlers
    elif name == "EmailActionHandlers":
        from .action_handlers import EmailActionHandlers
        return EmailActionHandlers
    elif name == "EmailMultiStepHandlers":
        from .multi_step_handlers import EmailMultiStepHandlers
        return EmailMultiStepHandlers
    elif name == "EmailLLMGenerationHandlers":
        from .llm_generation_handlers import EmailLLMGenerationHandlers
        return EmailLLMGenerationHandlers
    elif name == "EmailConversationalHandlers":
        from .conversational_handlers import EmailConversationalHandlers
        return EmailConversationalHandlers
    elif name == "EmailUtilityHandlers":
        from .utility_handlers import EmailUtilityHandlers
        return EmailUtilityHandlers
    elif name == "EmailClassificationHandlers":
        from .classification_handlers import EmailClassificationHandlers
        return EmailClassificationHandlers
    elif name == "EmailFeedbackHandlers":
        from .feedback_handlers import EmailFeedbackHandlers
        return EmailFeedbackHandlers
    elif name == "EmailManagementHandlers":
        from .management_handlers import EmailManagementHandlers
        return EmailManagementHandlers
    elif name == "EmailQueryProcessingHandlers":
        from .query_processing_handlers import EmailQueryProcessingHandlers
        return EmailQueryProcessingHandlers
    elif name == "EmailSummarizationHandlers":
        from .summarization_handlers import EmailSummarizationHandlers
        return EmailSummarizationHandlers
    elif name == "SenderExtractor":
        from .sender_extractor import SenderExtractor
        return SenderExtractor
    elif name == "EmailActionTypes":
        from .constants import EmailActionTypes
        return EmailActionTypes
    elif name == "EmailParserConfig":
        from .constants import EmailParserConfig
        return EmailParserConfig
    elif name == "EmailEntityTypes":
        from .constants import EmailEntityTypes
        return EmailEntityTypes
    elif name == "EmailFolderTypes":
        from .constants import EmailFolderTypes
        return EmailFolderTypes
    elif name == "EmailPriorities":
        from .constants import EmailPriorities
        return EmailPriorities
    elif name == "EmailCategories":
        from .constants import EmailCategories
        return EmailCategories
    elif name == "EmailSearchPatterns":
        from .constants import EmailSearchPatterns
        return EmailSearchPatterns
    elif name == "EmailKeywordSynonyms":
        from .constants import EmailKeywordSynonyms
        return EmailKeywordSynonyms
    elif name == "EmailResponseTemplates":
        from .constants import EmailResponseTemplates
        return EmailResponseTemplates
    elif name == "get_action_validation_rules":
        from .constants import get_action_validation_rules
        return get_action_validation_rules
    
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
