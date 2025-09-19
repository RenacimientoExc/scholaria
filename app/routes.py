import os, re, uuid, logging, secrets, json, io, time
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from flask import send_file
from flask import Blueprint, request, session as login_session, redirect, url_for, render_template, flash, jsonify, current_app, send_from_directory, session, Response, stream_with_context, request, current_app
from flask_login import LoginManager
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv
from datetime import datetime, timedelta
from sqlalchemy import and_, or_
from typing import Generator, List, Dict
from .email_utils import send_invitation_email, send_password_reset_email
from .file_reader import procesar_archivo
from .models import db, Usuario, ChatIA, MensajeChatIA, ArchivoMateria, InviteToken, RolUsuario, Institucion, TipoTarea, PatologiaAlumno, profesor_curso_materia, alumno_patologia, Curso, Materia, Tarea, RespuestaTarea, SesionAprendiendoPreguntar, AnalyticaComprension, AlertaContenidoSensible
from .groq_stream import chat_ia_universal
load_dotenv()
routes = Blueprint('routes', __name__)
bp = Blueprint("chat", __name__)
logger = logging.getLogger(__name__)



#======================================
#               UTILS
#======================================    
def get_institution_statistics(institution_id):
    """Función helper corregida para obtener estadísticas"""
    stats = {
        'profesores': 0,
        'tutores': 0, 
        'alumnos': 0,
        'padres': 0
    }
    
    # 🔧 CORRECCIÓN: Profesores usando JOIN explícito
    stats['profesores'] = db.session.query(Usuario.id).distinct().join(
        profesor_curso_materia, Usuario.id == profesor_curso_materia.c.profesor_id
    ).join(
        Curso, profesor_curso_materia.c.curso_id == Curso.id
    ).filter(
        Curso.institucion_id == institution_id,
        Usuario.activo == True,
        Usuario.rol == RolUsuario.PROFESOR
    ).count()
    
    # 🔧 CORRECCIÓN: Tutores usando JOIN explícito
    stats['tutores'] = db.session.query(Usuario.id).join(
        Curso, Usuario.id == Curso.tutor_id
    ).filter(
        Curso.institucion_id == institution_id,
        Usuario.activo == True,
        Usuario.rol == RolUsuario.TUTOR
    ).count()
    
    # 🔧 CORRECCIÓN: Alumnos usando JOIN explícito
    stats['alumnos'] = db.session.query(Usuario.id).join(
        Curso, Usuario.curso_id == Curso.id
    ).filter(
        Curso.institucion_id == institution_id,
        Usuario.activo == True,
        Usuario.rol == RolUsuario.ALUMNO
    ).count()
    
    # Para padres, mantén la lógica existente que funciona
    alumnos_ids = db.session.query(Usuario.id).join(
        Curso, Usuario.curso_id == Curso.id
    ).filter(
        Curso.institucion_id == institution_id,
        Usuario.rol == RolUsuario.ALUMNO
    ).subquery()
    
    padres_ids = set()
    
    padres_como_padre = db.session.query(Usuario.padre_id).filter(
        Usuario.id.in_(alumnos_ids),
        Usuario.padre_id.isnot(None)
    ).all()
    
    madres_como_madre = db.session.query(Usuario.madre_id).filter(
        Usuario.id.in_(alumnos_ids),
        Usuario.madre_id.isnot(None)
    ).all()
    
    for padre_id, in padres_como_padre:
        if padre_id:
            padres_ids.add(padre_id)
            
    for madre_id, in madres_como_madre:
        if madre_id:
            padres_ids.add(madre_id)
    
    stats['padres'] = len(padres_ids)
    
    return stats

# CORRECCIÓN para get_recent_activities
def get_recent_activities(institution_id, limit=10):
    """Obtiene las actividades recientes de una institución - CORREGIDO"""
    actividades = []
    hace_30_dias = datetime.now() - timedelta(days=30)
    
    # 🔧 CORRECCIÓN: Alumnos nuevos usando JOIN explícito
    nuevos_alumnos = db.session.query(Usuario).join(
        Curso, Usuario.curso_id == Curso.id
    ).filter(
        Curso.institucion_id == institution_id,
        Usuario.fecha_creacion >= hace_30_dias,
        Usuario.activo == True,
        Usuario.rol == RolUsuario.ALUMNO
    ).order_by(Usuario.fecha_creacion.desc()).limit(5).all()
    
    for alumno in nuevos_alumnos:
        actividades.append({
            'tipo': 'alumno_nuevo',
            'icono': 'fa-user-plus',
            'titulo': f'Nuevo alumno: {alumno.nombre} {alumno.apellido}',
            'descripcion': f'Se registró en el curso {alumno.curso.nombre if alumno.curso else "Sin asignar"}',
            'fecha': alumno.fecha_creacion
        })
    
    # 🔧 CORRECCIÓN: Profesores nuevos usando JOIN explícito
    nuevos_profesores = db.session.query(Usuario).distinct().join(
        profesor_curso_materia, Usuario.id == profesor_curso_materia.c.profesor_id
    ).join(
        Curso, profesor_curso_materia.c.curso_id == Curso.id  
    ).filter(
        Curso.institucion_id == institution_id,
        Usuario.fecha_creacion >= hace_30_dias,
        Usuario.activo == True,
        Usuario.rol == RolUsuario.PROFESOR
    ).order_by(Usuario.fecha_creacion.desc()).limit(3).all()
    
    for profesor in nuevos_profesores:
        actividades.append({
            'tipo': 'profesor_nuevo',
            'icono': 'fa-chalkboard-teacher',
            'titulo': f'Nuevo profesor: {profesor.nombre} {profesor.apellido}',
            'descripcion': 'Se unió al equipo docente',
            'fecha': profesor.fecha_creacion
        })
    
    # El resto del código sigue igual...
    
    nuevos_cursos = Curso.query.filter(
        Curso.institucion_id == institution_id,
        Curso.fecha_creacion >= hace_30_dias
    ).order_by(Curso.fecha_creacion.desc()).limit(3).all()
    
    for curso in nuevos_cursos:
        actividades.append({
            'tipo': 'curso_nuevo',
            'icono': 'fa-graduation-cap',
            'titulo': f'Nuevo curso: {curso.nombre}',
            'descripcion': f'Nivel: {curso.nivel or "No especificado"}',
            'fecha': curso.fecha_creacion
        })
    
    # 🔧 CORRECCIÓN: Archivos usando JOIN explícito
    nuevos_archivos = db.session.query(ArchivoMateria).join(Materia).join(Curso).filter(
        Curso.institucion_id == institution_id,
        ArchivoMateria.fecha_subida >= hace_30_dias
    ).order_by(ArchivoMateria.fecha_subida.desc()).limit(3).all()
    
    for archivo in nuevos_archivos:
        profesor = Usuario.query.get(archivo.profesor_id)
        actividades.append({
            'tipo': 'archivo_subido',
            'icono': 'fa-file-upload',
            'titulo': f'Material subido: {archivo.nombre_tema}',
            'descripcion': f'Por {profesor.nombre if profesor else "Usuario desconocido"} en {archivo.materia.nombre}',
            'fecha': archivo.fecha_subida
        })
    
    actividades.sort(key=lambda x: x['fecha'], reverse=True)
    return actividades[:limit]

def get_system_alerts(institution_id):
    """
    Genera alertas del sistema para la institución
    """
    alertas = []
    
    # Cursos sin tutor
    cursos_sin_tutor = Curso.query.filter(
        Curso.institucion_id == institution_id,
        Curso.tutor_id.is_(None)
    ).count()
    
    if cursos_sin_tutor > 0:
        alertas.append({
            'tipo': 'warning',
            'mensaje': f'Hay {cursos_sin_tutor} curso(s) sin tutor asignado',
            'accion': 'Gestionar Cursos'
        })
    
    # Alumnos sin curso asignado
    # Esto requiere una consulta más compleja dependiendo de cómo manejes la relación
    
    # Alertas de contenido sensible
    alertas_contenido = AlertaContenidoSensible.query.join(
        ChatIA
    ).join(Usuario).join(Curso).filter(
        Curso.institucion_id == institution_id,
        AlertaContenidoSensible.revisada == False
    ).count()
    
    if alertas_contenido > 0:
        alertas.append({
            'tipo': 'danger',
            'mensaje': f'Hay {alertas_contenido} alerta(s) de contenido sensible sin revisar',
            'accion': 'Ver Alertas'
        })
    
    return alertas
    
def _sse_json_event(data: dict) -> str:
    """
    Formatea datos como evento Server-Sent Event en formato JSON.
    """
    import json
    try:
        json_str = json.dumps(data, ensure_ascii=False)
        return f"data: {json_str}\n\n"
    except Exception as e:
        logger.error(f"Error formatting SSE event: {e}")
        return "data: {\"error\": \"Failed to format response\"}\n\n"

UPLOAD_FOLDER = 'uploads'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def create_directory_structure(institution_name, course_name, subject_name):
    """Crea la estructura de directorios para almacenar archivos"""
    # Sanitizar nombres para usar como carpetas
    safe_institution = secure_filename(institution_name).replace('_', ' ')
    safe_course = secure_filename(course_name).replace('_', ' ')
    safe_subject = secure_filename(subject_name).replace('_', ' ')
    
    path = os.path.join(UPLOAD_FOLDER, safe_institution, safe_course, safe_subject)
    os.makedirs(path, exist_ok=True)
    return path

def create_admin_user():
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")

    if not admin_email or not admin_password:
        print("ADMIN_EMAIL o ADMIN_PASSWORD no están definidos en .env")
        return

    existing_admin = Usuario.query.filter_by(email=admin_email).first()
    if not existing_admin:
        from datetime import date
        admin_user = Usuario(
            nombre="Admin",           # ✅ Usar 'nombre' en lugar de 'first_name'
            apellido="Principal",     # ✅ Usar 'apellido' en lugar de 'last_name'
            email=admin_email,
            fecha_nacimiento=date(1990, 1, 1),  # ✅ Campo requerido
            rol=RolUsuario.ADMIN,     # ✅ Usar enum
            password_hash=generate_password_hash(admin_password)
        )
        db.session.add(admin_user)
        db.session.commit()
        print("✅ Usuario administrador creado")
    else:
        print("⚹️ Usuario administrador ya existe")

def is_admin(user):
    return user.role == 'admin'

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

ALLOWED_EXTENSIONS = {
    # Documentos
    'pdf', 'txt', 'doc', 'docx', 'odt',
    
    # ImÃƒÂ¡genes
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp',
    
    # Presentaciones
    'ppt', 'pptx', 'odp',
    
    # Video
    'mp4', 'avi', 'mov', 'mkv', 'wmv', 'webm',
    
    # Audio
    'mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a',
    
    # Archivos comprimidos
    'zip', 'rar', '7z',
    
    # Otros textos
    'md', 'csv', 'json',
}
MAX_FILE_SIZE = 100 * 1024 * 1024





#======================================
#         CONTEXTO DE RUTAS
#======================================
@routes.context_processor
def inject_user_globals():
    if 'user_id' in login_session:
        user = Usuario.query.get(login_session['user_id'])
        # ✅ Verificar que el usuario existe antes de acceder a sus propiedades
        if user:
            sessions = ChatIA.query\
                        .filter_by(usuario_id=user.id)\
                        .order_by(ChatIA.fecha_ultimo_mensaje.desc())\
                        .all()
            return {
                'sessions': sessions,
                'user_name': user.nombre,  # ✅ Usar 'nombre'
                'user': user
            }
    # ✅ Retornar diccionario vacío si no hay usuario o el usuario no existe
    return {}





#======================================
#      INVITACION A LA PLATAFORMA
#======================================
@routes.route('/send_invitation', methods=['POST'])
def send_invitation():
    user_id = session.get('user_id')
    user = db.session.get(Usuario, user_id)
    if not user or user.rol != RolUsuario.ADMIN:
        return redirect(url_for('routes.login'))

    email = request.form['email']
    nombre = request.form['nombre']
    apellido = request.form['apellido']
    role = request.form['role']

    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(days=2)

    if isinstance(role, str):
        role_enum = RolUsuario(role)
    else:
        role_enum = role

    # ✅ NUEVO: Obtener la institución del admin que está enviando la invitación
    admin_institucion = user.get_institucion()  # o user.institucion si es admin normal
    
    # ✅ NUEVO: Preparar datos adicionales con institucion_id
    datos_adicionales = {}
    if admin_institucion:
        datos_adicionales['institucion_id'] = admin_institucion.id
    
    # Si hay datos específicos del formulario (curso, patologías, etc.)
    if request.form.get('curso_id'):
        datos_adicionales['curso_id'] = int(request.form['curso_id'])
    
    if request.form.get('fecha_nacimiento'):
        datos_adicionales['fecha_nacimiento'] = request.form['fecha_nacimiento']
    
    # Para alumnos: patologías
    patologias = request.form.getlist('patologias')  # Si las envías como checkbox
    if patologias:
        datos_adicionales['patologias'] = patologias

    invitation = InviteToken(
        email=email, 
        token=token, 
        rol=role_enum,
        nombre=nombre,
        apellido=apellido,
        fecha_expiracion=expires
    )
    
    # ✅ NUEVO: Guardar datos adicionales
    if datos_adicionales:
        invitation.set_datos_adicionales(datos_adicionales)
    
    db.session.add(invitation)
    db.session.commit()

    link = url_for('routes.accept_invitation', token=token, _external=True)

    send_invitation_email(
        to_email=email,
        first_name=nombre,
        invite_url=link,
        expiration="48 horas"
    )

    flash("Invitación enviada con éxito", "success")
    return redirect(url_for('routes.admin_panel'))

@routes.route('/registro/aceptar', methods=['GET', 'POST'])
def accept_invitation():
    token_str = request.args.get('token')
    token_obj = InviteToken.query.filter_by(token=token_str).first()

    if not token_obj or not token_obj.is_valid():
        flash("Invitación no válida o expirada.", "error")
        return redirect(url_for('routes.login'))

    if request.method == 'POST':
        password = request.form['password']
        confirm_password = request.form.get('confirm_password', '')
        
        # Validar que las contraseñas coincidan
        if password != confirm_password:
            flash("Las contraseñas no coinciden", "error")
            return render_template("register_from_invite.html", invitation=token_obj)
        
        # Validar longitud mínima de contraseña
        if len(password) < 6:
            flash("La contraseña debe tener al menos 6 caracteres", "error")
            return render_template("register_from_invite.html", invitation=token_obj)
        
        try:
            # Verificar si ya existe un usuario con este email
            existing_user = Usuario.query.filter_by(email=token_obj.email).first()
            
            # ✅ NUEVO: Obtener datos adicionales desde el token
            datos_adicionales = token_obj.get_datos_adicionales()
            institucion_id = datos_adicionales.get('institucion_id')
            
            if existing_user:
                # Si el usuario ya existe, solo actualizamos la contraseña y activamos
                existing_user.set_password(password)
                existing_user.activo = True
                
                # ✅ NUEVO: Asignar institución si no la tiene
                if not existing_user.institucion_id and institucion_id:
                    existing_user.institucion_id = institucion_id
                
                # Marcar el email como confirmado si no lo estaba
                if not existing_user.is_email_confirmed:
                    existing_user.email_confirmed_at = datetime.utcnow()
                
                # Actualizar datos desde la invitación si es necesario
                if not existing_user.nombre or existing_user.nombre != token_obj.nombre:
                    existing_user.nombre = token_obj.nombre
                if not existing_user.apellido or existing_user.apellido != token_obj.apellido:
                    existing_user.apellido = token_obj.apellido
                
                db.session.delete(token_obj)
                db.session.commit()
                
                flash("Contraseña establecida exitosamente", "success")
                return redirect(url_for('routes.login'))
            else:
                # Crear nuevo usuario con datos de la invitación
                from datetime import date
                
                # Fecha de nacimiento: usar la de datos adicionales o una por defecto
                fecha_nacimiento = date(2000, 1, 1)  # Por defecto
                if datos_adicionales.get('fecha_nacimiento'):
                    try:
                        fecha_nacimiento = datetime.strptime(datos_adicionales['fecha_nacimiento'], '%Y-%m-%d').date()
                    except (ValueError, TypeError):
                        pass
                
                new_user = Usuario(
                    email=token_obj.email,
                    nombre=token_obj.nombre,
                    apellido=token_obj.apellido,
                    rol=token_obj.rol,
                    fecha_nacimiento=fecha_nacimiento,
                    activo=True,
                    email_confirmed_at=datetime.utcnow()
                )
                
                # ✅ NUEVO: Asignar institución
                if institucion_id:
                    new_user.institucion_id = institucion_id
                    print(f"DEBUG: Asignando institucion_id {institucion_id} al usuario {new_user.email}")
                else:
                    print(f"ADVERTENCIA: No se encontró institucion_id en datos_adicionales para {new_user.email}")
                
                new_user.set_password(password)
                
                # Configuraciones adicionales según el rol
                if token_obj.rol == RolUsuario.ALUMNO and datos_adicionales.get('curso_id'):
                    new_user.curso_id = datos_adicionales['curso_id']
                
                db.session.add(new_user)
                db.session.flush()  # Para obtener el ID del usuario
                
                # Si es alumno y tiene patologías, agregarlas
                if (token_obj.rol == RolUsuario.ALUMNO and 
                    datos_adicionales.get('patologias') and 
                    hasattr(new_user, 'agregar_patologia')):
                    try:
                        for patologia in datos_adicionales['patologias']:
                            new_user.agregar_patologia(patologia)
                    except Exception as e:
                        logger.error(f"Error agregando patologías: {e}")
                
                # Si es tutor y tiene curso asignado, actualizarlo
                if (token_obj.rol == RolUsuario.TUTOR and 
                    datos_adicionales.get('curso_id')):
                    try:
                        curso = Curso.query.get(datos_adicionales['curso_id'])
                        if curso and not curso.tutor_id:
                            curso.tutor_id = new_user.id
                    except Exception as e:
                        logger.error(f"Error asignando tutor a curso: {e}")
                
                db.session.delete(token_obj)
                db.session.commit()
                
                print(f"DEBUG: Usuario creado exitosamente: {new_user.email} con institucion_id: {new_user.institucion_id}")
                
                flash("Cuenta creada exitosamente", "success")
                return redirect(url_for('routes.login'))
                
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error procesando invitación: {e}")
            flash("Error al procesar la invitación. Intente nuevamente.", "error")
            return render_template("register_from_invite.html", invitation=token_obj)

    # GET request - mostrar formulario con datos de la invitación
    return render_template("register_from_invite.html", invitation=token_obj)


# ✅ FUNCIÓN ADICIONAL: Para migrar usuarios existentes sin institucion_id
def migrar_usuarios_sin_institucion():
    """
    Función temporal para asignar institucion_id a usuarios existentes
    Ejecuta esto una vez desde la consola Flask o agrega una ruta temporal
    """
    # Buscar la primera institución disponible (si solo tienes una)
    primera_institucion = Institucion.query.first()
    
    if not primera_institucion:
        print("No hay instituciones creadas")
        return
    
    # Usuarios sin institución asignada (excluyendo directores)
    usuarios_sin_institucion = Usuario.query.filter(
        Usuario.institucion_id.is_(None),
        Usuario.rol != RolUsuario.DIRECTOR
    ).all()
    
    print(f"Encontrados {len(usuarios_sin_institucion)} usuarios sin institución")
    
    for usuario in usuarios_sin_institucion:
        usuario.institucion_id = primera_institucion.id
        print(f"Asignando {usuario.email} a institución {primera_institucion.nombre}")
    
    db.session.commit()
    print("Migración completada")




#======================================
#               LOGIN
#======================================
@routes.route('/')
def root():
    return redirect(url_for('routes.login'))

@routes.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')

        user = Usuario.query.filter_by(email=email).first()

        if not user:
            flash("Usuario no encontrado", "error")
            return render_template('login.html')

        # Validar que el rol enviado coincide con el rol del usuario
        if role == 'student' and user.rol not in [RolUsuario.ALUMNO, RolUsuario.PADRE, RolUsuario.MADRE]:
            flash("Este email no pertenece a un alumno", "error")
            return render_template('login.html')
        elif role == 'staff' and user.rol not in [RolUsuario.ADMIN, RolUsuario.DIRECTOR, RolUsuario.PROFESOR, RolUsuario.TUTOR]:
            flash("Este email no pertenece a un profesor o admin", "error")
            return render_template('login.html')

        # Validar contraseña
        if user.check_password(password):
            login_session['user_id'] = user.id
            login_session['user_name'] = user.nombre

            # Redirigir a panel según rol
            if user.rol == RolUsuario.ADMIN:
                return redirect(url_for('routes.admin_panel'))
            
            elif user.rol == RolUsuario.DIRECTOR:
                # ✅ SOLUCIÓN: Buscar la institución donde este usuario es director
                institucion = Institucion.query.filter_by(director_id=user.id).first()
                if institucion:
                    return redirect(url_for('routes.director_panel', institution_id=institucion.id))
                else:
                    flash("Error: Director sin institución asignada", "error")
                    return render_template('login.html')
                
            elif user.rol == RolUsuario.PROFESOR:
                institucion = user.get_institucion()  # Usa el método que ya existe
                if institucion:
                    return redirect(url_for('routes.profesor_panel'))
                else:
                    flash("Error: Profesor sin institución asignada", "error")
                    return render_template('login.html')
                
            elif user.rol == RolUsuario.ALUMNO:
                return redirect(url_for('routes.chat_index'))
            
        else:
            flash("Contraseña incorrecta", "error")

    return render_template('login.html')

@routes.route("/logout", methods=["POST"])
def logout():
    login_session.clear()
    return redirect(url_for("routes.login"))

@routes.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        
        # Buscar usuario por email
        user = Usuario.query.filter_by(email=email).first()
        
        if user:
            # Generar token seguro
            reset_token = secrets.token_urlsafe(32)
            
            # Guardar token en la base de datos (necesitarás agregar estos campos al modelo Usuario)
            user.reset_password_token = reset_token
            user.reset_password_expires = datetime.utcnow() + timedelta(hours=1)  # Token expira en 1 hora
            
            try:
                db.session.commit()
                
                # Construir URL de reseteo
                reset_url = url_for('routes.reset_password', token=reset_token, _external=True)
                
                # Enviar email
                send_password_reset_email(
                    to_email=user.email,
                    first_name=user.nombre,
                    reset_url=reset_url,
                    expiration="1 hora"
                )
                
                flash("Se ha enviado un enlace de recuperación a tu email", "success")
                
            except Exception as e:
                db.session.rollback()
                print(f"Error enviando email de reseteo: {e}")
                flash("Hubo un problema enviando el email. Intenta más tarde.", "error")
        else:
            # Por seguridad, mostramos el mismo mensaje aunque el usuario no exista
            flash("Se ha enviado un enlace de recuperación a tu email", "success")
        
        return redirect(url_for('routes.login'))
    
    return render_template('forgot_password.html')


@routes.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # Buscar usuario por token
    user = Usuario.query.filter_by(reset_password_token=token).first()
    
    # Verificar que el token existe y no ha expirado
    if not user or not user.reset_password_expires or user.reset_password_expires < datetime.utcnow():
        flash("El enlace de recuperación ha expirado o no es válido", "error")
        return redirect(url_for('routes.forgot_password'))
    
    if request.method == 'POST':
        new_password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validar que las contraseñas coinciden
        if new_password != confirm_password:
            flash("Las contraseñas no coinciden", "error")
            return render_template('reset_password.html', token=token)
        
        # Validar longitud mínima
        if len(new_password) < 6:
            flash("La contraseña debe tener al menos 6 caracteres", "error")
            return render_template('reset_password.html', token=token)
        
        # Actualizar contraseña
        user.set_password(new_password)  # Asume que tienes este método en tu modelo
        user.reset_password_token = None
        user.reset_password_expires = None
        
        try:
            db.session.commit()
            flash("Tu contraseña ha sido actualizada exitosamente", "success")
            return redirect(url_for('routes.login'))
        except Exception as e:
            db.session.rollback()
            print(f"Error actualizando contraseña: {e}")
            flash("Hubo un problema actualizando tu contraseña", "error")
    
    return render_template('reset_password.html', token=token)




#======================================
#                ADMIN
#======================================
@routes.route('/admin/panel')
def admin_panel():
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.ADMIN:  # ✅ Usar enum
        flash("No autorizado", "error")
        return redirect(url_for('routes.chat_index'))

    return render_template('admin_panel.html')

@routes.route('/create_institution', methods=['POST'])
def create_institution():
    """Nueva ruta para crear instituciones con director"""
    user_id = session.get('user_id')
    user = db.session.get(Usuario, user_id)
    if not user or user.rol != RolUsuario.ADMIN:
        return redirect(url_for('routes.login'))

    # Datos de la institución
    nombre_institucion = request.form['nombre_institucion']
    
    # Datos del director
    email_director = request.form['email_director']
    nombre_director = request.form['nombre_director']
    apellido_director = request.form['apellido_director']
    fecha_nacimiento_str = request.form['fecha_nacimiento_director']
    
    # Manejo de logos (opcional)
    logo_grande = None
    logo_pequeno = None
    
    if 'logo_grande' in request.files and request.files['logo_grande'].filename:
        logo_file = request.files['logo_grande']
        if allowed_file(logo_file.filename):
            filename = secure_filename(f"logo_grande_{secrets.token_hex(8)}_{logo_file.filename}")
            logos_path = os.path.join(current_app.config.get('UPLOAD_ROOT', 'uploads'), 'logos')
            os.makedirs(logos_path, exist_ok=True)
            logo_path = os.path.join(logos_path, filename)
            logo_file.save(logo_path)
            logo_grande = filename
    
    if 'logo_pequeno' in request.files and request.files['logo_pequeno'].filename:
        logo_file = request.files['logo_pequeno']
        if allowed_file(logo_file.filename):
            filename = secure_filename(f"logo_pequeno_{secrets.token_hex(8)}_{logo_file.filename}")
            logos_path = os.path.join(current_app.config.get('UPLOAD_ROOT', 'uploads'), 'logos')
            os.makedirs(logos_path, exist_ok=True)
            logo_path = os.path.join(logos_path, filename)
            logo_file.save(logo_path)
            logo_pequeno = filename
    
    try:
        # Convertir fecha de nacimiento
        from datetime import datetime, date
        if fecha_nacimiento_str:
            fecha_nacimiento = datetime.strptime(fecha_nacimiento_str, '%Y-%m-%d').date()
        else:
            fecha_nacimiento = date(1980, 1, 1)  # Fecha por defecto

        # Verificar que el email no exista
        existing_user = Usuario.query.filter_by(email=email_director).first()
        if existing_user:
            flash("Ya existe un usuario con ese email", "error")
            return redirect(url_for('routes.admin_panel'))

        # Generar token para invitación
        token = secrets.token_urlsafe(32)
        expires = datetime.utcnow() + timedelta(days=2)

        # PASO 1: Crear la institución primero (sin director_id)
        institucion = Institucion(
            nombre=nombre_institucion,
            # director_id se asignará después
            logo_grande=logo_grande,
            logo_pequeno=logo_pequeno
        )
        db.session.add(institucion)
        db.session.flush()  # Para obtener el ID de la institución

        # PASO 2: Crear el director CON el institucion_id
        director = Usuario(
            email=email_director,
            nombre=nombre_director,
            apellido=apellido_director,
            fecha_nacimiento=fecha_nacimiento,
            rol=RolUsuario.DIRECTOR,
            institucion_id=institucion.id,  # ← AQUÍ se asigna el institucion_id
            activo=False  # Marcar como inactivo hasta que acepte
        )
        db.session.add(director)
        db.session.flush()  # Para obtener el ID del director

        # PASO 3: Actualizar la institución con el director_id
        institucion.director_id = director.id

        # Crear token de invitación
        invitation = InviteToken(
            email=email_director,
            token=token,
            rol=RolUsuario.DIRECTOR,
            nombre=nombre_director,
            apellido=apellido_director,
            fecha_expiracion=expires
        )
        db.session.add(invitation)
        
        db.session.commit()

        # Enviar email usando la función existente
        link = url_for('routes.accept_invitation', token=token, _external=True)
        
        send_invitation_email(
            to_email=email_director,
            first_name=nombre_director,
            invite_url=link,
            expiration="48 horas"
        )

        print(f"[OK] Invitación enviada a {email_director}")
        flash(f"Institución '{nombre_institucion}' creada exitosamente. Se envió email al director.", "success")
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creando institución: {e}")
        flash("Error al crear la institución. Revise los datos e intente nuevamente.", "error")

    return redirect(url_for('routes.admin_panel'))


@routes.route('/api/institutions', methods=['GET'])
def get_institutions_v2():
    """Versión mejorada usando relaciones ORM"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'no autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.ADMIN:
        return jsonify({'error': 'no autorizado'}), 403

    try:
        # 🆕 MEJOR ENFOQUE: Usar relaciones ORM directamente
        instituciones = Institucion.query.all()
        
        result = []
        for inst in instituciones:
            # Usar la relación ORM 'director' definida en el modelo
            director = inst.director  # Esto usa la relación que ya tienes definida
            result.append({
                'id': inst.id,
                'nombre': inst.nombre,
                'logo_grande': inst.logo_grande,
                'logo_pequeno': inst.logo_pequeno,
                'fecha_creacion': inst.fecha_creacion.isoformat(),
                'director': {
                    'id': director.id,
                    'nombre': director.nombre,
                    'apellido': director.apellido,
                    'email': director.email,
                    'activo': director.activo,
                    'email_confirmado': director.is_email_confirmed
                } if director else None,  # Protección en caso de director None
                'valores_institucionales': inst.valores_institucionales,
                'metodologia_pedagogica': inst.metodologia_pedagogica,
                'configuracion_ia': inst.configuracion_ia
            })
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error obteniendo instituciones: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@routes.route('/uploads/logos/<filename>')
def serve_logo(filename):
    """Servir archivos de logos"""
    logos_path = os.path.join(current_app.config.get('UPLOAD_ROOT', 'uploads'), 'logos')
    return send_from_directory(logos_path, filename)

@routes.route('/api/institution/<int:institution_id>', methods=['GET'])
def get_institution_details(institution_id):
    """Obtener detalles completos de una institución"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'no autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.ADMIN:
        return jsonify({'error': 'no autorizado'}), 403

    try:
        # Obtener institución con director
        institucion = db.session.query(Institucion).filter_by(id=institution_id).first()
        if not institucion:
            return jsonify({'error': 'Institución no encontrada'}), 404

        director = institucion.director
        
        # Obtener TODOS los usuarios que pertenecen a esta institución
        usuarios_institucion = Usuario.query.filter_by(institucion_id=institution_id).all()

        result = {
            'id': institucion.id,
            'nombre': institucion.nombre,
            'logo_grande': institucion.logo_grande,
            'logo_pequeno': institucion.logo_pequeno,
            'fecha_creacion': institucion.fecha_creacion.isoformat(),
            'valores_institucionales': institucion.valores_institucionales,
            'metodologia_pedagogica': institucion.metodologia_pedagogica,
            'configuracion_ia': institucion.configuracion_ia,
            'director': {
                'id': director.id,
                'nombre': director.nombre,
                'apellido': director.apellido,
                'email': director.email,
                'fecha_nacimiento': director.fecha_nacimiento.isoformat() if director.fecha_nacimiento else None,
                'rol': director.rol.value,
                'activo': director.activo,
                'email_confirmado': director.is_email_confirmed,
                'fecha_creacion': director.fecha_creacion.isoformat() if hasattr(director, 'fecha_creacion') else None
            },
            'usuarios': []
        }

        # Agregar todos los usuarios de la institución (incluyendo director, profesores, estudiantes, etc.)
        for usuario in usuarios_institucion:
            result['usuarios'].append({
                'id': usuario.id,
                'nombre': usuario.nombre,
                'apellido': usuario.apellido,
                'email': usuario.email,
                'rol': usuario.rol.value,
                'activo': usuario.activo,
                'email_confirmado': usuario.is_email_confirmed,
                'fecha_nacimiento': usuario.fecha_nacimiento.isoformat() if usuario.fecha_nacimiento else None
            })

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error obteniendo detalles de institución: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500


@routes.route('/api/institution/<int:institution_id>/director', methods=['PUT'])
def update_director(institution_id):
    """Actualizar datos del director de una institución"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'no autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.ADMIN:
        return jsonify({'error': 'no autorizado'}), 403

    try:
        # Obtener institución
        institucion = Institucion.query.get(institution_id)
        if not institucion:
            return jsonify({'error': 'Institución no encontrada'}), 404

        director = institucion.director
        
        # Obtener datos del request
        data = request.get_json()
        
        # Validar email único (excepto el actual)
        if 'email' in data and data['email'] != director.email:
            existing_user = Usuario.query.filter_by(email=data['email']).first()
            if existing_user:
                return jsonify({'error': 'Ya existe un usuario con ese email'}), 400

        # Actualizar campos
        if 'nombre' in data:
            director.nombre = data['nombre'].strip()
        
        if 'apellido' in data:
            director.apellido = data['apellido'].strip()
        
        if 'email' in data:
            director.email = data['email'].strip()
        
        if 'fecha_nacimiento' in data and data['fecha_nacimiento']:
            from datetime import datetime
            director.fecha_nacimiento = datetime.strptime(data['fecha_nacimiento'], '%Y-%m-%d').date()
        
        if 'password' in data and data['password'].strip():
            director.set_password(data['password'])
        
        # Actualizar timestamp
        director.fecha_actualizacion = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Director actualizado exitosamente',
            'director': {
                'id': director.id,
                'nombre': director.nombre,
                'apellido': director.apellido,
                'email': director.email,
                'fecha_nacimiento': director.fecha_nacimiento.isoformat() if director.fecha_nacimiento else None
            }
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error actualizando director: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500





#======================================
#            RUTAS DEL DIRECTOR
#======================================
@routes.route('/institution/<int:institution_id>/director')
def director_panel(institution_id):
    """Panel principal del director"""
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))
     
    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        flash("No autorizado", "error")
        return redirect(url_for('routes.chat_index'))
     
    # Verificar que el director pertenece a esta institución
    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        flash("No autorizado para esta institución", "error")
        return redirect(url_for('routes.chat_index'))
    
    # === ESTADÍSTICAS CORREGIDAS USANDO institucion_id ===
    
    # 1. Cursos activos
    total_cursos_activos = Curso.query.filter(
        Curso.institucion_id == institution_id
    ).count()
    
    # 2. Materias activas
    total_materias_activas = db.session.query(Materia).join(Curso).filter(
        Curso.institucion_id == institution_id
    ).count()
    
    # 3. Usuarios por rol usando institucion_id
    total_alumnos = Usuario.query.filter(
        Usuario.rol == RolUsuario.ALUMNO,
        Usuario.activo == True,
        Usuario.institucion_id == institution_id
    ).count()
    
    total_profesores = Usuario.query.filter(
        Usuario.rol == RolUsuario.PROFESOR,
        Usuario.activo == True,
        Usuario.institucion_id == institution_id
    ).count()
    
    total_tutores = Usuario.query.filter(
        Usuario.rol == RolUsuario.TUTOR,
        Usuario.activo == True,
        Usuario.institucion_id == institution_id
    ).count()
    
    # 4. Padres - obtener IDs únicos de padre_id y madre_id de alumnos de la institución
    alumnos_institucion = Usuario.query.filter(
        Usuario.rol == RolUsuario.ALUMNO,
        Usuario.activo == True,
        Usuario.institucion_id == institution_id
    ).all()
    
    padres_ids = set()
    for alumno in alumnos_institucion:
        if alumno.padre_id:
            padres_ids.add(alumno.padre_id)
        if alumno.madre_id:
            padres_ids.add(alumno.madre_id)
    
    # Verificar que los padres existen y están activos
    total_padres = Usuario.query.filter(
        Usuario.id.in_(padres_ids),
        Usuario.activo == True
    ).count() if padres_ids else 0
    
    total_usuarios_activos = total_profesores + total_tutores + total_alumnos + total_padres
    
    # 5. Interacciones IA
    inicio_mes = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Obtener todos los usuarios de la institución (incluyendo padres)
    usuarios_institucion_ids = []
    
    # Usuarios directos de la institución
    usuarios_directos = Usuario.query.filter(
        Usuario.institucion_id == institution_id,
        Usuario.activo == True
    ).all()
    usuarios_institucion_ids.extend([u.id for u in usuarios_directos])
    
    # Agregar padres
    usuarios_institucion_ids.extend(list(padres_ids))
    
    # Contar interacciones IA
    interacciones_ia_mes = 0
    if usuarios_institucion_ids:
        try:
            interacciones_ia_mes = MensajeChatIA.query.join(ChatIA).filter(
                ChatIA.usuario_id.in_(usuarios_institucion_ids),
                MensajeChatIA.fecha_envio >= inicio_mes
            ).count()
        except Exception as e:
            print(f"Error al contar interacciones IA: {e}")
            interacciones_ia_mes = 0
    
    # 6. Estado de configuración IA
    configuracion_ia_completa = bool(
        institucion.valores_institucionales and 
        institucion.metodologia_pedagogica
    )
    
    # === ACTIVIDADES RECIENTES CORREGIDAS ===
    actividades_recientes = []
    hace_30_dias = datetime.now() - timedelta(days=30)
    
    # Nuevos alumnos de la institución
    nuevos_alumnos = Usuario.query.filter(
        Usuario.rol == RolUsuario.ALUMNO,
        Usuario.activo == True,
        Usuario.institucion_id == institution_id,
        Usuario.fecha_creacion >= hace_30_dias
    ).order_by(Usuario.fecha_creacion.desc()).limit(5).all()
    
    for alumno in nuevos_alumnos:
        curso = Curso.query.get(alumno.curso_id) if alumno.curso_id else None
        actividades_recientes.append({
            'tipo': 'alumno_nuevo',
            'icono': 'fa-user-plus',
            'titulo': f'Nuevo alumno: {alumno.nombre} {alumno.apellido}',
            'descripcion': f'Se registró en el curso {curso.nombre if curso else "Sin asignar"}',
            'fecha': alumno.fecha_creacion
        })
    
    # Nuevos profesores
    nuevos_profesores = Usuario.query.filter(
        Usuario.rol == RolUsuario.PROFESOR,
        Usuario.activo == True,
        Usuario.institucion_id == institution_id,
        Usuario.fecha_creacion >= hace_30_dias
    ).order_by(Usuario.fecha_creacion.desc()).limit(3).all()
    
    for profesor in nuevos_profesores:
        actividades_recientes.append({
            'tipo': 'profesor_nuevo',
            'icono': 'fa-chalkboard-teacher',
            'titulo': f'Nuevo profesor: {profesor.nombre} {profesor.apellido}',
            'descripcion': f'Se unió a la institución',
            'fecha': profesor.fecha_creacion
        })
    
    # Nuevos cursos
    nuevos_cursos = Curso.query.filter(
        Curso.institucion_id == institution_id,
        Curso.fecha_creacion >= hace_30_dias
    ).order_by(Curso.fecha_creacion.desc()).limit(3).all()
    
    for curso in nuevos_cursos:
        actividades_recientes.append({
            'tipo': 'curso_nuevo',
            'icono': 'fa-graduation-cap',
            'titulo': f'Nuevo curso: {curso.nombre}',
            'descripcion': f'Nivel: {curso.nivel or "No especificado"}',
            'fecha': curso.fecha_creacion
        })
    
    # Archivos subidos recientemente
    try:
        nuevos_archivos = db.session.query(ArchivoMateria).join(Materia).join(Curso).filter(
            Curso.institucion_id == institution_id,
            ArchivoMateria.fecha_subida >= hace_30_dias
        ).order_by(ArchivoMateria.fecha_subida.desc()).limit(3).all()
        
        for archivo in nuevos_archivos:
            profesor = Usuario.query.get(archivo.profesor_id)
            actividades_recientes.append({
                'tipo': 'archivo_subido',
                'icono': 'fa-file-upload',
                'titulo': f'Material subido: {archivo.nombre_tema}',
                'descripcion': f'Por {profesor.nombre if profesor else "Usuario desconocido"} en {archivo.materia.nombre}',
                'fecha': archivo.fecha_subida
            })
    except Exception as e:
        print(f"Error al obtener archivos recientes: {e}")
    
    # Ordenar actividades por fecha
    actividades_recientes.sort(key=lambda x: x['fecha'], reverse=True)
    actividades_recientes = actividades_recientes[:10]
    
    # === ALERTAS DEL SISTEMA ===
    alertas = []
    
    # Cursos sin tutor
    cursos_sin_tutor = Curso.query.filter(
        Curso.institucion_id == institution_id,
        Curso.tutor_id.is_(None)
    ).count()
    
    if cursos_sin_tutor > 0:
        alertas.append({
            'tipo': 'warning',
            'mensaje': f'Hay {cursos_sin_tutor} curso(s) sin tutor asignado',
            'accion': 'Gestionar Cursos'
        })
    
    # Usuarios sin asignar a cursos
    alumnos_sin_curso = Usuario.query.filter(
        Usuario.rol == RolUsuario.ALUMNO,
        Usuario.activo == True,
        Usuario.institucion_id == institution_id,
        Usuario.curso_id.is_(None)
    ).count()
    
    if alumnos_sin_curso > 0:
        alertas.append({
            'tipo': 'info',
            'mensaje': f'Hay {alumnos_sin_curso} alumno(s) sin asignar a un curso',
            'accion': 'Gestionar Alumnos'
        })
    
    # Configuración IA incompleta
    if not configuracion_ia_completa:
        alertas.append({
            'tipo': 'info',
            'mensaje': 'La configuración de IA no está completa',
            'accion': 'Configurar IA'
        })
    
    # Alertas de contenido sensible
    try:
        alertas_contenido = AlertaContenidoSensible.query.filter_by(revisada=False).count()
        if alertas_contenido > 0:
            alertas.append({
                'tipo': 'danger',
                'mensaje': f'Hay {alertas_contenido} alerta(s) de contenido sensible sin revisar',
                'accion': 'Ver Alertas'
            })
    except Exception as e:
        print(f"Error al obtener alertas de contenido: {e}")
    
    # === ESTADÍSTICAS DETALLADAS ===
    estadisticas_detalladas = {
        'usuarios_por_rol': {
            'profesores': total_profesores,
            'tutores': total_tutores,
            'alumnos': total_alumnos,
            'padres': total_padres
        },
        'cursos_y_materias': {
            'cursos': total_cursos_activos,
            'materias': total_materias_activas
        },
        'interacciones_ia': {
            'este_mes': interacciones_ia_mes,
            'promedio_diario': round(interacciones_ia_mes / max(datetime.now().day, 1), 1) if interacciones_ia_mes > 0 else 0
        }
    }
    
    return render_template('director_panel.html', 
                         institucion=institucion,
                         user_name=f"{user.nombre} {user.apellido}",
                         total_usuarios_activos=total_usuarios_activos,
                         total_cursos_activos=total_cursos_activos,
                         total_materias_activas=total_materias_activas,
                         interacciones_ia_mes=interacciones_ia_mes,
                         configuracion_ia_completa=configuracion_ia_completa,
                         actividades_recientes=actividades_recientes,
                         estadisticas_detalladas=estadisticas_detalladas,
                         alertas=alertas)

@routes.route('/institution/<int:institution_id>/director/config', methods=['GET', 'POST'])
def director_config(institution_id):
    """Configuración de valores institucionales y IA"""
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        flash("No autorizado", "error")
        return redirect(url_for('routes.chat_index'))

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        flash("No autorizado", "error")
        return redirect(url_for('routes.director_panel', institution_id=institution_id))

    if request.method == 'POST':
        try:
            # Actualizar valores institucionales
            institucion.valores_institucionales = request.form.get('valores_institucionales', '').strip()
            institucion.metodologia_pedagogica = request.form.get('metodologia_pedagogica', '').strip()
            
            # Configuración IA como JSON
            config_ia = {
                'tono': request.form.get('tono_ia', 'formal'),
                'enfoque_pedagogico': request.form.get('enfoque_pedagogico', 'tradicional'),
                'nivel_detalle': request.form.get('nivel_detalle', 'medio'),
                'usar_ejemplos': request.form.get('usar_ejemplos') == 'on',
                'instrucciones_especiales': request.form.get('instrucciones_especiales', '').strip()
            }
            institucion.configuracion_ia = json.dumps(config_ia)
            
            db.session.commit()
            flash("Configuración actualizada exitosamente", "success")
            return redirect(url_for('routes.director_config', institution_id=institution_id))
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error actualizando configuración: {e}")
            flash("Error al actualizar configuración", "error")

    # Cargar configuración existente para el GET
    config_ia_actual = {}
    if institucion.configuracion_ia:
        try:
            config_ia_actual = json.loads(institucion.configuracion_ia)
        except (TypeError, json.JSONDecodeError):
            config_ia_actual = {}

    return render_template('director_config.html', 
                         institucion=institucion,
                         config_ia=config_ia_actual,
                         user_name=f"{user.nombre} {user.apellido}")

@routes.route('/institution/<int:institution_id>/director/users')
def director_users(institution_id):
    """Ver todos los usuarios de la institución - CORREGIDO"""
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        flash("No autorizado", "error")
        return redirect(url_for('routes.chat_index'))

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        flash("No autorizado", "error")
        return redirect(url_for('routes.director_panel', institution_id=institution_id))

    # CORREGIDO: Usar institucion_id para obtener usuarios
    try:
        # 1. Obtener profesores de la institución
        profesores = Usuario.query.filter_by(
            rol=RolUsuario.PROFESOR,
            institucion_id=institution_id
        ).all()
        
        # 2. Obtener alumnos de la institución 
        alumnos = Usuario.query.filter_by(
            rol=RolUsuario.ALUMNO,
            institucion_id=institution_id
        ).all()
        
        # 3. Obtener tutores de la institución
        tutores = Usuario.query.filter_by(
            rol=RolUsuario.TUTOR,
            institucion_id=institution_id
        ).all()
        
        # 4. Obtener padres/madres de alumnos de la institución
        padres_ids = set()
        for alumno in alumnos:
            if alumno.padre_id:
                padres_ids.add(alumno.padre_id)
            if alumno.madre_id:
                padres_ids.add(alumno.madre_id)
        
        padres = Usuario.query.filter(
            Usuario.id.in_(padres_ids)
        ).all() if padres_ids else []

        # 5. Obtener cursos de la institución
        cursos = Curso.query.filter_by(institucion_id=institution_id).all()

        # 6. Obtener lista de patologías disponibles
        patologias_disponibles = [
            {'value': p.value, 'label': p.value.replace('_', ' ').title()} 
            for p in PatologiaAlumno
        ]

        # === DEBUG INFO ===
        print(f"=== DEBUG DIRECTOR USERS ===")
        print(f"Institución ID: {institution_id}")
        print(f"Profesores encontrados: {len(profesores)}")
        print(f"Alumnos encontrados: {len(alumnos)}")
        print(f"Tutores encontrados: {len(tutores)}")
        print(f"Padres encontrados: {len(padres)}")
        print(f"Cursos disponibles: {len(cursos)}")
        print(f"Patologías disponibles: {len(patologias_disponibles)}")
        
        # Mostrar algunos detalles de cada grupo
        if profesores:
            print(f"Primeros 3 profesores: {[(p.nombre, p.email, p.activo) for p in profesores[:3]]}")
        if alumnos:
            print(f"Primeros 3 alumnos: {[(a.nombre, a.email, a.activo, a.curso_id) for a in alumnos[:3]]}")
        if tutores:
            print(f"Primeros 3 tutores: {[(t.nombre, t.email, t.activo) for t in tutores[:3]]}")
        if padres:
            print(f"Primeros 3 padres: {[(p.nombre, p.email, p.activo) for p in padres[:3]]}")
        print(f"===============================")

        return render_template('director_users.html', 
                             institucion=institucion,
                             profesores=profesores,
                             alumnos=alumnos,
                             tutores=tutores,
                             padres=padres,
                             cursos=cursos,
                             patologias_disponibles=patologias_disponibles)

    except Exception as e:
        logger.error(f"Error en director_users: {e}")
        flash("Error cargando la página de usuarios", "error")
        return redirect(url_for('routes.director_panel', institution_id=institution_id))


@routes.route('/institution/<int:institution_id>/director/users/export/<format>')
def director_export_users(institution_id, format):
    """Exportar datos de usuarios en diferentes formatos - CORREGIDO"""
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        flash("No autorizado", "error")
        return redirect(url_for('routes.chat_index'))

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        flash("No autorizado", "error")
        return redirect(url_for('routes.director_panel', institution_id=institution_id))

    # Validar formato
    valid_formats = ['excel', 'csv', 'pdf']
    if format.lower() not in valid_formats:
        flash("Formato no válido", "error")
        return redirect(url_for('routes.director_users', institution_id=institution_id))

    try:
        # CORREGIDO: Usar institucion_id para obtener usuarios
        todos_usuarios = []
        
        # Profesores
        profesores = Usuario.query.filter_by(
            rol=RolUsuario.PROFESOR,
            institucion_id=institution_id
        ).all()
        todos_usuarios.extend(profesores)
        
        # Alumnos
        alumnos = Usuario.query.filter_by(
            rol=RolUsuario.ALUMNO,
            institucion_id=institution_id
        ).all()
        todos_usuarios.extend(alumnos)
        
        # Tutores
        tutores = Usuario.query.filter_by(
            rol=RolUsuario.TUTOR,
            institucion_id=institution_id
        ).all()
        todos_usuarios.extend(tutores)
        
        # Padres/Madres
        padres_ids = set()
        for alumno in alumnos:
            if alumno.padre_id:
                padres_ids.add(alumno.padre_id)
            if alumno.madre_id:
                padres_ids.add(alumno.madre_id)
        
        if padres_ids:
            padres = Usuario.query.filter(Usuario.id.in_(padres_ids)).all()
            todos_usuarios.extend(padres)

        # Preparar datos para exportación
        datos_exportacion = []
        for usuario in todos_usuarios:
            curso_nombre = ""
            if usuario.rol == RolUsuario.ALUMNO and usuario.curso:
                curso_nombre = usuario.curso.nombre
            elif usuario.rol == RolUsuario.TUTOR:
                curso_tutor = Curso.query.filter_by(tutor_id=usuario.id, institucion_id=institution_id).first()
                if curso_tutor:
                    curso_nombre = f"Tutor de {curso_tutor.nombre}"
            elif usuario.rol == RolUsuario.PROFESOR:
                # CORREGIDO: Obtener cursos que enseña usando la tabla intermedia
                cursos_profesor = db.session.query(Curso.nombre).join(
                    profesor_curso_materia, Curso.id == profesor_curso_materia.c.curso_id
                ).filter(
                    profesor_curso_materia.c.profesor_id == usuario.id,
                    Curso.institucion_id == institution_id
                ).distinct().all()
                if cursos_profesor:
                    curso_nombre = ", ".join([c[0] for c in cursos_profesor])

            # Obtener patologías si es alumno
            patologias_str = ""
            if usuario.rol == RolUsuario.ALUMNO:
                try:
                    patologias = usuario.get_patologias()
                    if patologias:
                        patologias_list = []
                        for p in patologias:
                            if hasattr(p, 'value'):
                                patologias_list.append(p.value.replace('_', ' ').title())
                            else:
                                patologias_list.append(str(p))
                        patologias_str = ", ".join(patologias_list)
                except:
                    patologias_str = ""

            datos_exportacion.append({
                'ID': usuario.id,
                'Nombre': usuario.nombre,
                'Apellido': usuario.apellido,
                'Email': usuario.email,
                'Rol': usuario.rol.value.title(),
                'Fecha Nacimiento': usuario.fecha_nacimiento.strftime('%d/%m/%Y') if usuario.fecha_nacimiento else '',
                'Curso': curso_nombre,
                'Patologías': patologias_str,
                'Estado': 'Activo' if usuario.activo else 'Inactivo',
                'Fecha Registro': usuario.fecha_creacion.strftime('%d/%m/%Y') if usuario.fecha_creacion else ''
            })

        # Generar archivo según el formato
        if format.lower() == 'excel':
            return export_to_excel(datos_exportacion, f"usuarios_{institucion.nombre}")
        elif format.lower() == 'csv':
            return export_to_csv(datos_exportacion, f"usuarios_{institucion.nombre}")
        elif format.lower() == 'pdf':
            return export_to_pdf(datos_exportacion, f"Usuarios - {institucion.nombre}")

    except Exception as e:
        logger.error(f"Error exportando usuarios: {e}")
        flash("Error al generar el archivo de exportación", "error")
        return redirect(url_for('routes.director_users', institution_id=institution_id))


@routes.route('/institution/<int:institution_id>/director/users/invite', methods=['POST'])
def director_invite_user(institution_id):
    """Crear invitación para nuevo usuario con datos completos - MEJORADO"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403

    try:
        data = request.get_json()
        print(f"=== DATOS RECIBIDOS ===")
        print(f"Data: {data}")
        print(f"=====================")
        
        # Validar que se recibieron datos
        if not data:
            print("ERROR: No se recibieron datos JSON")
            return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400
        
        # Validar datos básicos requeridos
        required_fields = ['email', 'nombre', 'apellido', 'rol']
        for field in required_fields:
            if not data.get(field):
                print(f"ERROR: Campo requerido faltante: {field}")
                return jsonify({'success': False, 'error': f'Campo {field} es requerido'}), 400

        email = data['email'].strip().lower()
        nombre = data['nombre'].strip()
        apellido = data['apellido'].strip()
        rol_str = data['rol'].strip().upper()

        print(f"Datos procesados - Email: {email}, Nombre: {nombre}, Apellido: {apellido}, Rol: {rol_str}")

        # Verificar email único
        existing_user = Usuario.query.filter_by(email=email).first()
        if existing_user:
            print(f"ERROR: Email ya registrado: {email}")
            return jsonify({'success': False, 'error': 'Este email ya está registrado'}), 400
        
        # Verificar si ya hay una invitación pendiente
        existing_invite = InviteToken.query.filter_by(email=email).first()
        if existing_invite and existing_invite.is_valid():
            print(f"ERROR: Invitación pendiente para: {email}")
            return jsonify({'success': False, 'error': 'Ya existe una invitación pendiente para este email'}), 400

        # Convertir y validar rol
        try:
            rol = RolUsuario(rol_str.lower())
            print(f"Rol convertido exitosamente: {rol}")
        except ValueError as ve:
            print(f"ERROR: Rol inválido - {rol_str}: {ve}")
            valid_roles = [r.value for r in RolUsuario]
            return jsonify({
                'success': False, 
                'error': f'Rol inválido. Roles válidos: {valid_roles}'
            }), 400

        # Validaciones específicas por rol
        curso_id = None
        fecha_nacimiento = None
        patologias = []

        # Para ALUMNO: curso y fecha nacimiento requeridos
        if rol == RolUsuario.ALUMNO:
            print("Validando datos específicos de ALUMNO...")
            
            # Validar curso_id
            if not data.get('curso_id'):
                print("ERROR: Curso requerido para alumno")
                return jsonify({'success': False, 'error': 'Curso es requerido para alumnos'}), 400
            
            try:
                curso_id = int(data['curso_id'])
                print(f"Curso ID convertido: {curso_id}")
            except (ValueError, TypeError) as e:
                print(f"ERROR: curso_id inválido: {data.get('curso_id')} - {e}")
                return jsonify({'success': False, 'error': 'ID de curso inválido'}), 400
            
            # Verificar que el curso existe y pertenece a esta institución
            curso = Curso.query.get(curso_id)
            if not curso:
                print(f"ERROR: Curso no encontrado: {curso_id}")
                return jsonify({'success': False, 'error': 'Curso no encontrado'}), 400
            
            if curso.institucion_id != institution_id:
                print(f"ERROR: Curso no pertenece a la institución - Curso inst: {curso.institucion_id}, Actual: {institution_id}")
                return jsonify({'success': False, 'error': 'Curso no pertenece a esta institución'}), 400
            
            # Validar fecha de nacimiento
            if not data.get('fecha_nacimiento'):
                print("ERROR: Fecha de nacimiento requerida para alumno")
                return jsonify({'success': False, 'error': 'Fecha de nacimiento es requerida para alumnos'}), 400
            
            try:
                fecha_nacimiento = datetime.strptime(data['fecha_nacimiento'], '%Y-%m-%d').date()
                print(f"Fecha de nacimiento convertida: {fecha_nacimiento}")
            except ValueError as e:
                print(f"ERROR: Formato de fecha inválido: {data.get('fecha_nacimiento')} - {e}")
                return jsonify({'success': False, 'error': 'Formato de fecha inválido (usar YYYY-MM-DD)'}), 400
            
            # Procesar patologías si se proporcionan
            if data.get('patologias'):
                patologias = data['patologias']
                print(f"Patologías recibidas: {patologias}")
                
                if not isinstance(patologias, list):
                    print("ERROR: Patologías debe ser una lista")
                    return jsonify({'success': False, 'error': 'Patologías debe ser una lista'}), 400
                
                # Validar que las patologías existen
                patologias_validas = [p.value for p in PatologiaAlumno]
                for patologia in patologias:
                    if patologia not in patologias_validas:
                        print(f"ERROR: Patología inválida: {patologia}")
                        return jsonify({
                            'success': False, 
                            'error': f'Patología "{patologia}" no es válida. Válidas: {patologias_validas}'
                        }), 400

        # Para TUTOR: puede tener curso asignado
        elif rol == RolUsuario.TUTOR:
            if data.get('curso_id'):
                try:
                    curso_id = int(data['curso_id'])
                except (ValueError, TypeError):
                    return jsonify({'success': False, 'error': 'ID de curso inválido'}), 400
                    
                curso = Curso.query.get(curso_id)
                if not curso or curso.institucion_id != institution_id:
                    return jsonify({'success': False, 'error': 'Curso inválido'}), 400
                # Verificar que el curso no tiene tutor
                if curso.tutor_id:
                    return jsonify({'success': False, 'error': 'Este curso ya tiene un tutor asignado'}), 400

        # Para otros roles, fecha de nacimiento opcional pero si se proporciona debe ser válida
        elif data.get('fecha_nacimiento'):
            try:
                fecha_nacimiento = datetime.strptime(data['fecha_nacimiento'], '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'success': False, 'error': 'Formato de fecha inválido (usar YYYY-MM-DD)'}), 400

        print(f"Validaciones completadas - Creando invitación...")

        # Eliminar invitación anterior si existe
        if existing_invite:
            db.session.delete(existing_invite)
            print("Invitación anterior eliminada")

        # Crear nueva invitación con datos completos
        token = secrets.token_urlsafe(32)
        expires = datetime.utcnow() + timedelta(days=7)

        # Datos adicionales para la invitación
        datos_adicionales = {
            'curso_id': curso_id,
            'fecha_nacimiento': fecha_nacimiento.isoformat() if fecha_nacimiento else None,
            'patologias': patologias,
            'institucion_id': institution_id
        }

        print(f"Datos adicionales: {datos_adicionales}")

        invitation = InviteToken(
            email=email,
            token=token,
            rol=rol,
            nombre=nombre,
            apellido=apellido,
            fecha_expiracion=expires
        )
        
        # Usar el método para guardar datos adicionales
        invitation.set_datos_adicionales(datos_adicionales)
        
        db.session.add(invitation)
        db.session.commit()
        
        print(f"Invitación guardada en BD con ID: {invitation.id}")

        # Generar mensaje personalizado según el rol
        rol_messages = {
            RolUsuario.PROFESOR: "como profesor",
            RolUsuario.TUTOR: "como tutor",
            RolUsuario.ALUMNO: f"como alumno del curso {curso.nombre}" if curso_id else "como alumno",
            RolUsuario.PADRE: "como padre",
            RolUsuario.MADRE: "como madre"
        }

        # Enviar email de invitación
        invite_url = url_for('routes.accept_invitation', token=token, _external=True)
        
        # Intentar enviar email
        email_sent = True
        try:
            send_invitation_email(
                to_email=email,
                first_name=nombre,
                institution_name=institucion.nombre,
                role=rol_messages.get(rol, rol.value),
                invite_url=invite_url,
                expiration="7 días"
            )
            print("Email de invitación enviado exitosamente")
        except Exception as e:
            print(f"Error enviando email de invitación: {e}")
            email_sent = False

        response_message = f'Invitación creada para {nombre} {apellido} ({email}) {rol_messages.get(rol, rol.value)}'
        if not email_sent:
            response_message += '. Advertencia: El email no pudo ser enviado.'

        print(f"=== INVITACIÓN CREADA EXITOSAMENTE ===")
        print(f"Email: {email}, Rol: {rol.value}")
        print(f"Institución: {institution_id}")
        print(f"Token: {token}")
        print(f"====================================")

        return jsonify({
            'success': True,
            'message': response_message,
            'invitation_id': invitation.id,
            'invite_url': invite_url if not email_sent else None
        })

    except ValueError as ve:
        db.session.rollback()
        print(f"ValueError: {ve}")
        return jsonify({'success': False, 'error': str(ve)}), 400
    except Exception as e:
        db.session.rollback()
        print(f"Error inesperado: {e}")
        logger.error(f"Error creating invitation: {e}")
        return jsonify({'success': False, 'error': f'Error interno del servidor: {str(e)}'}), 500


@routes.route('/institution/<int:institution_id>/director/users/<int:user_id>/toggle-status', methods=['POST'])
def director_toggle_user_status(institution_id, user_id):
    """Activar/desactivar usuario - CORREGIDO"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    director = Usuario.query.get(login_session['user_id'])
    if director.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != director.id:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    try:
        usuario = Usuario.query.get_or_404(user_id)
        
        # CORREGIDO: Verificar que el usuario pertenece a la institución usando institucion_id
        user_belongs = False
        
        # Para usuarios con institucion_id directo
        if usuario.institucion_id == institution_id:
            user_belongs = True
        # Para padres/madres (verificar a través de hijos)
        elif usuario.rol in [RolUsuario.PADRE, RolUsuario.MADRE]:
            hijos = usuario.get_hijos()
            for hijo in hijos:
                if hijo.institucion_id == institution_id:
                    user_belongs = True
                    break
        
        if not user_belongs:
            return jsonify({'success': False, 'error': 'Usuario no pertenece a esta institución'}), 403
        
        # Cambiar estado
        usuario.activo = not usuario.activo
        db.session.commit()
        
        action = "activado" if usuario.activo else "desactivado"
        print(f"=== USUARIO {action.upper()} ===")
        print(f"Usuario: {usuario.email}")
        print(f"Nuevo estado: {usuario.activo}")
        print(f"=========================")
        
        return jsonify({
            'success': True,
            'message': f'Usuario {action} exitosamente',
            'new_status': usuario.activo
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error toggling user status: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500


@routes.route('/institution/<int:institution_id>/director/users/<int:user_id>/edit', methods=['GET', 'POST'])
def director_edit_user(institution_id, user_id):
    """Editar datos de usuario - CORREGIDO"""
    if 'user_id' not in login_session:
        if request.method == 'POST':
            return jsonify({'success': False, 'error': 'No autorizado'}), 401
        return redirect(url_for('routes.login'))

    director = Usuario.query.get(login_session['user_id'])
    if director.rol != RolUsuario.DIRECTOR:
        if request.method == 'POST':
            return jsonify({'success': False, 'error': 'No autorizado'}), 403
        flash("No autorizado", "error")
        return redirect(url_for('routes.chat_index'))

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != director.id:
        if request.method == 'POST':
            return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403
        flash("No autorizado", "error")
        return redirect(url_for('routes.director_panel', institution_id=institution_id))

    usuario = Usuario.query.get_or_404(user_id)

    # CORREGIDO: Verificar pertenencia usando institucion_id
    user_belongs = False
    try:
        # Para usuarios con institucion_id directo
        if usuario.institucion_id == institution_id:
            user_belongs = True
        # Para padres/madres (verificar a través de hijos)
        elif usuario.rol in [RolUsuario.PADRE, RolUsuario.MADRE]:
            hijos = usuario.get_hijos()
            for hijo in hijos:
                if hijo.institucion_id == institution_id:
                    user_belongs = True
                    break
    except Exception as e:
        logger.error(f"Error verificando pertenencia del usuario: {e}")
        user_belongs = False
    
    if not user_belongs:
        if request.method == 'POST':
            return jsonify({'success': False, 'error': 'Usuario no pertenece a esta institución'}), 403
        flash("Usuario no pertenece a esta institución", "error")
        return redirect(url_for('routes.director_users', institution_id=institution_id))

    # ========== GET REQUEST - Devolver datos del usuario ==========
    if request.method == 'GET':
        try:
            # Obtener patologías actuales si es alumno
            patologias_actuales = []
            if usuario.rol == RolUsuario.ALUMNO:
                try:
                    patologias_obj = usuario.get_patologias()
                    patologias_actuales = []
                    for p in patologias_obj:
                        if hasattr(p, 'value'):
                            patologias_actuales.append(p.value)
                        else:
                            patologias_actuales.append(str(p))
                except Exception as e:
                    logger.error(f"Error obteniendo patologías: {e}")
                    patologias_actuales = []

            # Preparar datos del usuario
            user_data = {
                'id': usuario.id,
                'nombre': usuario.nombre,
                'apellido': usuario.apellido,
                'email': usuario.email,
                'rol': usuario.rol.value,
                'rol_display': usuario.rol.value.title(),
                'activo': usuario.activo,
                'fecha_nacimiento': usuario.fecha_nacimiento.strftime('%Y-%m-%d') if usuario.fecha_nacimiento else '',
                'curso_id': usuario.curso_id if hasattr(usuario, 'curso_id') else None,
                'patologias': patologias_actuales,
                'fecha_creacion': usuario.fecha_creacion.strftime('%d/%m/%Y %H:%M') if usuario.fecha_creacion else 'N/A',
                'fecha_actualizacion': usuario.fecha_actualizacion.strftime('%d/%m/%Y %H:%M') if usuario.fecha_actualizacion else 'N/A'
            }

            # Información adicional según el rol
            if usuario.rol == RolUsuario.ALUMNO and usuario.curso:
                user_data['curso_nombre'] = usuario.curso.nombre
            elif usuario.rol == RolUsuario.TUTOR:
                curso_tutor = Curso.query.filter_by(tutor_id=usuario.id, institucion_id=institution_id).first()
                if curso_tutor:
                    user_data['curso_tutor_nombre'] = curso_tutor.nombre

            return jsonify({
                'success': True,
                'user': user_data
            })

        except Exception as e:
            logger.error(f"Error obteniendo datos del usuario: {e}")
            return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

    # ========== POST REQUEST - Actualizar usuario ==========
    if request.method == 'POST':
        try:
            data = request.get_json()
            
            if not data:
                return jsonify({'success': False, 'error': 'No se recibieron datos'}), 400

            # Validar datos básicos
            changes_made = []

            # Actualizar nombre
            if 'nombre' in data and data['nombre'].strip():
                new_nombre = data['nombre'].strip()
                if new_nombre != usuario.nombre:
                    usuario.nombre = new_nombre
                    changes_made.append('nombre')

            # Actualizar apellido
            if 'apellido' in data and data['apellido'].strip():
                new_apellido = data['apellido'].strip()
                if new_apellido != usuario.apellido:
                    usuario.apellido = new_apellido
                    changes_made.append('apellido')

            # Actualizar email
            if 'email' in data and data['email'].strip():
                new_email = data['email'].strip().lower()
                if new_email != usuario.email:
                    # Verificar que el email no esté en uso por otro usuario
                    existing = Usuario.query.filter(
                        Usuario.email == new_email,
                        Usuario.id != user_id
                    ).first()
                    if existing:
                        return jsonify({'success': False, 'error': 'Este email ya está en uso por otro usuario'}), 400
                    
                    usuario.email = new_email
                    changes_made.append('email')

            # Actualizar fecha de nacimiento (todos los roles)
            if 'fecha_nacimiento' in data and data['fecha_nacimiento']:
                try:
                    new_fecha = datetime.strptime(data['fecha_nacimiento'], '%Y-%m-%d').date()
                    if new_fecha != usuario.fecha_nacimiento:
                        usuario.fecha_nacimiento = new_fecha
                        changes_made.append('fecha de nacimiento')
                except ValueError:
                    return jsonify({'success': False, 'error': 'Formato de fecha inválido'}), 400

            # Actualizaciones específicas para ALUMNO
            if usuario.rol == RolUsuario.ALUMNO:
                # Actualizar curso
                if 'curso_id' in data:
                    new_curso_id = data['curso_id'] if data['curso_id'] else None
                    if new_curso_id != usuario.curso_id:
                        if new_curso_id:
                            # Verificar que el curso existe y pertenece a esta institución
                            curso = Curso.query.get(new_curso_id)
                            if not curso or curso.institucion_id != institution_id:
                                return jsonify({'success': False, 'error': 'Curso inválido'}), 400
                        
                        usuario.curso_id = new_curso_id
                        changes_made.append('curso')

                # Actualizar patologías
                if 'patologias' in data:
                    new_patologias = data['patologias'] if data['patologias'] else []
                    
                    # Obtener patologías actuales
                    try:
                        current_patologias = usuario.get_patologias()
                        current_patologias_values = []
                        for p in current_patologias:
                            if hasattr(p, 'value'):
                                current_patologias_values.append(p.value)
                            else:
                                current_patologias_values.append(str(p))
                    except Exception as e:
                        logger.error(f"Error obteniendo patologías actuales: {e}")
                        current_patologias_values = []

                    # Comparar si hay cambios
                    if set(new_patologias) != set(current_patologias_values):
                        # Validar que las nuevas patologías son válidas
                        patologias_validas = [p.value for p in PatologiaAlumno]
                        for patologia in new_patologias:
                            if patologia not in patologias_validas:
                                return jsonify({'success': False, 'error': f'Patología "{patologia}" no es válida'}), 400

                        # Eliminar patologías actuales
                        try:
                            for patologia in current_patologias:
                                usuario.remover_patologia(patologia)
                        except Exception as e:
                            logger.error(f"Error removiendo patologías: {e}")

                        # Agregar nuevas patologías
                        try:
                            for patologia_value in new_patologias:
                                usuario.agregar_patologia(patologia_value)
                        except Exception as e:
                            logger.error(f"Error agregando patologías: {e}")
                            return jsonify({'success': False, 'error': 'Error actualizando patologías'}), 500

                        changes_made.append('patologías')

            # Actualizar fecha de actualización
            usuario.fecha_actualizacion = datetime.utcnow()
            
            # Guardar cambios
            db.session.commit()
            
            # Preparar mensaje de respuesta
            if changes_made:
                cambios_texto = ', '.join(changes_made)
                message = f'Usuario actualizado exitosamente. Cambios realizados: {cambios_texto}'
            else:
                message = 'No se detectaron cambios en los datos del usuario'
            
            logger.info(f"Usuario {usuario.email} actualizado por director {director.email}. Cambios: {changes_made}")
            
            print(f"=== USUARIO ACTUALIZADO ===")
            print(f"Usuario: {usuario.email}")
            print(f"Cambios realizados: {changes_made}")
            print(f"===========================")
            
            return jsonify({
                'success': True,
                'message': message,
                'changes_made': changes_made
            })

        except ValueError as ve:
            db.session.rollback()
            logger.error(f"Error de validación actualizando usuario: {ve}")
            return jsonify({'success': False, 'error': str(ve)}), 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error actualizando usuario: {e}")
            return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

    # Nunca debería llegar aquí
    return jsonify({'success': False, 'error': 'Método no permitido'}), 405


# Funciones auxiliares para exportación - CORREGIDAS
def export_to_excel(data, filename):
    """Exportar datos a Excel - CORREGIDO"""
    try:
        import io
        import pandas as pd
        from flask import send_file
        
        if not data:
            # Crear DataFrame vacío con headers
            df = pd.DataFrame(columns=['ID', 'Nombre', 'Apellido', 'Email', 'Rol', 'Fecha Nacimiento', 'Curso/Asignación', 'Patologías', 'Fecha Registro'])
        else:
            # Crear DataFrame
            df = pd.DataFrame(data)
        
        # Crear archivo en memoria
        output = io.BytesIO()
        
        # Escribir a Excel usando xlsxwriter
        try:
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Usuarios')
                
                # Obtener el workbook y worksheet para formatear
                workbook = writer.book
                worksheet = writer.sheets['Usuarios']
                
                # Definir formatos
                header_format = workbook.add_format({
                    'bold': True,
                    'text_wrap': True,
                    'valign': 'top',
                    'fg_color': '#667eea',
                    'font_color': 'white',
                    'border': 1
                })
                
                cell_format = workbook.add_format({
                    'text_wrap': True,
                    'valign': 'top',
                    'border': 1
                })
                
                # Aplicar formato a headers
                for col_num, value in enumerate(df.columns.values):
                    worksheet.write(0, col_num, value, header_format)
                
                # Ajustar ancho de columnas
                column_widths = {
                    'ID': 8,
                    'Nombre': 15,
                    'Apellido': 15,
                    'Email': 25,
                    'Rol': 12,
                    'Fecha Nacimiento': 15,
                    'Curso/Asignación': 30,
                    'Patologías': 35,
                    'Fecha Registro': 15
                }
                
                for col_num, col_name in enumerate(df.columns.values):
                    width = column_widths.get(col_name, 20)
                    worksheet.set_column(col_num, col_num, width, cell_format)
                
                # Aplicar filtros
                worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)
                
                # Congelar primera fila
                worksheet.freeze_panes(1, 0)
        
        except Exception as e:
            logger.error(f"Error con xlsxwriter: {e}")
            # Fallback to openpyxl
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Usuarios')
                
                # Obtener el workbook y worksheet para formatear
                workbook = writer.book
                worksheet = writer.sheets['Usuarios']
                
                # Ajustar ancho de columnas
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'{filename}.xlsx'
        )
        
    except ImportError:
        logger.error("pandas o xlsxwriter no están instalados")
        return export_to_csv(data, filename)  # Fallback a CSV
    except Exception as e:
        logger.error(f"Error en export_to_excel: {e}")
        return export_to_csv(data, filename)  # Fallback a CSV


def export_to_csv(data, filename):
    """Exportar datos a CSV - CORREGIDO"""
    import io
    import csv
    from flask import Response
    
    output = io.StringIO()
    
    if data:
        fieldnames = data[0].keys()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        
        writer.writeheader()
        for row in data:
            # Limpiar datos para CSV
            clean_row = {}
            for key, value in row.items():
                # Convertir a string y limpiar caracteres problemáticos
                clean_value = str(value) if value is not None else ''
                clean_value = clean_value.replace('\n', ' ').replace('\r', ' ')
                clean_row[key] = clean_value
            writer.writerow(clean_row)
    else:
        # Archivo CSV vacío con headers
        fieldnames = ['ID', 'Nombre', 'Apellido', 'Email', 'Rol', 'Fecha Nacimiento', 'Curso/Asignación', 'Patologías', 'Fecha Registro']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
    
    response = Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename={filename}.csv'
        }
    )
    
    return response


def export_to_pdf(data, title):
    """Exportar datos a PDF - CORREGIDO"""
    try:
        import io
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from flask import send_file
        
        # Crear archivo en memoria
        buffer = io.BytesIO()
        
        # Configurar documento en landscape para más espacio
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
        elements = []
        
        # Estilos
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Title'],
            fontSize=18,
            textColor=colors.HexColor('#667eea'),
            spaceAfter=30,
            alignment=1  # Centrado
        )
        
        # Título
        title_para = Paragraph(title, title_style)
        elements.append(title_para)
        elements.append(Spacer(1, 12))
        
        # Preparar datos para la tabla
        if data:
            # Headers - SIN columna Estado
            headers = ['Nombre', 'Apellido', 'Email', 'Rol', 'Fecha Nac.', 'Curso', 'Fecha Registro']
            table_data = [headers]
            
            # Datos
            for row in data:
                # Truncar texto largo para que quepa en PDF
                curso_asignacion = row.get('Curso', '')
                if len(curso_asignacion) > 25:
                    curso_asignacion = curso_asignacion[:22] + '...'
                
                table_data.append([
                    row.get('Nombre', ''),
                    row.get('Apellido', ''),
                    row.get('Email', ''),
                    row.get('Rol', ''),
                    row.get('Fecha Nacimiento', ''),
                    row.get('Curso', ''),
                    row.get('Fecha Registro', '')
                ])
        else:
            # Tabla vacía
            headers = ['Nombre', 'Apellido', 'Email', 'Rol', 'Fecha Nac.', 'Curso', 'Fecha Registro']
            table_data = [headers, ['Sin datos', '', '', '', '', '', '']]
        
        # Crear tabla
        table = Table(table_data)
        
        # Estilo de tabla
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        
        elements.append(table)
        
        # Construir PDF
        doc.build(elements)
        buffer.seek(0)
        
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'{title.replace(" ", "_")}.pdf'
        )
        
    except ImportError:
        logger.error("reportlab no está instalado")
        flash("Error: La librería ReportLab no está disponible para generar PDFs", "error")
        return redirect(url_for('routes.director_users'))
    except Exception as e:
        logger.error(f"Error en export_to_pdf: {e}")
        flash("Error al generar el archivo PDF", "error")
        return redirect(url_for('routes.director_users'))

@routes.route('/institution/<int:institution_id>/director/courses')
def director_courses(institution_id):
    """Gestión de cursos y materias"""
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        flash("No autorizado", "error")
        return redirect(url_for('routes.chat_index'))

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        flash("No autorizado", "error")
        return redirect(url_for('routes.director_panel', institution_id=institution_id))

    try:
        # Obtener cursos con información de profesores por materia Y alumnos
        cursos = Curso.query.filter_by(institucion_id=institution_id).all()
        
        # Para cada curso, obtener las materias, profesores asignados Y alumnos
        for curso in cursos:
            # Asegurar que curso.materias esté inicializado
            if not hasattr(curso, 'materias'):
                curso.materias = []
                
            # Procesar materias y profesores
            for materia in curso.materias:
                try:
                    # Obtener profesor asignado a esta materia específica
                    profesor = db.session.query(Usuario).join(
                        profesor_curso_materia, Usuario.id == profesor_curso_materia.c.profesor_id
                    ).filter(
                        profesor_curso_materia.c.materia_id == materia.id,
                        profesor_curso_materia.c.curso_id == curso.id,
                        Usuario.activo == True
                    ).first()
                    
                    # Agregar profesor a la materia como atributo temporal
                    materia.profesor_asignado = profesor
                    
                except Exception as e:
                    logger.error(f"Error obteniendo profesor para materia {materia.id}: {e}")
                    materia.profesor_asignado = None
            
            # NUEVO: Obtener alumnos del curso
            try:
                # Los alumnos ya están disponibles a través de la relación curso.alumnos
                # definida en el modelo, pero vamos a asegurar que esté disponible
                if not hasattr(curso, 'alumnos'):
                    curso.alumnos = Usuario.query.filter_by(
                        curso_id=curso.id,
                        rol=RolUsuario.ALUMNO,
                        activo=True
                    ).order_by(Usuario.apellido, Usuario.nombre).all()
                
                # Debug: mostrar información de alumnos
                print(f"Curso {curso.nombre}: {len(curso.alumnos)} alumnos")
                
            except Exception as e:
                logger.error(f"Error obteniendo alumnos para curso {curso.id}: {e}")
                curso.alumnos = []
        
        # CORREGIDO: Obtener solo profesores y tutores de la institución
        profesores = Usuario.query.filter_by(
            rol=RolUsuario.PROFESOR, 
            activo=True,
            institucion_id=institution_id
        ).all()
        
        tutores = Usuario.query.filter_by(
            rol=RolUsuario.TUTOR, 
            activo=True,
            institucion_id=institution_id
        ).all()

        # NUEVO: También obtener todos los alumnos de la institución para estadísticas
        total_alumnos = Usuario.query.filter_by(
            rol=RolUsuario.ALUMNO,
            activo=True,
            institucion_id=institution_id
        ).count()

        # === DEBUG INFO ACTUALIZADO ===
        print(f"=== DEBUG DIRECTOR COURSES ===")
        print(f"Institución ID: {institution_id}")
        print(f"Total cursos: {len(cursos)}")
        print(f"Profesores disponibles: {len(profesores)}")
        print(f"Tutores disponibles: {len(tutores)}")
        print(f"Total alumnos institución: {total_alumnos}")
        for curso in cursos:
            print(f"Curso: {curso.nombre}, Materias: {len(curso.materias)}, Alumnos: {len(curso.alumnos)}")
        print(f"==================================")

        return render_template('director_courses.html', 
                             institucion=institucion,
                             cursos=cursos,
                             profesores=profesores,
                             tutores=tutores,
                             total_alumnos=total_alumnos)
                             
    except Exception as e:
        logger.error(f"Error in director_courses: {e}")
        flash("Error cargando la página de cursos", "error")
        return redirect(url_for('routes.director_panel', institution_id=institution_id))

@routes.route('/institution/<int:institution_id>/director/courses/create', methods=['POST'])
def director_create_course(institution_id):
    """Crear nuevo curso"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'no autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'error': 'no autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'error': 'no autorizado'}), 403

    try:
        data = request.get_json()
        
        # CORREGIDO: Validar que el tutor pertenezca a la institución
        tutor_id = data.get('tutor_id') if data.get('tutor_id') else None
        if tutor_id:
            tutor = Usuario.query.filter_by(
                id=tutor_id, 
                rol=RolUsuario.TUTOR,
                activo=True,
                institucion_id=institution_id
            ).first()
            if not tutor:
                return jsonify({'error': 'Tutor no válido o no pertenece a esta institución'}), 400
        
        nuevo_curso = Curso(
            nombre=data['nombre'],
            nivel=data.get('nivel', ''),
            institucion_id=institution_id,
            tutor_id=tutor_id
        )
        
        db.session.add(nuevo_curso)
        db.session.commit()
        
        print(f"=== CURSO CREADO ===")
        print(f"ID: {nuevo_curso.id}, Nombre: {nuevo_curso.nombre}")
        print(f"Institución: {institution_id}, Tutor: {tutor_id}")
        print(f"===================")
        
        return jsonify({
            'success': True,
            'message': 'Curso creado exitosamente',
            'course_id': nuevo_curso.id
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating course: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@routes.route('/institution/<int:institution_id>/director/courses/<int:course_id>/edit', methods=['POST'])
def director_edit_course(institution_id, course_id):
    """Editar curso existente"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403

    curso = Curso.query.get_or_404(course_id)
    if curso.institucion_id != institution_id:
        return jsonify({'success': False, 'error': 'Curso no pertenece a esta institución'}), 403

    try:
        data = request.get_json()
        
        # Actualizar datos del curso
        curso.nombre = data.get('nombre', curso.nombre)
        curso.nivel = data.get('nivel', curso.nivel)
        
        # CORREGIDO: Validar tutor pertenezca a la institución
        new_tutor_id = data.get('tutor_id')
        if new_tutor_id == '':  # String vacío = sin tutor
            curso.tutor_id = None
        elif new_tutor_id:
            # Verificar que el tutor existe y pertenece a la institución
            tutor = Usuario.query.filter_by(
                id=new_tutor_id, 
                rol=RolUsuario.TUTOR,
                activo=True,
                institucion_id=institution_id
            ).first()
            if not tutor:
                return jsonify({'success': False, 'error': 'Tutor inválido o no pertenece a esta institución'}), 400
            curso.tutor_id = new_tutor_id
        
        db.session.commit()
        
        print(f"=== CURSO ACTUALIZADO ===")
        print(f"ID: {curso.id}, Nombre: {curso.nombre}")
        print(f"Nuevo tutor: {curso.tutor_id}")
        print(f"========================")
        
        return jsonify({
            'success': True,
            'message': 'Curso actualizado exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating course: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500


@routes.route('/institution/<int:institution_id>/director/courses/<int:course_id>/delete', methods=['DELETE'])
def director_delete_course(institution_id, course_id):
    """Eliminar curso"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403

    curso = Curso.query.get_or_404(course_id)
    if curso.institucion_id != institution_id:
        return jsonify({'success': False, 'error': 'Curso no pertenece a esta institución'}), 403

    try:
        # CORREGIDO: Verificar alumnos usando institucion_id
        alumnos_count = Usuario.query.filter_by(
            curso_id=course_id, 
            rol=RolUsuario.ALUMNO,
            activo=True,
            institucion_id=institution_id
        ).count()
        
        if alumnos_count > 0:
            return jsonify({
                'success': False, 
                'error': f'No se puede eliminar el curso. Hay {alumnos_count} alumno(s) asignado(s)'
            }), 400

        # Verificar archivos asociados a materias del curso
        archivos_count = 0
        for materia in curso.materias:
            archivos_count += ArchivoMateria.query.filter_by(materia_id=materia.id).count()
        
        if archivos_count > 0:
            return jsonify({
                'success': False, 
                'error': f'No se puede eliminar el curso. Hay {archivos_count} archivo(s) asociado(s) a sus materias'
            }), 400

        # Eliminar materias del curso (esto eliminará también las relaciones con profesores)
        for materia in curso.materias:
            # Limpiar relaciones con profesores
            materia.profesores.clear()
            db.session.delete(materia)
        
        # Eliminar el curso
        db.session.delete(curso)
        db.session.commit()
        
        print(f"=== CURSO ELIMINADO ===")
        print(f"ID: {course_id}, Institución: {institution_id}")
        print(f"======================")
        
        return jsonify({
            'success': True,
            'message': 'Curso eliminado exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting course: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@routes.route('/institution/<int:institution_id>/director/courses/<int:course_id>/available-students')
def get_available_students(institution_id, course_id):
    """Obtener alumnos disponibles para asignar a un curso"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403

    curso = Curso.query.get_or_404(course_id)
    if curso.institucion_id != institution_id:
        return jsonify({'success': False, 'error': 'Curso no pertenece a esta institución'}), 403

    try:
        # Obtener alumnos de la institución que NO estén asignados a este curso
        alumnos_disponibles = Usuario.query.filter(
            Usuario.rol == RolUsuario.ALUMNO,
            Usuario.activo == True,
            Usuario.institucion_id == institution_id,
            or_(Usuario.curso_id == None, Usuario.curso_id != course_id)
        ).order_by(Usuario.apellido, Usuario.nombre).all()

        # Formatear respuesta
        students_data = []
        for alumno in alumnos_disponibles:
            students_data.append({
                'id': alumno.id,
                'nombre': alumno.nombre,
                'apellido': alumno.apellido,
                'email': alumno.email,
                'fecha_nacimiento': alumno.fecha_nacimiento.strftime('%Y-%m-%d') if alumno.fecha_nacimiento else None,
                'curso_actual': alumno.curso.nombre if alumno.curso else 'Sin curso'
            })

        print(f"=== ALUMNOS DISPONIBLES ===")
        print(f"Curso ID: {course_id}")
        print(f"Alumnos disponibles: {len(students_data)}")
        print(f"==============================")

        return jsonify({
            'success': True,
            'students': students_data,
            'total': len(students_data)
        })

    except Exception as e:
        logger.error(f"Error getting available students: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500


@routes.route('/institution/<int:institution_id>/director/courses/<int:course_id>/add-students', methods=['POST'])
def add_students_to_course(institution_id, course_id):
    """Asignar alumnos seleccionados a un curso"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403

    curso = Curso.query.get_or_404(course_id)
    if curso.institucion_id != institution_id:
        return jsonify({'success': False, 'error': 'Curso no pertenece a esta institución'}), 403

    try:
        data = request.get_json()
        student_ids = data.get('student_ids', [])
        
        if not student_ids:
            return jsonify({'success': False, 'error': 'No se seleccionaron alumnos'}), 400

        added_count = 0
        errors = []

        for student_id in student_ids:
            try:
                # Verificar que el alumno existe y pertenece a la institución
                alumno = Usuario.query.filter_by(
                    id=student_id,
                    rol=RolUsuario.ALUMNO,
                    activo=True,
                    institucion_id=institution_id
                ).first()

                if not alumno:
                    errors.append(f"Alumno con ID {student_id} no encontrado o no válido")
                    continue

                # Verificar si el alumno ya está en otro curso
                if alumno.curso_id and alumno.curso_id != course_id:
                    # Remover del curso anterior (opcional, dependiendo de la lógica de negocio)
                    print(f"Moviendo alumno {alumno.nombre} {alumno.apellido} del curso {alumno.curso_id} al curso {course_id}")

                # Asignar al nuevo curso
                alumno.curso_id = course_id
                added_count += 1

            except Exception as e:
                logger.error(f"Error adding student {student_id}: {e}")
                errors.append(f"Error procesando alumno {student_id}")

        db.session.commit()

        print(f"=== ALUMNOS ASIGNADOS ===")
        print(f"Curso ID: {course_id}")
        print(f"Alumnos asignados: {added_count}")
        print(f"Errores: {len(errors)}")
        print(f"========================")

        result = {
            'success': True,
            'added_count': added_count,
            'message': f'Se asignaron {added_count} alumno(s) exitosamente'
        }

        if errors:
            result['errors'] = errors
            result['message'] += f'. {len(errors)} error(es) encontrado(s)'

        return jsonify(result)

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding students to course: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500


@routes.route('/institution/<int:institution_id>/director/courses/<int:course_id>/remove-student/<int:student_id>', methods=['DELETE'])
def remove_student_from_course(institution_id, course_id, student_id):
    """Quitar un alumno específico del curso"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403

    curso = Curso.query.get_or_404(course_id)
    if curso.institucion_id != institution_id:
        return jsonify({'success': False, 'error': 'Curso no pertenece a esta institución'}), 403

    try:
        # Verificar que el alumno existe y está en este curso
        alumno = Usuario.query.filter_by(
            id=student_id,
            rol=RolUsuario.ALUMNO,
            activo=True,
            curso_id=course_id,
            institucion_id=institution_id
        ).first()

        if not alumno:
            return jsonify({
                'success': False, 
                'error': 'Alumno no encontrado o no pertenece a este curso'
            }), 404

        # Verificar si el alumno tiene tareas o actividades pendientes
        # (Opcional: puedes añadir esta validación si es necesario)
        
        # Remover del curso (establecer curso_id a None)
        alumno.curso_id = None
        db.session.commit()

        print(f"=== ALUMNO REMOVIDO ===")
        print(f"Alumno: {alumno.nombre} {alumno.apellido}")
        print(f"Removido del curso: {curso.nombre}")
        print(f"======================")

        return jsonify({
            'success': True,
            'message': f'Alumno {alumno.nombre} {alumno.apellido} removido del curso exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error removing student from course: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500


# RUTA ADICIONAL: Obtener detalles completos de alumnos de un curso (para modal expandido)
@routes.route('/institution/<int:institution_id>/director/courses/<int:course_id>/students')
def get_course_students_details(institution_id, course_id):
    """Obtener lista completa de alumnos del curso con detalles"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403

    curso = Curso.query.get_or_404(course_id)
    if curso.institucion_id != institution_id:
        return jsonify({'success': False, 'error': 'Curso no pertenece a esta institución'}), 403

    try:
        # Obtener todos los alumnos del curso
        alumnos = Usuario.query.filter_by(
            curso_id=course_id,
            rol=RolUsuario.ALUMNO,
            activo=True
        ).order_by(Usuario.apellido, Usuario.nombre).all()

        # Formatear respuesta con más detalles
        students_data = []
        for alumno in alumnos:
            # Obtener información de padres
            padres = alumno.get_padres()
            padres_info = [{'nombre': p.nombre, 'apellido': p.apellido, 'email': p.email} for p in padres]
            
            # Obtener patologías si las tiene
            patologias = []
            if alumno.is_alumno():
                try:
                    patologias = [p.value if hasattr(p, 'value') else str(p) for p in alumno.get_patologias()]
                except:
                    patologias = []

            students_data.append({
                'id': alumno.id,
                'nombre': alumno.nombre,
                'apellido': alumno.apellido,
                'email': alumno.email,
                'fecha_nacimiento': alumno.fecha_nacimiento.strftime('%Y-%m-%d') if alumno.fecha_nacimiento else None,
                'fecha_creacion': alumno.fecha_creacion.strftime('%Y-%m-%d') if alumno.fecha_creacion else None,
                'padres': padres_info,
                'patologias': patologias
            })

        return jsonify({
            'success': True,
            'students': students_data,
            'total': len(students_data),
            'curso': {
                'id': curso.id,
                'nombre': curso.nombre,
                'nivel': curso.nivel
            }
        })

    except Exception as e:
        logger.error(f"Error getting course students details: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500


# RUTA ADICIONAL: Transferir alumno entre cursos
@routes.route('/institution/<int:institution_id>/director/transfer-student', methods=['POST'])
def transfer_student_between_courses(institution_id):
    """Transferir un alumno de un curso a otro"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403

    try:
        data = request.get_json()
        student_id = data.get('student_id')
        from_course_id = data.get('from_course_id')  # Puede ser None si no tiene curso
        to_course_id = data.get('to_course_id')

        if not student_id or not to_course_id:
            return jsonify({'success': False, 'error': 'Datos incompletos'}), 400

        # Verificar alumno
        alumno = Usuario.query.filter_by(
            id=student_id,
            rol=RolUsuario.ALUMNO,
            activo=True,
            institucion_id=institution_id
        ).first()

        if not alumno:
            return jsonify({'success': False, 'error': 'Alumno no encontrado'}), 404

        # Verificar curso destino
        curso_destino = Curso.query.filter_by(
            id=to_course_id,
            institucion_id=institution_id
        ).first()

        if not curso_destino:
            return jsonify({'success': False, 'error': 'Curso destino no encontrado'}), 404

        # Realizar transferencia
        curso_origen_nombre = alumno.curso.nombre if alumno.curso else 'Sin curso'
        alumno.curso_id = to_course_id
        db.session.commit()

        print(f"=== TRANSFERENCIA ALUMNO ===")
        print(f"Alumno: {alumno.nombre} {alumno.apellido}")
        print(f"De: {curso_origen_nombre}")
        print(f"A: {curso_destino.nombre}")
        print(f"===========================")

        return jsonify({
            'success': True,
            'message': f'Alumno transferido de "{curso_origen_nombre}" a "{curso_destino.nombre}" exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error transferring student: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500
    


@routes.route('/institution/<int:institution_id>/director/subjects/<int:subject_id>/edit', methods=['POST'])
def director_edit_subject(institution_id, subject_id):
    """Editar materia existente"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403

    materia = Materia.query.get_or_404(subject_id)
    if materia.curso.institucion_id != institution_id:
        return jsonify({'success': False, 'error': 'Materia no pertenece a esta institución'}), 403

    try:
        data = request.get_json()
        
        # Actualizar datos de la materia
        materia.nombre = data.get('nombre', materia.nombre)
        materia.descripcion = data.get('descripcion', materia.descripcion)
        
        # NUEVO: Manejar asignación de profesor
        nuevo_profesor_id = data.get('profesor_id')
        
        # Obtener profesor actualmente asignado
        profesor_actual = db.session.query(Usuario).join(
            profesor_curso_materia, Usuario.id == profesor_curso_materia.c.profesor_id
        ).filter(
            profesor_curso_materia.c.materia_id == subject_id,
            profesor_curso_materia.c.curso_id == materia.curso_id,
            Usuario.activo == True
        ).first()
        
        profesor_actual_id = profesor_actual.id if profesor_actual else None
        
        # Si hay cambio en la asignación de profesor
        if str(nuevo_profesor_id or '') != str(profesor_actual_id or ''):
            
            # Remover asignación anterior si existe
            if profesor_actual_id:
                db.session.execute(
                    profesor_curso_materia.delete().where(
                        profesor_curso_materia.c.profesor_id == profesor_actual_id,
                        profesor_curso_materia.c.curso_id == materia.curso_id,
                        profesor_curso_materia.c.materia_id == subject_id
                    )
                )
                print(f"Removido profesor anterior: {profesor_actual_id}")
            
            # Asignar nuevo profesor si se especifica
            if nuevo_profesor_id:
                # Verificar que el profesor pertenece a la institución
                nuevo_profesor = Usuario.query.filter_by(
                    id=nuevo_profesor_id,
                    rol=RolUsuario.PROFESOR,
                    activo=True,
                    institucion_id=institution_id
                ).first()
                
                if not nuevo_profesor:
                    db.session.rollback()
                    return jsonify({'success': False, 'error': 'Profesor no válido o no pertenece a esta institución'}), 400
                
                # Crear nueva asignación
                nueva_asignacion = profesor_curso_materia.insert().values(
                    profesor_id=nuevo_profesor_id,
                    curso_id=materia.curso_id,
                    materia_id=subject_id
                )
                
                db.session.execute(nueva_asignacion)
                print(f"Asignado nuevo profesor: {nuevo_profesor_id}")
        
        db.session.commit()
        
        print(f"=== MATERIA ACTUALIZADA ===")
        print(f"ID: {materia.id}, Nombre: {materia.nombre}")
        print(f"Curso: {materia.curso.nombre}")
        print(f"Profesor: {nuevo_profesor_id or 'Sin asignar'}")
        print(f"==========================")
        
        return jsonify({
            'success': True,
            'message': 'Materia actualizada exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating subject: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500


@routes.route('/institution/<int:institution_id>/director/subjects/<int:subject_id>/delete', methods=['DELETE'])
def director_delete_subject(institution_id, subject_id):
    """Eliminar materia"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403

    materia = Materia.query.get_or_404(subject_id)
    if materia.curso.institucion_id != institution_id:
        return jsonify({'success': False, 'error': 'Materia no pertenece a esta institución'}), 403

    try:
        # Verificar si hay archivos subidos para esta materia
        archivos_count = ArchivoMateria.query.filter_by(materia_id=subject_id).count()
        if archivos_count > 0:
            return jsonify({
                'success': False, 
                'error': f'No se puede eliminar la materia. Hay {archivos_count} archivo(s) asociado(s)'
            }), 400
        
        # CORREGIDO: Limpiar relaciones con profesores antes de eliminar
        materia.profesores.clear()
        
        # Eliminar la materia
        db.session.delete(materia)
        db.session.commit()
        
        print(f"=== MATERIA ELIMINADA ===")
        print(f"ID: {subject_id}")
        print(f"========================")
        
        return jsonify({
            'success': True,
            'message': 'Materia eliminada exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting subject: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@routes.route('/institution/<int:institution_id>/director/courses/<int:course_id>/subjects', methods=['POST'])
def director_add_subject(institution_id, course_id):
    """Agregar materia a un curso"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'no autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'error': 'no autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'error': 'no autorizado'}), 403

    curso = Curso.query.get_or_404(course_id)
    if curso.institucion_id != institution_id:
        return jsonify({'error': 'Curso no pertenece a esta institución'}), 403

    try:
        data = request.get_json()
        
        # Verificar que no exista una materia con el mismo nombre en el curso
        materia_existente = Materia.query.filter_by(
            curso_id=course_id,
            nombre=data['nombre']
        ).first()
        
        if materia_existente:
            return jsonify({
                'error': f'Ya existe una materia llamada "{data["nombre"]}" en este curso'
            }), 400
        
        nueva_materia = Materia(
            nombre=data['nombre'],
            descripcion=data.get('descripcion', ''),
            curso_id=course_id
        )
        
        db.session.add(nueva_materia)
        db.session.flush()  # Para obtener el ID de la nueva materia
        
        # AGREGADO: Manejar asignación de profesor al crear
        profesor_id = data.get('profesor_id')
        
        if profesor_id:
            # Verificar que el profesor pertenece a la institución
            profesor = Usuario.query.filter_by(
                id=profesor_id,
                rol=RolUsuario.PROFESOR,
                activo=True,
                institucion_id=institution_id
            ).first()
            
            if not profesor:
                db.session.rollback()
                return jsonify({'error': 'Profesor no válido o no pertenece a esta institución'}), 400
            
            # Crear la asignación profesor-curso-materia
            nueva_asignacion = profesor_curso_materia.insert().values(
                profesor_id=profesor_id,
                curso_id=course_id,
                materia_id=nueva_materia.id
            )
            
            db.session.execute(nueva_asignacion)
            print(f"Profesor asignado: {profesor_id} a materia: {nueva_materia.id}")
        
        db.session.commit()
        
        print(f"=== MATERIA CREADA ===")
        print(f"ID: {nueva_materia.id}, Nombre: {nueva_materia.nombre}")
        print(f"Curso: {course_id}, Institución: {institution_id}")
        print(f"Profesor: {profesor_id or 'Sin asignar'}")
        print(f"======================")
        
        return jsonify({
            'success': True,
            'message': 'Materia creada exitosamente',
            'subject_id': nueva_materia.id
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating subject: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

# NUEVO: Ruta para asignar profesor a materia
@routes.route('/institution/<int:institution_id>/director/subjects/<int:subject_id>/assign-teacher', methods=['POST'])
def director_assign_teacher_to_subject(institution_id, subject_id):
    """Asignar profesor a una materia específica"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403

    materia = Materia.query.get_or_404(subject_id)
    if materia.curso.institucion_id != institution_id:
        return jsonify({'success': False, 'error': 'Materia no pertenece a esta institución'}), 403

    try:
        data = request.get_json()
        profesor_id = data.get('profesor_id')
        
        if not profesor_id:
            return jsonify({'success': False, 'error': 'ID de profesor requerido'}), 400
        
        # Verificar que el profesor pertenece a la institución
        profesor = Usuario.query.filter_by(
            id=profesor_id,
            rol=RolUsuario.PROFESOR,
            activo=True,
            institucion_id=institution_id
        ).first()
        
        if not profesor:
            return jsonify({'success': False, 'error': 'Profesor no válido o no pertenece a esta institución'}), 400
        
        # Verificar si ya está asignado
        ya_asignado = db.session.query(profesor_curso_materia).filter_by(
            profesor_id=profesor_id,
            curso_id=materia.curso_id,
            materia_id=subject_id
        ).first()
        
        if ya_asignado:
            return jsonify({'success': False, 'error': 'El profesor ya está asignado a esta materia'}), 400
        
        # Crear la asignación
        nueva_asignacion = profesor_curso_materia.insert().values(
            profesor_id=profesor_id,
            curso_id=materia.curso_id,
            materia_id=subject_id
        )
        
        db.session.execute(nueva_asignacion)
        db.session.commit()
        
        print(f"=== PROFESOR ASIGNADO ===")
        print(f"Profesor: {profesor.nombre} {profesor.apellido} (ID: {profesor_id})")
        print(f"Materia: {materia.nombre} (ID: {subject_id})")
        print(f"Curso: {materia.curso.nombre}")
        print(f"========================")
        
        return jsonify({
            'success': True,
            'message': f'Profesor {profesor.nombre} {profesor.apellido} asignado exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error assigning teacher to subject: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

# NUEVO: Ruta para remover profesor de materia
@routes.route('/institution/<int:institution_id>/director/subjects/<int:subject_id>/remove-teacher/<int:teacher_id>', methods=['DELETE'])
def director_remove_teacher_from_subject(institution_id, subject_id, teacher_id):
    """Remover profesor de una materia específica"""
    if 'user_id' not in login_session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'success': False, 'error': 'No autorizado para esta institución'}), 403

    materia = Materia.query.get_or_404(subject_id)
    if materia.curso.institucion_id != institution_id:
        return jsonify({'success': False, 'error': 'Materia no pertenece a esta institución'}), 403

    try:
        # Eliminar la asignación
        db.session.execute(
            profesor_curso_materia.delete().where(
                profesor_curso_materia.c.profesor_id == teacher_id,
                profesor_curso_materia.c.curso_id == materia.curso_id,
                profesor_curso_materia.c.materia_id == subject_id
            )
        )
        
        db.session.commit()
        
        profesor = Usuario.query.get(teacher_id)
        print(f"=== PROFESOR REMOVIDO ===")
        print(f"Profesor: {profesor.nombre if profesor else 'Desconocido'} (ID: {teacher_id})")
        print(f"Materia: {materia.nombre} (ID: {subject_id})")
        print(f"=========================")
        
        return jsonify({
            'success': True,
            'message': 'Profesor removido exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error removing teacher from subject: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500

@routes.route('/institution/<int:institution_id>/director/analytics')
def director_analytics(institution_id):
    """Panel principal de analíticas"""
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        flash("No autorizado", "error")
        return redirect(url_for('routes.chat_index'))

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        flash("No autorizado", "error")
        return redirect(url_for('routes.director_panel', institution_id=institution_id))

    return render_template('director_analytics.html', institucion=institucion)


@routes.route('/api/institution/<int:institution_id>/director/analytics/comprehension')
def director_analytics_comprehension(institution_id):
    """API para analíticas de comprensión"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'no autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'error': 'no autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'error': 'no autorizado'}), 403

    try:
        # Parámetros de filtro
        curso_id = request.args.get('curso_id', type=int)
        materia_id = request.args.get('materia_id', type=int)
        alumno_id = request.args.get('alumno_id', type=int)
        fecha_inicio = request.args.get('fecha_inicio')
        fecha_fin = request.args.get('fecha_fin')

        # Obtener cursos de la institución
        cursos = Curso.query.filter_by(institucion_id=institution_id).all()
        curso_ids = [c.id for c in cursos]

        # Query base
        query = db.session.query(AnalyticaComprension).join(Usuario).filter(
            Usuario.curso_id.in_(curso_ids)
        )

        # Aplicar filtros
        if curso_id:
            query = query.filter(AnalyticaComprension.curso_id == curso_id)
        if materia_id:
            query = query.filter(AnalyticaComprension.materia_id == materia_id)
        if alumno_id:
            query = query.filter(AnalyticaComprension.alumno_id == alumno_id)
        if fecha_inicio:
            fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d').date()
            query = query.filter(AnalyticaComprension.periodo_inicio >= fecha_inicio_dt)
        if fecha_fin:
            fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d').date()
            query = query.filter(AnalyticaComprension.periodo_fin <= fecha_fin_dt)

        analiticas = query.all()
        
        # Procesar datos
        result = []
        for analytic in analiticas:
            result.append({
                'alumno_id': analytic.alumno_id,
                'alumno_nombre': f"{analytic.alumno.nombre} {analytic.alumno.apellido}",
                'materia_nombre': analytic.materia.nombre if analytic.materia else 'Todas',
                'curso_nombre': analytic.curso.nombre if analytic.curso else 'Todos',
                'promedio_comprension': analytic.promedio_comprension,
                'total_interacciones': analytic.total_interacciones,
                'fecha_calculo': analytic.fecha_calculo.isoformat(),
                'periodo_inicio': analytic.periodo_inicio.isoformat() if analytic.periodo_inicio else None,
                'periodo_fin': analytic.periodo_fin.isoformat() if analytic.periodo_fin else None
            })

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error getting comprehension analytics: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500


@routes.route('/api/institution/<int:institution_id>/director/analytics/sensitive-content')
def director_analytics_sensitive(institution_id):
    """API para analíticas de contenido sensible"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'no autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'error': 'no autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'error': 'no autorizado'}), 403

    try:
        # Obtener alumnos de la institución
        cursos = Curso.query.filter_by(institucion_id=institution_id).all()
        curso_ids = [c.id for c in cursos]
        alumnos = Usuario.query.filter(
            Usuario.curso_id.in_(curso_ids),
            Usuario.rol == RolUsuario.ALUMNO
        ).all()
        alumno_ids = [a.id for a in alumnos]

        # Parámetros de filtro
        fecha_inicio = request.args.get('fecha_inicio')
        fecha_fin = request.args.get('fecha_fin')
        tipo_contenido = request.args.get('tipo_contenido')
        nivel_riesgo = request.args.get('nivel_riesgo')

        # Query
        query = AlertaContenidoSensible.query.filter(
            AlertaContenidoSensible.alumno_id.in_(alumno_ids)
        )

        if fecha_inicio:
            fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
            query = query.filter(AlertaContenidoSensible.fecha_alerta >= fecha_inicio_dt)
        if fecha_fin:
            fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d')
            query = query.filter(AlertaContenidoSensible.fecha_alerta <= fecha_fin_dt)
        if tipo_contenido:
            query = query.filter(AlertaContenidoSensible.tipo_contenido == tipo_contenido)
        if nivel_riesgo:
            query = query.filter(AlertaContenidoSensible.nivel_riesgo == nivel_riesgo)

        alertas = query.order_by(AlertaContenidoSensible.fecha_alerta.desc()).all()

        result = []
        for alerta in alertas:
            result.append({
                'id': alerta.id,
                'alumno_nombre': f"{alerta.alumno.nombre} {alerta.alumno.apellido}",
                'tipo_contenido': alerta.tipo_contenido,
                'contexto': alerta.contexto[:200] + '...' if len(alerta.contexto) > 200 else alerta.contexto,
                'nivel_riesgo': alerta.nivel_riesgo,
                'fecha_alerta': alerta.fecha_alerta.isoformat(),
                'revisada': alerta.revisada
            })

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error getting sensitive content analytics: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500


@routes.route('/api/institution/<int:institution_id>/director/analytics/learning-questions')
def director_analytics_learning_questions(institution_id):
    """API para analíticas de 'Aprendiendo a preguntar'"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'no autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'error': 'no autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'error': 'no autorizado'}), 403

    try:
        # Obtener alumnos de la institución
        cursos = Curso.query.filter_by(institucion_id=institution_id).all()
        curso_ids = [c.id for c in cursos]
        alumnos = Usuario.query.filter(
            Usuario.curso_id.in_(curso_ids),
            Usuario.rol == RolUsuario.ALUMNO
        ).all()
        alumno_ids = [a.id for a in alumnos]

        # Query sesiones
        sesiones = SesionAprendiendoPreguntar.query.filter(
            SesionAprendiendoPreguntar.alumno_id.in_(alumno_ids)
        ).order_by(SesionAprendiendoPreguntar.fecha_sesion.desc()).all()

        result = []
        for sesion in sesiones:
            result.append({
                'id': sesion.id,
                'alumno_nombre': f"{sesion.alumno.nombre} {sesion.alumno.apellido}",
                'tema': sesion.tema,
                'pregunta_alumno': sesion.pregunta_alumno[:100] + '...' if sesion.pregunta_alumno and len(sesion.pregunta_alumno) > 100 else sesion.pregunta_alumno,
                'exito_sesion': sesion.exito_sesion,
                'fecha_sesion': sesion.fecha_sesion.isoformat()
            })

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error getting learning questions analytics: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500


@routes.route('/api/institution/<int:institution_id>/director/analytics/file-utility')
def director_analytics_file_utility(institution_id):
    """API para analíticas de utilidad de archivos subidos por profesores"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'no autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if user.rol != RolUsuario.DIRECTOR:
        return jsonify({'error': 'no autorizado'}), 403

    institucion = Institucion.query.get_or_404(institution_id)
    if institucion.director_id != user.id:
        return jsonify({'error': 'no autorizado'}), 403

    try:
        # Obtener archivos de materias de la institución
        archivos = db.session.query(ArchivoMateria).join(Materia).join(Curso).filter(
            Curso.institucion_id == institution_id
        ).order_by(ArchivoMateria.fecha_subida.desc()).all()

        result = []
        for archivo in archivos:
            profesor = Usuario.query.get(archivo.profesor_id)
            result.append({
                'id': archivo.id,
                'nombre_tema': archivo.nombre_tema,
                'profesor_nombre': f"{profesor.nombre} {profesor.apellido}" if profesor else 'N/A',
                'materia_nombre': archivo.materia.nombre,
                'curso_nombre': archivo.materia.curso.nombre,
                'utilidad_ia_score': archivo.utilidad_ia_score,
                'fecha_subida': archivo.fecha_subida.isoformat(),
                'tareas_generadas': len(archivo.tareas_generadas)
            })

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error getting file utility analytics: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500





#======================================
#          RUTAS DEL PROFESOR
#======================================
@routes.route('/profesor/panel')
def profesor_panel():
    """Panel principal del profesor"""
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))

    user = Usuario.query.get(login_session['user_id'])

    if not user or user.rol != RolUsuario.PROFESOR:
        flash("No autorizado", "error")
        return redirect(url_for('routes.login'))

# Obtener institución del profesor
    institucion = user.get_institucion()
    if not institucion:
        flash("Profesor no asignado a una institución", "error")
        return redirect(url_for('routes.login'))

    # Obtener cursos y materias del profesor
    # El profesor puede estar asignado a múltiples cursos y materias
    cursos_materias = db.session.query(Curso, Materia)\
        .join(Materia, Curso.id == Materia.curso_id)\
        .join(profesor_curso_materia)\
        .filter(profesor_curso_materia.c.profesor_id == user.id)\
        .all()

    # Organizar datos por curso
    cursos_dict = {}
    for curso, materia in cursos_materias:
        if curso.id not in cursos_dict:
            cursos_dict[curso.id] = {
                'curso': curso,
                'materias': []
            }
        cursos_dict[curso.id]['materias'].append(materia)

    # Obtener archivos subidos por este profesor
    archivos_recientes = ArchivoMateria.query\
        .filter_by(profesor_id=user.id)\
        .order_by(ArchivoMateria.fecha_subida.desc())\
        .limit(10)\
        .all()

    # Estadísticas para el dashboard
    total_archivos = ArchivoMateria.query.filter_by(profesor_id=user.id).count()
    
    # Archivos de este mes
    from datetime import datetime, timedelta
    inicio_mes = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    archivos_este_mes = ArchivoMateria.query\
        .filter(ArchivoMateria.profesor_id == user.id)\
        .filter(ArchivoMateria.fecha_subida >= inicio_mes)\
        .count()

    # Total de alumnos en los cursos del profesor
    total_alumnos = db.session.query(Usuario)\
        .join(Curso, Usuario.curso_id == Curso.id)\
        .join(Materia, Curso.id == Materia.curso_id)\
        .join(profesor_curso_materia)\
        .filter(profesor_curso_materia.c.profesor_id == user.id)\
        .filter(Usuario.rol == RolUsuario.ALUMNO)\
        .distinct(Usuario.id)\
        .count()

    # Promedio de utilidad IA
    archivos_con_score = ArchivoMateria.query\
        .filter_by(profesor_id=user.id)\
        .filter(ArchivoMateria.utilidad_ia_score > 0)\
        .all()
    
    promedio_utilidad = 0
    if archivos_con_score:
        promedio_utilidad = round(sum(a.utilidad_ia_score for a in archivos_con_score) / len(archivos_con_score), 1)

    # Archivos más populares (basado en utilidad_ia_score)
    archivos_populares = ArchivoMateria.query\
        .filter_by(profesor_id=user.id)\
        .filter(ArchivoMateria.utilidad_ia_score > 0)\
        .order_by(ArchivoMateria.utilidad_ia_score.desc())\
        .limit(5)\
        .all()

    # Actividades recientes (simuladas - puedes expandir esto)
    actividades_recientes = []
    for archivo in archivos_recientes[:5]:
        actividades_recientes.append({
            'titulo': f'Archivo subido: {archivo.nombre_tema}',
            'descripcion': f'En {archivo.materia.nombre}',
            'fecha': archivo.fecha_subida,
            'icono': 'fa-upload'
        })

    # Alertas del sistema (opcional)
    alertas = []
    archivos_sin_procesar = ArchivoMateria.query\
        .filter_by(profesor_id=user.id)\
        .filter(ArchivoMateria.texto_extraido == None)\
        .count()
    
    if archivos_sin_procesar > 0:
        alertas.append({
            'tipo': 'warning',
            'mensaje': f'Tienes {archivos_sin_procesar} archivo(s) pendiente(s) de procesar',
            'accion': 'Procesar ahora'
        })

    return render_template('profesor_panel.html', 
                         cursos_materias=cursos_dict,
                         archivos_recientes=archivos_recientes,
                         institucion=institucion,
                         user_name=user.nombre,
                         total_archivos=total_archivos,
                         archivos_este_mes=archivos_este_mes,
                         total_alumnos=total_alumnos,
                         promedio_utilidad=promedio_utilidad,
                         archivos_populares=archivos_populares,
                         actividades_recientes=actividades_recientes,
                         alertas=alertas)


@routes.route('/profesor/materia/<int:materia_id>')
def profesor_materia_detalle(materia_id):
    """Detalle de una materia específica"""
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))

    user = Usuario.query.get(login_session['user_id'])
    if not user or user.rol != RolUsuario.PROFESOR:
        flash("No autorizado", "error")
        return redirect(url_for('routes.chat_index'))

    # Verificar que el profesor tiene acceso a esta materia
    materia = db.session.query(Materia)\
        .join(profesor_curso_materia)\
        .filter(
            profesor_curso_materia.c.profesor_id == user.id,
            profesor_curso_materia.c.materia_id == materia_id
        ).first()

    if not materia:
        flash("No tienes acceso a esta materia", "error")
        return redirect(url_for('routes.profesor_panel'))

    # Obtener archivos de esta materia
    archivos = ArchivoMateria.query\
        .filter_by(materia_id=materia_id, profesor_id=user.id)\
        .order_by(ArchivoMateria.fecha_subida.desc())\
        .all()

    # Obtener tareas de esta materia
    tareas = Tarea.query\
        .filter_by(materia_id=materia_id, profesor_id=user.id)\
        .order_by(Tarea.fecha_creacion.desc())\
        .all()

    return render_template('profesor_materia.html', 
                         materia=materia, 
                         archivos=archivos,
                         tareas=tareas)


@routes.route('/profesor/subir_archivo', methods=['POST'])
def profesor_subir_archivo():
    """Subir archivo a una materia"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if not user or user.rol != RolUsuario.PROFESOR:
        return jsonify({'error': 'No autorizado'}), 403

    try:
        # Validar datos del formulario
        materia_id = request.form.get('materia_id')
        nombre_tema = request.form.get('nombre_tema', '').strip()
        notas_adicionales = request.form.get('notas_adicionales', '').strip()
        instrucciones_ensenanza = request.form.get('instrucciones_ensenanza', '').strip()

        if not materia_id or not nombre_tema:
            return jsonify({'error': 'Materia y nombre del tema son obligatorios'}), 400

        # Verificar que el profesor tiene acceso a esta materia
        materia = db.session.query(Materia)\
            .join(profesor_curso_materia)\
            .filter(
                profesor_curso_materia.c.profesor_id == user.id,
                profesor_curso_materia.c.materia_id == int(materia_id)
            ).first()

        if not materia:
            return jsonify({'error': 'No tienes acceso a esta materia'}), 403

        # Validar archivo
        if 'archivo' not in request.files:
            return jsonify({'error': 'No se seleccionó ningún archivo'}), 400

        archivo = request.files['archivo']
        if archivo.filename == '':
            return jsonify({'error': 'No se seleccionó ningún archivo'}), 400

        if not allowed_file(archivo.filename):
            return jsonify({'error': 'Tipo de archivo no permitido'}), 400

        # Obtener institución del profesor
        institucion = user.get_institucion()
        if not institucion:
            return jsonify({'error': 'Profesor no asignado a una institución'}), 400

        # Crear estructura de carpetas: uploads/(institución)/(curso)/(materia)/
        carpeta_institucion = secure_filename(institucion.nombre)
        carpeta_curso = secure_filename(materia.curso.nombre)
        carpeta_materia = secure_filename(materia.nombre)

        upload_dir = os.path.join(
            current_app.config.get('UPLOAD_ROOT', 'uploads'),
            carpeta_institucion,
            carpeta_curso,
            carpeta_materia
        )

        # Crear directorio si no existe
        os.makedirs(upload_dir, exist_ok=True)

        # Generar nombre único para el archivo
        filename = secure_filename(archivo.filename)
        nombre_base, extension = os.path.splitext(filename)
        filename_unico = f"{nombre_base}_{secrets.token_hex(8)}{extension}"
        
        archivo_path = os.path.join(upload_dir, filename_unico)

        # Guardar archivo
        archivo.save(archivo_path)

        # Crear registro en base de datos
        archivo_materia = ArchivoMateria(
            nombre_tema=nombre_tema,
            archivo_path=archivo_path,
            notas_adicionales=notas_adicionales if notas_adicionales else None,
            instrucciones_ensenanza=instrucciones_ensenanza if instrucciones_ensenanza else None,
            materia_id=int(materia_id),
            profesor_id=user.id
        )

        db.session.add(archivo_materia)
        db.session.flush()  # Para obtener el ID

        # Procesar archivo con file_reader.py
        try:
            texto_extraido = procesar_archivo(archivo_path)
            
            if texto_extraido and not texto_extraido.startswith('[Error'):
                archivo_materia.texto_extraido = texto_extraido
            else:
                archivo_materia.texto_extraido = f"[Error] No se pudo extraer texto: {texto_extraido or 'Formato no soportado'}"
                
        except ImportError:
            archivo_materia.texto_extraido = "[Error] Módulo file_reader no disponible"
        except Exception as e:
            logger.error(f"Error procesando archivo {archivo_path}: {e}")
            archivo_materia.texto_extraido = f"[Error] Error procesando archivo: {str(e)}"

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Archivo subido y procesado exitosamente',
            'archivo_id': archivo_materia.id,
            'procesado': archivo_materia.esta_procesado()
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error subiendo archivo: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500


@routes.route('/profesor/archivo/<int:archivo_id>')
def profesor_ver_archivo(archivo_id):
    """Ver detalles de un archivo"""
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))

    user = Usuario.query.get(login_session['user_id'])
    if not user or user.rol != RolUsuario.PROFESOR:
        flash("No autorizado", "error")
        return redirect(url_for('routes.chat_index'))

    # Obtener archivo y verificar permisos
    archivo = ArchivoMateria.query.filter_by(
        id=archivo_id, 
        profesor_id=user.id
    ).first()

    if not archivo:
        flash("Archivo no encontrado", "error")
        return redirect(url_for('routes.profesor_panel'))

    return render_template('profesor_archivo_detalle.html', archivo=archivo)


@routes.route('/profesor/archivo/<int:archivo_id>/editar', methods=['POST'])
def profesor_editar_archivo(archivo_id):
    """Editar metadatos de un archivo"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if not user or user.rol != RolUsuario.PROFESOR:
        return jsonify({'error': 'No autorizado'}), 403

    try:
        # Obtener archivo y verificar permisos
        archivo = ArchivoMateria.query.filter_by(
            id=archivo_id, 
            profesor_id=user.id
        ).first()

        if not archivo:
            return jsonify({'error': 'Archivo no encontrado'}), 404

        # Actualizar campos
        data = request.get_json()
        
        if 'nombre_tema' in data:
            archivo.nombre_tema = data['nombre_tema'].strip()
        
        if 'notas_adicionales' in data:
            archivo.notas_adicionales = data['notas_adicionales'].strip() or None
        
        if 'instrucciones_ensenanza' in data:
            archivo.instrucciones_ensenanza = data['instrucciones_ensenanza'].strip() or None

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Archivo actualizado exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error editando archivo: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500


@routes.route('/profesor/archivo/<int:archivo_id>/eliminar', methods=['DELETE'])
def profesor_eliminar_archivo(archivo_id):
    """Eliminar un archivo"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if not user or user.rol != RolUsuario.PROFESOR:
        return jsonify({'error': 'No autorizado'}), 403

    try:
        # Obtener archivo y verificar permisos
        archivo = ArchivoMateria.query.filter_by(
            id=archivo_id, 
            profesor_id=user.id
        ).first()

        if not archivo:
            return jsonify({'error': 'Archivo no encontrado'}), 404

        # Eliminar archivo físico
        try:
            if os.path.exists(archivo.archivo_path):
                os.remove(archivo.archivo_path)
        except Exception as e:
            logger.warning(f"No se pudo eliminar archivo físico {archivo.archivo_path}: {e}")

        # Eliminar registro de base de datos
        db.session.delete(archivo)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Archivo eliminado exitosamente'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error eliminando archivo: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500


@routes.route('/profesor/reprocesar_archivo/<int:archivo_id>', methods=['POST'])
def profesor_reprocesar_archivo(archivo_id):
    """Reprocesar un archivo con file_reader.py"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'No autorizado'}), 401

    user = Usuario.query.get(login_session['user_id'])
    if not user or user.rol != RolUsuario.PROFESOR:
        return jsonify({'error': 'No autorizado'}), 403

    try:
        # Obtener archivo y verificar permisos
        archivo = ArchivoMateria.query.filter_by(
            id=archivo_id, 
            profesor_id=user.id
        ).first()

        if not archivo:
            return jsonify({'error': 'Archivo no encontrado'}), 404

        # Verificar que el archivo físico existe
        if not os.path.exists(archivo.archivo_path):
            return jsonify({'error': 'Archivo físico no encontrado'}), 404

        # Reprocesar archivo
        try:
            texto_extraido = procesar_archivo(archivo.archivo_path)
            
            if texto_extraido and not texto_extraido.startswith('[Error'):
                archivo.texto_extraido = texto_extraido
                mensaje = 'Archivo reprocesado exitosamente'
                procesado = True
            else:
                archivo.texto_extraido = f"[Error] No se pudo extraer texto: {texto_extraido or 'Formato no soportado'}"
                mensaje = 'Error al reprocesar archivo'
                procesado = False
                
        except ImportError:
            archivo.texto_extraido = "[Error] Módulo file_reader no disponible"
            mensaje = 'Módulo de procesamiento no disponible'
            procesado = False
        except Exception as e:
            logger.error(f"Error reprocesando archivo {archivo.archivo_path}: {e}")
            archivo.texto_extraido = f"[Error] Error procesando archivo: {str(e)}"
            mensaje = 'Error al reprocesar archivo'
            procesado = False

        db.session.commit()

        return jsonify({
            'success': procesado,
            'message': mensaje,
            'procesado': procesado,
            'texto_preview': archivo.get_resumen_texto(300) if procesado else None
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error reprocesando archivo: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500





#======================================
#           RUTAS DEL ALUMNO
#======================================
@routes.route('/alumno/panel')
def alumno_panel():
    """Panel principal para alumnos"""
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))
    
    user = Usuario.query.get(login_session['user_id'])
    if not user or user.rol not in [RolUsuario.ALUMNO, RolUsuario.PADRE, RolUsuario.MADRE]:
        flash("Acceso no autorizado", "error")
        return redirect(url_for('routes.login'))
    
    try:
        # Obtener datos del alumno
        chats_recientes = chat_ia_universal.obtener_chats_usuario(user.id)[:5]  # Últimos 5 chats
        
        # Obtener materias del alumno
        materias = []
        if hasattr(user, 'cursos') and user.cursos:
            for curso in user.cursos:
                materias_curso = Materia.query.filter_by(curso_id=curso.id).all()
                for materia in materias_curso:
                    materias.append({
                        'nombre': materia.nombre,
                        'curso': curso.nombre,
                        'descripcion': materia.descripcion
                    })
        
        # Obtener archivos de estudio disponibles
        archivos_disponibles = []
        if hasattr(user, 'cursos') and user.cursos:
            for curso in user.cursos:
                archivos_curso = ArchivoMateria.query.filter_by(
                    curso_id=curso.id
                ).order_by(
                    ArchivoMateria.fecha_subida.desc()
                ).limit(10).all()
                
                for archivo in archivos_curso:
                    archivos_disponibles.append({
                        'tema': archivo.nombre_tema,
                        'materia': archivo.materia.nombre if archivo.materia else 'Sin materia',
                        'fecha': archivo.fecha_subida.strftime('%d/%m/%Y'),
                        'profesor': archivo.profesor.nombre if archivo.profesor else 'Sin profesor'
                    })
        
        return render_template('alumno_panel.html', 
                             chats_recientes=chats_recientes,
                             materias=materias,
                             archivos_disponibles=archivos_disponibles,
                             user_name=user.nombre,
                             user_role=user.rol.value if hasattr(user.rol, 'value') else str(user.rol))
                             
    except Exception as e:
        logger.error(f"Error en panel del alumno: {e}")
        flash("Error cargando el panel", "error")
        return redirect(url_for('routes.chat_index'))





#======================================
#          RUTAS DE LA IA
#======================================
@routes.route('/chat')
def chat_index():
    """Página principal del chat para cualquier usuario autenticado"""
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))
    
    user = Usuario.query.get(login_session['user_id'])
    if not user:
        flash("Usuario no encontrado", "error")
        return redirect(url_for('routes.login'))
    
    # Obtener chats existentes
    chats = chat_ia_universal.obtener_chats_usuario(user.id)
    
    # Determinar el template según el rol
    template_name = 'profesor_chat.html' if user.rol == RolUsuario.PROFESOR else 'alumno_chat.html'
    
    return render_template(template_name, 
                         chats=chats, 
                         user_name=user.nombre,
                         user_role=user.rol.value if hasattr(user.rol, 'value') else str(user.rol))

@routes.route('/chat/nuevo', methods=['POST'])
def crear_chat():
    """Crea un nuevo chat para cualquier usuario"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'No autorizado'}), 401
    
    user = Usuario.query.get(login_session['user_id'])
    if not user:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    
    try:
        data = request.get_json()
        nombre_chat = data.get('nombre', '') if data else ''
        
        chat = chat_ia_universal.crear_chat(user.id, nombre_chat)
        
        if chat:
            return jsonify({
                'success': True,
                'chat_id': chat.id,
                'nombre': chat.nombre_chat
            })
        else:
            return jsonify({'error': 'Error creando chat'}), 500
            
    except Exception as e:
        logger.error(f"Error en crear_chat: {e}")
        return jsonify({'error': 'Error interno'}), 500

@routes.route('/chat/<int:chat_id>')
def ver_chat(chat_id):
    """Ver un chat específico para cualquier usuario"""
    if 'user_id' not in login_session:
        return redirect(url_for('routes.login'))
    
    user = Usuario.query.get(login_session['user_id'])
    if not user:
        flash("Usuario no encontrado", "error")
        return redirect(url_for('routes.login'))
    
    # Verificar que el chat pertenece al usuario
    chat = ChatIA.query.filter_by(
        id=chat_id, 
        usuario_id=user.id
    ).first()
    
    if not chat:
        flash("Chat no encontrado", "error")
        return redirect(url_for('routes.chat_index'))
    
    # Obtener mensajes del chat
    mensajes = chat_ia_universal.obtener_mensajes_chat(chat_id)
    
    # Obtener todos los chats para el sidebar
    chats = chat_ia_universal.obtener_chats_usuario(user.id)
    
    # Determinar el template según el rol
    template_name = 'profesor_chat.html' if user.rol == RolUsuario.PROFESOR else 'alumno_chat.html'
    
    return render_template(template_name, 
                         chats=chats,
                         chat_actual=chat,
                         mensajes=mensajes,
                         user_name=user.nombre,
                         user_role=user.rol.value if hasattr(user.rol, 'value') else str(user.rol))

@routes.route('/chat/<int:chat_id>/mensaje', methods=['POST'])
def enviar_mensaje(chat_id):
    """Envía un mensaje en el chat para cualquier usuario"""
    logger.info(f"=== INICIO enviar_mensaje - Chat ID: {chat_id} ===")
    
    if 'user_id' not in login_session:
        logger.warning("Usuario no autenticado")
        return jsonify({'error': 'No autorizado'}), 401
    
    user_id = login_session['user_id']
    logger.info(f"Usuario autenticado: {user_id}")
    
    user = Usuario.query.get(user_id)
    if not user:
        logger.error(f"Usuario {user_id} no encontrado en BD")
        return jsonify({'error': 'Usuario no encontrado'}), 404
    
    logger.info(f"Usuario encontrado: {user.nombre} - Rol: {user.rol}")
    
    try:
        # Debug del request
        logger.info(f"Content-Type: {request.content_type}")
        logger.info(f"Request method: {request.method}")
        logger.info(f"Request headers: {dict(request.headers)}")
        
        # Verificar JSON
        if not request.is_json:
            logger.error("Request no es JSON")
            return jsonify({'error': 'Content-Type debe ser application/json'}), 400
        
        data = request.get_json()
        if data is None:
            logger.error("No se pudo parsear JSON")
            return jsonify({'error': 'JSON inválido'}), 400
        
        logger.info(f"Datos recibidos: {data}")
        
        contenido = data.get('contenido', '').strip()
        
        if not contenido:
            logger.warning("Mensaje vacío")
            return jsonify({'error': 'Mensaje vacío'}), 400
        
        logger.info(f"Contenido del mensaje: {contenido[:100]}...")
        
        # Verificar estado del cliente IA
        logger.info(f"Cliente IA inicializado: {chat_ia_universal.client is not None}")
        if not chat_ia_universal.client:
            logger.error("Cliente de Groq no inicializado")
            return jsonify({'error': 'Servicio de IA no disponible'}), 503
        
        # Verificar variables de entorno críticas
        api_key_presente = bool(os.getenv('GROQ_API_KEY'))
        logger.info(f"GROQ_API_KEY presente: {api_key_presente}")
        
        # Verificar chat
        try:
            chat = ChatIA.query.filter_by(id=chat_id, usuario_id=user.id).first()
            if not chat:
                logger.error(f"Chat {chat_id} no encontrado para usuario {user.id}")
                return jsonify({'error': 'Chat no encontrado o no autorizado'}), 404
            logger.info(f"Chat encontrado: {chat.nombre_chat}")
        except Exception as db_error:
            logger.error(f"Error consultando chat: {db_error}")
            return jsonify({'error': 'Error de base de datos'}), 500
        
        # Intentar enviar mensaje
        logger.info("Llamando a chat_ia_universal.enviar_mensaje...")
        success, respuesta = chat_ia_universal.enviar_mensaje(chat_id, contenido, user)
        
        logger.info(f"Resultado enviar_mensaje - Success: {success}")
        logger.info(f"Respuesta obtenida: {str(respuesta)[:200]}...")
        
        if success:
            logger.info("Mensaje enviado exitosamente")
            return jsonify({
                'success': True,
                'respuesta': respuesta
            })
        else:
            logger.error(f"Error en enviar_mensaje: {respuesta}")
            return jsonify({'error': respuesta or 'Error desconocido'}), 500
            
    except Exception as e:
        logger.error(f"Error inesperado: {str(e)}", exc_info=True)
        return jsonify({'error': f'Error interno: {str(e)}'}), 500
    
    finally:
        logger.info("=== FIN enviar_mensaje ===")

# También añadir un endpoint de diagnóstico
@routes.route('/debug/chat-ia-status', methods=['GET'])
def debug_chat_ia_status():
    """Endpoint para diagnosticar el estado del sistema de chat IA"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'No autorizado'}), 401
    
    status = {
        'groq_client_initialized': chat_ia_universal.client is not None,
        'groq_api_key_present': bool(os.getenv('GROQ_API_KEY')),
        'groq_model': os.getenv('GROQ_MODEL', 'No configurado'),
        'database_accessible': False,
        'environment_vars': {}
    }
    
    # Verificar base de datos
    try:
        test_count = Usuario.query.count()
        status['database_accessible'] = True
        status['users_count'] = test_count
    except Exception as e:
        status['database_error'] = str(e)
    
    # Variables de entorno (sin mostrar valores sensibles)
    env_vars = ['NOMBRE', 'LIMITACIONES', 'ROL_IA_ALUMNOS', 'ROL_IA_PROFESORES', 'EDAD_REGULACION']
    for var in env_vars:
        status['environment_vars'][var] = bool(os.getenv(var))
    
    return jsonify(status)

@routes.route('/chat/<int:chat_id>/eliminar', methods=['DELETE'])
def eliminar_chat(chat_id):
    """Elimina un chat para cualquier usuario"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'No autorizado'}), 401
    
    user = Usuario.query.get(login_session['user_id'])
    if not user:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    
    try:
        success = chat_ia_universal.eliminar_chat(chat_id, user.id)
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Chat no encontrado'}), 404
            
    except Exception as e:
        logger.error(f"Error eliminando chat: {e}")
        return jsonify({'error': 'Error interno'}), 500

@routes.route('/chat/<int:chat_id>/renombrar', methods=['PUT'])
def renombrar_chat(chat_id):
    """Renombra un chat para cualquier usuario"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'No autorizado'}), 401
    
    user = Usuario.query.get(login_session['user_id'])
    if not user:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    
    try:
        data = request.get_json()
        nuevo_nombre = data.get('nombre', '').strip()
        
        if not nuevo_nombre:
            return jsonify({'error': 'Nombre vacío'}), 400
        
        success = chat_ia_universal.renombrar_chat(chat_id, user.id, nuevo_nombre)
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Chat no encontrado'}), 404
            
    except Exception as e:
        logger.error(f"Error renombrando chat: {e}")
        return jsonify({'error': 'Error interno'}), 500


@routes.route('/debug/env-check', methods=['GET'])
def check_environment():
    """Verifica el estado de las variables de entorno"""
    if 'user_id' not in login_session:
        return jsonify({'error': 'No autorizado'}), 401
    
    env_status = {
        'GROQ_API_KEY': {
            'present': bool(os.getenv('GROQ_API_KEY')),
            'length': len(os.getenv('GROQ_API_KEY', '')),
            'preview': (os.getenv('GROQ_API_KEY', '')[:8] + '...' if os.getenv('GROQ_API_KEY') else 'No encontrada')
        },
        'GROQ_MODEL': os.getenv('GROQ_MODEL', 'No configurado'),
        'GROQ_TEMPERATURE': os.getenv('GROQ_TEMPERATURE', 'No configurado'),
        'GROQ_MAX_TOKENS': os.getenv('GROQ_MAX_TOKENS', 'No configurado'),
        'other_vars': {
            'NOMBRE': bool(os.getenv('NOMBRE')),
            'LIMITACIONES': bool(os.getenv('LIMITACIONES')),
            'ROL_IA_ALUMNOS': bool(os.getenv('ROL_IA_ALUMNOS')),
            'ROL_IA_PROFESORES': bool(os.getenv('ROL_IA_PROFESORES'))
        }
    }
    
    return jsonify(env_status)
