# /// script
# dependencies = [
#   "pydantic==2.12.5"
# ]
# ///

from pydantic import BaseModel, EmailStr
from typing import Optional

class Candidate(BaseModel):
    """
    Pydantic model for representing a political candidate.
    
    Required fields:
    - name: The candidate's full name
    - party: The political party the candidate belongs to
    
    Optional fields:
    - email: The candidate's email address (validated as email format)
    - storkreds: The electoral district
    - additional_info: Any additional information about the candidate
    """
    name: str
    party: str
    email: Optional[EmailStr] = None
    storkreds: Optional[str] = None
    additional_info: Optional[str] = None

    class Config:
        from_attributes = True  # Allow creating from dictionaries
        json_schema_extra = {
            "examples": [
                {
                    "name": "John Doe",
                    "party": "SF",
                    "email": "john.doe@example.com",
                    "storkreds": "København",
                    "additional_info": "Additional information about the candidate"
                }
            ]
        }