from pydantic import BaseModel
from typing import List

class MergeJob(BaseModel):
    name: str
    target_id: str
    source_ids: List[str]
    description: str = ""
