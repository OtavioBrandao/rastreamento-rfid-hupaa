"""Handshake TLS real em loopback, com certificado efêmero; não prova HiveMQ."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
from tempfile import TemporaryDirectory
import unittest

from rfid_ingestion.config import Settings
from rfid_ingestion.connection import tls_context


@unittest.skipUnless(shutil.which("openssl"), "exige OpenSSL para certificado efêmero")
class TlsTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.cert = str(Path(cls.directory.name) / "cert.pem")
        cls.key = str(Path(cls.directory.name) / "private.key")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", cls.key, "-out", cls.cert, "-days", "1",
                        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def handshake(self, context, hostname):
        server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server.load_cert_chain(self.cert, self.key)
        with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as pool:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(5)

            def accept():
                connection, _ = listener.accept()
                with connection:
                    try:
                        with server.wrap_socket(connection, server_side=True) as secured:
                            secured.sendall(b"ok")
                    except ssl.SSLError:
                        pass  # O cliente encerra quando rejeita certificado/hostname.

            task = pool.submit(accept)
            try:
                with socket.create_connection(listener.getsockname(), timeout=5) as raw:
                    with context.wrap_socket(raw, server_hostname=hostname) as secured:
                        self.assertEqual(secured.recv(2), b"ok")
            finally:
                task.result(timeout=6)

    def test_trusted_certificate_succeeds(self):
        self.handshake(tls_context(Settings(mqtt_ca_cert=self.cert)), "localhost")

    def test_untrusted_certificate_is_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(tls_context(Settings()), "localhost")

    def test_wrong_hostname_is_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(tls_context(Settings(mqtt_ca_cert=self.cert)), "wrong.example")
