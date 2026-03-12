"""
Punto di ingresso principale.
  - Sviluppo:    python main.py
  - Produzione:  waitress-serve --host=0.0.0.0 --port=5000 main:app
"""
from app import app

if __name__ == "__main__":
    try:
        from waitress import serve
        print("SigraFilm NOC — avviato su http://localhost:5000")
        serve(app, host="0.0.0.0", port=5000, threads=4)
    except ImportError:
        # Fallback: Flask dev server
        app.run(host="0.0.0.0", port=5000, debug=True)
