# scripts/generate_code_summary.py
import ast
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

class CodeAnalyzer:
    """Analyze Python files to extract functions and their signatures."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.tree = None
        self.source = ""

    def parse(self) -> bool:
        """Parse the Python file."""
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.source = f.read()
            self.tree = ast.parse(self.source)
            return True
        except Exception as e:
            print(f"Error parsing {self.file_path}: {e}")
            return False

    def get_module_docstring(self) -> str:
        """Extract module-level docstring."""
        docstring = ast.get_docstring(self.tree) or ""
        if docstring:
            # Get first line only
            return docstring.split('\n')[0].strip()
        return ""

    def extract_all_functions(self) -> List[Dict]:
        """Extract all functions (including class methods) with their full signatures."""
        functions = []

        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                func_info = {
                    'name': node.name,
                    'signature': self._get_full_signature(node),
                    'docstring': ast.get_docstring(node) or "",
                    'line_number': node.lineno,
                    'class_name': self._get_parent_class(node)
                }
                functions.append(func_info)

        # Sort by line number to maintain order
        functions.sort(key=lambda x: x['line_number'])
        return functions

    def _get_full_signature(self, node: ast.FunctionDef) -> str:
        """Extract the full function signature with defaults."""
        args_list = []

        # Get all arguments
        args = node.args

        # Regular args
        num_defaults = len(args.defaults)
        num_args = len(args.args)

        for i, arg in enumerate(args.args):
            arg_str = arg.arg

            # Add annotation if present
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"

            # Add default value if present
            default_index = i - (num_args - num_defaults)
            if default_index >= 0:
                default_val = ast.unparse(args.defaults[default_index])
                arg_str += f" = {default_val}"

            args_list.append(arg_str)

        # Varargs (*args)
        if args.vararg:
            vararg_str = f"*{args.vararg.arg}"
            if args.vararg.annotation:
                vararg_str += f": {ast.unparse(args.vararg.annotation)}"
            args_list.append(vararg_str)

        # Keyword-only args
        for i, arg in enumerate(args.kwonlyargs):
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            if i < len(args.kw_defaults) and args.kw_defaults[i]:
                arg_str += f" = {ast.unparse(args.kw_defaults[i])}"
            args_list.append(arg_str)

        # Kwargs (**kwargs)
        if args.kwarg:
            kwarg_str = f"**{args.kwarg.arg}"
            if args.kwarg.annotation:
                kwarg_str += f": {ast.unparse(args.kwarg.annotation)}"
            args_list.append(kwarg_str)

        return f"def {node.name}({', '.join(args_list)})"

    def _get_parent_class(self, node: ast.FunctionDef) -> Optional[str]:
        """Try to find parent class name (limited capability)."""
        # This is a simplified approach - AST doesn't directly provide parent info
        # We'll mark methods by checking if first arg is 'self' or 'cls'
        if node.args.args and node.args.args[0].arg in ('self', 'cls'):
            return "method"
        return None


def generate_summary():
    """Generate a code summary in the specified format."""

    # Define the base directories
    sections = {
        'DOD': 'dod',
        'MFX': 'mfx',
        'Scripts': 'scripts',
        'TFS': 'tfs'
    }

    summary = []

    # Header
    summary.append("# Code Repository Summary\n\n")
    summary.append("!!! info \"Auto-Generated Documentation\"\n")
    summary.append(f"    Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

    # Table of Contents
    summary.append("## Table of Contents\n\n")
    for section_name in sections.keys():
        summary.append(f"- [{section_name}](#{section_name.lower()})\n")
    summary.append("- [Repository Statistics](#repository-statistics)\n")
    summary.append("\n<div class='page-break'></div>\n\n")

    # Statistics
    total_modules = 0
    total_functions = 0

    # Process each section
    for section_name, section_path in sections.items():
        summary.append(f"## {section_name}\n\n")

        base_path = Path(section_path)
        if not base_path.exists():
            summary.append(f"*Path not found: {section_path}*\n\n")
            continue

        # Collect all Python files, organized by directory
        py_files = sorted([f for f in base_path.rglob("*.py") if f.name != "__init__.py"])

        if not py_files:
            summary.append("*No Python files found.*\n\n")
            continue

        for py_file in py_files:
            total_modules += 1
            rel_path = py_file.relative_to(base_path)

            # Handle subdirectories in the name
            if rel_path.parent != Path('.'):
                display_name = f"{rel_path.parent}/{py_file.stem}"
            else:
                display_name = py_file.stem

            # Module header with indentation
            summary.append(f"**{display_name}** - `{py_file.name}`")

            # Analyze the file
            analyzer = CodeAnalyzer(py_file)
            if not analyzer.parse():
                summary.append(" *(Error parsing file)*\n\n")
                continue

            # Module docstring
            module_doc = analyzer.get_module_docstring()
            if module_doc:
                summary.append(f" *{module_doc}*")
            summary.append("\n\n")

            # Extract all functions
            functions = analyzer.extract_all_functions()

            if functions:
                for func in functions:
                    total_functions += 1
                    # Indent function signatures
                    summary.append(f"   `{func['signature']}`\n\n")
            else:
                summary.append("   *(No public functions)*\n\n")

        summary.append("\n")

    # Statistics footer
    summary.append("---\n\n")
    summary.append("## Repository Statistics\n\n")
    summary.append(f"- **Total Modules:** {total_modules}\n")
    summary.append(f"- **Total Functions:** {total_functions}\n")

    # Write to docs/code_summary.md
    output_path = Path('docs/code_summary.md')
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(summary)

    print(f"✅ Code summary generated: {output_path}")
    print(f"📊 Statistics: {total_modules} modules, {total_functions} functions")

    return output_path, total_modules, total_functions


def generate_pdf(markdown_file: Path):
    """Generate a beautifully formatted PDF version of the code summary."""

    try:
        import markdown
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
    except ImportError:
        print("\n⚠️  PDF generation requires additional packages.")
        print("Install with: pip install markdown weasyprint")
        print("\nSkipping PDF generation...")
        return None

    print("\n📄 Generating PDF version...")

    # Read the markdown file
    with open(markdown_file, 'r', encoding='utf-8') as f:
        md_content = f.read()

    # Remove MkDocs-specific admonitions for cleaner PDF
    md_content = md_content.replace('!!! info "Auto-Generated Documentation"\n', '')
    md_content = md_content.replace('    Last updated:', '\n**Last updated:**')
    md_content = md_content.replace('    ', '')

    # Convert markdown to HTML
    md = markdown.Markdown(extensions=['extra', 'codehilite', 'toc', 'tables'])
    html_content = md.convert(md_content)

    # Get current date for cover page
    current_date = datetime.now().strftime('%B %d, %Y')

    # Create a beautifully styled HTML document
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>MFX Code Repository - User Cheat Sheet</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

            @page {{
                size: A4;
                margin: 2.5cm 2cm;

                @top-left {{
                    content: "MFX Code Repository";
                    font-size: 9pt;
                    color: #666;
                    font-family: 'Inter', sans-serif;
                }}

                @top-right {{
                    content: "{current_date}";
                    font-size: 9pt;
                    color: #666;
                    font-family: 'Inter', sans-serif;
                }}

                @bottom-center {{
                    content: "Page " counter(page) " of " counter(pages);
                    font-size: 9pt;
                    color: #666;
                    font-family: 'Inter', sans-serif;
                }}
            }}

            @page :first {{
                @top-left {{ content: none; }}
                @top-right {{ content: none; }}
                @bottom-center {{ content: none; }}
            }}

            /* Cover page styling */
            .cover {{
                page-break-after: always;
                height: 100vh;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                text-align: center;
                background: linear-gradient(135deg, #ff6f00 0%, #d84315 100%);
                color: white;
                margin: -2.5cm -2cm;
                padding: 2.5cm 2cm;
            }}

            .cover h1 {{
                font-size: 42pt;
                font-weight: 700;
                margin-bottom: 20px;
                border: none;
                color: white;
            }}

            .cover .subtitle {{
                font-size: 18pt;
                font-weight: 300;
                margin-bottom: 40px;
                opacity: 0.9;
            }}

            .cover .info {{
                font-size: 12pt;
                margin-top: 60px;
                opacity: 0.8;
            }}

            /* Body styling */
            body {{
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                font-size: 10pt;
                line-height: 1.6;
                color: #2c3e50;
                font-weight: 400;
            }}

            /* Headers */
            h1 {{
                color: #d84315;
                border-bottom: 4px solid #ff6f00;
                padding-bottom: 12px;
                margin-top: 40px;
                margin-bottom: 20px;
                font-size: 24pt;
                font-weight: 700;
                page-break-before: always;
                page-break-after: avoid;
            }}

            h1:first-of-type {{
                page-break-before: avoid;
                margin-top: 0;
            }}

            h2 {{
                color: #ff6f00;
                border-bottom: 2px solid #ffb74d;
                padding-bottom: 8px;
                margin-top: 30px;
                margin-bottom: 15px;
                font-size: 16pt;
                font-weight: 600;
                page-break-after: avoid;
            }}

            h3 {{
                color: #e65100;
                margin-top: 20px;
                margin-bottom: 10px;
                font-size: 12pt;
                font-weight: 600;
                page-break-after: avoid;
            }}

            h4 {{
                color: #f57c00;
                margin-top: 15px;
                margin-bottom: 8px;
                font-size: 11pt;
                font-weight: 600;
            }}

            /* Code styling */
            code {{
                background-color: #f8f9fa;
                padding: 2px 6px;
                border-radius: 3px;
                font-family: 'JetBrains Mono', 'Courier New', monospace;
                font-size: 9pt;
                color: #e91e63;
                border: 1px solid #e9ecef;
            }}

            pre {{
                background-color: #f8f9fa;
                padding: 12px;
                border-left: 4px solid #ff6f00;
                border-radius: 4px;
                overflow-x: auto;
                page-break-inside: avoid;
                margin: 10px 0;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }}

            pre code {{
                background-color: transparent;
                padding: 0;
                color: #2c3e50;
                border: none;
                font-size: 8.5pt;
                line-height: 1.5;
            }}

            /* Text emphasis */
            strong {{
                color: #d84315;
                font-weight: 600;
            }}

            em {{
                color: #546e7a;
                font-style: italic;
            }}

            /* Horizontal rules */
            hr {{
                border: none;
                border-top: 2px solid #eceff1;
                margin: 25px 0;
            }}

            /* Lists */
            ul, ol {{
                margin-left: 20px;
                margin-bottom: 15px;
            }}

            li {{
                margin-bottom: 6px;
                line-height: 1.5;
            }}

            ul li {{
                list-style-type: square;
            }}

            /* Links */
            a {{
                color: #1976d2;
                text-decoration: none;
            }}

            a:hover {{
                text-decoration: underline;
            }}

            /* Table of Contents */
            .toc {{
                background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%);
                padding: 20px;
                border-radius: 8px;
                margin-bottom: 30px;
                border: 2px solid #ffb74d;
                page-break-inside: avoid;
            }}

            .toc h2 {{
                color: #e65100;
                border: none;
                margin-top: 0;
            }}

            /* Statistics box */
            .statistics {{
                background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
                padding: 20px;
                border-radius: 8px;
                margin-top: 30px;
                border: 2px solid #64b5f6;
                page-break-inside: avoid;
            }}

            .statistics h2 {{
                color: #1565c0;
                border: none;
                margin-top: 0;
            }}

            /* Tables */
            table {{
                border-collapse: collapse;
                width: 100%;
                margin: 15px 0;
                font-size: 9pt;
                page-break-inside: avoid;
            }}

            th {{
                background-color: #ff6f00;
                color: white;
                padding: 10px;
                text-align: left;
                font-weight: 600;
            }}

            td {{
                padding: 8px;
                border-bottom: 1px solid #eceff1;
            }}

            tr:nth-child(even) {{
                background-color: #f8f9fa;
            }}

            /* Module sections */
            .module {{
                margin-bottom: 20px;
                padding: 15px;
                background-color: #fafafa;
                border-left: 4px solid #ff6f00;
                border-radius: 4px;
                page-break-inside: avoid;
            }}

            /* Blockquotes */
            blockquote {{
                border-left: 4px solid #ff6f00;
                padding-left: 15px;
                margin-left: 0;
                color: #546e7a;
                font-style: italic;
            }}

            /* Page breaks */
            .page-break {{
                page-break-after: always;
            }}

            /* Avoid breaks */
            h1, h2, h3, h4, h5, h6 {{
                page-break-after: avoid;
            }}

            /* Footer note */
            .footer-note {{
                margin-top: 40px;
                padding-top: 20px;
                border-top: 2px solid #eceff1;
                font-size: 9pt;
                color: #78909c;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <!-- Cover Page -->
        <div class="cover">
            <h1>MFX Code Repository</h1>
            <div class="subtitle">User Cheat Sheet & Function Reference</div>
            <div class="info">
                <p>LCLS MFX Beamline</p>
                <p>Generated: {current_date}</p>
            </div>
        </div>

        <!-- Content -->
        {html_content}

        <!-- Footer -->
        <div class="footer-note">
            <p>This document is automatically generated from the MFX repository.</p>
            <p>For the most up-to-date information, visit the online documentation.</p>
        </div>
    </body>
    </html>
    """

    # Generate PDF with the desired filename
    pdf_path = markdown_file.parent / 'user_cheat_sheet.pdf'

    font_config = FontConfiguration()
    html = HTML(string=html_template)

    css = CSS(string='''
        @page {
            size: A4;
            margin: 2.5cm 2cm;
        }
    ''', font_config=font_config)

    html.write_pdf(pdf_path, stylesheets=[css], font_config=font_config)

    print(f"✅ PDF generated: {pdf_path}")
    file_size = pdf_path.stat().st_size / 1024  # Size in KB
    print(f"   File size: {file_size:.1f} KB")
    return pdf_path


if __name__ == "__main__":
    # Generate markdown summary
    md_path, modules, functions = generate_summary()

    # Generate PDF version
    pdf_path = generate_pdf(md_path)

    if pdf_path:
        print(f"\n✨ Summary complete!")
        print(f"   - Markdown: {md_path}")
        print(f"   - PDF: {pdf_path}")
        print(f"   - Modules: {modules}")
        print(f"   - Functions: {functions}")
    else:
        print(f"\n✨ Markdown summary complete: {md_path}")