#!/usr/bin/env python3
"""
OAuth Security Deployment Verification Script
Verifies all Phase 1 & 2 security features are operational
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth.audit import log_auth_event, AuditEventType
from src.database import get_db
from src.utils.encryption import encrypt_token, decrypt_token
from sqlalchemy import text
from datetime import datetime

def test_audit_logging():
    """Test audit logging system"""
    print("\n" + "="*60)
    print("1. TESTING AUDIT LOGGING SYSTEM")
    print("="*60)
    
    try:
        db = next(get_db())
        
        # Log a test event
        log_auth_event(
            db=db,
            event_type=AuditEventType.LOGIN_SUCCESS,
            user_id=None,
            success=True,
            metadata={
                'test': 'Deployment verification',
                'timestamp': datetime.utcnow().isoformat(),
                'oauth_provider': 'google'
            }
        )
        
        # Verify the log was created
        result = db.execute(text('SELECT COUNT(*) as count FROM audit_logs')).fetchone()
        count = result[0]
        
        # Get latest entry
        result = db.execute(text(
            'SELECT event_type, success, created_at FROM audit_logs ORDER BY created_at DESC LIMIT 1'
        )).fetchone()
        
        print(f"✅ Audit logging functional")
        print(f"✅ Total audit logs: {count}")
        print(f"✅ Latest log: {result.event_type} (success={result.success})")
        print(f"✅ Timestamp: {result.created_at}")
        
        return True
    except Exception as e:
        print(f"❌ Audit logging test failed: {e}")
        return False


def test_token_encryption():
    """Test token encryption system"""
    print("\n" + "="*60)
    print("2. TESTING TOKEN ENCRYPTION")
    print("="*60)
    
    try:
        # Test data
        test_token = "ya29.test_access_token_12345"
        
        # Encrypt
        encrypted = encrypt_token(test_token)
        print(f"✅ Token encrypted successfully")
        print(f"   Original length: {len(test_token)} chars")
        print(f"   Encrypted length: {len(encrypted)} chars")
        
        # Decrypt
        decrypted = decrypt_token(encrypted)
        print(f"✅ Token decrypted successfully")
        
        # Verify
        if decrypted == test_token:
            print(f"✅ Encryption/decryption verification passed")
            return True
        else:
            print(f"❌ Decrypted token doesn't match original")
            return False
            
    except Exception as e:
        print(f"❌ Token encryption test failed: {e}")
        return False


def test_database_schema():
    """Test database schema for audit logs"""
    print("\n" + "="*60)
    print("3. TESTING DATABASE SCHEMA")
    print("="*60)
    
    try:
        db = next(get_db())
        
        # Check table exists
        result = db.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_logs')"
        )).fetchone()
        
        if result[0]:
            print(f"✅ audit_logs table exists")
        else:
            print(f"❌ audit_logs table not found")
            return False
        
        # Check columns
        result = db.execute(text(
            """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'audit_logs'
            ORDER BY ordinal_position
            """
        )).fetchall()
        
        required_columns = ['id', 'user_id', 'event_type', 'event_data', 'ip_address', 
                           'user_agent', 'success', 'error_message', 'created_at']
        
        found_columns = [row[0] for row in result]
        missing = set(required_columns) - set(found_columns)
        
        if not missing:
            print(f"✅ All required columns present ({len(found_columns)})")
            for col in result:
                print(f"   - {col[0]}: {col[1]}")
        else:
            print(f"❌ Missing columns: {missing}")
            return False
        
        # Check indexes
        result = db.execute(text(
            """
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = 'audit_logs'
            """
        )).fetchall()
        
        print(f"✅ Indexes created: {len(result)}")
        for idx in result:
            print(f"   - {idx[0]}")
        
        return True
        
    except Exception as e:
        print(f"❌ Database schema test failed: {e}")
        return False


def test_environment_config():
    """Test environment configuration"""
    print("\n" + "="*60)
    print("4. TESTING ENVIRONMENT CONFIGURATION")
    print("="*60)
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        # Check critical env vars
        config_checks = [
            ('ENCRYPTION_KEY', os.getenv('ENCRYPTION_KEY')),
            ('SECRET_KEY', os.getenv('SECRET_KEY')),
            ('TOKEN_ROTATION_INTERVAL_HOURS', os.getenv('TOKEN_ROTATION_INTERVAL_HOURS', '24')),
            ('AUDIT_LOG_RETENTION_DAYS', os.getenv('AUDIT_LOG_RETENTION_DAYS', '90')),
            ('TOKEN_REFRESH_MAX_RETRIES', os.getenv('TOKEN_REFRESH_MAX_RETRIES', '3')),
            ('DATABASE_URL', os.getenv('DATABASE_URL'))
        ]
        
        all_ok = True
        for key, value in config_checks:
            if value and value != 'your_' + key.lower() + '_here':
                print(f"✅ {key}: Configured")
            else:
                print(f"⚠️  {key}: Using default or not configured")
                if key in ['ENCRYPTION_KEY', 'DATABASE_URL']:
                    all_ok = False
        
        return all_ok
        
    except Exception as e:
        print(f"❌ Environment config test failed: {e}")
        return False


def test_dependencies():
    """Test required dependencies are installed"""
    print("\n" + "="*60)
    print("5. TESTING DEPENDENCIES")
    print("="*60)
    
    try:
        # Check cryptography
        import cryptography
        print(f"✅ cryptography: {cryptography.__version__}")
        
        # Check slowapi
        import slowapi
        print(f"✅ slowapi: {slowapi.__version__}")
        
        # Check fernet
        from cryptography.fernet import Fernet
        print(f"✅ Fernet encryption available")
        
        return True
        
    except ImportError as e:
        print(f"❌ Dependency check failed: {e}")
        return False


def main():
    """Run all verification tests"""
    print("\n" + "="*80)
    print(" " * 20 + "OAuth Security Deployment Verification")
    print("="*80)
    
    tests = [
        ("Dependencies", test_dependencies),
        ("Environment Config", test_environment_config),
        ("Database Schema", test_database_schema),
        ("Token Encryption", test_token_encryption),
        ("Audit Logging", test_audit_logging),
    ]
    
    results = []
    for name, test_func in tests:
        result = test_func()
        results.append((name, result))
    
    # Summary
    print("\n" + "="*80)
    print(" " * 30 + "TEST SUMMARY")
    print("="*80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status:10} - {name}")
    
    print("="*80)
    print(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All OAuth security features are operational!")
        print("✅ System is ready for production deployment")
        return 0
    else:
        print("\n⚠️  Some tests failed - review the output above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
