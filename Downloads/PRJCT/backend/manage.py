#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

def main():
   """Run administrative tasks."""
   # Add the backend directory to Python path
   backend_dir = os.path.dirname(os.path.abspath(__file__))
   sys.path.insert(0, backend_dir)
   
   # Add the parent directory (containing backend/) to Python path
   parent_dir = str(Path(backend_dir).parent)
   if parent_dir not in sys.path:
       sys.path.insert(0, parent_dir)

   os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_project.settings')
   
   try:
       from django.core.management import execute_from_command_line
   except ImportError as exc:
       raise ImportError(
           "Couldn't import Django. Are you sure it's installed and "
           "available on your PYTHONPATH environment variable? Did you "
           "forget to activate a virtual environment?"
       ) from exc
   
   # Check for installed apps
   try:
       import channels
       import rest_framework
       import strategies
   except ImportError as exc:
       raise ImportError(
           f"Couldn't import required packages: {exc}. "
           "Please check your virtual environment and installed packages."
       ) from exc
       
   try:
       execute_from_command_line(sys.argv)
   except Exception as exc:
       print(f"Error executing command: {exc}")
       print(f"Current PYTHONPATH: {sys.path}")
       raise

if __name__ == '__main__':
   main()