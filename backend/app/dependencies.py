"""Things endpoints ask FastAPI to hand them. Tests swap these for temporary versions."""

from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import utcnow


def get_data_dir() -> Path:
    return settings.data_dir


def get_now() -> datetime:
    return utcnow()


SessionDep = Annotated[Session, Depends(get_session)]
DataDirDep = Annotated[Path, Depends(get_data_dir)]
NowDep = Annotated[datetime, Depends(get_now)]
