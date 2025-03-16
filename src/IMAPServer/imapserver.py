#!/usr/bin/env python
import os
import re
import argparse
import csv
from io import BytesIO
from email.parser import BytesHeaderParser
from twisted.internet import reactor, protocol, defer
from twisted.application import service, internet
from twisted.mail import imap4
from twisted.cred import portal, credentials
from zope.interface import implementer
from twisted.cred import error
from twisted.cred.checkers import ICredentialsChecker
from twisted.mail.imap4 import MessageSet


CREDENTIALS_CSV = "/home/estudiante/Documentos/Universidad/Redes/Tareas/Tarea1/src/IMAPServer/credentials.csv"


@implementer(ICredentialsChecker)
class CSVCredentialsChecker:
    credentialInterfaces = (credentials.IUsernamePassword,)

    def __init__(self, csvPath):
        self.creds = {}
        try:
            with open(csvPath, newline='', encoding="utf-8") as csvfile:
                reader = csv.reader(csvfile)
                for row in reader:
                    if len(row) < 2:
                        continue
                    if "@" not in row[0]:
                        continue
                    user = row[0].strip()
                    pwd = row[1].strip()
                    self.creds[user] = pwd
        except Exception as e:
            print("Error al cargar credenciales desde CSV:", e)
            raise e

    def requestAvatarId(self, credentials):
        username = (credentials.username.decode('utf-8')
                    if isinstance(credentials.username, bytes)
                    else credentials.username).strip().strip('"')
        password = (credentials.password.decode('utf-8')
                    if isinstance(credentials.password, bytes)
                    else credentials.password).strip().strip('"')
        print("Intento de login - Usuario:", username, "Contraseña:", password)
        if username in self.creds and self.creds[username] == password:
            return defer.succeed(username)
        else:
            return defer.fail(error.UnauthorizedLogin("Invalid login"))


class FileMessage:
    def __init__(self, uid, filepath):
        self.uid = uid
        self.filepath = filepath
        self._deleted = False

    def getUID(self):
        return self.uid

    def getFlags(self):
        return []

    def getSize(self):
        try:
            return os.path.getsize(self.filepath)
        except Exception:
            return 0

    def getHeaders(self, *args, **kwargs):

        try:
            with open(self.filepath, "rb") as f:
                header_bytes = b""
                for line in f:
                    if line.strip() == b"":
                        break
                    header_bytes += line
            parser = BytesHeaderParser()
            headers = parser.parsebytes(header_bytes)
            return dict(headers.items())
        except Exception:
            return {}

    def getBody(self, skipAlreadyRetrieved=False):
        if self._deleted:
            return defer.succeed(b"")
        try:
            with open(self.filepath, "rb") as f:
                body = f.read()
            self._deleted = True
            return defer.succeed(body)
        except Exception as e:
            return defer.fail(e)

    def getBodyFile(self):
        try:
            with open(self.filepath, "rb") as f:
                data = f.read()
            self._deleted = True
            return BytesIO(data)
        except Exception as e:
            raise e

    def isMultipart(self):
        return False

@implementer(imap4.IMailbox)
class FileMailbox:
    def __init__(self, mailboxDir):
        self.mailboxDir = mailboxDir
        self._messages = None

    def _scanMessages(self):
        self._messages = {}
        files = sorted(os.listdir(self.mailboxDir))
        uid = 1
        for f in files:
            fpath = os.path.join(self.mailboxDir, f)
            if os.path.isfile(fpath):
                self._messages[uid] = FileMessage(uid, fpath)
                uid += 1

    def listMessages(self):
        self._scanMessages()
        return self._messages

    def fetch(self, msgnum, skipAlreadyRetrieved=False, uid=False):

        self._scanMessages()
        if isinstance(msgnum, MessageSet):
            first = getattr(msgnum, 'first', None)
            last = getattr(msgnum, 'last', None)
            if first is not None and last is not None:
                msgnums = list(range(first, last + 1))
            elif first is not None:
                msgnums = [first]
            else:
                m = re.search(r'\d+', str(msgnum))
                if m:
                    msgnums = [int(m.group(0))]
                else:
                    return defer.fail(TypeError("No se pudo interpretar MessageSet"))
        else:
            msgnums = [msgnum]
        results = {}
        for m in msgnums:
            if m in self._messages:
                results[m] = self._messages[m]
        return iter(results.items())

    def expunge(self):
        return defer.succeed(None)

    def getFlags(self):
        return []

    def getMessageCount(self):
        self._scanMessages()
        return len(self._messages) if self._messages is not None else 0

    def getRecentCount(self):
        return 0

    def getUnseenCount(self):
        return 0

    def getUIDValidity(self):
        return 1

    def isWriteable(self):
        return True

    def getHierarchicalDelimiter(self):
        return "/"

    def addListener(self, listener):
        pass

    def removeListener(self, listener):
        pass


@implementer(imap4.IAccount)
class IMAPAccount:
    def __init__(self, avatarId, base_storage):
        self.avatarId = avatarId.decode('utf-8') if isinstance(avatarId, bytes) else avatarId
        parts = self.avatarId.split('@')
        if len(parts) != 2:
            raise Exception("Formato de email inválido")
        local_part, domain = parts
        self.mailboxPath = os.path.join(base_storage, domain, local_part)
        os.makedirs(self.mailboxPath, exist_ok=True)

    def listMailboxes(self, ref, mbox):
        # Devuelve una lista de tuplas (nombre, buzón)
        return list({"INBOX": FileMailbox(self.mailboxPath)}.items())

    def select(self, mbox, rw):
        mailboxes = dict(self.listMailboxes(None, None))
        if mbox in mailboxes:
            return mailboxes[mbox]
        else:
            raise Exception("Mailbox not found")

    def create(self, mbox):
        new_path = os.path.join(self.mailboxPath, mbox)
        os.makedirs(new_path, exist_ok=True)
        return FileMailbox(new_path)

    def delete(self, mbox):
        mbox_path = os.path.join(self.mailboxPath, mbox)
        try:
            os.rmdir(mbox_path)
            return True
        except Exception as e:
            raise Exception("No se pudo eliminar el buzón: " + str(e))

    def subscribe(self, mbox):
        print(f"Suscripción a {mbox} solicitada, pero no implementada.")

    def isSubscribed(self, mbox):
        # Para este ejemplo, asumimos que todos los buzones están suscritos.
        return True


@implementer(portal.IRealm)
class IMAPRealm:
    def __init__(self, base_storage):
        self.base_storage = base_storage

    def requestAvatar(self, avatarId, mind, *interfaces):
        if imap4.IAccount in interfaces:
            account = IMAPAccount(avatarId, self.base_storage)
            return imap4.IAccount, account, lambda: None
        raise NotImplementedError("Interfaz no soportada")


class IMAP4ServerFactory(protocol.ServerFactory):
    def __init__(self, portal):
        self.portal = portal

    def buildProtocol(self, addr):
        p = imap4.IMAP4Server()
        p.portal = self.portal
        p.challengers = {b"LOGIN": imap4.LOGINCredentials,
                         b"PLAIN": imap4.PLAINCredentials}
        return p


def parse_args():
    parser = argparse.ArgumentParser(description="Servidor IMAP con Twisted")
    parser.add_argument("-s", "--storage", required=True,
                        help="Ruta base de almacenamiento de correos (estructura: base/dominio/usuario)")
    parser.add_argument("-p", "--port", type=int, required=True,
                        help="Puerto en el que se ejecutará el servidor IMAP")
    return parser.parse_args()

def main():
    args = parse_args()
    realm = IMAPRealm(args.storage)
    checker = CSVCredentialsChecker(CREDENTIALS_CSV)
    imap_portal = portal.Portal(realm, [checker])
    imapFactory = IMAP4ServerFactory(imap_portal)
    print("Servidor IMAP iniciado en el puerto", args.port)
    reactor.listenTCP(args.port, imapFactory)
    reactor.run()

if __name__ == '__main__':
    main()
