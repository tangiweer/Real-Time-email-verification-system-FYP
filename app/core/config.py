# Shared between training notebooks and the live pipeline — change here, not in both places
EXTRACTOR_SETTINGS: dict[str, set[str]] = {
    "SUSPICIOUS_TOKENS": {
        "temp", "fake", "test", "trash", "spam", "junk", "throwaway",
        "mailinator", "guerrilla", "sharklasers", "yopmail", "discard",
        "disposable", "tmpmail", "spamgourmet", "maildrop", "nospam",
        "dead", "noemail", "nomail", "noname", "nobody",
    },
    "SUSPICIOUS_TLDS": {
        ".xyz", ".top", ".club", ".gq", ".cf", ".tk", ".ml",
        ".ga", ".icu", ".buzz", ".stream", ".loan",
    },
    "ROLE_PREFIXES": {
        "admin", "support", "info", "noreply", "no-reply",
        "postmaster", "webmaster", "abuse", "security", "jobs",
    },
    "KNOWN_PROVIDERS": {
        "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com",
        "protonmail.com", "pm.me", "fastmail.com", "zoho.com", "tutanota.com",
        "mail.com", "yandex.com", "gmx.com", "posteo.de",
    }
}
