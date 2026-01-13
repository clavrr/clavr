#!/usr/bin/env python3
"""
Test Data Export Functionality

Quick script to verify GDPR data export implementation works correctly.
"""

import sys
import os
from pathlib import Path
import json
import zipfile
import io
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.features.data_export import DataExportService
from src.database import get_db_context
from src.database.models import User, UserSettings, Session as SessionModel, ConversationMessage
from src.utils.config import load_config
from sqlalchemy.orm import Session


def print_header(text: str):
    """Print section header"""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_success(text: str):
    """Print success message"""
    print(f"✅ {text}")


def print_error(text: str):
    """Print error message"""
    print(f"❌ {text}")


def print_info(text: str):
    """Print info message"""
    print(f"ℹ️  {text}")


def test_export_metadata():
    """Test 1: Export metadata generation"""
    print_header("Test 1: Export Metadata Generation")
    
    try:
        with get_db_context() as db:
            # Get first user
            user = db.query(User).first()
            if not user:
                print_error("No users found in database")
                return False
            
            config = load_config()
            service = DataExportService(db, config)
            
            metadata = service._get_export_metadata(user)
            
            # Verify metadata
            assert "export_date" in metadata
            assert "user_id" in metadata
            assert "user_email" in metadata
            assert metadata["data_controller"] == "Notely Agent"
            assert "GDPR" in metadata["gdpr_compliance"]
            
            print_success("Export metadata generated correctly")
            print_info(f"User: {metadata['user_email']}")
            print_info(f"Export date: {metadata['export_date']}")
            print_info(f"GDPR compliance: {metadata['gdpr_compliance']}")
            
            return True
            
    except Exception as e:
        print_error(f"Failed to generate export metadata: {e}")
        return False


async def test_json_export():
    """Test 2: JSON export format"""
    print_header("Test 2: JSON Export Format")
    
    try:
        with get_db_context() as db:
            user = db.query(User).first()
            if not user:
                print_error("No users found in database")
                return False
            
            config = load_config()
            service = DataExportService(db, config)
            
            # Generate JSON export
            export_data = await service.export_user_data(
                user_id=user.id,
                format="json",
                include_vectors=False,
                include_email_content=False  # Skip for speed
            )
            
            # Verify structure
            assert isinstance(export_data, dict)
            assert "export_metadata" in export_data
            assert "user_profile" in export_data
            assert "user_settings" in export_data
            assert "sessions" in export_data
            assert "conversation_history" in export_data
            
            # Verify user profile
            profile = export_data["user_profile"]
            assert profile["user_id"] == user.id
            assert profile["email"] == user.email
            
            print_success("JSON export generated successfully")
            print_info(f"Data categories: {len(export_data.keys())}")
            print_info(f"User ID: {profile['user_id']}")
            print_info(f"Email: {profile['email']}")
            
            # Verify JSON serializable
            json_str = json.dumps(export_data, default=str)
            print_success(f"Export is JSON serializable ({len(json_str):,} bytes)")
            
            return True
            
    except Exception as e:
        print_error(f"Failed to generate JSON export: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_csv_export():
    """Test 3: CSV export format"""
    print_header("Test 3: CSV Export Format")
    
    try:
        with get_db_context() as db:
            user = db.query(User).first()
            if not user:
                print_error("No users found in database")
                return False
            
            config = load_config()
            service = DataExportService(db, config)
            
            # Generate CSV export
            csv_files = await service.export_user_data(
                user_id=user.id,
                format="csv",
                include_vectors=False,
                include_email_content=False
            )
            
            # Verify structure
            assert isinstance(csv_files, dict)
            
            print_success("CSV export generated successfully")
            print_info(f"Number of CSV files: {len(csv_files)}")
            
            for filename, content in csv_files.items():
                if content:
                    lines = content.count('\n')
                    print_info(f"  - {filename}: {lines} lines, {len(content):,} bytes")
            
            return True
            
    except Exception as e:
        print_error(f"Failed to generate CSV export: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_zip_export():
    """Test 4: ZIP archive export"""
    print_header("Test 4: ZIP Archive Export")
    
    try:
        with get_db_context() as db:
            user = db.query(User).first()
            if not user:
                print_error("No users found in database")
                return False
            
            config = load_config()
            service = DataExportService(db, config)
            
            # Generate ZIP export
            zip_bytes = await service.export_user_data(
                user_id=user.id,
                format="zip",
                include_vectors=False,
                include_email_content=False
            )
            
            # Verify it's bytes
            assert isinstance(zip_bytes, bytes)
            assert len(zip_bytes) > 0
            
            # Verify it's a valid ZIP
            zip_buffer = io.BytesIO(zip_bytes)
            with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
                files = zip_file.namelist()
                
                # Verify required files
                assert "complete_export.json" in files
                assert "README.txt" in files
                
                print_success("ZIP archive generated successfully")
                print_info(f"ZIP size: {len(zip_bytes):,} bytes")
                print_info(f"Files in archive: {len(files)}")
                
                for filename in files:
                    file_info = zip_file.getinfo(filename)
                    print_info(f"  - {filename}: {file_info.file_size:,} bytes")
                
                # Verify JSON content
                json_content = zip_file.read("complete_export.json")
                data = json.loads(json_content)
                assert "user_profile" in data
                
                print_success("ZIP contents verified")
            
            return True
            
    except Exception as e:
        print_error(f"Failed to generate ZIP export: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_security():
    """Test 5: Security - Token exclusion"""
    print_header("Test 5: Security - Token Exclusion")
    
    try:
        with get_db_context() as db:
            user = db.query(User).first()
            if not user:
                print_error("No users found in database")
                return False
            
            config = load_config()
            service = DataExportService(db, config)
            
            # Generate export
            export_data = await service.export_user_data(
                user_id=user.id,
                format="json",
                include_vectors=False
            )
            
            # Check sessions for sensitive data
            sessions = export_data.get("sessions", [])
            
            for session in sessions:
                # Verify sensitive tokens are NOT included
                assert "session_token" not in session, "Session token found in export!"
                assert "gmail_access_token" not in session, "Gmail access token found!"
                assert "gmail_refresh_token" not in session, "Gmail refresh token found!"
                
                # Verify metadata IS included
                assert "session_id" in session
                assert "created_at" in session or "expires_at" in session
            
            print_success("Sensitive tokens correctly excluded from export")
            print_info(f"Verified {len(sessions)} sessions")
            print_info("✓ Session tokens excluded")
            print_info("✓ Gmail access tokens excluded")
            print_info("✓ Gmail refresh tokens excluded")
            print_info("✓ Session metadata included")
            
            return True
            
    except AssertionError as e:
        print_error(f"Security check failed: {e}")
        return False
    except Exception as e:
        print_error(f"Security test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_gdpr_compliance():
    """Test 6: GDPR compliance verification"""
    print_header("Test 6: GDPR Compliance Verification")
    
    try:
        with get_db_context() as db:
            user = db.query(User).first()
            if not user:
                print_error("No users found in database")
                return False
            
            config = load_config()
            service = DataExportService(db, config)
            
            # Generate export
            export_data = await service.export_user_data(
                user_id=user.id,
                format="json",
                include_vectors=False
            )
            
            # GDPR Article 20 requirements
            required_categories = [
                "export_metadata",
                "user_profile",
                "user_settings",
                "sessions",
                "conversation_history",
                "emails",
                "calendar_events",
                "tasks"
            ]
            
            print_info("Checking GDPR Article 20 requirements...")
            
            # 1. Check all data categories present
            for category in required_categories:
                assert category in export_data, f"Missing category: {category}"
                print_success(f"✓ {category} included")
            
            # 2. Check metadata includes GDPR info
            metadata = export_data["export_metadata"]
            assert "gdpr_compliance" in metadata
            assert "Article 20" in metadata["gdpr_compliance"]
            print_success("✓ GDPR metadata included")
            
            # 3. Verify machine-readable (JSON)
            json_str = json.dumps(export_data, default=str)
            assert len(json_str) > 0
            print_success("✓ Machine-readable format (JSON)")
            
            # 4. Verify structured format
            assert isinstance(export_data, dict)
            print_success("✓ Structured format")
            
            print_success("All GDPR Article 20 requirements met! ✅")
            
            return True
            
    except AssertionError as e:
        print_error(f"GDPR compliance check failed: {e}")
        return False
    except Exception as e:
        print_error(f"GDPR test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("  GDPR DATA EXPORT - FUNCTIONALITY TEST")
    print("  Testing comprehensive data export implementation")
    print("=" * 70)
    
    results = {
        "Export Metadata": test_export_metadata(),
        "JSON Export": await test_json_export(),
        "CSV Export": await test_csv_export(),
        "ZIP Export": await test_zip_export(),
        "Security": await test_security(),
        "GDPR Compliance": await test_gdpr_compliance(),
    }
    
    # Summary
    print_header("Test Summary")
    
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name:.<50} {status}")
    
    print("\n" + "-" * 70)
    print(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        print_success("All tests passed! Data export is working correctly. 🎉")
        return 0
    else:
        print_error(f"{total - passed} test(s) failed. Please review errors above.")
        return 1


if __name__ == "__main__":
    import asyncio
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
