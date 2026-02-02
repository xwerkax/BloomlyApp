from django import template
from urllib.parse import quote

register = template.Library()

def _get_profile(user):
    # Dostosuj nazwę relacji, jeśli u Ciebie jest inna niż 'profiluzytkownika'
    return getattr(user, "profiluzytkownika", None)

@register.simple_tag
def avatar_url(user, size=64):
    """
    Zwraca URL avatara użytkownika:
    - jeśli ma wgrany avatar (jeśli kiedyś przywrócisz pole) → URL pliku
    - w przeciwnym razie: fallback z ui-avatars (inicjały)
    """
    if not user or not getattr(user, "is_authenticated", False):
        return f"https://ui-avatars.com/api/?name=Guest&size={int(size)}&background=6c757d&color=ffffff"

    prof = _get_profile(user)
    # Jeżeli wrócisz do uploadu i model ma pole 'avatar':
    if prof and getattr(prof, "avatar", None):
        try:
            return prof.avatar.url
        except Exception:
            pass

    name = (user.get_full_name() or user.username or user.email or "User").strip()
    return f"https://ui-avatars.com/api/?name={quote(name)}&size={int(size)}&background=198754&color=ffffff&bold=true"
