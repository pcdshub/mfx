#!/usr/bin/env python3
"""
Script to generate MFX documentation.

This script:
1. Cleans outdated .md files from docs/ folder (except index.md)
2. Finds all .py files in the repo (respecting .gitignore)
3. Generates .md files only if they don't exist or content changed
4. Generates mkdocs.yml with all files organized by module structure
"""

import yaml
from pathlib import Path
from typing import List, Dict, Set, Optional
import shutil
import fnmatch
import argparse


def parse_gitignore(repo_path: Path) -> Set[str]:
    """
    Parse .gitignore file and return set of patterns to ignore.

    Parameters
    ----------
    repo_path : Path
        Path to repository root

    Returns
    -------
    Set[str]
        Set of gitignore patterns
    """
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


def is_ignored(
    path: Path,
    repo_path: Path,
    gitignore_patterns: Set[str],
    exclude_dirs: Optional[Set[str]] = None
) -> bool:
    """
    Check if path should be ignored based on gitignore and exclusions.

    Parameters
    ----------
    path : Path
        Path to check
    repo_path : Path
        Repository root path
    gitignore_patterns : Set[str]
        Set of gitignore patterns
    exclude_dirs : Optional[Set[str]], optional
        Additional directories to exclude, by default None

    Returns
    -------
    bool
        True if path should be ignored, False otherwise
    """
    try:
        relative = path.relative_to(repo_path)
    except ValueError:
        return False

    path_str = str(relative).replace('\\', '/')
    parts = relative.parts

    # Check exclude_dirs first
    if exclude_dirs:
        for part in parts:
            if part in exclude_dirs:
                return True

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


def clean_docs_folder(
    docs_path: Path,
    valid_md_files: Set[Path],
    preserve_files: Optional[Set[str]] = None,
    backup: bool = False
) -> None:
    """
    Remove only orphaned .md files from docs folder.

    Parameters
    ----------
    docs_path : Path
        Path to docs folder
    valid_md_files : Set[Path]
        Set of valid markdown file paths
    preserve_files : Optional[Set[str]], optional
        Files to preserve from deletion, by default None
    backup : bool, optional
        Whether to create backup before cleaning, by default False
    """
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
        # Skip if it's a preserved file
        if md_file.name in preserve_files:
            continue

        # Remove if it's not in the valid files set
        if md_file not in valid_md_files:
            md_file.unlink()
            removed_count += 1
            print(f"  🗑️  Removed orphaned: "
                  f"{md_file.relative_to(docs_path)}")

    # Remove empty directories (except preserved ones)
    for item in list(docs_path.rglob('*')):
        if item.is_dir() and item.name not in preserve_dirs:
            try:
                if not any(item.iterdir()):
                    item.rmdir()
            except OSError:
                pass

    if removed_count > 0:
        print(f"🗑️  Removed {removed_count} orphaned .md files from docs/")


def create_md_file(md_path: Path, module_path: str) -> bool:
    """
    Create markdown file with mkdocstrings notation only if needed.

    Parameters
    ----------
    md_path : Path
        Path where markdown file should be created
    module_path : str
        Python module path (e.g., 'package.module.file')

    Returns
    -------
    bool
        True if file was created/updated, False if unchanged
    """
    title = module_path.split('.')[-1].replace('_', ' ').title()
    content = f"""# {title}

::: {module_path}
"""

    # Check if file exists and has same content
    if md_path.exists():
        existing_content = md_path.read_text()
        if existing_content == content:
            return False  # No change needed

    # Create or update file
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(content)
    return True


def organize_by_module_structure(
    python_files: List[Path],
    repo_path: Path
) -> Dict:
    """
    Organize Python files by their module structure.

    Parameters
    ----------
    python_files : List[Path]
        List of Python file paths
    repo_path : Path
        Repository root path

    Returns
    -------
    Dict
        Nested dictionary representing module structure
    """
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


def build_nav_from_structure(
    structure: Dict,
    max_depth: int = 10,
    current_depth: int = 0
) -> List:
    """
    Build mkdocs nav structure from module structure.

    Parameters
    ----------
    structure : Dict
        Nested dictionary representing module structure
    max_depth : int, optional
        Maximum depth to traverse, by default 10
    current_depth : int, optional
        Current traversal depth, by default 0

    Returns
    -------
    List
        Navigation structure for mkdocs
    """
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

    for dir_name, dir_structure in sorted(dirs.items()):
        subnav = build_nav_from_structure(
            dir_structure,
            max_depth,
            current_depth + 1
        )
        if subnav:
            nav.append({dir_name.replace('_', ' ').title(): subnav})

    return nav


def get_module_path(py_file: Path, repo_path: Path) -> str:
    """
    Convert file path to Python module path.

    Parameters
    ----------
    py_file : Path
        Python file path
    repo_path : Path
        Repository root path

    Returns
    -------
    str
        Python module path (e.g., 'package.module.file')
    """
    relative = py_file.relative_to(repo_path)
    parts = list(relative.parts)
    parts[-1] = parts[-1].replace('.py', '')
    return '.'.join(parts)


def create_mkdocs_config(nav_structure: List, repo_path: Path) -> Dict:
    """
    Create mkdocs configuration dictionary.

    Parameters
    ----------
    nav_structure : List
        Navigation structure
    repo_path : Path
        Repository root path

    Returns
    -------
    Dict
        MkDocs configuration dictionary
    """
    config = {
        'site_name': repo_path.name,
        'theme': {
            'name': 'material',
            'features': [
                'navigation.tabs',
                'navigation.sections',
                'navigation.expand',
                'search.suggest',
                'search.highlight',
            ]
        },
        'plugins': [
            'search',
            {
                'mkdocstrings': {
                    'handlers': {
                        'python': {
                            'options': {
                                'show_source': True,
                                'show_root_heading': True,
                            }
                        }
                    }
                }
            }
        ],
        'nav': [
            {'Home': 'index.md'},
            *nav_structure
        ]
    }
    return config


def find_python_files(
    repo_path: Path,
    gitignore_patterns: Set[str],
    exclude_dirs: Optional[Set[str]] = None
) -> List[Path]:
    """
    Find all Python files in repository, respecting .gitignore and exclusions.

    Parameters
    ----------
    repo_path : Path
        Repository root path
    gitignore_patterns : Set[str]
        Set of gitignore patterns
    exclude_dirs : Optional[Set[str]], optional
        Additional directories to exclude, by default None

    Returns
    -------
    List[Path]
        Sorted list of Python file paths
    """
    python_files = []
    for py_file in repo_path.rglob('*.py'):
        # Skip __init__.py files
        if py_file.name == '__init__.py':
            continue

        if not is_ignored(py_file, repo_path, gitignore_patterns,
                          exclude_dirs):
            python_files.append(py_file)
    return sorted(python_files)


def generate_docs(
    repo_path: str = '.',
    docs_path: str = 'docs',
    backup: bool = False,
    show_ignored: bool = False,
    exclude_dirs: Optional[Set[str]] = None
) -> None:
    """
    Main documentation generation function.

    Parameters
    ----------
    repo_path : str, optional
        Repository root path, by default '.'
    docs_path : str, optional
        Documentation folder path, by default 'docs'
    backup : bool, optional
        Whether to create backups, by default False
    show_ignored : bool, optional
        Whether to show gitignore patterns, by default False
    exclude_dirs : Optional[Set[str]], optional
        Additional directories to exclude, by default None
    """
    repo = Path(repo_path).resolve()
    docs = (Path(docs_path) if Path(docs_path).is_absolute()
            else repo / docs_path)

    # Always exclude these directories
    base_exclude_dirs = {
        '.git', '__pycache__', 'docs', 'dev', 'experiments', 'jungfrau'
    }

    # Merge with additional exclusions if provided
    if exclude_dirs:
        exclude_dirs = base_exclude_dirs | exclude_dirs
    else:
        exclude_dirs = base_exclude_dirs

    print("=" * 70)
    print("📚 MFX Documentation Generator")
    print("=" * 70)

    print("\n🔍 Parsing .gitignore...")
    gitignore_patterns = parse_gitignore(repo)
    print(f"  Found {len(gitignore_patterns)} ignore patterns")

    if show_ignored:
        print("\n📋 Gitignore patterns:")
        for pattern in sorted(gitignore_patterns):
            print(f"  - {pattern}")

    print(f"\n🚫 Excluded directories:")
    for excl in sorted(exclude_dirs):
        print(f"  - {excl}")

    print("\n🐍 Finding Python files...")
    python_files = find_python_files(repo, gitignore_patterns, exclude_dirs)

    if not python_files:
        print("⚠️  No Python files found!")
        return

    print(f"  Found {len(python_files)} Python files")

    # Calculate which .md files should exist
    valid_md_files = set()
    for py_file in python_files:
        relative = py_file.relative_to(repo)
        md_path = docs / relative.with_suffix('.md')
        valid_md_files.add(md_path)

    print(f"\n🧹 Cleaning orphaned files...")
    clean_docs_folder(docs, valid_md_files, backup=backup)

    print(f"\n📝 Creating/updating markdown files...")
    created_count = 0
    updated_count = 0
    skipped_count = 0

    for py_file in python_files:
        module_path = get_module_path(py_file, repo)
        relative = py_file.relative_to(repo)
        md_path = docs / relative.with_suffix('.md')

        existed_before = md_path.exists()
        was_modified = create_md_file(md_path, module_path)

        if was_modified:
            if not existed_before:
                created_count += 1
                action = "✓ Created"
            else:
                updated_count += 1
                action = "↻ Updated"

            if created_count + updated_count <= 5:
                print(f"  {action}: {relative.with_suffix('.md')}")
        else:
            skipped_count += 1

    if created_count + updated_count > 5:
        print(f"  ... and {created_count + updated_count - 5} more files")

    print(f"\n📊 Summary:")
    print(f"  ✓ Created: {created_count}")
    print(f"  ↻ Updated: {updated_count}")
    print(f"  ⊘ Skipped (unchanged): {skipped_count}")

    print(f"\n🗂️  Organizing module structure...")
    structure = organize_by_module_structure(python_files, repo)
    nav_structure = build_nav_from_structure(structure)

    print(f"\n📋 Generating mkdocs.yml...")
    config = create_mkdocs_config(nav_structure, repo)
    mkdocs_path = repo / 'mkdocs.yml'

    # Only backup and update if config changed
    new_config_yaml = yaml.dump(
        config,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=1000
    )

    should_update = True
    if mkdocs_path.exists():
        existing_config = mkdocs_path.read_text()
        if existing_config == new_config_yaml:
            should_update = False
            print(f"  ⊘ mkdocs.yml unchanged")

    if should_update:
        if mkdocs_path.exists() and backup:
            shutil.copy2(mkdocs_path, mkdocs_path.with_suffix('.yml.bak'))
            print(f"  📦 Backed up existing mkdocs.yml")

        with open(mkdocs_path, 'w') as f:
            f.write(new_config_yaml)
        print(f"  ✓ Updated mkdocs.yml")

    print("\n" + "=" * 70)
    print("✅ Documentation generated successfully!")
    print("=" * 70)
    print(f"\nNext steps:")
    print(f"  1. Create/update docs/index.md")
    print(f"  2. Run: mkdocs serve")
    print(f"  3. Visit: http://127.0.0.1:8000")
    print("=" * 70 + "\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Generate MFX documentation'
    )
    parser.add_argument(
        '--repo-path',
        default='.',
        help='Repository root path'
    )
    parser.add_argument(
        '--docs-path',
        default='docs',
        help='Docs folder path'
    )
    parser.add_argument(
        '--backup',
        action='store_true',
        help='Create backups'
    )
    parser.add_argument(
        '--show-ignored',
        action='store_true',
        help='Show gitignore patterns being used'
    )
    parser.add_argument(
        '--exclude',
        nargs='*',
        help='Additional directories to exclude'
    )
    args = parser.parse_args()

    exclude_dirs = set(args.exclude) if args.exclude else None

    generate_docs(
        repo_path=args.repo_path,
        docs_path=args.docs_path,
        backup=args.backup,
        show_ignored=args.show_ignored,
        exclude_dirs=exclude_dirs
    )