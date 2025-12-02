"""
Celery Tasks for Data Export

Background tasks for generating user data exports asynchronously.
Uses the existing Celery infrastructure with dedicated export queue.
"""

from celery import Task
from typing import Dict, Any
import logging
import asyncio
import os
from datetime import datetime, timedelta

from src.workers.celery_app import celery_app
from src.workers.base_task import BaseTask
from src.features.data_export import DataExportService
from src.utils import PerformanceContext
from src.database import get_db_context
from src.utils.config import load_config

logger = logging.getLogger(__name__)


@celery_app.task(
    base=BaseTask,
    name="export.generate_user_export",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    queue="default",  # Use default queue for exports
    time_limit=600,  # 10 minute timeout for large exports
)
def generate_user_export_task(
    self: Task,
    user_id: int,
    format: str = "zip",
    include_vectors: bool = False,
    include_email_content: bool = True
) -> Dict[str, Any]:
    """
    Generate a complete data export for a user (async)
    
    This task runs in the background and can handle large exports without
    blocking the API.
    
    Args:
        user_id: User ID to generate export for
        format: Export format ('json', 'csv', or 'zip')
        include_vectors: Include vector embeddings (WARNING: very large!)
        include_email_content: Include full email content
    
    Returns:
        Dictionary with export data or file path
    """
    with PerformanceContext(f"generate_export_user_{user_id}"):
        logger.info(
            f"[Task {self.request.id}] Generating {format} export for user {user_id} "
            f"(vectors={include_vectors}, email_content={include_email_content})"
        )
        
        try:
            with get_db_context() as db:
                service = DataExportService(db)
                
                # Generate export (run async function in sync context)
                export_data = asyncio.run(service.export_user_data(
                    user_id=user_id,
                    format=format,
                    include_emails=include_email_content,
                    include_settings=True
                ))
                
                logger.info(
                    f"[Task {self.request.id}] Successfully generated export for user {user_id}"
                )
                
                return {
                    "status": "success",
                    "user_id": user_id,
                    "format": format,
                    "generated_at": datetime.utcnow().isoformat(),
                    "data": export_data
                }
                
        except Exception as e:
            logger.error(
                f"[Task {self.request.id}] Failed to generate export for user {user_id}: {e}",
                exc_info=True
            )
            
            # Retry with exponential backoff
            if self.request.retries < self.max_retries:
                logger.info(f"[Task {self.request.id}] Retrying... (attempt {self.request.retries + 1})")
                raise self.retry(exc=e)
            
            # Final failure
            return {
                "status": "error",
                "user_id": user_id,
                "error": str(e),
                "generated_at": datetime.utcnow().isoformat()
            }


@celery_app.task(
    base=BaseTask,
    name="export.cleanup_expired_exports",
    bind=True,
    queue="default"
)
def cleanup_expired_exports_task(self: Task, max_age_hours: int = 24) -> Dict[str, Any]:
    """
    Clean up old export files (periodic task)
    
    This task should run periodically (e.g., daily) to remove old export files
    that users haven't downloaded.
    
    Args:
        max_age_hours: Maximum age of export files to keep (default: 24 hours)
    
    Returns:
        Cleanup statistics
    """
    with PerformanceContext("cleanup_expired_exports"):
        logger.info(f"[Task {self.request.id}] Cleaning up exports older than {max_age_hours} hours")
        
        try:
            import shutil
            from pathlib import Path
            
            # Determine export storage directory
            export_dir = Path("data/exports")  # Default local filesystem storage
            
            # Check if using S3 storage
            use_s3 = os.getenv("EXPORT_STORAGE_BACKEND", "local").lower() == "s3"
            
            cleaned_count = 0
            cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
            
            if use_s3:
                # S3 cleanup logic
                s3_bucket = os.getenv("EXPORT_S3_BUCKET")
                s3_prefix = os.getenv("EXPORT_S3_PREFIX", "exports/")
                
                if not s3_bucket:
                    logger.warning("S3 bucket not configured, skipping S3 cleanup")
                else:
                    try:
                        import boto3
                        from botocore.exceptions import ClientError
                        
                        s3_client = boto3.client('s3')
                        
                        # List objects in the exports prefix
                        paginator = s3_client.get_paginator('list_objects_v2')
                        pages = paginator.paginate(Bucket=s3_bucket, Prefix=s3_prefix)
                        
                        for page in pages:
                            for obj in page.get('Contents', []):
                                # Check if object is older than cutoff
                                if obj['LastModified'].replace(tzinfo=None) < cutoff_time:
                                    try:
                                        s3_client.delete_object(Bucket=s3_bucket, Key=obj['Key'])
                                        cleaned_count += 1
                                        logger.debug(f"Deleted S3 object: {obj['Key']}")
                                    except ClientError as e:
                                        logger.error(f"Failed to delete S3 object {obj['Key']}: {e}")
                        
                        logger.info(f"[S3] Cleaned up {cleaned_count} expired exports from S3")
                    except Exception as e:
                        logger.error(f"S3 cleanup failed: {e}")
            else:
                # Local filesystem cleanup
                if export_dir.exists():
                    for file_path in export_dir.glob("*.zip"):
                        try:
                            # Check file modification time
                            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                            
                            if mtime < cutoff_time:
                                file_path.unlink()
                                cleaned_count += 1
                                logger.debug(f"Deleted local export: {file_path.name}")
                        except Exception as e:
                            logger.error(f"Failed to delete {file_path}: {e}")
                    
                    logger.info(f"[LOCAL] Cleaned up {cleaned_count} expired exports from filesystem")
                else:
                    logger.info(f"Export directory {export_dir} does not exist, nothing to clean")
            
            logger.info(f"[Task {self.request.id}] Cleaned up {cleaned_count} expired exports")
            
            return {
                "status": "success",
                "cleaned_count": cleaned_count,
                "max_age_hours": max_age_hours,
                "storage_backend": "s3" if use_s3 else "local",
                "cleaned_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(
                f"[Task {self.request.id}] Failed to cleanup exports: {e}",
                exc_info=True
            )
            return {
                "status": "error",
                "error": str(e),
                "cleaned_at": datetime.utcnow().isoformat()
            }


@celery_app.task(
    base=BaseTask,
    name="export.generate_scheduled_export",
    bind=True,
    queue="default"
)
def generate_scheduled_export_task(
    self: Task,
    user_id: int,
    schedule_type: str = "monthly"
) -> Dict[str, Any]:
    """
    Generate a scheduled automatic export for a user
    
    Some users may want automatic monthly/quarterly exports for backup purposes.
    
    Args:
        user_id: User ID to generate export for
        schedule_type: Type of schedule ('weekly', 'monthly', 'quarterly')
    
    Returns:
        Export generation result
    """
    with PerformanceContext(f"scheduled_export_user_{user_id}"):
        logger.info(
            f"[Task {self.request.id}] Generating {schedule_type} scheduled export for user {user_id}"
        )
        
        try:
            # Use the main export task
            result = generate_user_export_task.apply(
                kwargs={
                    "user_id": user_id,
                    "format": "zip",
                    "include_vectors": False,
                    "include_email_content": True
                }
            )
            
            logger.info(
                f"[Task {self.request.id}] Scheduled export completed for user {user_id}"
            )
            
            return {
                "status": "success",
                "user_id": user_id,
                "schedule_type": schedule_type,
                "export_result": result.get(),
                "generated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(
                f"[Task {self.request.id}] Scheduled export failed for user {user_id}: {e}",
                exc_info=True
            )
            return {
                "status": "error",
                "user_id": user_id,
                "schedule_type": schedule_type,
                "error": str(e),
                "generated_at": datetime.utcnow().isoformat()
            }


def cleanup_old_exports(
    export_dir: str,
    max_age_days: int = 7,
    storage_backend: str = "local"
) -> int:
    """
    Clean up export files older than max_age_days
    
    This function supports both local filesystem and S3 storage backends
    to automatically remove old export files and prevent disk space issues.
    
    Args:
        export_dir: Directory or S3 prefix containing exports
        max_age_days: Maximum age in days before deletion (default: 7)
        storage_backend: Storage backend to use ('local' or 's3')
    
    Returns:
        Number of files deleted
        
    Example:
        # Clean up local exports older than 7 days
        deleted = cleanup_old_exports('/tmp/exports', max_age_days=7, storage_backend='local')
        
        # Clean up S3 exports older than 30 days
        deleted = cleanup_old_exports('exports/user_123', max_age_days=30, storage_backend='s3')
    """
    from pathlib import Path
    
    cutoff_time = datetime.now() - timedelta(days=max_age_days)
    deleted_count = 0
    
    try:
        if storage_backend == "local":
            # Local filesystem cleanup
            export_path = Path(export_dir)
            if not export_path.exists():
                logger.warning(f"Export directory does not exist: {export_dir}")
                return 0
            
            for file_path in export_path.glob("*"):
                if file_path.is_file():
                    try:
                        file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                        if file_mtime < cutoff_time:
                            file_path.unlink()
                            deleted_count += 1
                            logger.info(f"Deleted old export file: {file_path.name}")
                    except Exception as e:
                        logger.error(f"Failed to delete {file_path}: {e}")
        
        elif storage_backend == "s3":
            # S3 cleanup logic
            try:
                import boto3
                from botocore.exceptions import ClientError
                
                s3_client = boto3.client('s3')
                bucket = os.getenv('EXPORT_BUCKET', 'clavr-exports')
                prefix = export_dir if export_dir.endswith('/') else f"{export_dir}/"
                
                # List objects in the prefix
                paginator = s3_client.get_paginator('list_objects_v2')
                pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
                
                for page in pages:
                    for obj in page.get('Contents', []):
                        try:
                            # S3 LastModified is timezone-aware, make cutoff_time aware too
                            obj_modified = obj['LastModified'].replace(tzinfo=None)
                            if obj_modified < cutoff_time:
                                s3_client.delete_object(Bucket=bucket, Key=obj['Key'])
                                deleted_count += 1
                                logger.info(f"Deleted old S3 export: {obj['Key']}")
                        except Exception as e:
                            logger.error(f"Failed to delete S3 object {obj.get('Key')}: {e}")
                            
            except ImportError:
                logger.error("boto3 not installed, cannot clean up S3 exports")
            except ClientError as e:
                logger.error(f"S3 client error during cleanup: {e}")
        else:
            logger.error(f"Unknown storage backend: {storage_backend}")
    
    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
    
    if deleted_count > 0:
        logger.info(f"Cleanup complete: deleted {deleted_count} old export file(s)")
    
    return deleted_count