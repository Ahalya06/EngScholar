from flask import Flask, flash, redirect, render_template, request, url_for, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from config import engine, SessionLocal, Base, redis_client, User
from sqlalchemy import text
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-please-change-in-production')

# ========== Initialize Database ==========
def init_db():
    """Create all database tables"""
    try:
        Base.metadata.create_all(bind=engine)
        print("✅ Database tables created/verified")
        return True
    except Exception as e:
        print(f"⚠️ Database initialization error: {e}")
        return False

# Run initialization on first request
@app.before_request
def before_request():
    if not hasattr(app, 'db_initialized'):
        app.db_initialized = init_db()

# ========== Registration Route ==========
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        db = None
        try:
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            # Validation
            if not all([name, email, password, confirm_password]):
                flash('All fields are required', 'danger')
                return render_template('register.html')
            
            if password != confirm_password:
                flash('Passwords do not match', 'danger')
                return render_template('register.html')
            
            if len(password) < 8:
                flash('Password must be at least 8 characters', 'danger')
                return render_template('register.html')
            
            # Check if user exists
            db = SessionLocal()
            existing_user = db.query(User).filter_by(email=email).first()
            
            if existing_user:
                flash('Email already registered. Please log in.', 'danger')
                return render_template('register.html')
            
            # Create new user
            hashed_password = generate_password_hash(password)
            new_user = User(
                name=name,
                email=email,
                password_hash=hashed_password
            )
            
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
            
            # Cache user in Redis if available
            if redis_client:
                try:
                    redis_client.setex(f"user:{email}", 3600, str(new_user.id))
                except:
                    pass
            
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
            
        except Exception as e:
            if db:
                db.rollback()
            print(f"❌ Registration error: {str(e)}")
            flash('Registration failed. Please try again.', 'danger')
            return render_template('register.html')
        finally:
            if db:
                db.close()
    
    return render_template('register.html')

@app.route('/login')
def login():
    return render_template('login.html')

# ========== Health Check Endpoints ==========
@app.route('/health')
def health():
    """Basic health check"""
    status = {
        "database": "❌",
        "redis": "❌",
        "postgres": "❌"
    }
    
    # Check PostgreSQL
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        status["database"] = "✅"
        status["postgres"] = "✅"
        print("✅ PostgreSQL health check passed")
    except Exception as e:
        print(f"❌ PostgreSQL health check failed: {e}")
    
    # Check Redis
    try:
        if redis_client and redis_client.ping():
            status["redis"] = "✅"
            print("✅ Redis health check passed")
    except Exception as e:
        print(f"❌ Redis health check failed: {e}")
    
    return jsonify(status)

@app.route('/test-db')
def test_db():
    """Test database connection with detailed info"""
    try:
        db = SessionLocal()
        
        # Get PostgreSQL version
        version = db.execute(text("SELECT version()")).scalar()
        
        # Check if users table exists
        tables = db.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)).fetchall()
        
        db.close()
        
        return jsonify({
            "status": "success",
            "database": "PostgreSQL",
            "version": version[:50] + "..." if len(version) > 50 else version,
            "tables": [t[0] for t in tables],
            "users_table_exists": "users" in [t[0] for t in tables]
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/init-db')
def init_db_route():
    """Initialize database tables"""
    try:
        Base.metadata.create_all(bind=engine)
        return jsonify({
            "status": "success",
            "message": "Database tables created successfully!"
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
    @app.route('/db-info')
def db_info():
    """Get database information"""
    try:
        db = SessionLocal()
        
        # Get database info
        info = db.execute(text("""
            SELECT 
                current_database() as database_name,
                current_user as user,
                version() as version
        """)).first()
        
        db.close()
        
        return jsonify({
            "database": info[0],
            "user": info[1],
            "version": info[2][:100],
            "type": "PostgreSQL"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== Run Application ==========
if __name__ == '__main__':
    # Initialize database before running
    init_db()
    app.run(debug=True)