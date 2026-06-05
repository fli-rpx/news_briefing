#!/usr/bin/env python3
"""Custom HTTP server for Morning Briefing.

Serves the project directory as root, and mounts /Users/fudongli/.hermes/
under the URL path /reports/ so browsers can access PDF files.

Usage:
    python3 serve.py [port]

Default port is 8080.
"""

import http.server
import os
import socketserver
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_ROOT = "/Users/fudongli/.hermes"
REPORTS_PREFIX = "/reports/"


class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Handle /reports/ prefix to serve PDFs from hermes directory
        if path.startswith(REPORTS_PREFIX):
            subpath = path[len(REPORTS_PREFIX):]
            # Prevent directory traversal
            subpath = os.path.normpath("/" + subpath).lstrip("/")
            return os.path.join(REPORTS_ROOT, subpath)
        # Default: serve from project directory
        return super().translate_path(path)

    def end_headers(self):
        # Enable cross-origin isolation for PDF viewing if needed
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    with socketserver.TCPServer(("", PORT), RequestHandler) as httpd:
        print(f"Serving Morning Briefing at http://localhost:{PORT}")
        print(f"Project root:  {PROJECT_ROOT}")
        print(f"Reports mount: {REPORTS_ROOT} -> {REPORTS_PREFIX}")
        print("Press Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")
