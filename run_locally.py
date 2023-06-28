import os

from dotenv import load_dotenv
from pyngrok import ngrok

if __name__ == '__main__':
    load_dotenv()

    # <NgrokTunnel: "tcp://0.tcp.ngrok.io:12345" -> "localhost:{PORT}">
    ssh_tunnel = ngrok.connect(int(os.getenv("PORT")), "http")
    tunnels = ngrok.get_tunnels()

    # Print tunnel public url to STDOUT for the main bash script to catch
    print(tunnels[0].public_url, flush=True)

    ngrok_process = ngrok.get_ngrok_process()
    try:
        # Block until CTRL-C or some other terminating event
        ngrok_process.proc.wait()
    except KeyboardInterrupt:
        print(" Shutting down server.")

        ngrok.kill()
