#!/usr/bin/env python3
"""
Script to:
1. Clean all .md files from docs/ folder (except index.md)
2. Find all .py files in the repo (respecting .gitignore)
3. Generate .md files with mkdocstrings notation
4. Generate mkdocs.yml with all files organized by module structure
"""

import yaml
from pathlib import Path
from typing import List, Dict, Set
import shutil
import fnmatch


def parse_gitignore(repo_path: Path) -> Set[str]:
    """Parse .gitignore file and return set of patterns to ignore."""
    gitignore_path = repo_path / '.gitignore'
    patterns = set()

    if not gitignore_path.exists():
        return patterns

    with open(gitignore_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                patterns.add(line)

    return patterns


def is_ignored(path: Path, repo_path: Path, gitignore_patterns: Set[str]) -> bool:
    """Check if a path should be ignored based on gitignore patterns."""
    try:
        relative = path.relative_to(repo_path)
    except ValueError:
        return False

    path_str = str(relative).replace('\\', '/')
    parts = relative.parts

    for pattern in gitignore_patterns:
        pattern = pattern.lstrip('/')

        if fnmatch.fnmatch(path_str, pattern):
            return True

        if fnmatch.fnmatch(path_str, f'**/{pattern}'):
            return True

        for i, part in enumerate(parts):
            if fnmatch.fnmatch(part, pattern):
                return True

            partial_path = '/'.join(parts[:i+1])
            if fnmatch.fnmatch(partial_path, pattern):
                return True

    return False


def clean_docs_folder(docs_path: Path, preserve_files: Set[str] = None, backup: bool = True):
    """Remove all .md files from docs folder."""
    if preserve_files is None:
        preserve_files = {'index.md'}

    preserve_dirs = {'media', 'assets', 'images', 'static'}

    if not docs_path.exists():
        docs_path.mkdir(parents=True, exist_ok=True)
        return

    if backup:
        backup_path = docs_path.parent / f"{docs_path.name}_backup"
        if backup_path.exists():
            shutil.rmtree(backup_path)
        shutil.copytree(docs_path, backup_path)
        print(f"📦 Backed up docs/ to {backup_path.name}/")

    removed_count = 0
    for md_file in docs_path.rglob('*.md'):
        if md_file.name not in preserve_files:
            md_file.unlink()
            removed_count += 1

    for item in docs_path.iterdir():
        if item.is_dir() and item.name not in preserve_dirs:
            shutil.rmtree(item)

    print(f"🗑️  Removed {removed_count} .md files from docs/")


def find_python_files(repo_path: Path, gitignore_patterns: Set[str] = None,
                     exclude_dirs: Set[str] = None) -> List[Path]:
    """Find all Python files in the repository, respecting .gitignore."""
    if gitignore_patterns is None:
        gitignore_patterns = parse_gitignore(repo_path)

    if exclude_dirs is None:
        exclude_dirs = {'.git', '__pycache__', 'docs', 'dev', 'experiments'}
    else:
        exclude_dirs = exclude_dirs | {'.git', '__pycache__', 'docs', 'dev', 'experiments'}

    python_files = []

    for py_file in repo_path.rglob('*.py'):
        if py_file.name == '__init__.py':
            continue

        if any(part in exclude_dirs or part.startswith('.')
               for part in py_file.relative_to(repo_path).parts[:-1]):
            continue

        if is_ignored(py_file, repo_path, gitignore_patterns):
            continue

        python_files.append(py_file)

    return sorted(python_files)


def get_module_path(py_file: Path, repo_path: Path) -> str:
    """Convert Python file path to module path."""
    relative = py_file.relative_to(repo_path)
    module_path = str(relative.with_suffix('')).replace('/', '.').replace('\\', '.')
    return module_path


def create_md_file(md_path: Path, module_path: str):
    """Create a markdown file with mkdocstrings notation."""
    title = module_path.split('.')[-1].replace('_', ' ').title()
    content = f"""# {title}

::: {module_path}
"""
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(content)


def organize_by_module_structure(python_files: List[Path], repo_path: Path) -> Dict:
    """Organize Python files by their module structure."""
    structure = {}
    for py_file in python_files:
        relative = py_file.relative_to(repo_path)
        parts = relative.parts
        current = structure
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        filename = parts[-1].replace('.py', '.md')
        current[filename] = str(relative.with_suffix('.md'))
    return structure


def build_nav_from_structure(structure: Dict, max_depth: int = 10, current_depth: int = 0) -> List:
    """Build mkdocs nav structure from module structure."""
    if current_depth >= max_depth:
        return []

    nav = []
    files = []
    dirs = {}

    for key, value in sorted(structure.items()):
        if isinstance(value, str):
            files.append(value)
        elif isinstance(value, dict):
            dirs[key] = value

    nav.extend(files)

    for dir_name, dir_contents in dirs.items():
        sub_nav = build_nav_from_structure(dir_contents, max_depth, current_depth + 1)
        if sub_nav:
            display_name = dir_name.replace('_', ' ').title()
            nav.append({display_name: sub_nav})

    return nav


def create_mkdocs_config(nav_structure: List, repo_path: Path) -> Dict:
    """Create complete mkdocs.yml configuration."""
    nav = [{'Home': 'index.md'}]
    if nav_structure:
        nav.append({'API Reference': nav_structure})

    return {
        'site_name': 'MFX Docs',
        'repo_url': 'https://github.com/pcdshub/mfx',
        'site_author': 'JTB',
        'copyright': '© 2025 LCLS',
        'nav': nav,
        'watch': [str(repo_path)],
        'plugins': [
            'search',
            {
                'mkdocstrings': {
                    'handlers': {
                        'python': {
                            'paths': [str(repo_path)],
                            'options': {
                                'docstring_style': 'numpy',
                                'show_source': True,
                                'show_root_heading': True,
                                'show_root_full_path': False,
                            }
                        }
                    }
                }
            },
            'offline'
        ],
        'markdown_extensions': [
            {'pymdownx.highlight': {'anchor_linenums': True}},
            'pymdownx.inlinehilite',
            'pymdownx.snippets',
            'admonition',
            {'pymdownx.arithmatex': {'generic': True}},
            'footnotes',
            'pymdownx.details',
            'pymdownx.superfences',
            'pymdownx.mark',
            'attr_list'
        ],
        'theme': {
            'name': 'material',
            'logo': 'media/logo_2.png',
            'favicon': 'media/logo.png',
            'palette': [
                {
                    'scheme': 'default',
                    'primary': 'orange',
                    'accent': 'deep orange',
                    'toggle': {'icon': 'material/weather-night', 'name': 'Switch to dark mode'}
                },
                {
                    'scheme': 'slate',
                    'primary': 'deep orange',
                    'accent': 'orange',
                    'toggle': {'icon': 'material/weather-sunny', 'name': 'Switch to light mode'}
                }
            ]
        }
    }


def generate_docs(repo_path: str = '.', docs_path: str = 'docs',
                 preserve_files: Set[str] = None, backup: bool = True,
                 show_ignored: bool = False, exclude_dirs: Set[str] = None):
    """Main function to generate complete documentation."""
    repo = Path(repo_path).resolve()
    docs = repo / docs_path

    print("=" * 70)
    print("MFX Documentation Generator")
    print("=" * 70)
    print(f"\n📁 Repository: {repo}")
    print(f"📁 Docs folder: {docs}\n")

    print("🔍 Parsing .gitignore...")
    gitignore_patterns = parse_gitignore(repo)
    if gitignore_patterns:
        print(f"✓ Found {len(gitignore_patterns)} gitignore patterns")
        if show_ignored:
            print("  Patterns:")
            for pattern in sorted(gitignore_patterns):
                print(f"    - {pattern}")
    else:
        print("⚠️  No .gitignore found")

    default_exclusions = {'.git', '__pycache__', 'docs', 'dev', 'experiments'}
    all_exclusions = default_exclusions | (exclude_dirs if exclude_dirs else set())
    print(f"🚫 Excluding directories: {', '.join(sorted(all_exclusions))}")

    print()
    clean_docs_folder(docs, preserve_files=preserve_files, backup=backup)

    print(f"\n🔍 Searching for Python files (respecting .gitignore and exclusions)...")
    python_files = find_python_files(repo, gitignore_patterns, exclude_dirs)
    print(f"✓ Found {len(python_files)} Python files\n")

    if not python_files:
        print("⚠️  No Python files found!")
        return

    print(f"📝 Creating markdown files...")
    for i, py_file in enumerate(python_files):
        module_path = get_module_path(py_file, repo)
        relative = py_file.relative_to(repo)
        md_path = docs / relative.with_suffix('.md')
        create_md_file(md_path, module_path)
        if i < 5:
            print(f"  ✓ {relative.with_suffix('.md')} -> ::: {module_path}")

    if len(python_files) > 5:
        print(f"  ... and {len(python_files) - 5} more files")
    print(f"\n✓ Created {len(python_files)} markdown files")

    print(f"\n🗂️  Organizing module structure...")
    structure = organize_by_module_structure(python_files, repo)
    nav_structure = build_nav_from_structure(structure)

    print(f"\n📋 Generating mkdocs.yml...")
    config = create_mkdocs_config(nav_structure, repo)
    mkdocs_path = repo / 'mkdocs.yml'

    if mkdocs_path.exists():
        shutil.copy2(mkdocs_path, mkdocs_path.with_suffix('.yml.bak'))
        print(f"  📦 Backed up existing mkdocs.yml")

    with open(mkdocs_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False,
                 allow_unicode=True, width=1000)

    print(f"  ✓ Created {mkdocs_path}")
    print("\n" + "=" * 70)
    print("✅ Documentation generated successfully!")
    print("=" * 70)
    print(f"\nNext steps:")
    print(f"  1. Create/update docs/index.md")
    print(f"  2. Run: mkdocs serve")
    print(f"  3. Visit: http://127.0.0.1:8000")
    print(f"\nNote: mkdocstrings needs to find your modules.")
    print(f"      The 'paths' setting has been added to mkdocs.yml")
    print(f"      pointing to: {repo}")
    print("=" * 70 + "\n")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Generate MFX documentation')
    parser.add_argument('--repo-path', default='.', help='Repository root path')
    parser.add_argument('--docs-path', default='docs', help='Docs folder path')
    parser.add_argument('--no-backup', action='store_true', help='Skip backups')
    parser.add_argument('--show-ignored', action='store_true',
                       help='Show gitignore patterns being used')
    parser.add_argument('--exclude', nargs='*', help='Additional directories to exclude')
    args = parser.parse_args()

    exclude_dirs = set(args.exclude) if args.exclude else None

    generate_docs(
        repo_path=args.repo_path,
        docs_path=args.docs_path,
        backup=not args.no_backup,
        show_ignored=args.show_ignored,
        exclude_dirs=exclude_dirs
    )