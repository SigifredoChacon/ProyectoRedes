
from __future__ import print_function
import csv
import sys
import argparse
import io
from twisted.internet import reactor, protocol, defer
from twisted.application import service, internet
from twisted.mail import smtp
from email.message import EmailMessage
import email.utils

class MySMTPClient(smtp.ESMTPClient):

    def __init__(self, mailFrom, mailTo, mailData, *args, **kwargs):

        self.mailFrom = mailFrom
        self.mailTo = mailTo
        self.mailData = mailData
        super(MySMTPClient, self).__init__(*args, **kwargs)

    def getMailFrom(self):
        result = self.mailFrom
        self.mailFrom = None
        return result

    def getMailTo(self):
        return [self.mailTo]

    def getMailData(self):
        return io.BytesIO(self.mailData.encode("utf-8"))

    def sentMail(self, code, resp, numOk, addresses, log):
        print("[INFO] Enviado a {} direcciones: {}".format(numOk, addresses))
        self.transport.loseConnection()



class SMTPClientFactory(protocol.ClientFactory):
    def __init__(self, mailFrom, mailTo, mailData):

        self.mailFrom = mailFrom
        self.mailTo = mailTo
        self.mailData = mailData

    def buildProtocol(self, addr):
        return MySMTPClient(
            self.mailFrom,
            self.mailTo,
            self.mailData,
            secret=None,
            identity="localhost"
        )

    def clientConnectionFailed(self, connector, reason):

        print("[ERROR] Conexión fallida:", reason.getErrorMessage())
        global pendingMessages
        pendingMessages.errback(reason)



def sendEmail(host, port, mailFrom, mailTo, mailData):

    d = defer.Deferred()
    factory = SMTPClientFactory(mailFrom, mailTo, mailData)
    connector = reactor.connectTCP(host, port, factory)


    def onConnectionLost(_):
        d.callback("[OK] Correo enviado a {}.".format(mailTo))


    connector.transport = None

    def checkTransport(proto):
        connector.transport = proto.transport

    factory.protocol = lambda: MySMTPClient(
        mailFrom, mailTo, mailData,
        secret=None, identity="localhost"
    )
    oldBuildProtocol = factory.buildProtocol

    def newBuildProtocol(addr):
        proto = oldBuildProtocol(addr)
        proto.connectionLost = onConnectionLost
        checkTransport(proto)
        return proto

    factory.buildProtocol = newBuildProtocol

    return d


def parse_args():
    parser = argparse.ArgumentParser(description="Cliente SMTP con Twisted",  add_help=False)
    parser.add_argument("-h", "--host", required=True,
                        help="Servidor SMTP (IP o hostname)")
    parser.add_argument("-c", "--csv", required=True,
                        help="Archivo CSV con destinatarios")
    parser.add_argument("-m", "--message", required=True,
                        help="Archivo con el cuerpo base del mensaje")
    return parser.parse_args()

def build_eml(mailFrom, mailTo, subject, body, name):
    msg = EmailMessage()

    msg['Subject'] = subject
    msg['From'] = mailFrom
    msg['To'] = mailTo
    msg['Date'] = email.utils.formatdate(localtime=True)
    msg['MIME-Version'] = '1.0'

    msg.set_content(body.format(name=name))
    return msg

def main():
    mailFrom = input("Ingrese el email del remitente: ").strip()

    args = parse_args()

    try:
        with open(args.csv, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        print("[ERROR] No se pudo leer el CSV:", e)
        sys.exit(1)

    if not rows:
        print("[ERROR] El CSV está vacío")
        sys.exit(1)

    try:
        with open(args.message, "r", encoding="utf-8") as f:
            baseBody = f.read()
    except Exception as e:
        print("[ERROR] No se pudo leer el archivo de mensaje:", e)
        sys.exit(1)

    if args.host.lower() in ["localhost", "127.0.0.1"]:
        smtp_port = 2500
    else:
        smtp_port = 25

    global pendingMessages
    pendingMessages = defer.DeferredList([])

    for row in rows:

        mailTo = row["mail_to"]
        name = row.get("name", "")
        subject = row.get("subject", "Sin asunto")

        msg = build_eml(mailFrom, mailTo, subject, baseBody, name)
        eml_bytes = msg.as_bytes()


        d = sendEmail(args.host, smtp_port, mailFrom, mailTo, eml_bytes.decode('utf-8'))

        pendingMessages.addCallbacks(lambda x: x, lambda x: x)


    def onAllDone(_):
        print("[INFO] Todos los envíos completados. Saliendo.")
        reactor.stop()

    pendingMessages.addCallback(onAllDone)


if __name__ == "__main__":
    # Iniciamos la aplicación
    main()
    reactor.run()
