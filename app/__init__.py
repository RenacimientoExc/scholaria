# app/__init__.py
import os
from pathlib import Path
from flask import Flask
from dotenv import load_dotenv
from .models import db
from .routes import routes, create_admin_user

# === Configuración base ===
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


# === Factory para crear la app ===
def create_app(config_object=None):
    app = Flask(__name__)

    # Config por defecto (puede venir de .env)
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'mi_ia_proyecto.db'}"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY=os.getenv("SECRET_KEY", "super-secret-key"),
    )

    # Config extra opcional
    if config_object:
        app.config.update(config_object)

    # Carpeta uploads
    upload_root = os.path.join(app.root_path, 'uploads')
    os.makedirs(upload_root, exist_ok=True)
    app.config['UPLOAD_ROOT'] = upload_root

    # Inicializar extensiones
    db.init_app(app)

    # Registrar blueprint principal
    app.register_blueprint(routes)

    # Crear tablas y usuario admin si no existe
    with app.app_context():
        db.create_all()
        create_admin_user()

    return app
