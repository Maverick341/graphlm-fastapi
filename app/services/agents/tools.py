from agents import RunContextWrapper, function_tool
from dataclasses import dataclass

@dataclass
class AgentPromptContext:
    collection_names: list[str]
    source_ids: list[str]
    user_id: str
    chat_id: str

# ====usage in tools====
# @function_tool
# async def fetch_user_age(wrapper: RunContextWrapper[AgentPromptContext]) -> str:  
#     """Fetch the age of the user. Call this function to get user's age information."""
    
#     return f"The user {wrapper.context.name} is 47 years old"
