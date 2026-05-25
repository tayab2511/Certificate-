import sys
import os

# ─── Add your project folder to the Python path ───
path = '/home/YOUR_USERNAME/Certificate-'
if path not in sys.path:
    sys.path.insert(0, path)

# ─── Set environment variables ───
os.environ['OPENROUTER_API_KEY'] = 'YOUR_OPENROUTER_KEY_HERE'
os.environ['SECRET_KEY'] = 'cust-cert-super-secret-2025'

# ─── Import the Flask app ───
from app import app as application
