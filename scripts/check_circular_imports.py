#!/usr/bin/env python3
"""
Check for circular imports in the codebase.

Usage:
    python scripts/check_circular_imports.py
    python scripts/check_circular_imports.py --verbose
"""
import ast
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class ImportGraph:
    """Build and analyze import graph to detect cycles."""
    
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.graph: Dict[str, Set[str]] = defaultdict(set)
        self.module_paths: Dict[str, Path] = {}
    
    def _path_to_module(self, file_path: Path) -> str:
        """Convert file path to module name."""
        relative = file_path.relative_to(self.root_dir)
        parts = relative.parts[:-1] + (relative.stem,)
        return '.'.join(parts)
    
    def _resolve_import(self, module_name: str, current_file: Path) -> Optional[str]:
        """Resolve import to actual module name."""
        # Handle relative imports
        if module_name.startswith('.'):
            current_module = self._path_to_module(current_file)
            parts = current_module.split('.')
            dots = len(module_name) - len(module_name.lstrip('.'))
            if dots > len(parts):
                return None
            base_parts = parts[:-dots] if dots > 0 else parts
            module_name = '.'.join(base_parts + [module_name.lstrip('.')])
        
        # Try to find the module file
        parts = module_name.split('.')
        for i in range(len(parts), 0, -1):
            potential_path = self.root_dir / Path(*parts[:i]) / '__init__.py'
            if potential_path.exists():
                return '.'.join(parts[:i])
            potential_path = self.root_dir / Path(*parts[:i]) / f'{parts[i-1]}.py'
            if potential_path.exists():
                return '.'.join(parts[:i])
        
        return None
    
    def _extract_imports(self, file_path: Path) -> Set[str]:
        """Extract all imports from a Python file."""
        imports = set()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=str(file_path))
        except Exception as e:
            print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
            return imports
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolved = self._resolve_import(alias.name, file_path)
                    if resolved:
                        imports.add(resolved)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    resolved = self._resolve_import(node.module, file_path)
                    if resolved:
                        imports.add(resolved)
        
        return imports
    
    def build_graph(self):
        """Build import graph from all Python files."""
        src_dir = self.root_dir / 'src'
        
        for py_file in src_dir.rglob('*.py'):
            if py_file.name == '__pycache__':
                continue
            
            module_name = self._path_to_module(py_file)
            self.module_paths[module_name] = py_file
            
            imports = self._extract_imports(py_file)
            for imported_module in imports:
                # Only track imports within src/
                if imported_module.startswith('src.'):
                    self.graph[module_name].add(imported_module)
    
    def find_cycles(self) -> List[List[str]]:
        """Find all cycles in the import graph."""
        cycles = []
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        path: List[str] = []
        
        def dfs(node: str):
            if node in rec_stack:
                # Found a cycle
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycles.append(cycle)
                return
            
            if node in visited:
                return
            
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in self.graph.get(node, set()):
                dfs(neighbor)
            
            rec_stack.remove(node)
            path.pop()
        
        for node in self.graph:
            if node not in visited:
                dfs(node)
        
        return cycles
    
    def print_cycles(self, verbose: bool = False):
        """Print detected cycles."""
        cycles = self.find_cycles()
        
        if not cycles:
            print("✓ No circular imports detected!")
            return
        
        print(f"✗ Found {len(cycles)} circular import(s):\n")
        
        for i, cycle in enumerate(cycles, 1):
            print(f"Cycle {i}:")
            for j, module in enumerate(cycle[:-1]):
                print(f"  {module} -> {cycle[j+1]}")
            print()


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Check for circular imports')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()
    
    root_dir = Path(__file__).parent.parent
    graph = ImportGraph(root_dir)
    
    print("Building import graph...")
    graph.build_graph()
    
    print("Checking for circular imports...")
    graph.print_cycles(verbose=args.verbose)
    
    cycles = graph.find_cycles()
    sys.exit(1 if cycles else 0)


if __name__ == '__main__':
    main()

