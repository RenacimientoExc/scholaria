import os, logging
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
from flask import current_app, request, jsonify, render_template, redirect, url_for, flash, session as login_session
from groq import Groq
from .models import db, Usuario, RolUsuario, ChatIA, MensajeChatIA, ArchivoMateria, Materia, Curso, Institucion, profesor_curso_materia
from .markdown_renderer import markdown_renderer

logger = logging.getLogger(__name__)

class ChatIA_Universal:
    """Clase para manejar el chat de IA para todos los tipos de usuarios"""
    
    def __init__(self):
        self.client = None
        self.initialization_error = None
        self._initialize_groq()
    
    def _initialize_groq(self):
        """Inicializa el cliente de Groq con mejor manejo de errores"""
        try:
            # 1. Verificar API Key
            api_key = os.getenv('GROQ_API_KEY')
            if not api_key:
                error_msg = "GROQ_API_KEY no encontrada en variables de entorno"
                logger.error(error_msg)
                self.initialization_error = error_msg
                return False
            
            # 2. Validar formato de API Key
            api_key = api_key.strip()
            if len(api_key) < 10:
                error_msg = f"GROQ_API_KEY parece inválida (longitud: {len(api_key)})"
                logger.error(error_msg)
                self.initialization_error = error_msg
                return False
            
            # 3. Crear cliente
            logger.info("Intentando crear cliente de Groq...")
            self.client = Groq(api_key=api_key)
            
            # 4. Prueba básica de conexión
            logger.info("Probando conexión con Groq...")
            test_completion = self.client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[{"role": "user", "content": "test"}],
                max_tokens=5,
                timeout=10
            )
            
            if not test_completion or not test_completion.choices:
                raise Exception("Respuesta vacía en prueba de conexión")
            
            logger.info("Cliente de Groq inicializado y probado correctamente")
            self.initialization_error = None
            return True
            
        except Exception as e:
            error_msg = f"Error inicializando Groq: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.client = None
            self.initialization_error = error_msg
            return False
    
    def _get_env_vars(self) -> Dict[str, str]:
        """Obtiene las variables de entorno necesarias para el prompt"""
        return {
            "NOMBRE": os.getenv("NOMBRE"),
            "LIMITACIONES": os.getenv("LIMITACIONES"),
            "ROL_IA_ALUMNOS": os.getenv("ROL_IA_ALUMNOS"),
            "ROL_IA_PROFESORES": os.getenv("ROL_IA_PROFESORES"),
            "EDAD_REGULACION": os.getenv("EDAD_REGULACION")
        }
    
    def _get_groq_config(self) -> Dict[str, any]:
        """Obtiene la configuración de Groq desde variables de entorno"""
        return {
            "model": os.getenv("GROQ_MODEL", "llama3-8b-8192"),  # Modelo más estable
            "temperature": float(os.getenv("GROQ_TEMPERATURE", "0.7")),
            "max_tokens": int(os.getenv("GROQ_MAX_TOKENS", "2048")),
            "top_p": float(os.getenv("GROQ_TOP_P", "1.0")),
            "retry_delay": float(os.getenv("GROQ_RETRY_DELAY", "1.0")),
            "max_retries": int(os.getenv("GROQ_MAX_RETRIES", "3")),
            "stream_timeout": int(os.getenv("GROQ_STREAM_TIMEOUT", "30"))
        }
    
    def is_available(self) -> bool:
        """Verifica si el servicio de IA está disponible"""
        return self.client is not None
    
    def get_status(self) -> dict:
        """Retorna el estado del servicio"""
        return {
            'available': self.is_available(),
            'client_initialized': self.client is not None,
            'api_key_present': bool(os.getenv('GROQ_API_KEY')),
            'initialization_error': self.initialization_error
        }
    
    def reinitialize(self) -> bool:
        """Reinicializa el cliente de Groq"""
        logger.info("Reinicializando cliente de Groq...")
        self.client = None
        self.initialization_error = None
        return self._initialize_groq()
    
    def _get_archivos_data(self, usuario: Usuario) -> List[Dict]:
        """Obtiene datos de archivos del usuario de forma segura"""
        try:
            # Para profesores: obtener solo nombres de archivos
            if usuario.rol == RolUsuario.PROFESOR:
                try:
                    archivos = db.session.query(ArchivoMateria)\
                        .join(Materia, ArchivoMateria.materia_id == Materia.id)\
                        .join(Curso, Materia.curso_id == Curso.id)\
                        .join(profesor_curso_materia)\
                        .filter(profesor_curso_materia.c.profesor_id == usuario.id)\
                        .order_by(ArchivoMateria.fecha_subida.desc())\
                        .limit(10).all()
                    
                    archivos_data = []
                    for archivo in archivos:
                        try:
                            nombre_archivo = 'Sin nombre'
                            if archivo.archivo_path:
                                try:
                                    nombre_archivo = archivo.archivo_path.split('/')[-1]
                                except (AttributeError, IndexError):
                                    nombre_archivo = str(archivo.archivo_path) if archivo.archivo_path else 'Sin nombre'
                            
                            nombre_materia = 'Sin materia'
                            if hasattr(archivo, 'materia') and archivo.materia:
                                nombre_materia = archivo.materia.nombre or 'Sin materia'
                            
                            archivos_data.append({
                                'tema': archivo.nombre_tema or 'Sin tema',
                                'materia': nombre_materia,
                                'nombre_archivo': nombre_archivo
                            })
                            
                        except Exception as archivo_error:
                            logger.warning(f"Error procesando archivo {getattr(archivo, 'id', 'desconocido')}: {archivo_error}")
                            continue
                    
                    return archivos_data
                    
                except Exception as query_error:
                    logger.error(f"Error en consulta de archivos para profesor {usuario.id}: {query_error}")
                    return []
            
            # Para alumnos: obtener contenido completo de archivos
            else:
                try:
                    archivos = []
                    
                    if not hasattr(usuario, 'curso_id') or not usuario.curso_id:
                        logger.warning(f"Alumno {usuario.id} no tiene curso asignado")
                        return []
                    
                    archivos = db.session.query(ArchivoMateria)\
                        .join(Materia, ArchivoMateria.materia_id == Materia.id)\
                        .filter(Materia.curso_id == usuario.curso_id)\
                        .order_by(ArchivoMateria.fecha_subida.desc())\
                        .limit(10).all()
                    
                    archivos_data = []
                    for archivo in archivos:
                        try:
                            texto_procesado = 'Texto no disponible'
                            if archivo.texto_extraido:
                                try:
                                    texto_str = str(archivo.texto_extraido)
                                    if len(texto_str) > 2000:
                                        texto_procesado = texto_str[:2000] + '...'
                                    else:
                                        texto_procesado = texto_str
                                except Exception:
                                    texto_procesado = 'Error procesando texto'
                            
                            nombre_materia = 'Sin materia'
                            nombre_curso = 'Sin curso'
                            
                            if hasattr(archivo, 'materia') and archivo.materia:
                                nombre_materia = archivo.materia.nombre or 'Sin materia'
                                if hasattr(archivo.materia, 'curso') and archivo.materia.curso:
                                    nombre_curso = archivo.materia.curso.nombre or 'Sin curso'
                            
                            archivos_data.append({
                                'tema': archivo.nombre_tema or 'Sin tema',
                                'notas': archivo.notas_adicionales or 'Sin notas adicionales',
                                'instrucciones': archivo.instrucciones_ensenanza or 'Sin instrucciones específicas',
                                'texto': texto_procesado,
                                'materia': nombre_materia,
                                'curso': nombre_curso
                            })
                            
                        except Exception as archivo_error:
                            logger.warning(f"Error procesando archivo {getattr(archivo, 'id', 'desconocido')} para alumno: {archivo_error}")
                            continue
                    
                    return archivos_data
                    
                except Exception as query_error:
                    logger.error(f"Error en consulta de archivos para alumno {usuario.id}: {query_error}")
                    return []
        
        except Exception as e:
            logger.error(f"Error general obteniendo archivos del usuario {usuario.id}: {e}")
            return []
    
    def _build_system_prompt(self, usuario: Usuario) -> str:
        """Construye el prompt del sistema según el tipo de usuario"""
        try:
            env_vars = self._get_env_vars()
            
            nombre_usuario = usuario.nombre
            apellido_usuario = getattr(usuario, 'apellido', '')
            rol_usuario = usuario.rol.value if hasattr(usuario.rol, 'value') else str(usuario.rol)
            edad_usuario = self._calculate_age(usuario)
            institucion_data = self._get_institucion_data(usuario)
            archivos_data = self._get_archivos_data(usuario)
            
            if usuario.rol == RolUsuario.PROFESOR:
                rol_ia = env_vars.get('ROL_IA_PROFESORES', 'un asistente educativo para profesores')
                materias_info = self._get_materias_profesor(usuario)
            else:
                rol_ia = env_vars.get('ROL_IA_ALUMNOS', 'un asistente educativo para estudiantes')
                materias_info = self._get_materias_alumno(usuario)
            
            prompt_parts = [
                f"Eres {env_vars.get('NOMBRE', 'un asistente educativo')}, {rol_ia}.",
                f"Tus limitaciones son: {env_vars.get('LIMITACIONES', 'Responde de manera educativa y apropiada')}",
                "Ahora mismo estás hablando con:",
                f"{nombre_usuario} {apellido_usuario}.",
                f"Su rol es: {rol_usuario}.",
                f"Su edad es: {edad_usuario} años.",
                f"Regulación de edad: {env_vars.get('EDAD_REGULACION', '13')} años.",
                "Información de la institución:",
                f"Nombre: {institucion_data['nombre']}",
                f"Valores institucionales: {institucion_data['valores']}",
                f"Metodología pedagógica: {institucion_data['metodologia']}",
                f"Configuración IA: {institucion_data['configuracion']}",
                ""
            ]
            
            if usuario.rol == RolUsuario.PROFESOR:
                prompt_parts.extend(["Materias que enseña:"])
                for materia in materias_info:
                    prompt_parts.append(f"- {materia['nombre']} ({materia['curso']})")
            else:
                prompt_parts.extend(["Materias en las que está inscrito:"])
                for materia in materias_info:
                    prompt_parts.append(f"- {materia['nombre']} ({materia['curso']})")
            
            prompt_parts.extend([
                "",
                f"Archivos y contenidos disponibles del {'profesor' if usuario.rol == RolUsuario.PROFESOR else 'estudiante'}:"
            ])
            
            if archivos_data:
                if usuario.rol == RolUsuario.PROFESOR:
                    for idx, archivo in enumerate(archivos_data, 1):
                        prompt_parts.extend([
                            f"",
                            f"Archivo {idx}:",
                            f"- Tema: {archivo['tema']}",
                            f"- Materia: {archivo['materia']}",
                            f"- Nombre: {archivo['nombre_archivo']}"
                        ])
                else:
                    for idx, archivo in enumerate(archivos_data, 1):
                        prompt_parts.extend([
                            f"Archivos cargados por el profesor.",
                            f"Archivo {idx}:",
                            f"- Tema: {archivo['tema']}",
                            f"- Materia: {archivo['materia']}",
                            f"- Notas: {archivo['notas']}",
                            f"- Instrucciones de enseñanza: {archivo['instrucciones']}",
                            f"- Contenido: {archivo['texto']}..."
                        ])
            else:
                prompt_parts.append("No hay archivos disponibles actualmente.")
            
            return "\n".join(prompt_parts)
            
        except Exception as e:
            logger.error(f"Error construyendo prompt: {e}")
            rol_fallback = "profesor" if usuario.rol == RolUsuario.PROFESOR else "estudiante"
            return f"Eres un asistente educativo especializado para {rol_fallback}s. Ayuda de manera apropiada y educativa."
    
    def _calculate_age(self, usuario: Usuario) -> int:
        """Calcula la edad del usuario de forma segura"""
        try:
            if hasattr(usuario, 'fecha_nacimiento') and usuario.fecha_nacimiento:
                hoy = date.today()
                fecha_nac = usuario.fecha_nacimiento
                edad = hoy.year - fecha_nac.year - (
                    (hoy.month, hoy.day) < (fecha_nac.month, fecha_nac.day)
                )
                return max(0, min(edad, 120))
            else:
                return 30 if usuario.rol == RolUsuario.PROFESOR else 16
        except Exception:
            return 30 if usuario.rol == RolUsuario.PROFESOR else 16
    
    def _get_institucion_data(self, usuario: Usuario) -> Dict[str, str]:
        """Obtiene datos de la institución de forma segura"""
        try:
            if hasattr(usuario, 'get_institucion'):
                institucion = usuario.get_institucion()
                if institucion:
                    return {
                        'nombre': str(institucion.nombre if hasattr(institucion, 'nombre') else 'No especificado'),
                        'valores': str(institucion.valores_institucionales if hasattr(institucion, 'valores_institucionales') else 'No especificado'),
                        'metodologia': str(institucion.metodologia_pedagogica if hasattr(institucion, 'metodologia_pedagogica') else 'No especificado'),
                        'configuracion': str(institucion.configuracion_ia if hasattr(institucion, 'configuracion_ia') else 'Estándar')
                    }
        except Exception as e:
            logger.error(f"Error obteniendo datos de institución: {e}")
        
        return {
            'nombre': 'No especificado',
            'valores': 'No especificado',
            'metodologia': 'No especificado',
            'configuracion': 'Estándar'
        }
    
    def _get_materias_profesor(self, profesor: Usuario) -> List[Dict]:
        """Obtiene las materias que enseña el profesor"""
        try:
            from .models import profesor_curso_materia
            
            materias_cursos = db.session.query(Materia, Curso)\
                .join(Curso, Materia.curso_id == Curso.id)\
                .join(profesor_curso_materia)\
                .filter(profesor_curso_materia.c.profesor_id == profesor.id)\
                .all()
            
            materias_data = []
            for materia, curso in materias_cursos:
                materias_data.append({
                    'nombre': materia.nombre,
                    'curso': curso.nombre,
                    'descripcion': materia.descripcion or 'Sin descripción'
                })
            
            return materias_data
        except Exception as e:
            logger.error(f"Error obteniendo materias del profesor: {e}")
            return []
    
    def _get_materias_alumno(self, alumno: Usuario) -> List[Dict]:
        """Obtiene las materias en las que está inscrito el alumno"""
        try:
            materias_data = []
            
            if hasattr(alumno, 'cursos') and alumno.cursos:
                for curso in alumno.cursos:
                    materias = Materia.query.filter_by(curso_id=curso.id).all()
                    for materia in materias:
                        materias_data.append({
                            'nombre': materia.nombre,
                            'curso': curso.nombre,
                            'descripcion': materia.descripcion or 'Sin descripción'
                        })
            
            return materias_data
        except Exception as e:
            logger.error(f"Error obteniendo materias del alumno: {e}")
            return []
    
    # Continúa con el resto de métodos...
    def crear_chat(self, usuario_id: int, nombre_chat: str = None) -> Optional[ChatIA]:
        """Crea un nuevo chat para el usuario"""
        try:
            if not nombre_chat:
                nombre_chat = f"Chat {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            
            chat = ChatIA(
                nombre_chat=nombre_chat,
                usuario_id=usuario_id,
                fecha_creacion=datetime.utcnow(),
                fecha_ultimo_mensaje=datetime.utcnow()
            )
            
            db.session.add(chat)
            db.session.commit()
            
            logger.info(f"Chat creado exitosamente: {chat.id}")
            return chat
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creando chat: {e}")
            return None
    
    def eliminar_chat(self, chat_id: int, usuario_id: int) -> bool:
        """Elimina un chat y todos sus mensajes"""
        try:
            # Verificar que el chat pertenece al usuario
            chat = ChatIA.query.filter_by(
                id=chat_id, 
                usuario_id=usuario_id
            ).first()
            
            if not chat:
                return False
            
            # Eliminar mensajes asociados
            MensajeChatIA.query.filter_by(chat_id=chat_id).delete()
            
            # Eliminar el chat
            db.session.delete(chat)
            db.session.commit()
            
            logger.info(f"Chat {chat_id} eliminado exitosamente")
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error eliminando chat: {e}")
            return False
    
    def renombrar_chat(self, chat_id: int, usuario_id: int, nuevo_nombre: str) -> bool:
        """Renombra un chat"""
        try:
            chat = ChatIA.query.filter_by(
                id=chat_id, 
                usuario_id=usuario_id
            ).first()
            
            if not chat:
                return False
            
            chat.nombre_chat = nuevo_nombre.strip()[:200]  # Limitar longitud
            db.session.commit()
            
            return True
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error renombrando chat: {e}")
            return False
    
    def get_markdown_css(self) -> str:
        """Retorna los estilos CSS para el renderizado de Markdown"""
        return markdown_renderer.get_css_styles()


# Instancia global del chat IA universal
chat_ia_universal = ChatIA_Universal()
