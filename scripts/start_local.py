"""Start the 3D studio, map editor and real two-process missions."""
import argparse
import os
from pathlib import Path
import signal
import sys
import threading
import webbrowser
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hackroi.studio import make_studio_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT','8080')))
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--field', action='store_true', help='Open the original field missions with --open')
    parser.add_argument('--strictPort', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    server = make_studio_server(args.host,args.port,args.output)
    url = f'http://127.0.0.1:{server.server_address[1]}'
    print('Ариадна: '+url,flush=True)
    print('Остановить: Ctrl+C',flush=True)
    stop = threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    if args.open:webbrowser.open(url if args.field else url+'/home.html')
    try:stop.wait()
    finally:
        server.shutdown();server.server_close();server.studio.close();thread.join(timeout=3)


if __name__=='__main__':main()
