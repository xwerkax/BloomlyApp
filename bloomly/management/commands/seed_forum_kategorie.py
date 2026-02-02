from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django.apps import apps

class Command(BaseCommand):
    help = "Dodaje podstawowe kategorie forum (idempotentnie)."

    def handle(self, *args, **options):
        # Spróbuj wykryć model Kategoria automatycznie
        Kategoria = None
        for model in apps.get_models():
            if model.__name__.lower() == "kategoria":
                Kategoria = model
                break
        if not Kategoria:
            self.stderr.write(self.style.ERROR("Nie znalazłem modelu Kategoria."))
            return

        def add_cat(name, parent=None):
            slug = slugify(name)
            defaults = {"nazwa": name}
            if hasattr(Kategoria, "typ"):
                defaults["typ"] = "forum"
            if hasattr(Kategoria, "aktywna"):
                defaults["aktywna"] = True
            if hasattr(Kategoria, "rodzic"):
                defaults["rodzic"] = parent

            obj, created = Kategoria.objects.get_or_create(slug=slug, defaults=defaults)

            changed = False
            if getattr(obj, "nazwa", name) != name:
                obj.nazwa = name
                changed = True
            if hasattr(obj, "typ") and getattr(obj, "typ", None) != "forum":
                obj.typ = "forum"
                changed = True
            if hasattr(obj, "aktywna") and getattr(obj, "aktywna", True) is not True:
                obj.aktywna = True
                changed = True
            if parent is not None and hasattr(obj, "rodzic") and getattr(obj, "rodzic_id", None) != parent.id:
                obj.rodzic = parent
                changed = True
            if changed:
                obj.save()
            self.stdout.write((self.style.SUCCESS("✔ utworzono  ") if created else "• istnieje   ") + f"{name}")
            return obj

        main = [
            "Ogólne",
            "Podlewanie",
            "Przesadzanie",
            "Nawożenie",
            "Oświetlenie",
            "Choroby i szkodniki",
            "Ziemia i podłoża",
            "Rozmnażanie",
            "Identyfikacja roślin",
            "Wilgotność i temperatura",
            "Kwiaty doniczkowe",
            "Sukulenty i kaktusy",
        ]
        parents = {name: add_cat(name) for name in main}

        sub_map = {
            "Podlewanie": ["Zraszanie", "Częstotliwość", "Twardość wody"],
            "Przesadzanie": ["Dobór doniczki", "Drenaż", "Opieka po przesadzeniu"],
            "Choroby i szkodniki": ["Wełnowce", "Przędziorki", "Zgnilizny"],
            "Nawożenie": ["Rodzaje nawozów", "Harmonogram"],
            "Oświetlenie": ["Cieniolubne", "Światłolubne"],
        }
        for parent_name, children in sub_map.items():
            p = parents[parent_name]
            for child in children:
                add_cat(child, parent=p)

        q = Kategoria.objects.all()
        if hasattr(Kategoria, "typ"):
            q = q.filter(typ="forum")
        if hasattr(Kategoria, "rodzic"):
            root_q = q.filter(rodzic__isnull=True)
        else:
            root_q = q
        self.stdout.write(self.style.NOTICE(f"\nRazem kategorii forum: {q.count()}"))
        self.stdout.write(self.style.NOTICE(f"Główne kategorie: {list(root_q.values_list('nazwa', flat=True))}"))
