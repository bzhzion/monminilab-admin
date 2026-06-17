import re

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,28}[a-z0-9]$")

RESERVED_SLUGS = {
    "admin", "portail", "www", "mail", "smtp", "imap", "pop", "pop3",
    "api", "app", "static", "assets", "cdn", "media", "upload", "uploads",
    "ftp", "ssh", "vpn", "ns", "ns1", "ns2", "dns",
    "webmail", "cpanel", "whm", "plesk",
    "blog", "shop", "store", "support", "help", "docs", "status",
    "login", "logout", "register", "signup", "account", "dashboard",
    "monminilab",
}
