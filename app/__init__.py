# app/__init__.py
import os
import re
from pathlib import Path
from flask import Flask
from markdown import markdown
import bleach
from dotenv import load_dotenv
from .models import db
from .routes import routes, create_admin_user

# === Configuración base ===
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


# === Filtro Markdown seguro ===
def render_markdown(text):
    html = markdown(
        text,
        extensions=[
            "extra",
            "codehilite",
            "fenced_code",
            "tables",
            "sane_lists"
        ],
        output_format="html5"
    )

    # Insertar <br> después de etiquetas específicas si no hay <hr>
    for tag in ['h[1-6]', 'li', 'p', 'ol', 'ul']:
        pattern = rf'(</{tag}>)(?!\s*<hr>)'
        html = re.sub(pattern, r'\1<br>', html)

    # Evitar <br> entre </li> y cierre de lista
    html = re.sub(r'</li><br>\s*(</(ul|ol)>)', r'</li>\1', html)

    # Evitar <br> antes de <hr>
    html = re.sub(r'<br>\s*(<hr>)', r'\1', html)

    cleaned = bleach.clean(
        html,
        tags=[
            'p', 'div', 'span', 'br', 'hr',
            'strong', 'em', 'code', 'pre', 'blockquote',
            'ul', 'ol', 'li', 'a',
            'table', 'thead', 'tbody', 'tr', 'th', 'td',
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'del', 'ins'
        ],
        attributes={
            '*': ['class'],
            'a': ['href', 'title', 'target', 'rel'],
            'code': ['class'],
            'pre': ['class'],
        },
        protocols=['http', 'https', 'mailto'],
        strip=True
    )
    return cleaned


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

    # Registrar filtro Jinja
    app.jinja_env.filters['markdown'] = render_markdown

    # Inicializar extensiones
    db.init_app(app)

    # Registrar blueprint principal
    app.register_blueprint(routes)

    # Crear tablas y usuario admin si no existe
    with app.app_context():
        db.create_all()
        create_admin_user()

    return app
