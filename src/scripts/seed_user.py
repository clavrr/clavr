import argparse
import os
import uuid
from datetime import datetime, timedelta


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a development user into the database")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--google-id", default=None)
    parser.add_argument("--admin", action="store_true")
    parser.add_argument("--create-session", action="store_true", default=True)
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except ImportError:
        pass

    if not (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")):
        raise SystemExit("DATABASE_URL/POSTGRES_URL not set")

    from src.database import get_db_context
    from src.database.models import Session as DBSession, User
    from src.utils.security import generate_session_token

    email = args.email.strip().lower()
    name = args.name or email.split("@")[0]
    google_id = args.google_id or f"dev_{uuid.uuid4().hex}"

    with get_db_context() as db:
        user = db.query(User).filter(User.email == email).first()
        created_user = False
        if not user:
            user = User(
                email=email,
                name=name,
                google_id=google_id,
                created_at=datetime.utcnow(),
                indexing_status="not_started",
                email_indexed=False,
            )
            user.is_admin = bool(args.admin)
            db.add(user)
            db.commit()
            db.refresh(user)
            created_user = True
        else:
            # Ensure required fields are set (fresh DBs / old rows)
            changed = False
            if not user.google_id:
                user.google_id = google_id
                changed = True
            if args.name and user.name != args.name:
                user.name = args.name
                changed = True
            if args.admin and not user.is_admin:
                user.is_admin = True
                changed = True
            if changed:
                db.commit()
                db.refresh(user)

        raw_token = None
        if args.create_session:
            raw_token, hashed_token = generate_session_token()
            sess = DBSession(
                user_id=user.id,
                session_token=hashed_token,
                gmail_access_token="",
                gmail_refresh_token=None,
                granted_scopes=None,
                token_expiry=None,
                last_active_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(days=7),
            )
            db.add(sess)
            db.commit()
            db.refresh(sess)

    print("[OK] User seeded")
    print(f"  email: {email}")
    print(f"  user_id: {user.id}")
    print(f"  created: {created_user}")
    if raw_token:
        print("[OK] Session created")
        print("  Use this as a Bearer token (frontend localStorage session_token):")
        print(f"  {raw_token}")


if __name__ == "__main__":
    main()
