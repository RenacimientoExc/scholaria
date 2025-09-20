from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin as FlaskLoginUserMixin
from datetime import datetime
from enum import Enum
import uuid, json, os

db = SQLAlchemy()

# Enums para tipos especÃƒÆ’Ã‚Â­ficos
class RolUsuario(Enum):
    ADMIN = "admin"
    DIRECTOR = "director"
    PROFESOR = "profesor"
    TUTOR = "tutor"
    PADRE = "padre"
    MADRE = "madre"
    ALUMNO = "alumno"

class TipoTarea(Enum):
    VERDADERO_FALSO = "verdadero_falso"
    MULTIPLE_CHOICE = "multiple_choice"
    MATEMATICA = "matematica"
    COMPLETAR = "completar"
    TEXTO_LIBRE = "texto_libre"

class PatologiaAlumno(Enum):
    DISLEXIA = "dislexia"
    DISCALCULIA = "discalculia"
    DISGRAFIA = "disgrafia"
    TRASTORNO_PROCESAMIENTO_AUDITIVO = "trastorno_procesamiento_auditivo"
    DISPRAXIA = "dispraxia"
    SINDROME_DOWN = "sindrome_down"
    AUTISMO = "autismo"

# Tablas de asociaciÃƒÆ’Ã‚Â³n many-to-many
profesor_curso_materia = db.Table('profesor_curso_materia',
    db.Column('profesor_id', db.Integer, db.ForeignKey('usuarios.id'), primary_key=True),
    db.Column('curso_id', db.Integer, db.ForeignKey('cursos.id'), primary_key=True),
    db.Column('materia_id', db.Integer, db.ForeignKey('materias.id'), primary_key=True)
)

alumno_patologia = db.Table('alumno_patologia',
    db.Column('alumno_id', db.Integer, db.ForeignKey('usuarios.id'), primary_key=True),
    db.Column('patologia_valor', db.String(50), primary_key=True)  # Ã°Å¸â€Â¥ Guardar el valor string
)

class InviteToken(db.Model):
    __tablename__ = 'invite_tokens'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    rol = db.Column(db.Enum(RolUsuario), nullable=False)
    nombre = db.Column(db.String(100))
    apellido = db.Column(db.String(100))
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_expiracion = db.Column(db.DateTime)
    
    # Nuevo campo para datos adicionales (JSON)
    datos_adicionales = db.Column(db.Text)  # Almacena JSON con curso_id, patologÃ­as, etc.
    
    def is_valid(self):
        """Verifica si el token sigue siendo vÃ¡lido"""
        return datetime.utcnow() < self.fecha_expiracion
    
    def get_datos_adicionales(self):
        """Obtiene los datos adicionales como diccionario"""
        if self.datos_adicionales:
            try:
                return json.loads(self.datos_adicionales)
            except (TypeError, json.JSONDecodeError):
                return {}
        return {}
    
    def set_datos_adicionales(self, datos):
        """Establece los datos adicionales como JSON"""
        self.datos_adicionales = json.dumps(datos) if datos else None
    
    def __repr__(self):
        return f'<InviteToken {self.email} - {self.rol.value}>'

class Usuario(db.Model, FlaskLoginUserMixin):
    __tablename__ = 'usuarios'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    nombre = db.Column(db.String(100), nullable=False)
    apellido = db.Column(db.String(100), nullable=False)
    fecha_nacimiento = db.Column(db.Date, nullable=False)
    rol = db.Column(db.Enum(RolUsuario), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # ðŸ†• NUEVO: Campo para conectar usuario con instituciÃ³n
    institucion_id = db.Column(db.Integer, db.ForeignKey('instituciones.id'), nullable=True)
    
    # Campos adicionales para autenticaciÃ³n
    email_confirmed_at = db.Column(db.DateTime)
    failed_login_attempts = db.Column(db.Integer, default=0)
    last_login_at = db.Column(db.DateTime)
    locked_until = db.Column(db.DateTime)
    reset_password_token = db.Column(db.String(100), nullable=True)
    reset_password_expires = db.Column(db.DateTime, nullable=True)

    # Relaciones familiares (para Alumnos)
    padre_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    madre_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    curso_id = db.Column(db.Integer, db.ForeignKey('cursos.id'), nullable=True)
    
    # ðŸ”§ RELACIONES CORREGIDAS - Especificar foreign_keys para evitar ambigÃ¼edad
    
    # RelaciÃ³n con instituciÃ³n (para todos los usuarios excepto directores)
    institucion = db.relationship('Institucion', 
                                foreign_keys=[institucion_id],
                                backref='usuarios')
    
    # Relaciones familiares
    padre = db.relationship('Usuario', 
                           remote_side=[id], 
                           foreign_keys=[padre_id],
                           backref=db.backref('hijos_como_padre', lazy='dynamic'))
    
    madre = db.relationship('Usuario', 
                           remote_side=[id], 
                           foreign_keys=[madre_id],
                           backref=db.backref('hijos_como_madre', lazy='dynamic'))
    
    # Para Profesores - relaciÃ³n con cursos y materias
    cursos_materias = db.relationship('Materia', 
                                    secondary=profesor_curso_materia,
                                    backref='profesores')

    # Para Tutores - especificar explÃ­citamente la clave forÃ¡nea
    curso_tutor = db.relationship('Curso', 
                                foreign_keys='Curso.tutor_id',
                                backref='tutor', 
                                uselist=False)
    
    # ðŸ†• MÃ‰TODOS HELPER actualizados para trabajar con instituciones
    def get_institucion(self):
        """Obtiene la instituciÃ³n del usuario segÃºn su rol"""
        if self.is_director():
            return self.institucion_dirigida
        else:
            return self.institucion
    
    def set_institucion(self, institucion):
        """Asigna una instituciÃ³n al usuario"""
        if not self.is_director():  # Los directores ya tienen su relaciÃ³n especial
            self.institucion_id = institucion.id if institucion else None
    
    def pertenece_a_institucion(self, institucion_id):
        """Verifica si el usuario pertenece a una instituciÃ³n especÃ­fica"""
        user_institucion = self.get_institucion()
        return user_institucion and user_institucion.id == institucion_id
    
    # ... resto de mÃ©todos existentes sin cambios ...
    def get_hijos(self):
        """Obtiene todos los hijos (tanto como padre como madre)"""
        hijos = []
        if self.is_padre_o_madre():
            hijos_como_padre = Usuario.query.filter_by(padre_id=self.id).all()
            hijos.extend(hijos_como_padre)
            
            hijos_como_madre = Usuario.query.filter_by(madre_id=self.id).all()
            hijos.extend(hijos_como_madre)
            
            hijos = list(set(hijos))
        
        return hijos
    
    def get_padres(self):
        """Obtiene lista de padres (padre y/o madre)"""
        padres = []
        if self.padre:
            padres.append(self.padre)
        if self.madre:
            padres.append(self.madre)
        return padres
    
    def es_hijo_de(self, posible_padre):
        """Verifica si este usuario es hijo del usuario dado"""
        return (self.padre_id == posible_padre.id or 
                self.madre_id == posible_padre.id)
    
    def es_padre_de(self, posible_hijo):
        """Verifica si este usuario es padre del usuario dado"""
        return (posible_hijo.padre_id == self.id or 
                posible_hijo.madre_id == self.id)

    # Ã°Å¸â€Â¥ NUEVOS MÃƒâ€°TODOS para manejar patologÃƒÂ­as sin relaciÃƒÂ³n ORM problemÃƒÂ¡tica
    def agregar_patologia(self, patologia):
        """Agrega una patologÃƒÂ­a al alumno"""
        if isinstance(patologia, PatologiaAlumno):
            valor = patologia.value
        else:
            valor = str(patologia)
        
        # Verificar si ya existe
        existing = db.session.execute(
            alumno_patologia.select().where(
                (alumno_patologia.c.alumno_id == self.id) & 
                (alumno_patologia.c.patologia_valor == valor)
            )
        ).first()
        
        if not existing:
            db.session.execute(
                alumno_patologia.insert().values(
                    alumno_id=self.id,
                    patologia_valor=valor
                )
            )
    
    def remover_patologia(self, patologia):
        """Remueve una patologÃƒÂ­a del alumno"""
        if isinstance(patologia, PatologiaAlumno):
            valor = patologia.value
        else:
            valor = str(patologia)
        
        db.session.execute(
            alumno_patologia.delete().where(
                (alumno_patologia.c.alumno_id == self.id) & 
                (alumno_patologia.c.patologia_valor == valor)
            )
        )
    
    def get_patologias(self):
        """Obtiene todas las patologÃƒÂ­as del alumno"""
        result = db.session.execute(
            alumno_patologia.select().where(alumno_patologia.c.alumno_id == self.id)
        ).fetchall()
        
        patologias = []
        for row in result:
            try:
                patologias.append(PatologiaAlumno(row.patologia_valor))
            except ValueError:
                # Si el valor no es vÃƒÂ¡lido en el enum, lo incluimos como string
                patologias.append(row.patologia_valor)
        
        return patologias
    
    def tiene_patologia(self, patologia):
        """Verifica si el alumno tiene una patologÃƒÂ­a especÃƒÂ­fica"""
        if isinstance(patologia, PatologiaAlumno):
            valor = patologia.value
        else:
            valor = str(patologia)
        
        result = db.session.execute(
            alumno_patologia.select().where(
                (alumno_patologia.c.alumno_id == self.id) & 
                (alumno_patologia.c.patologia_valor == valor)
            )
        ).first()
        
        return result is not None
    
    # MÃƒÆ’Ã‚Â©todos para manejo de contraseÃƒÆ’Ã‚Â±as
    def set_password(self, password):
        """Establece la contraseÃƒÆ’Ã‚Â±a hasheada"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verifica la contraseÃƒÆ’Ã‚Â±a"""
        return check_password_hash(self.password_hash, password)
    
    # MÃƒÆ’Ã‚Â©todos requeridos por Flask-Login
    def get_id(self):
        """Retorna el ID ÃƒÆ’Ã‚Âºnico del usuario como string"""
        return str(self.id)
    
    def is_authenticated(self):
        """Retorna True si el usuario estÃƒÆ’Ã‚Â¡ autenticado"""
        return True
    
    def is_active(self):
        """Retorna True si el usuario estÃƒÆ’Ã‚Â¡ activo"""
        return self.activo and (not self.locked_until or self.locked_until < datetime.utcnow())
    
    def is_anonymous(self):
        """Retorna True si es usuario anÃƒÆ’Ã‚Â³nimo"""
        return False
    
    # MÃƒÆ’Ã‚Â©todos de utilidad para roles
    def has_role(self, role_name):
        """Verifica si el usuario tiene un rol especÃƒÆ’Ã‚Â­fico"""
        if isinstance(role_name, str):
            return self.rol.value == role_name
        elif isinstance(role_name, RolUsuario):
            return self.rol == role_name
        return False
    
    def is_admin(self):
        return self.has_role(RolUsuario.ADMIN)
    
    def is_director(self):
        return self.has_role(RolUsuario.DIRECTOR)
    
    def is_profesor(self):
        return self.has_role(RolUsuario.PROFESOR)
    
    def is_tutor(self):
        return self.has_role(RolUsuario.TUTOR)
    
    def is_padre_o_madre(self):
        return self.has_role(RolUsuario.PADRE) or self.has_role(RolUsuario.MADRE)
    
    def is_alumno(self):
        return self.has_role(RolUsuario.ALUMNO)
    
    # MÃƒÆ’Ã‚Â©todo para bloquear usuario temporalmente
    def lock_account(self, minutes=30):
        """Bloquea la cuenta por un tiempo determinado"""
        self.locked_until = datetime.utcnow() + datetime.timedelta(minutes=minutes)
        self.failed_login_attempts = 0
    
    # MÃƒÆ’Ã‚Â©todo para confirmar email
    def confirm_email(self):
        """Confirma el email del usuario"""
        self.email_confirmed_at = datetime.utcnow()
    
    @property
    def is_email_confirmed(self):
        """Verifica si el email estÃƒÆ’Ã‚Â¡ confirmado"""
        return self.email_confirmed_at is not None
    
    def __repr__(self):
        return f'<Usuario {self.nombre} {self.apellido} - {self.rol.value}>'

class Institucion(db.Model):
    __tablename__ = 'instituciones'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(200), nullable=False)
    logo_grande = db.Column(db.String(500))
    logo_pequeno = db.Column(db.String(500))
    director_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # ConfiguraciÃ³n de IA especÃ­fica para la instituciÃ³n
    valores_institucionales = db.Column(db.Text)
    metodologia_pedagogica = db.Column(db.Text)
    configuracion_ia = db.Column(db.Text)
    
    # ðŸ”§ RELACIÃ“N CORREGIDA - Especificar foreign_keys para el director
    director = db.relationship('Usuario', 
                              foreign_keys=[director_id],
                              backref='institucion_dirigida', 
                              uselist=False)
    
    # La relaciÃ³n 'usuarios' se crea automÃ¡ticamente por el backref en Usuario.institucion
    
    # ðŸ†• MÃ‰TODOS HELPER para trabajar con usuarios de la instituciÃ³n
    def get_todos_usuarios(self):
        """Obtiene todos los usuarios de la instituciÃ³n (incluyendo director)"""
        usuarios = list(self.usuarios)  # Usuarios conectados por institucion_id
        if self.director:
            usuarios.append(self.director)
        return usuarios
    
    def get_profesores(self):
        return [u for u in self.usuarios if u.is_profesor()]
    
    def get_tutores(self):
        return [u for u in self.usuarios if u.is_tutor()]
    
    def get_alumnos(self):
        return [u for u in self.usuarios if u.is_alumno()]
    
    def get_padres(self):
        return [u for u in self.usuarios if u.is_padre_o_madre()]
    
    def __repr__(self):
        return f'<Institucion {self.nombre}>'

class Curso(db.Model):
    __tablename__ = 'cursos'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    nivel = db.Column(db.String(50))  # Ej: "1ro Secundaria", "5to Grado"
    institucion_id = db.Column(db.Integer, db.ForeignKey('instituciones.id'), nullable=False)
    tutor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    alumnos = db.relationship('Usuario', backref='curso', foreign_keys='Usuario.curso_id')
    materias = db.relationship('Materia', backref='curso')
    institucion = db.relationship('Institucion', backref='cursos')
    
    def __repr__(self):
        return f'<Curso {self.nombre} - {self.nivel}>'

class Materia(db.Model):
    __tablename__ = 'materias'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    curso_id = db.Column(db.Integer, db.ForeignKey('cursos.id'), nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones con archivos y tareas
    archivos = db.relationship('ArchivoMateria', backref='materia')
    tareas = db.relationship('Tarea', backref='materia')
    
    def __repr__(self):
        return f'<Materia {self.nombre}>'

class ArchivoMateria(db.Model):
    __tablename__ = 'archivos_materia'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre_tema = db.Column(db.String(200), nullable=False)
    archivo_path = db.Column(db.String(500), nullable=False)
    notas_adicionales = db.Column(db.Text)
    instrucciones_ensenanza = db.Column(db.Text)
    utilidad_ia_score = db.Column(db.Float, default=0.0)
    texto_extraido = db.Column(db.Text, nullable=True)
    materia_id = db.Column(db.Integer, db.ForeignKey('materias.id'), nullable=False)
    profesor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha_subida = db.Column(db.DateTime, default=datetime.utcnow)
    
    tareas_generadas = db.relationship('Tarea', backref='archivo_origen')
    
    def __repr__(self):
        return f'<ArchivoMateria {self.nombre_tema}>'
    
    # MÃ©todo helper para verificar si el archivo fue procesado correctamente
    def esta_procesado(self):
        """Verifica si el archivo tiene texto extraÃ­do"""
        return (self.texto_extraido is not None and 
                self.texto_extraido.strip() != '' and 
                not self.texto_extraido.startswith('[Error'))
    
    def get_resumen_texto(self, max_chars=200):
        """Obtiene un resumen del texto extraÃ­do"""
        if not self.esta_procesado():
            return "Texto no disponible"
        
        texto = self.texto_extraido.strip()
        if len(texto) <= max_chars:
            return texto
        
        return texto[:max_chars] + "..."
    
    def get_tamaño_archivo_legible(self):
        """Obtiene el tamaÃ±o del archivo en formato legible"""
        try:
            if os.path.exists(self.archivo_path):
                size_bytes = os.path.getsize(self.archivo_path)
                
                if size_bytes < 1024:
                    return f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    return f"{size_bytes / 1024:.1f} KB"
                else:
                    return f"{size_bytes / (1024 * 1024):.1f} MB"
            return "Archivo no encontrado"
        except:
            return "TamaÃ±o desconocido"

class Tarea(db.Model):
    __tablename__ = 'tareas'
    
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    tipo = db.Column(db.Enum(TipoTarea), nullable=False)
    contenido = db.Column(db.Text)  # JSON con preguntas, opciones, etc.
    respuesta_correcta = db.Column(db.Text)  # JSON con respuestas correctas
    es_generada_ia = db.Column(db.Boolean, default=False)
    
    # Relaciones
    materia_id = db.Column(db.Integer, db.ForeignKey('materias.id'), nullable=False)
    profesor_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    archivo_origen_id = db.Column(db.Integer, db.ForeignKey('archivos_materia.id'), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_vencimiento = db.Column(db.DateTime, nullable=True)
    
    # Respuestas de alumnos
    respuestas = db.relationship('RespuestaTarea', backref='tarea')
    
    def __repr__(self):
        return f'<Tarea {self.titulo}>'

class RespuestaTarea(db.Model):
    __tablename__ = 'respuestas_tarea'
    
    id = db.Column(db.Integer, primary_key=True)
    respuesta = db.Column(db.Text, nullable=False)  # JSON con las respuestas
    es_correcta = db.Column(db.Boolean, nullable=True)  # Para tareas automÃƒÆ’Ã‚Â¡ticas
    puntuacion = db.Column(db.Float, nullable=True)
    devolucion_profesor = db.Column(db.Text)  # Para tareas de texto libre
    
    # Relaciones
    tarea_id = db.Column(db.Integer, db.ForeignKey('tareas.id'), nullable=False)
    alumno_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha_respuesta = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_correccion = db.Column(db.DateTime, nullable=True)
    
    # RelaciÃƒÆ’Ã‚Â³n con alumno
    alumno = db.relationship('Usuario', backref='respuestas_tareas')
    
    def __repr__(self):
        return f'<RespuestaTarea {self.id} - Alumno: {self.alumno_id}>'

class ChatIA(db.Model):
    __tablename__ = 'chats_ia'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre_chat = db.Column(db.String(200))  # Generado automÃƒÆ’Ã‚Â¡ticamente por IA
    carpeta = db.Column(db.String(100))  # Para organizaciÃƒÆ’Ã‚Â³n del alumno
    
    # Relaciones
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_ultimo_mensaje = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Mensajes del chat
    mensajes = db.relationship('MensajeChatIA', backref='chat', order_by='MensajeChatIA.fecha_envio')
    usuario = db.relationship('Usuario', backref='chats_ia')
    
    def __repr__(self):
        return f'<ChatIA {self.nombre_chat}>'

class MensajeChatIA(db.Model):
    __tablename__ = 'mensajes_chat_ia'
    
    id = db.Column(db.Integer, primary_key=True)
    contenido = db.Column(db.Text, nullable=False)
    es_usuario = db.Column(db.Boolean, nullable=False)
    archivo_audio_path = db.Column(db.String(500))
    
    # MÃƒÂ©tricas de la IA
    porcentaje_comprension = db.Column(db.Float, nullable=True)
    porcentaje_utilidad_archivo = db.Column(db.Float, nullable=True)
    exito_aprendiendo_preguntar = db.Column(db.Float, nullable=True)
    
    # Relaciones
    chat_id = db.Column(db.Integer, db.ForeignKey('chats_ia.id'), nullable=False)
    archivo_referenciado_id = db.Column(db.Integer, db.ForeignKey('archivos_materia.id'), nullable=True)
    fecha_envio = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Archivo referenciado
    archivo_referenciado = db.relationship('ArchivoMateria', backref='mensajes_chat')
    
    # Ã¢Å“â€¦ PROPIEDADES PARA COMPATIBILIDAD:
    @property
    def text(self):
        return self.contenido
    
    @text.setter
    def text(self, value):
        self.contenido = value
    
    @property
    def timestamp(self):
        return self.fecha_envio
    
    @timestamp.setter
    def timestamp(self, value):
        self.fecha_envio = value
    
    @property
    def sender(self):
        return "user" if self.es_usuario else "assistant"
    
    @sender.setter
    def sender(self, value):
        self.es_usuario = (value == "user")
    
    @property
    def session_id(self):
        return self.chat_id
    
    @session_id.setter
    def session_id(self, value):
        self.chat_id = value
    
    def __repr__(self):
        return f'<MensajeChat {self.id}>'

class SesionAprendiendoPreguntar(db.Model):
    __tablename__ = 'sesiones_aprendiendo_preguntar'
    
    id = db.Column(db.Integer, primary_key=True)
    texto_base = db.Column(db.Text, nullable=False)  # Texto "X" mostrado al alumno
    tema = db.Column(db.String(200), nullable=False)
    consejos_mostrados = db.Column(db.Text)  # JSON con consejos dados
    pregunta_alumno = db.Column(db.Text)
    respuesta_ia = db.Column(db.Text)
    exito_sesion = db.Column(db.Float)  # Porcentaje de ÃƒÆ’Ã‚Â©xito segÃƒÆ’Ã‚Âºn IA
    
    # Relaciones
    alumno_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    fecha_sesion = db.Column(db.DateTime, default=datetime.utcnow)
    
    alumno = db.relationship('Usuario', backref='sesiones_aprendiendo')
    
    def __repr__(self):
        return f'<SesionAprendiendoPreguntar {self.tema}>'

class AnalyticaComprension(db.Model):
    __tablename__ = 'analiticas_comprension'
    
    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    materia_id = db.Column(db.Integer, db.ForeignKey('materias.id'), nullable=True)
    curso_id = db.Column(db.Integer, db.ForeignKey('cursos.id'), nullable=True)
    
    # MÃƒÆ’Ã‚Â©tricas
    promedio_comprension = db.Column(db.Float)
    total_interacciones = db.Column(db.Integer, default=0)
    fecha_calculo = db.Column(db.DateTime, default=datetime.utcnow)
    periodo_inicio = db.Column(db.Date)
    periodo_fin = db.Column(db.Date)
    
    # Relaciones
    alumno = db.relationship('Usuario', backref='analiticas_comprension')
    materia = db.relationship('Materia', backref='analiticas_comprension')
    curso = db.relationship('Curso', backref='analiticas_comprension')
    
    def __repr__(self):
        return f'<AnalyticaComprension {self.alumno_id}>'

class AlertaContenidoSensible(db.Model):
    __tablename__ = 'alertas_contenido_sensible'
    
    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False)
    tipo_contenido = db.Column(db.String(100))  # muerte, suicidio, apuestas, etc.
    contexto = db.Column(db.Text)  # Fragmento relevante de la conversaciÃƒÆ’Ã‚Â³n
    nivel_riesgo = db.Column(db.String(20))  # bajo, medio, alto
    
    # Relaciones
    chat_id = db.Column(db.Integer, db.ForeignKey('chats_ia.id'), nullable=False)
    mensaje_id = db.Column(db.Integer, db.ForeignKey('mensajes_chat_ia.id'), nullable=False)
    fecha_alerta = db.Column(db.DateTime, default=datetime.utcnow)
    revisada = db.Column(db.Boolean, default=False)
    
    # Relaciones
    alumno = db.relationship('Usuario', backref='alertas_contenido')
    chat = db.relationship('ChatIA', backref='alertas')
    mensaje = db.relationship('MensajeChatIA', backref='alertas')
    
    def __repr__(self):
        return f'<AlertaContenido {self.tipo_contenido} - {self.nivel_riesgo}>'

# ÃƒÆ’Ã‚Ândices para optimizar consultas frecuentes
db.Index('idx_usuario_rol', Usuario.rol)
db.Index('idx_usuario_email', Usuario.email)
db.Index('idx_mensaje_chat_fecha', MensajeChatIA.fecha_envio)
db.Index('idx_respuesta_tarea_alumno', RespuestaTarea.alumno_id)
db.Index('idx_alerta_contenido_alumno_fecha', AlertaContenidoSensible.alumno_id, AlertaContenidoSensible.fecha_alerta)