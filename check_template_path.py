#!/usr/bin/env python3
import os

# Current calculation (from email_notification.py)
file_location = "/mnt/g/My Drive/Atomik App/PRJCT/fastapi_backend/app/services/email/email_notification.py"
current_calc = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(file_location))), "templates")
print(f"Current calculation gives: {current_calc}")

# What we need
correct_path = "/mnt/g/My Drive/Atomik App/PRJCT/fastapi_backend/app/templates"
print(f"We need: {correct_path}")

# How many dirname() calls we need
print("\nPath breakdown:")
print(f"__file__: app/services/email/email_notification.py")
print(f"dirname(__file__): app/services/email/")
print(f"dirname(dirname(__file__)): app/services/")
print(f"dirname(dirname(dirname(__file__))): app/")
print(f"join(..., 'templates'): app/templates/")

print("\nSo the current calculation should work...")

# Let's check the actual calculation in the current working directory
current_file = os.path.abspath("app/services/email/email_notification.py")
calculated = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(current_file))), "templates")
print(f"\nActual calculation: {calculated}")

# Check if it exists
print(f"Path exists: {os.path.exists(calculated)}")
if os.path.exists(calculated):
    print(f"Contents: {os.listdir(calculated)}")