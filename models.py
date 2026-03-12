from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)  # 🔧 cambiato da String(200) → Text
    role = db.Column(db.String(20), nullable=False, default="user")

    def __repr__(self):
        return f"<User {self.username}>"


class Problem(db.Model):
    __tablename__ = "problems"

    id = db.Column(db.Integer, primary_key=True)
    cinema = db.Column(db.String(100), nullable=False)
    sala = db.Column(db.String(50), nullable=False)
    tipo = db.Column(db.Text, nullable=False)   # ✅ già ok
    urgenza = db.Column(db.String(50), nullable=False)
    stato = db.Column(db.String(50), default="Aperto")
    autore = db.Column(db.String(80), nullable=False)

    def __repr__(self):
        return f"<Problem {self.id} - {self.tipo[:20]}>"
