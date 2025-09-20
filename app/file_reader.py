import os
import mimetypes
import fitz
import docx
from pptx import Presentation

def procesar_archivo(filepath):
    mime_type, _ = mimetypes.guess_type(filepath)
    ext = os.path.splitext(filepath)[1].lower()

    if ext == '.pdf':
        return extraer_pdf(filepath)
    elif ext in ['.doc', '.docx']:
        return extraer_word(filepath)
    elif ext == '.txt':
        return extraer_txt(filepath)
    elif ext in ['.jpg', '.jpeg', '.png']:
        return extraer_ocr(filepath)
    elif ext in ['.ppt', '.pptx']:
        return extraer_powerpoint(filepath)
    else:
        return f"[Archivo {os.path.basename(filepath)} subido. No se pudo procesar su contenido automáticamente.]"


def extraer_pdf(filepath):
    text = ""
    with fitz.open(filepath) as doc:
        for page in doc:
            text += page.get_text()
    return text.strip()


def extraer_word(filepath):
    doc = docx.Document(filepath)
    return "\n".join([p.text for p in doc.paragraphs]).strip()


def extraer_txt(filepath):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        return f.read().strip()


def extraer_powerpoint(filepath):
    prs = Presentation(filepath)
    text = ""
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                text += shape.text + "\n"
    return text.strip()

