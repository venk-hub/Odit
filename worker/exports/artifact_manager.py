"""
Manages artifact registration in the database and file paths.
"""
import os
import logging
from datetime import datetime
from sqlalchemy.orm import Session

logger = logging.getLogger("odit.worker.artifact_manager")


def register_artifact(
    db: Session,
    audit_run_id,
    artifact_type: str,
    file_path: str,
) -> None:
    """Register an artifact in the database."""
    from app.models import Artifact

    file_size = None
    if os.path.exists(file_path):
        file_size = os.path.getsize(file_path)

    artifact = Artifact(
        audit_run_id=audit_run_id,
        artifact_type=artifact_type,
        file_path=file_path,
        file_size_bytes=file_size,
        created_at=datetime.utcnow(),
    )
    db.add(artifact)
    db.commit()
    logger.info(f"Registered artifact: {artifact_type} -> {file_path} ({file_size} bytes)")


def get_artifact_dir(data_dir: str, audit_id: str) -> str:
    path = os.path.join(data_dir, "audits", str(audit_id), "reports")
    os.makedirs(path, exist_ok=True)
    return path
