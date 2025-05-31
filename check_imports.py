#!/usr/bin/env python3
"""Check for any remaining websocket model references"""

import os
import re

def check_imports(directory):
    """Check all Python files for websocket model imports"""
    issues = []
    
    for root, dirs, files in os.walk(directory):
        # Skip virtual environments and cache directories
        if 'venv' in root or '__pycache__' in root or '.git' in root:
            continue
            
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    # Check for WebSocketConnection imports
                    if 'WebSocketConnection' in content:
                        lines = content.split('\n')
                        for i, line in enumerate(lines, 1):
                            if 'WebSocketConnection' in line:
                                issues.append(f"{filepath}:{i} - {line.strip()}")
                                
                    # Check for websocket model imports
                    if re.search(r'from\s+.*models.*websocket\s+import', content):
                        lines = content.split('\n')
                        for i, line in enumerate(lines, 1):
                            if re.search(r'from\s+.*models.*websocket\s+import', line):
                                issues.append(f"{filepath}:{i} - {line.strip()}")
                                
                except Exception as e:
                    print(f"Error reading {filepath}: {e}")
                    
    return issues

if __name__ == "__main__":
    print("Checking for WebSocketConnection references...")
    issues = check_imports('app')
    
    if issues:
        print("\nFound issues:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("\nNo WebSocketConnection references found. All clean!")