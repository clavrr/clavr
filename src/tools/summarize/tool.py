"""
Summarize Tool - Content summarization capabilities
"""
import asyncio
from typing import Optional
from langchain.tools import BaseTool
from pydantic import Field

from ...utils.logger import setup_logger
from ...utils.config import Config

logger = setup_logger(__name__)


class SummarizeTool(BaseTool):
    """Summarization tool"""
    name: str = "summarize"
    description: str = "Summarize content (emails, documents, conversations). Use this for summarization requests."
    
    config: Optional[Config] = Field(default=None)
    
    def __init__(self, config: Optional[Config] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config
    
    def _run(self, content: str = "", **kwargs) -> str:
        """Execute summarization"""
        try:
            from ...agent.roles.synthesizer_role import SynthesizerRole
            
            synthesizer = SynthesizerRole(config=self.config)
            result = synthesizer.summarize(content)
            return result
        except Exception as e:
            logger.error(f"SummarizeTool error: {e}")
            return f"Error: {str(e)}"
    
    async def _arun(self, content: str = "", **kwargs) -> str:
        """Async execution - runs blocking _run in thread pool to avoid blocking event loop"""
        return await asyncio.to_thread(self._run, content=content, **kwargs)
