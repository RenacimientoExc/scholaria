import re, html
from urllib.parse import urlparse

class MarkdownRenderer:
    """Renderizador completo de Markdown para el chat de IA"""
    
    def __init__(self):
        self.code_languages = {
            'python': 'Python', 'py': 'Python',
            'javascript': 'JavaScript', 'js': 'JavaScript',
            'html': 'HTML', 'css': 'CSS',
            'java': 'Java', 'c': 'C', 'cpp': 'C++', 'c++': 'C++',
            'csharp': 'C#', 'c#': 'C#',
            'php': 'PHP', 'ruby': 'Ruby',
            'go': 'Go', 'rust': 'Rust',
            'sql': 'SQL', 'json': 'JSON',
            'xml': 'XML', 'yaml': 'YAML',
            'bash': 'Bash', 'shell': 'Shell',
            'r': 'R', 'matlab': 'MATLAB',
            'swift': 'Swift', 'kotlin': 'Kotlin',
            'typescript': 'TypeScript', 'ts': 'TypeScript'
        }
    
    def render(self, text: str) -> str:
        """Renderiza texto Markdown a HTML completo"""
        if not text:
            return ""
        
        # Escapar HTML básico primero
        text = html.escape(text)
        
        # Renderizar en orden específico para evitar conflictos
        text = self._render_code_blocks(text)
        text = self._render_math_blocks(text)
        text = self._render_tables(text)
        text = self._render_headers(text)
        text = self._render_blockquotes(text)
        text = self._render_lists(text)
        text = self._render_horizontal_rules(text)
        text = self._render_inline_code(text)
        text = self._render_inline_math(text)
        text = self._render_links(text)
        text = self._render_images(text)
        text = self._render_bold_italic(text)
        text = self._render_strikethrough(text)
        text = self._render_highlights(text)
        text = self._render_line_breaks(text)
        text = self._render_paragraphs(text)
        
        return text
    
    def _render_code_blocks(self, text: str) -> str:
        """Renderiza bloques de código con sintaxis highlighting"""
        def replace_code_block(match):
            language = match.group(1) or ''
            code = match.group(2) if match.group(2) is not None else match.group(4) or ''
            
            # Decodificar HTML entities en el código
            code = html.unescape(code)
            
            # Obtener nombre del lenguaje
            lang_name = self.code_languages.get(language.lower(), language.title() if language else 'Código')
            
            # Renderizar el código con highlight básico
            highlighted_code = self._highlight_code(code, language)
            
            return f'''
            <div class="code-block-container">
                <div class="code-header">
                    <span class="code-language">{lang_name}</span>
                    <button class="copy-btn" onclick="copyCode(this)" data-code="{html.escape(code)}">
                        📋 Copiar
                    </button>
                </div>
                <pre class="code-block language-{language}"><code>{highlighted_code}</code></pre>
            </div>
            '''
        
        # Patrón mejorado para bloques de código con ``` o ~~~
        pattern = r'```(\w+)?\s*\n(.*?)\n```|~~~(\w+)?\s*\n(.*?)\n~~~'
        text = re.sub(pattern, replace_code_block, text, flags=re.DOTALL)
        
        return text
    
    def _highlight_code(self, code: str, language: str) -> str:
        """Highlighting básico de sintaxis"""
        if not language:
            return html.escape(code)
        
        code = html.escape(code)
        
        if language.lower() in ['python', 'py']:
            # Palabras clave de Python
            keywords = ['def', 'class', 'if', 'elif', 'else', 'for', 'while', 'try', 'except', 'import', 'from', 'return', 'yield', 'lambda', 'with', 'as', 'pass', 'break', 'continue', 'and', 'or', 'not', 'in', 'is', 'None', 'True', 'False']
            for keyword in keywords:
                code = re.sub(f'\\b{re.escape(keyword)}\\b', f'<span class="keyword">{keyword}</span>', code)
            
            # Strings (mejorado)
            code = re.sub(r'(["\'])((?:\\.|(?!\1)[^\\])*?)\1', r'<span class="string">\1\2\1</span>', code)
            
            # Comentarios
            code = re.sub(r'(#.*?)$', r'<span class="comment">\1</span>', code, flags=re.MULTILINE)
            
        elif language.lower() in ['javascript', 'js']:
            # Palabras clave de JavaScript
            keywords = ['function', 'var', 'let', 'const', 'if', 'else', 'for', 'while', 'return', 'class', 'extends', 'import', 'export', 'default', 'true', 'false', 'null', 'undefined']
            for keyword in keywords:
                code = re.sub(f'\\b{re.escape(keyword)}\\b', f'<span class="keyword">{keyword}</span>', code)
            
            # Strings
            code = re.sub(r'(["\'])((?:\\.|(?!\1)[^\\])*?)\1', r'<span class="string">\1\2\1</span>', code)
            
            # Comentarios
            code = re.sub(r'(//.*?)$', r'<span class="comment">\1</span>', code, flags=re.MULTILINE)
            code = re.sub(r'(/\*.*?\*/)', r'<span class="comment">\1</span>', code, flags=re.DOTALL)
            
        elif language.lower() == 'css':
            # Selectores CSS
            code = re.sub(r'([.#]?[\w-]+)\s*{', r'<span class="selector">\1</span> {', code)
            # Propiedades
            code = re.sub(r'(\w+-?\w*)\s*:', r'<span class="property">\1</span>:', code)
        
        return code
    
    def _render_math_blocks(self, text: str) -> str:
        """Renderiza bloques de matemáticas con MathJax"""
        # Bloques de matemáticas con $$
        def replace_math_block(match):
            math_content = match.group(1)
            return f'<div class="math-block">$$\\displaystyle {math_content}$$</div>'
        
        text = re.sub(r'\$\$\s*\n?(.*?)\n?\s*\$\$', replace_math_block, text, flags=re.DOTALL)
        
        return text
    
    def _render_inline_math(self, text: str) -> str:
        """Renderiza matemáticas en línea"""
        # Matemáticas inline con $ (evitando conflictos con $$)
        text = re.sub(r'(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)', r'<span class="math-inline">$\1$</span>', text)
        
        return text
    
    def _render_tables(self, text: str) -> str:
        """Renderiza tablas Markdown mejorado"""
        def replace_table(match):
            table_text = match.group(0).strip()
            lines = [line.strip() for line in table_text.split('\n') if line.strip()]
            
            if len(lines) < 2:
                return match.group(0)
            
            # Buscar la línea separadora
            separator_line_idx = -1
            for i, line in enumerate(lines):
                if re.match(r'^\s*\|[\s\-:|]*\|\s*$', line) or re.match(r'^[\s\-:|]+$', line):
                    separator_line_idx = i
                    break
            
            if separator_line_idx == -1:
                return match.group(0)
            
            # Dividir en header y body
            header_lines = lines[:separator_line_idx]
            separator_line = lines[separator_line_idx]
            body_lines = lines[separator_line_idx + 1:]
            
            # Procesar header
            header_cells = []
            if header_lines:
                for line in header_lines:
                    if '|' in line:
                        raw_cells = line.split('|')
                        # Limpiar celdas vacías al inicio y final
                        if raw_cells and not raw_cells[0].strip():
                            raw_cells = raw_cells[1:]
                        if raw_cells and not raw_cells[-1].strip():
                            raw_cells = raw_cells[:-1]
                        
                        if not header_cells:  # Primera línea
                            header_cells = [cell.strip() for cell in raw_cells]
                        else:  # Líneas adicionales
                            for i, cell in enumerate(raw_cells):
                                if i < len(header_cells):
                                    header_cells[i] += ' ' + cell.strip()
            
            # Procesar alignment
            alignments = []
            if '|' in separator_line:
                align_cells = separator_line.split('|')
                if align_cells and not align_cells[0].strip():
                    align_cells = align_cells[1:]
                if align_cells and not align_cells[-1].strip():
                    align_cells = align_cells[:-1]
            else:
                align_cells = [separator_line]
            
            for cell in align_cells:
                cell = cell.strip()
                if cell.startswith(':') and cell.endswith(':'):
                    alignments.append('center')
                elif cell.endswith(':'):
                    alignments.append('right')
                else:
                    alignments.append('left')
            
            # Construir tabla HTML
            table_html = '<div class="table-container"><table class="markdown-table">'
            
            # Header
            if header_cells:
                table_html += '<thead><tr>'
                for i, cell in enumerate(header_cells):
                    align = alignments[i] if i < len(alignments) else 'left'
                    rendered_cell = self._render_table_cell_content(cell)
                    table_html += f'<th style="text-align: {align}">{rendered_cell}</th>'
                table_html += '</tr></thead>'
            
            # Body
            if body_lines:
                table_html += '<tbody>'
                for line in body_lines:
                    if '|' in line:
                        raw_cells = line.split('|')
                        if raw_cells and not raw_cells[0].strip():
                            raw_cells = raw_cells[1:]
                        if raw_cells and not raw_cells[-1].strip():
                            raw_cells = raw_cells[:-1]
                        
                        cells = [cell.strip() for cell in raw_cells]
                        
                        table_html += '<tr>'
                        for i, cell in enumerate(cells):
                            align = alignments[i] if i < len(alignments) else 'left'
                            rendered_cell = self._render_table_cell_content(cell)
                            table_html += f'<td style="text-align: {align}">{rendered_cell}</td>'
                        table_html += '</tr>'
                
                table_html += '</tbody>'
            
            table_html += '</table></div>'
            return table_html
        
        # Patrón mejorado para tablas
        table_pattern = r'(?:^.*\|.*$\n)+^[\s]*\|?[\s\-:|]*\|?[\s]*$\n(?:^.*\|.*$\n?)*'
        text = re.sub(table_pattern, replace_table, text, flags=re.MULTILINE)
        
        return text
    
    def _render_table_cell_content(self, cell: str) -> str:
        """Renderiza el contenido de una celda de tabla con elementos inline"""
        if not cell:
            return ""
        
        # Renderizar elementos inline comunes en tablas
        cell = self._render_bold_italic_simple(cell)
        cell = self._render_inline_code_simple(cell)
        cell = self._render_links_simple(cell)
        cell = cell.replace('<br>', '<br>')  # Mantener <br> tags
        cell = re.sub(r'  $', '<br>', cell, flags=re.MULTILINE)  # Dos espacios al final = <br>
        
        return cell
    
    def _render_bold_italic_simple(self, text: str) -> str:
        """Versión simplificada para celdas de tabla"""
        # Negrita e itálica combinadas
        text = re.sub(r'\*\*\*([^*]+)\*\*\*', r'<strong><em>\1</em></strong>', text)
        text = re.sub(r'___([^_]+)___', r'<strong><em>\1</em></strong>', text)
        
        # Solo negrita
        text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', text)
        
        # Solo itálica (evitando conflictos)
        text = re.sub(r'(?<!\w)\*([^*\s][^*]*?[^*\s]|\w)\*(?!\w)', r'<em>\1</em>', text)
        text = re.sub(r'(?<!\w)_([^_\s][^_]*?[^_\s]|\w)_(?!\w)', r'<em>\1</em>', text)
        
        return text
    
    def _render_inline_code_simple(self, text: str) -> str:
        """Versión simplificada para celdas de tabla"""
        text = re.sub(r'`([^`\n]+)`', r'<code class="inline-code">\1</code>', text)
        return text
    
    def _render_links_simple(self, text: str) -> str:
        """Versión simplificada para celdas de tabla"""
        def replace_link(match):
            link_text = match.group(1)
            url = match.group(2)
            title = match.group(3) if match.group(3) else ''
            
            # Validar URL
            if not self._is_safe_url(url):
                return f'<span class="invalid-link">{link_text}</span>'
            
            is_external = self._is_external_url(url)
            target = ' target="_blank" rel="noopener noreferrer"' if is_external else ''
            title_attr = f' title="{html.escape(title)}"' if title else ''
            
            return f'<a href="{html.escape(url)}" class="markdown-link"{target}{title_attr}>{link_text}</a>'
        
        text = re.sub(r'\[([^\]]+)\]\(([^\s\)]+)(?:\s+"([^"]+)")?\)', replace_link, text)
        return text
    
    def _render_headers(self, text: str) -> str:
        """Renderiza headers (H1-H6)"""
        def replace_header(match):
            level = len(match.group(1))
            content = match.group(2).strip()
            header_id = self._create_header_id(content)
            return f'<h{level} id="{header_id}" class="markdown-header">{self._render_inline_elements(content)}</h{level}>'
        
        # Headers con #
        text = re.sub(r'^(#{1,6})\s+(.+)$', replace_header, text, flags=re.MULTILINE)
        
        return text
    
    def _create_header_id(self, text: str) -> str:
        """Crea ID único para headers"""
        # Remover HTML y caracteres especiales
        clean_text = re.sub(r'<[^>]+>', '', text)
        clean_text = re.sub(r'[^\w\s-]', '', clean_text)
        clean_text = re.sub(r'\s+', '-', clean_text.strip())
        return clean_text.lower()
    
    def _render_blockquotes(self, text: str) -> str:
        """Renderiza blockquotes"""
        def replace_blockquote(match):
            content = match.group(1)
            # Procesar líneas del blockquote
            lines = content.split('\n')
            processed_lines = []
            for line in lines:
                line = re.sub(r'^>\s?', '', line)
                processed_lines.append(line)
            
            quote_content = '\n'.join(processed_lines)
            return f'<blockquote class="markdown-blockquote">{self._render_inline_elements(quote_content)}</blockquote>'
        
        # Blockquotes multilínea
        text = re.sub(r'^((?:^>\s?.*\n?)+)', replace_blockquote, text, flags=re.MULTILINE)
        
        return text
    
    def _render_lists(self, text: str) -> str:
        """Renderiza listas ordenadas y no ordenadas"""
        def process_list_item(line):
            # Remover marcadores de lista
            cleaned = re.sub(r'^[\s]*[-*+]\s+', '', line)  # Lista no ordenada
            cleaned = re.sub(r'^[\s]*\d+\.\s+', '', cleaned)  # Lista ordenada
            return self._render_inline_elements(cleaned)
        
        # Listas no ordenadas
        def replace_unordered_list(match):
            lines = match.group(0).strip().split('\n')
            items = [f'<li>{process_list_item(line)}</li>' for line in lines if line.strip()]
            return f'<ul class="markdown-list">{"".join(items)}</ul>'
        
        # Listas ordenadas
        def replace_ordered_list(match):
            lines = match.group(0).strip().split('\n')
            items = [f'<li>{process_list_item(line)}</li>' for line in lines if line.strip()]
            return f'<ol class="markdown-list">{"".join(items)}</ol>'
        
        # Procesar listas no ordenadas
        text = re.sub(r'^((?:^[\s]*[-*+]\s+.+\n?)+)', replace_unordered_list, text, flags=re.MULTILINE)
        
        # Procesar listas ordenadas
        text = re.sub(r'^((?:^[\s]*\d+\.\s+.+\n?)+)', replace_ordered_list, text, flags=re.MULTILINE)
        
        return text
    
    def _render_horizontal_rules(self, text: str) -> str:
        """Renderiza líneas horizontales"""
        text = re.sub(r'^[\s]*(-{3,}|={3,}|\*{3,})[\s]*$', '<hr class="markdown-hr">', text, flags=re.MULTILINE)
        return text
    
    def _render_inline_code(self, text: str) -> str:
        """Renderiza código inline"""
        text = re.sub(r'`([^`\n]+)`', r'<code class="inline-code">\1</code>', text)
        return text
    
    def _render_links(self, text: str) -> str:
        """Renderiza enlaces"""
        def replace_link(match):
            link_text = match.group(1)
            url = match.group(2)
            title = match.group(3) if match.group(3) else ''
            
            # Validar URL
            if not self._is_safe_url(url):
                return f'<span class="invalid-link">{link_text}</span>'
            
            # Determinar si es enlace externo
            is_external = self._is_external_url(url)
            target = ' target="_blank" rel="noopener noreferrer"' if is_external else ''
            title_attr = f' title="{html.escape(title)}"' if title else ''
            
            return f'<a href="{html.escape(url)}" class="markdown-link"{target}{title_attr}>{self._render_inline_elements(link_text)}</a>'
        
        # Enlaces con formato [texto](url "titulo")
        text = re.sub(r'\[([^\]]+)\]\(([^\s\)]+)(?:\s+"([^"]+)")?\)', replace_link, text)
        
        # URLs automáticas (mejorado)
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+[^\s<>"{}|\\^`\[\].,!?:;]'
        def replace_auto_url(match):
            url = match.group(0)
            return f'<a href="{url}" class="markdown-link auto-link" target="_blank" rel="noopener noreferrer">{url}</a>'
        
        text = re.sub(url_pattern, replace_auto_url, text)
        
        return text
    
    def _render_images(self, text: str) -> str:
        """Renderiza imágenes"""
        def replace_image(match):
            alt_text = match.group(1)
            url = match.group(2)
            title = match.group(3) if match.group(3) else alt_text
            
            # Validar URL de imagen
            if not self._is_safe_url(url):
                return f'<span class="invalid-image">Imagen no válida: {alt_text}</span>'
            
            return f'''
            <div class="image-container">
                <img src="{html.escape(url)}" alt="{html.escape(alt_text)}" title="{html.escape(title)}" class="markdown-image" loading="lazy">
            </div>
            '''
        
        # Imágenes con formato ![alt](url "title")
        text = re.sub(r'!\[([^\]]*)\]\(([^\s\)]+)(?:\s+"([^"]+)")?\)', replace_image, text)
        
        return text
    
    def _render_bold_italic(self, text: str) -> str:
        """Renderiza texto en negrita e itálica"""
        # Negrita e itálica combinadas
        text = re.sub(r'\*\*\*([^*]+)\*\*\*', r'<strong><em>\1</em></strong>', text)
        text = re.sub(r'___([^_]+)___', r'<strong><em>\1</em></strong>', text)
        
        # Solo negrita
        text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', text)
        
        # Solo itálica (mejorado para evitar conflictos)
        text = re.sub(r'(?<!\w)\*([^*\s][^*]*?[^*\s]|\w)\*(?!\w)', r'<em>\1</em>', text)
        text = re.sub(r'(?<!\w)_([^_\s][^_]*?[^_\s]|\w)_(?!\w)', r'<em>\1</em>', text)
        
        return text
    
    def _render_strikethrough(self, text: str) -> str:
        """Renderiza texto tachado"""
        text = re.sub(r'~~([^~]+)~~', r'<del>\1</del>', text)
        return text
    
    def _render_highlights(self, text: str) -> str:
        """Renderiza texto resaltado"""
        text = re.sub(r'==([^=]+)==', r'<mark>\1</mark>', text)
        return text
    
    def _render_line_breaks(self, text: str) -> str:
        """Renderiza saltos de línea"""
        # Dos espacios al final de línea + salto de línea = <br>
        text = re.sub(r'  \n', '<br>\n', text)
        return text
    
    def _render_paragraphs(self, text: str) -> str:
        """Renderiza párrafos"""
        # Dividir por líneas vacías para crear párrafos
        paragraphs = re.split(r'\n\s*\n', text.strip())
        
        processed_paragraphs = []
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if paragraph:
                # No envolver en <p> si ya tiene elementos de bloque
                if not re.search(r'<(?:div|h[1-6]|ul|ol|table|blockquote|pre|hr)', paragraph):
                    paragraph = f'<p class="markdown-paragraph">{paragraph}</p>'
                processed_paragraphs.append(paragraph)
        
        return '\n\n'.join(processed_paragraphs)
    
    def _render_inline_elements(self, text: str) -> str:
        """Renderiza elementos inline sin procesar bloques"""
        text = self._render_inline_code(text)
        text = self._render_inline_math(text)
        text = self._render_links(text)
        text = self._render_bold_italic(text)
        text = self._render_strikethrough(text)
        text = self._render_highlights(text)
        return text
    
    def _is_safe_url(self, url: str) -> bool:
        """Valida que la URL sea segura"""
        try:
            parsed = urlparse(url)
            # Permitir HTTP, HTTPS, y rutas relativas
            return parsed.scheme in ['http', 'https', ''] and not parsed.netloc.startswith('.')
        except:
            return False
    
    def _is_external_url(self, url: str) -> bool:
        """Determina si la URL es externa"""
        try:
            parsed = urlparse(url)
            return parsed.netloc != ''
        except:
            return False
    
    def get_css_styles(self) -> str:
        """Retorna los estilos CSS necesarios para el renderizado"""
        return '''
        <style>
        /* Estilos para elementos Markdown */
        .markdown-content {
            line-height: 1.6;
            color: #333;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
        }
        
        /* Headers */
        .markdown-header {
            margin-top: 1.5em;
            margin-bottom: 0.5em;
            font-weight: 600;
            line-height: 1.25;
        }
        
        .markdown-header:first-child {
            margin-top: 0;
        }
        
        /* Párrafos */
        .markdown-paragraph {
            margin: 1em 0;
        }
        
        /* Código inline */
        .inline-code {
            background-color: #f6f8fa;
            border-radius: 3px;
            font-size: 85%;
            margin: 0;
            padding: 0.2em 0.4em;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
            color: #d73a49;
        }
        
        /* Bloques de código */
        .code-block-container {
            background-color: #f6f8fa;
            border-radius: 6px;
            margin: 1em 0;
            overflow: hidden;
        }
        
        .code-header {
            background-color: #e1e4e8;
            padding: 8px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #d0d7de;
        }
        
        .code-language {
            font-size: 12px;
            font-weight: 600;
            color: #656d76;
        }
        
        .copy-btn {
            background: none;
            border: none;
            color: #656d76;
            cursor: pointer;
            font-size: 12px;
            padding: 4px 8px;
            border-radius: 3px;
            transition: background-color 0.2s ease;
        }
        
        .copy-btn:hover {
            background-color: #d0d7de;
        }
        
        .code-block {
            background-color: #f6f8fa;
            border-radius: 0;
            font-size: 85%;
            line-height: 1.45;
            overflow: auto;
            padding: 16px;
            margin: 0;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
        }
        
        .code-block code {
            background: transparent;
            border: 0;
            display: inline;
            font-size: inherit;
            line-height: inherit;
            margin: 0;
            overflow: visible;
            padding: 0;
            white-space: pre;
            word-wrap: normal;
        }
        
        /* Syntax highlighting */
        .keyword { color: #d73a49; font-weight: bold; }
        .string { color: #032f62; }
        .comment { color: #6a737d; font-style: italic; }
        .tag { color: #22863a; }
        .selector { color: #6f42c1; }
        .property { color: #005cc5; }
        
        /* Matemáticas */
        .math-block {
            text-align: center;
            margin: 1em 0;
            padding: 1em;
            background-color: #f8f9fa;
            border-radius: 4px;
            overflow-x: auto;
        }
        
        .math-inline {
            background-color: #f6f8fa;
            padding: 0.1em 0.2em;
            border-radius: 3px;
        }
        
        /* Tablas mejoradas */
        .table-container {
            overflow-x: auto;
            margin: 1em 0;
            border-radius: 6px;
            border: 1px solid #d0d7de;
        }
        
        .markdown-table {
            border-collapse: collapse;
            border-spacing: 0;
            width: 100%;
            max-width: 100%;
            background-color: transparent;
            font-size: 14px;
        }
        
        .markdown-table th,
        .markdown-table td {
            padding: 8px 12px;
            border: 1px solid #d0d7de;
            vertical-align: top;
            word-wrap: break-word;
        }
        
        .markdown-table th {
            background-color: #f6f8fa;
            font-weight: 600;
            text-align: left;
        }
        
        .markdown-table td {
            background-color: #ffffff;
        }
        
        .markdown-table tr:nth-child(even) td {
            background-color: #f9f9f9;
        }
        
        .markdown-table th:first-child,
        .markdown-table td:first-child {
            border-left: none;
        }
        
        .markdown-table th:last-child,
        .markdown-table td:last-child {
            border-right: none;
        }
        
        .markdown-table tr:first-child th {
            border-top: none;
        }
        
        .markdown-table tr:last-child td {
            border-bottom: none;
        }
        
        /* Mejor manejo de contenido en celdas */
        .markdown-table td ul,
        .markdown-table td ol {
            margin: 0.5em 0;
            padding-left: 1.5em;
        }
        
        .markdown-table td li {
            margin: 0.2em 0;
        }
        
        .markdown-table td p {
            margin: 0.5em 0;
        }
        
        .markdown-table td p:first-child {
            margin-top: 0;
        }
        
        .markdown-table td p:last-child {
            margin-bottom: 0;
        }
        
        .markdown-table td br {
            line-height: 1.4;
        }
        
        /* Listas */
        .markdown-list {
            margin: 1em 0;
            padding-left: 2em;
        }
        
        .markdown-list li {
            margin: 0.25em 0;
        }
        
        /* Listas anidadas */
        .markdown-list .markdown-list {
            margin: 0.25em 0;
        }
        
        /* Blockquotes */
        .markdown-blockquote {
            margin: 1em 0;
            padding: 0 1em;
            color: #656d76;
            border-left: 4px solid #d0d7de;
            background-color: #f6f8fa;
            border-radius: 0 4px 4px 0;
        }
        
        .markdown-blockquote p {
            margin: 0.5em 0;
        }
        
        /* Enlaces */
        .markdown-link {
            color: #0969da;
            text-decoration: none;
            border-bottom: 1px solid transparent;
            transition: all 0.2s ease;
        }
        
        .markdown-link:hover {
            text-decoration: underline;
            border-bottom-color: #0969da;
        }
        
        .invalid-link {
            color: #cf222e;
            text-decoration: line-through;
        }
        
        /* Enlaces automáticos */
        .auto-link {
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
            font-size: 0.9em;
            background-color: #f6f8fa;
            padding: 0.1em 0.3em;
            border-radius: 3px;
        }
        
        /* Imágenes */
        .image-container {
            text-align: center;
            margin: 1em 0;
        }
        
        .markdown-image {
            max-width: 100%;
            height: auto;
            border-radius: 6px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24);
            transition: transform 0.2s ease;
        }
        
        .markdown-image:hover {
            transform: scale(1.02);
        }
        
        .invalid-image {
            color: #cf222e;
            font-style: italic;
            background-color: #fff1f0;
            padding: 0.5em 1em;
            border-radius: 4px;
            border-left: 4px solid #cf222e;
        }
        
        /* Líneas horizontales */
        .markdown-hr {
            border: none;
            border-top: 2px solid #d0d7de;
            margin: 1.5em 0;
            background: linear-gradient(to right, transparent, #d0d7de 20%, #d0d7de 80%, transparent);
        }
        
        /* Elementos de formato */
        strong { 
            font-weight: 600; 
            color: #1f2328;
        }
        
        em { 
            font-style: italic; 
            color: #656d76;
        }
        
        del { 
            text-decoration: line-through; 
            opacity: 0.7; 
            color: #656d76;
        }
        
        mark { 
            background-color: #fff8c5; 
            padding: 0.1em 0.3em; 
            border-radius: 3px;
            border: 1px solid #f1e05a;
        }
        
        /* Modo oscuro */
        [data-theme="dark"] .markdown-content {
            color: #e6edf3;
        }
        
        [data-theme="dark"] .inline-code {
            background-color: #21262d;
            color: #f85149;
        }
        
        [data-theme="dark"] .code-block-container {
            background-color: #21262d;
        }
        
        [data-theme="dark"] .code-header {
            background-color: #30363d;
            border-bottom-color: #21262d;
        }
        
        [data-theme="dark"] .code-language {
            color: #7d8590;
        }
        
        [data-theme="dark"] .copy-btn {
            color: #7d8590;
        }
        
        [data-theme="dark"] .copy-btn:hover {
            background-color: #21262d;
        }
        
        [data-theme="dark"] .code-block {
            background-color: #21262d;
            color: #e6edf3;
        }
        
        [data-theme="dark"] .table-container {
            border-color: #30363d;
        }
        
        [data-theme="dark"] .markdown-table th,
        [data-theme="dark"] .markdown-table td {
            border-color: #30363d;
        }
        
        [data-theme="dark"] .markdown-table th {
            background-color: #21262d;
        }
        
        [data-theme="dark"] .markdown-table td {
            background-color: #0d1117;
        }
        
        [data-theme="dark"] .markdown-table tr:nth-child(even) td {
            background-color: #161b22;
        }
        
        [data-theme="dark"] .markdown-blockquote {
            color: #7d8590;
            border-left-color: #30363d;
            background-color: #21262d;
        }
        
        [data-theme="dark"] .markdown-link {
            color: #58a6ff;
        }
        
        [data-theme="dark"] .markdown-link:hover {
            border-bottom-color: #58a6ff;
        }
        
        [data-theme="dark"] .auto-link {
            background-color: #21262d;
        }
        
        [data-theme="dark"] .math-block {
            background-color: #21262d;
        }
        
        [data-theme="dark"] .math-inline {
            background-color: #21262d;
        }
        
        [data-theme="dark"] strong {
            color: #f0f6fc;
        }
        
        [data-theme="dark"] mark {
            background-color: #3d2906;
            border-color: #9e6a03;
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            .markdown-content {
                font-size: 14px;
            }
            
            .code-block {
                font-size: 12px;
                padding: 12px;
            }
            
            .table-container {
                font-size: 12px;
            }
            
            .markdown-table th,
            .markdown-table td {
                padding: 6px 8px;
            }
            
            .code-header {
                padding: 6px 12px;
            }
            
            .markdown-list {
                padding-left: 1.5em;
            }
        }
        
        @media (max-width: 480px) {
            .markdown-content {
                font-size: 13px;
            }
            
            .markdown-table {
                font-size: 11px;
            }
            
            .markdown-table th,
            .markdown-table td {
                padding: 4px 6px;
            }
        }
        </style>
        
        <script>
        // Script para copiar código
        function copyCode(button) {
            const code = button.getAttribute('data-code');
            navigator.clipboard.writeText(code).then(function() {
                const originalText = button.textContent;
                button.textContent = '✅ Copiado';
                setTimeout(() => {
                    button.textContent = originalText;
                }, 2000);
            }).catch(function(err) {
                console.error('Error copiando código: ', err);
                const originalText = button.textContent;
                button.textContent = '❌ Error';
                setTimeout(() => {
                    button.textContent = originalText;
                }, 2000);
            });
        }
        
        // Cargar MathJax si hay contenido matemático
        document.addEventListener('DOMContentLoaded', function() {
            if (document.querySelector('.math-block') || document.querySelector('.math-inline')) {
                // Configurar MathJax
                window.MathJax = {
                    tex: {
                        inlineMath: [[', ']],
                        displayMath: [['$', '$']],
                        processEscapes: true,
                        processEnvironments: true
                    },
                    options: {
                        skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
                        processHtmlClass: 'math-block|math-inline'
                    }
                };
                
                const script = document.createElement('script');
                script.src = 'https://polyfill.io/v3/polyfill.min.js?features=es6';
                document.head.appendChild(script);
                
                const script2 = document.createElement('script');
                script2.src = 'https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js';
                script2.onload = function() {
                    if (window.MathJax) {
                        MathJax.typesetPromise();
                    }
                };
                document.head.appendChild(script2);
            }
        });
        
        // Mejorar el scroll horizontal en tablas
        document.addEventListener('DOMContentLoaded', function() {
            const tables = document.querySelectorAll('.table-container');
            tables.forEach(container => {
                const table = container.querySelector('table');
                if (table && table.scrollWidth > container.clientWidth) {
                    container.style.cursor = 'grab';
                    let isDown = false;
                    let startX;
                    let scrollLeft;
                    
                    container.addEventListener('mousedown', (e) => {
                        isDown = true;
                        container.style.cursor = 'grabbing';
                        startX = e.pageX - container.offsetLeft;
                        scrollLeft = container.scrollLeft;
                    });
                    
                    container.addEventListener('mouseleave', () => {
                        isDown = false;
                        container.style.cursor = 'grab';
                    });
                    
                    container.addEventListener('mouseup', () => {
                        isDown = false;
                        container.style.cursor = 'grab';
                    });
                    
                    container.addEventListener('mousemove', (e) => {
                        if (!isDown) return;
                        e.preventDefault();
                        const x = e.pageX - container.offsetLeft;
                        const walk = (x - startX) * 2;
                        container.scrollLeft = scrollLeft - walk;
                    });
                }
            });
        });
        </script>
        '''

# Instancia global del renderizador
markdown_renderer = MarkdownRenderer()