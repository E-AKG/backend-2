"""Hilfsfunktionen für Adressen (Straße, PLZ, Ort)"""


def build_address(data: dict) -> str:
    """Baut kombinierte Adresse aus address_street, postal_code, city.
    Fallback auf address wenn die neuen Felder leer sind."""
    street = (data.get("address_street") or "").strip()
    plz = (data.get("postal_code") or "").strip()
    city = (data.get("city") or "").strip()
    if street or plz or city:
        plz_city = " ".join(filter(None, [plz, city]))
        return ", ".join(filter(None, [street, plz_city]))
    return (data.get("address") or "").strip()
