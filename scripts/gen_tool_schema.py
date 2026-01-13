import json
from src.tools.brief.tool import BriefTool
from src.ai.voice.tool_converter import convert_to_elevenlabs_tools
from src.utils.config import Config

def generate_schema():
    config = Config()
    tool = BriefTool(config=config)
    eleven_tools = convert_to_elevenlabs_tools([tool])
    print(json.dumps(eleven_tools[0], indent=2))

if __name__ == "__main__":
    generate_schema()
