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
            "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            "temperature": float(os.getenv("GROQ_TEMPERATURE", "0.7")),
            "max_tokens": int(os.getenv("GROQ_MAX_TOKENS", "65536")),
            "top_p": float(os.getenv("GROQ_TOP_P", "1.0")),
            "retry_delay": float(os.getenv("GROQ_RETRY_DELAY", "1.0")),
            "max_retries": int(os.getenv("GROQ_MAX_RETRIES", "3")),
            "stream_timeout": int(os.getenv("GROQ_STREAM_TIMEOUT", "30"))
        }
    
    def _get_archivos_data(self, usuario: Usuario) -> List[Dict]:
        try:
         # Para profesores: obtener solo nombres de archivos
            if usuario.rol == RolUsuario.PROFESOR:
                archivos = db.session.query(ArchivoMateria)\
                    .join(Materia, ArchivoMateria.materia_id == Materia.id)\
                    .join(Curso, Materia.curso_id == Curso.id)\
                    .join(profesor_curso_materia)\
                    .filter(profesor_curso_materia.c.profesor_id == usuario.id)\
                    .order_by(ArchivoMateria.fecha_subida.desc())\
                    .limit(10).all()
            
                archivos_data = []
                for archivo in archivos:
                # Extraer nombre del archivo desde archivo_path
                    nombre_archivo = archivo.archivo_path.split('/')[-1] if archivo.archivo_path else 'Sin nombre'
                
                    archivos_data.append({
                    'tema': archivo.nombre_tema or 'Sin tema',
                     'materia': archivo.materia.nombre if archivo.materia else 'Sin materia',
                    'nombre_archivo': nombre_archivo
                })
    
        # Para alumnos: obtener contenido completo de archivos
            else:
                archivos = []
                try:
                # CORRECCIÓN: El alumno tiene UN curso asignado, no múltiples
                    if usuario.curso_id:  # Verificar que el alumno tenga un curso asignado
                    # Obtener archivos del curso del alumno
                        archivos = db.session.query(ArchivoMateria)\
                            .join(Materia, ArchivoMateria.materia_id == Materia.id)\
                            .filter(Materia.curso_id == usuario.curso_id)\
                            .order_by(ArchivoMateria.fecha_subida.desc())\
                            .limit(10).all()
                    else:
                        logger.warning(f"Alumno {usuario.id} no tiene curso asignado")
                        archivos = []
                
                except Exception as e:
                    logger.warning(f"Error obteniendo archivos para alumno: {e}")
                    archivos = []
        
                archivos_data = []
                for archivo in archivos:
                    archivos_data.append({
                    'tema': archivo.nombre_tema or 'Sin tema',
                    'notas': archivo.notas_adicionales or 'Sin notas adicionales',
                    'instrucciones': archivo.instrucciones_ensenanza or 'Sin instrucciones específicas',
                    'texto': (archivo.texto_extraido[:2000] + '...' if archivo.texto_extraido and len(archivo.texto_extraido) > 2000 else archivo.texto_extraido) if archivo.texto_extraido else 'Texto no disponible',
                    'materia': archivo.materia.nombre if archivo.materia else 'Sin materia',
                    'curso': archivo.materia.curso.nombre if archivo.materia and archivo.materia.curso else 'Sin curso'
                })
    
            return archivos_data

        except Exception as e:
            logger.error(f"Error obteniendo archivos del usuario: {e}")
            return []
    
    def _build_system_prompt(self, usuario: Usuario) -> str:
        """Construye el prompt del sistema según el tipo de usuario"""
        try:
            env_vars = self._get_env_vars()
            
            # Datos básicos del usuario
            nombre_usuario = usuario.nombre
            apellido_usuario = getattr(usuario, 'apellido', '')
            rol_usuario = usuario.rol.value if hasattr(usuario.rol, 'value') else str(usuario.rol)
            
            # Calcular edad del usuario
            edad_usuario = self._calculate_age(usuario)
            
            # Datos de la institución
            institucion_data = self._get_institucion_data(usuario)
            
            # Datos de archivos y materias
            archivos_data = self._get_archivos_data(usuario)
            
            # Selección del rol de la IA según el tipo de usuario
            if usuario.rol == RolUsuario.PROFESOR:
                rol_ia = env_vars['ROL_IA_PROFESORES']
                materias_info = self._get_materias_profesor(usuario)
            else:
                rol_ia = env_vars['ROL_IA_ALUMNOS']
                materias_info = self._get_materias_alumno(usuario)
            
            # Construir prompt base
            prompt_parts = [
                f"Eres {env_vars['NOMBRE']}, {rol_ia}.",
                f"Tus limitaciones son: {env_vars['LIMITACIONES']}",
                "Ahora mismo estás hablando con:",
                f"{nombre_usuario} {apellido_usuario}.",
                f"Su rol es: {rol_usuario}.",
                f"Su edad es: {edad_usuario} años.",
                f"Sesgo de edad para algunos temas: {env_vars['EDAD_REGULACION']} años.",
                "Información de la institución:",
                f"Nombre: {institucion_data['nombre']}",
                f"Valores institucionales: {institucion_data['valores']}",
                f"Metodología pedagógica: {institucion_data['metodologia']}",
                f"Configuración IA: {institucion_data['configuracion']}",
                ""
            ]
            
            # Agregar información específica según el rol
            if usuario.rol == RolUsuario.PROFESOR:
                prompt_parts.extend([
                    "Materias que enseña:",
                ])
                for materia in materias_info:
                    prompt_parts.append(f"- {materia['nombre']} ({materia['curso']})")
            else:
                prompt_parts.extend([
                    "Materias en las que está inscrito:",
                ])
                for materia in materias_info:
                    prompt_parts.append(f"- {materia['nombre']} ({materia['curso']})")
            
            prompt_parts.extend([
                "",
                f"Archivos y contenidos disponibles del {'profesor' if usuario.rol == RolUsuario.PROFESOR else 'estudiante'}:"
            ])
            
            # Agregar archivos
            if archivos_data:
                if usuario.rol == RolUsuario.PROFESOR:
                    # Para profesores: solo nombres de archivos
                    for idx, archivo in enumerate(archivos_data, 1):
                        prompt_parts.extend([
                            f"",
                            f"Archivo {idx}:",
                            f"- Tema: {archivo['tema']}",
                            f"- Materia: {archivo['materia']}",
                            f"- Nombre: {archivo['nombre_archivo']}"
                        ])
                else:
                    # Para alumnos: contenido completo
                    for idx, archivo in enumerate(archivos_data, 1):
                        prompt_parts.extend([
                            f"Archivos Cargados por el prfoesor.",
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
            # Prompt básico de fallback
            rol_fallback = "profesor" if usuario.rol == RolUsuario.PROFESOR else "estudiante"
            return f"Eres un asistente educativo especializado para {rol_fallback}s. Ayuda de manera apropiada y educativa. Puedes usar formato Markdown completo en tus respuestas."
    
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
                # Edad por defecto según el rol
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
            # Consultar materias del profesor usando la tabla de asociación
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
            
            # Si el alumno tiene cursos asignados
            if hasattr(alumno, 'cursos') and alumno.cursos:
                for curso in alumno.cursos:
                    # Obtener materias del curso
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
    
    def obtener_chats_usuario(self, usuario_id: int) -> List[ChatIA]:
        """Obtiene todos los chats del usuario"""
        try:
            chats = ChatIA.query.filter_by(
                usuario_id=usuario_id
            ).order_by(
                ChatIA.fecha_ultimo_mensaje.desc()
            ).all()
            
            return chats
        except Exception as e:
            logger.error(f"Error obteniendo chats: {e}")
            return []
    
    def obtener_mensajes_chat(self, chat_id: int) -> List[Dict]:
        """Obtiene todos los mensajes de un chat con contenido renderizado"""
        try:
            mensajes_db = MensajeChatIA.query.filter_by(
                chat_id=chat_id
            ).order_by(
                MensajeChatIA.fecha_envio.asc()
            ).all()
            
            mensajes_procesados = []
            for mensaje in mensajes_db:
                mensaje_dict = {
                    'id': mensaje.id,
                    'contenido_original': mensaje.contenido,
                    'contenido_renderizado': mensaje.contenido,  # Por defecto, sin renderizar
                    'es_usuario': mensaje.es_usuario,
                    'fecha_envio': mensaje.fecha_envio,
                    'chat_id': mensaje.chat_id
                }
                
                # Renderizar solo los mensajes de la IA (no los del usuario)
                if not mensaje.es_usuario:
                    try:
                        mensaje_dict['contenido_renderizado'] = markdown_renderer.render(mensaje.contenido)
                    except Exception as render_error:
                        logger.warning(f"Error renderizando mensaje {mensaje.id}: {render_error}")
                        # Si hay error en el renderizado, usar el contenido original
                        mensaje_dict['contenido_renderizado'] = mensaje.contenido
                
                mensajes_procesados.append(mensaje_dict)
            
            return mensajes_procesados
        except Exception as e:
            logger.error(f"Error obteniendo mensajes: {e}")
            return []
    
    def enviar_mensaje(self, chat_id: int, contenido: str, usuario: Usuario) -> Tuple[bool, Optional[str]]:
        """Envía un mensaje y obtiene respuesta de la IA"""
        try:
            if not self.client:
                return False, "Cliente de IA no disponible"
            
            # Verificar que el chat pertenece al usuario
            chat = ChatIA.query.filter_by(
                id=chat_id, 
                usuario_id=usuario.id
            ).first()
            
            if not chat:
                return False, "Chat no encontrado"
            
            # Guardar mensaje del usuario
            mensaje_usuario = MensajeChatIA(
                contenido=contenido,
                es_usuario=True,
                chat_id=chat_id,
                fecha_envio=datetime.utcnow()
            )
            
            db.session.add(mensaje_usuario)
            db.session.flush()  # Para obtener el ID
            
            # Obtener historial de mensajes para contexto (obtener objetos originales para la API)
            mensajes_previos_db = MensajeChatIA.query.filter_by(
                chat_id=chat_id
            ).order_by(
                MensajeChatIA.fecha_envio.asc()
            ).all()
            
            # Construir prompt del sistema
            system_prompt = self._build_system_prompt(usuario)
            
            # Preparar historial para la API
            messages = [{"role": "system", "content": system_prompt}]
            
            # Agregar mensajes previos (últimos 20 para no exceder límites)
            for msg in mensajes_previos_db[-20:]:
                if msg.id != mensaje_usuario.id:  # Excluir el mensaje actual
                    role = "user" if msg.es_usuario else "assistant"
                    messages.append({
                        "role": role,
                        "content": msg.contenido  # Usar contenido original sin renderizar
                    })
            
            # Agregar mensaje actual
            messages.append({
                "role": "user",
                "content": contenido
            })
            
            # Llamar a la API de Groq
            try:
                groq_config = self._get_groq_config()
                
                completion = self.client.chat.completions.create(
                    model=groq_config["model"],
                    messages=messages,
                    temperature=groq_config["temperature"],
                    max_tokens=groq_config["max_tokens"],
                    top_p=groq_config["top_p"],
                    stop=None,
                    stream=False
                )
                
                respuesta_ia = completion.choices[0].message.content
                
            except Exception as api_error:
                logger.error(f"Error en API de Groq: {api_error}")
                respuesta_ia = "Lo siento, estoy experimentando dificultades técnicas. Por favor, intenta nuevamente en unos momentos."
            
            # Guardar respuesta de la IA (sin renderizar en BD)
            mensaje_ia = MensajeChatIA(
                contenido=respuesta_ia,  # Contenido original sin renderizar
                es_usuario=False,
                chat_id=chat_id,
                fecha_envio=datetime.utcnow()
            )
            
            db.session.add(mensaje_ia)
            
            # Actualizar fecha del último mensaje del chat
            chat.fecha_ultimo_mensaje = datetime.utcnow()
            
            # Si es el primer intercambio, generar nombre del chat automáticamente
            if not chat.nombre_chat or chat.nombre_chat.startswith("Chat "):
                try:
                    nombre_sugerido = self._generar_nombre_chat(contenido, respuesta_ia)
                    if nombre_sugerido:
                        chat.nombre_chat = nombre_sugerido
                except Exception as e:
                    logger.warning(f"Error generando nombre de chat: {e}")
            
            db.session.commit()
            
            # Renderizar la respuesta para enviarla al frontend
            try:
                respuesta_renderizada = markdown_renderer.render(respuesta_ia)
            except Exception as render_error:
                logger.warning(f"Error renderizando respuesta: {render_error}")
                respuesta_renderizada = respuesta_ia
            
            return True, respuesta_renderizada
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error enviando mensaje: {e}")
            return False, f"Error interno: {str(e)}"
    
    def _generar_nombre_chat(self, mensaje_usuario: str, respuesta_ia: str) -> Optional[str]:
        """Genera un nombre descriptivo para el chat basado en el primer intercambio"""
        try:
            if not self.client:
                return None
            
            groq_config = self._get_groq_config()
            
            prompt_nombre = f"""
            Basándote en esta conversación inicial entre un usuario y un asistente educativo, 
            genera un título corto y descriptivo (máximo 4-5 palabras) que capture el tema principal:

            Usuario: {mensaje_usuario[:200]}...
            Asistente: {respuesta_ia[:200]}...

            Responde solo con el título, sin comillas ni explicaciones.
            """
            
            completion = self.client.chat.completions.create(
                model=groq_config["model"],
                messages=[{"role": "user", "content": prompt_nombre}],
                temperature=0.3,
                max_tokens=50
            )
            
            nombre = completion.choices[0].message.content.strip()
            
            # Limpiar y validar el nombre
            if len(nombre) > 50:
                nombre = nombre[:47] + "..."
            
            return nombre if nombre else None
            
        except Exception as e:
            logger.error(f"Error generando nombre de chat: {e}")
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

