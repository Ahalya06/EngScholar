import os
import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime

# ========== PostgreSQL Configuration ==========
# Get PostgreSQL URL from Vercel environment variables
DATABASE_URL = os.environ.get('POSTGRES_URL')

# If no POSTGRES_URL, use local SQLite for development
if not DATABASE_URL:
    DATABASE_URL = 'sqlite:///engscholar.db'
    print("⚠️ Using SQLite (development mode)")
else:
    # Vercel uses postgres://, SQLAlchemy needs postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    print("✅ Using PostgreSQL")

# Create engine with PostgreSQL settings
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_timeout=30
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ========== Redis Configuration ==========
redis_client = None
try:
    REDIS_URL = os.environ.get('REDIS_URL') or os.environ.get('KV_REST_API_URL')
    if REDIS_URL:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        print("✅ Redis connected")
    else:
        print("⚠️ Redis not configured")
except Exception as e:
    print(f"⚠️ Redis connection failed: {e}")

# ========== User Model ==========
class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<User {self.email}>"