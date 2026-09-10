from pydantic import BaseModel
from typing import Optional

class OrganisationRules(BaseModel):
    """Configuration for organisation plans."""
    strategy: str                                         
    primary_grouping: str                                                                                      
    secondary_grouping: Optional[str] = None
    custom_parameter: Optional[str] = None                                                 
    max_depth: int = 2
    preserve_existing: bool = True
    rename_files: bool = False
    group_versions: bool = True
    keep_related_together: bool = True
    min_confidence: float = 0.6
    low_confidence_action: str = 'leave'
