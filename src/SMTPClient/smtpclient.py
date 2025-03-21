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
    # Inicializa el cliente SMTP con remitente, destinatario y datos del mensaje.
    def __init__(self, mailFrom, mailTo, mailData, *args, **kwargs):

        self.mailFrom = mailFrom
        self.mailTo = mailTo
        self.mailData = mailData
        super(MySMTPClient, self).__init__(*args, **kwargs)

    # Devuelve el remitente y lo limpia para evitar duplicados en envíos múltiples.
    def getMailFrom(self):
        result = self.mailFrom
        self.mailFrom = None
        return result

    # Retorna una lista que contiene el destinatario del correo.
    def getMailTo(self):
        return [self.mailTo]

    # Convierte el contenido del mensaje a un stream de bytes para el envío.
    def getMailData(self):
        return io.BytesIO(self.mailData.encode("utf-8"))

    # Notifica el envío correcto del correo e indica al transporte que cierre la conexión.
    def sentMail(self, code, resp, numOk, addresses, log):
        print("[INFO] Enviado a {} direcciones: {}".format(numOk, addresses))
        self.transport.loseConnection()



class SMTPClientFactory(protocol.ClientFactory):
    # Inicializa la fábrica del cliente SMTP con los datos necesarios para crear el protocolo.
    def __init__(self, mailFrom, mailTo, mailData):

        self.mailFrom = mailFrom
        self.mailTo = mailTo
        self.mailData = mailData

    # Construye y retorna una instancia de MySMTPClient para la conexión.
    def buildProtocol(self, addr):
        return MySMTPClient(
            self.mailFrom,
            self.mailTo,
            self.mailData,
            secret=None,
            identity="localhost"
        )

    # Maneja la falla de conexión, imprimiendo el error y propagándolo a pendingMessages.
    def clientConnectionFailed(self, connector, reason):

        print("[ERROR] Conexión fallida:", reason.getErrorMessage())
        global pendingMessages
        pendingMessages.errback(reason)



# Configura y envía el correo estableciendo la conexión y retornando un Deferred.
def sendEmail(host, port, mailFrom, mailTo, mailData):

    d = defer.Deferred()
    factory = SMTPClientFactory(mailFrom, mailTo, mailData)
    connector = reactor.connectTCP(host, port, factory)


    # Callback que se ejecuta cuando se pierde la conexión, notificando el envío exitoso.
    def onConnectionLost(_):
        d.callback("[OK] Correo enviado a {}.".format(mailTo))


    connector.transport = None

    # Asigna el transporte del protocolo a la conexión.
    def checkTransport(proto):
        connector.transport = proto.transport

    factory.protocol = lambda: MySMTPClient(
        mailFrom, mailTo, mailData,
        secret=None, identity="localhost"
    )
    oldBuildProtocol = factory.buildProtocol

    # Reemplaza el mtodo de construcción del protocolo para incluir onConnectionLost y asignar el transporte.
    def newBuildProtocol(addr):
        proto = oldBuildProtocol(addr)
        proto.connectionLost = onConnectionLost
        checkTransport(proto)
        return proto

    factory.buildProtocol = newBuildProtocol

    return d


# Parsea los argumentos de línea de comandos necesarios para configurar el cliente SMTP.
def parse_args():
    parser = argparse.ArgumentParser(description="Cliente SMTP con Twisted",  add_help=False)
    parser.add_argument("-h", "--host", required=True,
                        help="Servidor SMTP (IP o hostname)")
    parser.add_argument("-c", "--csv", required=True,
                        help="Archivo CSV con destinatarios")
    parser.add_argument("-m", "--message", required=True,
                        help="Archivo con el cuerpo base del mensaje")
    return parser.parse_args()

# Construye el mensaje de correo (EML) en formato MIME usando remitente, destinatario, asunto, cuerpo y personalización del nombre.
def build_eml(mailFrom, mailTo, subject, body, name):
    msg = EmailMessage()

    msg['Subject'] = subject
    msg['From'] = mailFrom
    msg['To'] = mailTo
    msg['Date'] = email.utils.formatdate(localtime=True)
    msg['MIME-Version'] = '1.0'

    msg.set_content(body.format(name=name))
    return msg

# Función main que gestiona la lectura de datos, procesamiento del CSV y envío de correos.
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
        smtp_port = 2525

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


    # Callback final que se ejecuta cuando todos los envíos han finalizado.
    def onAllDone(_):
        print("[INFO] Todos los envíos completados. Saliendo.")
        reactor.stop()

    pendingMessages.addCallback(onAllDone)


if __name__ == "__main__":
    # Iniciamos la aplicación y arrancamos el reactor.
    main()
    reactor.run()
