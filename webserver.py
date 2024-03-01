'''the Webserver that actually serves the Kaffee information.'''

from phew import server
from phew.template import render_template
from phew.server import redirect

import time
# from typing import Optional, List, Tuple

DOMAIN: str = "kaffee-counter.local"

html: str
with open('resources/index.html', "r", encoding="utf-8") as f:
    html = f.read()

if len(html) < 100:
    raise FileNotFoundError("HTML could not be found.")

@server.catchall()
def catchall(request):
    '''The catchall implementations'''
    return "Der Kaffee ist ausgelaufen. Nichts gefunden!", 404

def init_webserver():
    '''Initialisiere den Webserver.'''
    print("Starte Server...")
    server.run()
    print()
    print("Server gestartet.")
