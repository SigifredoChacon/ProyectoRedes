
from zope.interface import implementer

from twisted.internet import defer
from twisted.mail import smtp
from twisted.mail.imap4 import LOGINCredentials, PLAINCredentials


from twisted.cred.portal import IRealm
from twisted.cred.portal import Portal
import argparse
from twisted.python import log
import sys
log.startLogging(sys.stdout)


@implementer(smtp.IMessageDelivery)
class ConsoleMessageDelivery:

    def __init__(self, domains, storage_path):
        self.domains = domains  # Lista de dominios permitidos
        self.storage_path = storage_path

    def receivedHeader(self, helo, origin, recipients):
        return "Received: server sigifedo.lat"

    def validateFrom(self, helo, origin):
        # All addresses are accepted
        return origin

    def validateTo(self, user):
        recipient_domain = getattr(user.dest, "domain", None)
        local_part = getattr(user.dest, "local", None)

        if isinstance(recipient_domain, bytes):
            recipient_domain = recipient_domain.decode('utf-8', errors='replace')
        if isinstance(local_part, bytes):
            local_part = local_part.decode('utf-8', errors='replace')
        #print("DEBUG: user.dest.domain =", repr(recipient_domain))
        if recipient_domain not in self.domains:
            raise smtp.SMTPBadRcpt(user)
        return lambda: ConsoleMessage(self.storage_path, recipient_domain, local_part)


@implementer(smtp.IMessage)
class ConsoleMessage:
    def __init__(self, storage_path, domain, local_part):
        self.storage_path = storage_path
        self.domain = domain
        self.local_part = local_part
        self.lines = []

    def lineReceived(self, line):
        if isinstance(line, bytes):
            line = line.decode('utf-8', errors='replace')
        self.lines.append(line)

    def eomReceived(self):

        import os
        import time

        message= "\n".join(self.lines)

        domain_path = os.path.join(self.storage_path, self.domain)
        user_path = os.path.join(domain_path, self.local_part)

        os.makedirs(user_path, exist_ok=True)

        filename= "message_{}.eml".format(time.time()*1000)
        filepath= os.path.join(user_path,filename)

        with open(filepath,"w", encoding="utf-8")as f:
            f.write(message)

        print(f"Correo guardado en: {filepath}")
        self.lines = None
        return defer.succeed(None)

    def connectionLost(self):
        # There was an error, throw away the stored lines
        self.lines = None


class ConsoleSMTPFactory(smtp.SMTPFactory):
    protocol = smtp.ESMTP

    def __init__(self, portal, delivery, *args, **kwargs):
        smtp.SMTPFactory.__init__(self, *args, **kwargs)
        self.portal = portal
        self.delivery = delivery

    def buildProtocol(self, addr):
        p = smtp.SMTPFactory.buildProtocol(self, addr)
        p.delivery = self.delivery
        p.challengers = {
            b"LOGIN": LOGINCredentials,
            b"PLAIN": PLAINCredentials
        }
        return p


@implementer(IRealm)
class SimpleRealm:
    def __init__(self,delivery):
        self.delivery = delivery

    def requestAvatar(self, avatarId, mind, *interfaces):
        if smtp.IMessageDelivery in interfaces:
            return smtp.IMessageDelivery, self.delivery, lambda: None
        raise NotImplementedError()

def parse_args():
    parser = argparse.ArgumentParser(description="Servidor SMTP con Twisted")
    parser.add_argument("-d", "--domains", required=True,
                        help="Lista de dominios aceptados (separados por comas)")
    parser.add_argument("-s", "--storage", required=True,
                        help="Ruta de almacenamiento de correos")
    parser.add_argument("-p", "--port", type=int, required=True,
                        help="Puerto en el que se ejecutará el servidor SMTP")
    return parser.parse_args()


def main():
    from twisted.application import internet
    from twisted.application import service

    args = parse_args()

    # Procesa la lista de dominios (ejemplo: "example.com,otro.com")
    domains_list = [d.strip() for d in args.domains.split(",")]

    delivery = ConsoleMessageDelivery(domains_list, args.storage)

    realm = SimpleRealm(delivery)
    portal = Portal(realm)

    a = service.Application("Console SMTP Server")
    smtpFactory = ConsoleSMTPFactory(portal, delivery)
    internet.TCPServer(args.port, smtpFactory).setServiceParent(a)

    return a


application = main()

if __name__ == '__main__':
    from twisted.application import service
    from twisted.internet import reactor

    # 1. Arranca el servicio
    service.IService(application).startService()

    # 2. Arranca el reactor
    reactor.run()
