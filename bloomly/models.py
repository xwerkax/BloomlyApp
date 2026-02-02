from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import time
from datetime import timedelta
from typing import Optional
import math

class ProfilUzytkownika(models.Model):
    # Połączenie z wbudowanym modelem User (1 do 1)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profiluzytkownika")

    # Dodatkowe pola
    telefon = models.CharField(max_length=15, blank=True, verbose_name="Telefon")
    data_urodzenia = models.DateField(null=True, blank=True, verbose_name="Data urodzenia")


    # Preferencje aplikacji
    powiadomienia_email = models.BooleanField(default=True, verbose_name="Powiadomienia email")

    # Znaczniki czasowe
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profil {self.user.username}"

    class Meta:
        verbose_name = "Profil użytkownika"
        verbose_name_plural = "Profile użytkowników"

    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    biogram = models.TextField(blank=True, max_length=600)  # NOWE

    def __str__(self):
        return f"Profil: {self.user.username}"


# WAŻNE: Automatyczne tworzenie profilu gdy ktoś się rejestruje
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:  # Jeśli użytkownik jest nowy
        ProfilUzytkownika.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profiluzytkownika.save()


class Roslina(models.Model):
    KATEGORIE_ROSLIN = [
        ('doniczkowa', 'Roślina doniczkowa'),
        ('ogrodowa', 'Roślina ogrodowa'),
        ('balkonowa', 'Roślina balkonowa'),
        ('ziolowa', 'Roślina ziołowa'),
    ]

    POZIOM_TRUDNOSCI = [
        ('latwy', 'Łatwy'),
        ('sredni', 'Średni'),
        ('trudny', 'Trudny'),
    ]

    # Relacja do właściciela
    wlasciciel = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Właściciel")

    # Podstawowe informacje
    nazwa = models.CharField(max_length=200, verbose_name="Nazwa własna")
    gatunek = models.CharField(max_length=200, verbose_name="Gatunek", help_text="np. Monstera deliciosa")
    kategoria = models.CharField(max_length=20, choices=KATEGORIE_ROSLIN, verbose_name="Kategoria")
    poziom_trudnosci = models.CharField(max_length=10, choices=POZIOM_TRUDNOSCI, default='sredni',
                                        verbose_name="Poziom trudności")

    # Daty
    data_zakupu = models.DateField(verbose_name="Data zakupu/otrzymania")
    data_dodania = models.DateTimeField(auto_now_add=True, verbose_name="Data dodania do aplikacji")

    # Lokalizacja i opis
    lokalizacja = models.CharField(max_length=100, blank=True, verbose_name="Lokalizacja",
                                   help_text="np. salon, balkon, kuchnia")
    notatki = models.TextField(blank=True, verbose_name="Notatki")

    # Zdjęcie
    zdjecie = models.ImageField(upload_to='rosliny/', blank=True, null=True, verbose_name="Zdjęcie")

    # Ustawienia pielęgnacji
    czestotliwosc_podlewania = models.IntegerField(default=7, verbose_name="Częstotliwość podlewania (dni)")
    ostatnie_podlewanie = models.DateField(null=True, blank=True, verbose_name="Ostatnie podlewanie")

    # Status
    is_active = models.BooleanField(default=True, verbose_name="Aktywna")

    class Meta:
        verbose_name = "Roślina"
        verbose_name_plural = "Rośliny"
        ordering = ['-data_dodania']

    def __str__(self):
        return self.nazwa

    def dni_od_podlewania(self):
        """Ile dni minęło od ostatniego podlewania"""
        if self.ostatnie_podlewanie:
            return (timezone.now().date() - self.ostatnie_podlewanie).days
        return None

    def czy_potrzebuje_podlewania(self):
        """Czy roślina potrzebuje podlewania"""
        dni = self.dni_od_podlewania()
        if dni is None:
            return True  # Brak danych o podlewaniu
        return dni >= self.czestotliwosc_podlewania


class CzynoscPielegnacyjna(models.Model):
    TYPY_CZYNNOSCI = [
        ('podlewanie', 'Podlewanie'),
        ('nawozenie', 'Nawożenie'),
        ('przycinanie', 'Przycinanie'),
        ('przesadzanie', 'Przesadzanie'),
    ]

    STAN_GLEBY = [
        ('dry', 'sucha'),
        ('moist', 'lekko wilgotna'),
        ('wet', 'mokra'),
    ]
    ILOSC_WODY = [
        ('low', 'mało'),
        ('med', 'średnio'),
        ('high', 'dużo'),
    ]

    stan_gleby = models.CharField(max_length=8, choices=STAN_GLEBY, blank=True, null=True, verbose_name="Stan gleby")
    ilosc_wody = models.CharField(max_length=8, choices=ILOSC_WODY, blank=True, null=True, verbose_name="Ilość wody")

    interwal_dni = models.FloatField(blank=True, null=True, verbose_name="Interwał od poprzedniego (dni)")

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # Tylko dla podlewania licz interwał i aktualizuj roślinę
        if self.typ == 'podlewanie':
            prev = (
                CzynoscPielegnacyjna.objects
                .filter(roslina=self.roslina, typ='podlewanie', data__lt=self.data)
                .order_by('-data')
                .first()
            )
            if prev:
                delta = self.data - prev.data
                interval = delta.total_seconds() / 86400.0
                if self.interwal_dni != interval:
                    CzynoscPielegnacyjna.objects.filter(pk=self.pk).update(interwal_dni=interval)

            if is_new and (
                    self.roslina.ostatnie_podlewanie is None or self.data.date() > self.roslina.ostatnie_podlewanie):
                self.roslina.ostatnie_podlewanie = self.data.date()
                self.roslina.save(update_fields=['ostatnie_podlewanie'])
    # Relacje
    roslina = models.ForeignKey(Roslina, on_delete=models.CASCADE, verbose_name="Roślina")
    uzytkownik = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Użytkownik")

    # Szczegóły czynności
    typ = models.CharField(max_length=20, choices=TYPY_CZYNNOSCI, verbose_name="Typ czynności")
    data = models.DateTimeField(default=timezone.now, verbose_name="Data wykonania")
    wykonane = models.BooleanField(default=True, verbose_name="Wykonane")

    # Dodatkowe informacje
    notatki = models.TextField(blank=True, verbose_name="Notatki")
    zdjecie = models.ImageField(upload_to='czynnosci/', blank=True, null=True, verbose_name="Zdjęcie")

    class Meta:
        verbose_name = "Czynność pielęgnacyjna"
        verbose_name_plural = "Czynności pielęgnacyjne"
        ordering = ['-data']

    def __str__(self):
        return f"{self.get_typ_display()} - {self.roslina.nazwa} ({self.data.strftime('%d.%m.%Y')})"

class Przypomnienie(models.Model):
    """
    Przypomnienia dotyczą TYLKO podlewania.
    Statusy: tylko 'oczekujace' i 'wykonane'.
    'wyslane' to wyłącznie flaga techniczna (czy wysłano powiadomienie), a nie osobny status.
    """
    TYPY_PRZYPOMNIE = [
        ('podlewanie', 'Podlewanie'),
    ]

    STATUS_CHOICES = [
        ('oczekujace', 'Oczekujące'),
        ('wykonane', 'Wykonane'),
    ]

    # Relacje
    roslina = models.ForeignKey(Roslina, on_delete=models.CASCADE, verbose_name="Roślina")
    uzytkownik = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Użytkownik")

    # Szczegóły przypomnienia
    typ = models.CharField(
        max_length=20,
        choices=TYPY_PRZYPOMNIE,
        default='podlewanie',
        verbose_name="Typ przypomnienia",
    )
    tytul = models.CharField(max_length=200, verbose_name="Tytuł")
    tresc = models.TextField(verbose_name="Treść przypomnienia")

    # Daty
    data_przypomnienia = models.DateTimeField(verbose_name="Data przypomnienia")
    data_utworzenia = models.DateTimeField(auto_now_add=True, verbose_name="Data utworzenia")
    data_wyslania = models.DateTimeField(null=True, blank=True, verbose_name="Data wysłania")
    data_wykonania = models.DateTimeField(null=True, blank=True, verbose_name="Data wykonania")

    # Status (tylko 2 stany)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='oczekujace',
        verbose_name="Status",
    )

    # Flaga techniczna – czy powiadomienie (mail/SMS) zostało wysłane
    wyslane = models.BooleanField(default=False, verbose_name="Wysłane")

    # Powtarzalność – używamy bardziej jako metadanych dla ML (ostatni użyty interwał),
    # NIE jako „sztywnego kalendarza”.
    powtarzalne = models.BooleanField(default=True, verbose_name="Systemowe (ML)")
    interwal_dni = models.IntegerField(null=True, blank=True, verbose_name="Interwał (dni) wg ML")

    # Metadane
    automatyczne = models.BooleanField(default=True, verbose_name="Utworzone automatycznie")
    priorytet = models.IntegerField(default=1, verbose_name="Priorytet (1-5)")

    class Meta:
        verbose_name = "Przypomnienie"
        verbose_name_plural = "Przypomnienia"
        ordering = ['data_przypomnienia']

    def __str__(self):
        return f"{self.tytul} - {self.roslina.nazwa} ({self.data_przypomnienia.strftime('%d.%m.%Y')})"

    # --- Logika pomocnicza ---

    def is_overdue(self) -> bool:
        """Czy przypomnienie jest przeterminowane (tylko dla oczekujących)."""
        if self.status != 'oczekujace' or not self.data_przypomnienia:
            return False
        try:
            return timezone.localtime(self.data_przypomnienia) < timezone.localtime(timezone.now())
        except Exception:
            # fallback: bezpieczne porównanie datowe
            try:
                return self.data_przypomnienia < timezone.now()
            except Exception:
                return False

    def dni_do_przypomnienia(self):
        """
        Zwraca int dni:
          - przyszłość: math.ceil(days_float)  -> UX: 0.1 dnia => 1 dzień (pokazuje "Za 1 dzień")
          - przeszłość: math.floor(days_float)  -> -0.1 => -1 (po terminie)
        Używamy timezone.localtime() żeby porównania były w tej samej strefie.
        """
        if not self.data_przypomnienia:
            return None

        try:
            now = timezone.localtime(timezone.now())
            target = timezone.localtime(self.data_przypomnienia)
        except Exception:
            # Bezpieczeństwo: fallback na porównanie dat jeśli coś pójdzie nie tak
            try:
                return (self.data_przypomnienia.date() - timezone.now().date()).days
            except Exception:
                return None

        delta_seconds = (target - now).total_seconds()
        days_float = delta_seconds / 86400.0

        if delta_seconds >= 0:
            return int(math.ceil(days_float))
        else:
            return int(math.floor(days_float))

    def opis_rekomendacji(self):
        """
        Tekst 'Rekomendacja: za X dni / dziś / X dni temu' dla listy przypomnień.
        """
        dni = self.dni_do_przypomnienia()

        if dni > 1:
            return f"Za {dni} dni"  # ✅ ZMIEŃ - wielka litera, bez kropki
        elif dni == 1:
            return "Za 1 dzień"  # ✅ ZMIEŃ
        elif dni == 0:
            return "Dzisiaj"  # ✅ ZMIEŃ
        else:
            return f"{-dni} dni po terminie"

    def oznacz_jako_wykonane(self):
        """
        Oznacz przypomnienie jako wykonane.
        NIE tworzy kolejnego przypomnienia – to zadanie Celery/odswiez_przypomnienie_rosliny
        (ONE-OPEN: nowe powstaje dopiero po wykonaniu poprzedniego).
        """
        self.status = 'wykonane'
        self.data_wykonania = timezone.now()
        self.save(update_fields=['status', 'data_wykonania'])

    def odloz(self, dni: int = 1):
        """
        Przesuń termin przypomnienia o określoną liczbę dni.
        Status pozostaje 'oczekujace' (nie mamy osobnego statusu 'odlozone').
        """
        self.data_przypomnienia += timedelta(days=dni)
        self.save(update_fields=['data_przypomnienia'])


# ================== FUNKCJE POMOCNICZE – TYLKO PODLEWANIE, TYLKO ML ==================

def _wyznacz_interwal_ml_dni(roslina: Roslina) -> int:
    """
    Zwraca interwał podlewania w dniach oparty na AnalizaPielegnacji (ML).
    Jeśli model nie ma jeszcze wystarczających danych lub pewność jest niska,
    fallback: czestotliwosc_podlewania z modelu Roslina.
    """
    # Domyślnie – to co użytkownik ustawił przy roślinie
    domyslny = max(1, roslina.czestotliwosc_podlewania or 7)

    try:
        analiza = roslina.analiza  # OneToOneField AnalizaPielegnacji
    except AnalizaPielegnacji.DoesNotExist:
        return domyslny

    # Minimalne wymagania, żeby ufać ML (możesz dopasować progi)
    if (
        analiza.rekomendowana_czestotliwosc
        and analiza.liczba_podlan >= 5
        and analiza.pewnosc_rekomendacji >= 0.5
    ):
        return max(1, analiza.rekomendowana_czestotliwosc)

    return domyslny


from django.db import transaction


def utworz_przypomnienie_podlewanie(roslina) -> Optional[Przypomnienie]:
    """
    ONE-OPEN + ML - thread-safe version
    """
    if not roslina.is_active:
        return None

    interwal_dni = _wyznacz_interwal_ml_dni(roslina)

    # Oblicz docelową datę
    if roslina.ostatnie_podlewanie:
        baza = roslina.ostatnie_podlewanie
    else:
        baza = timezone.now().date()

    docelowa_data = baza + timedelta(days=interwal_dni)
    noon = time(12, 0)
    naive_dt = timezone.datetime.combine(docelowa_data, noon)
    data_przypomnienia = timezone.make_aware(naive_dt)

    # ✅ ATOMOWA OPERACJA - zapobiega race conditions
    with transaction.atomic():
        # Pobierz WSZYSTKIE oczekujące przypomnienia
        oczekujace = list(
            Przypomnienie.objects
            .filter(roslina=roslina, status='oczekujace')
            .select_for_update()  # ← LOCK na poziomie bazy!
            .order_by('data_przypomnienia')
        )

        if oczekujace:
            # Zostaw tylko PIERWSZE, usuń resztę (cleanup duplikatów)
            do_zachowania = oczekujace[0]

            if len(oczekujace) > 1:
                # Usuń duplikaty
                for przyp in oczekujace[1:]:
                    przyp.delete()

            # Zaktualizuj pozostałe
            if (
                    do_zachowania.data_przypomnienia != data_przypomnienia
                    or do_zachowania.interwal_dni != interwal_dni
            ):
                do_zachowania.data_przypomnienia = data_przypomnienia
                do_zachowania.interwal_dni = interwal_dni
                do_zachowania.automatyczne = True
                do_zachowania.powtarzalne = True
                do_zachowania.save(update_fields=[
                    'data_przypomnienia',
                    'interwal_dni',
                    'automatyczne',
                    'powtarzalne'
                ])

            return do_zachowania

        # Brak przypomnienia - utwórz nowe
        return Przypomnienie.objects.create(
            roslina=roslina,
            uzytkownik=roslina.wlasciciel,
            typ='podlewanie',
            tytul=f'Podlej {roslina.nazwa}',
            tresc=(
                f'Czas podlać {roslina.nazwa} ({roslina.gatunek}). '
                f'Ostatnie podlewanie: {roslina.ostatnie_podlewanie or "brak danych"}. '
                f'Interwał (ML): co {interwal_dni} dni.'
            ),
            data_przypomnienia=data_przypomnienia,
            powtarzalne=True,
            interwal_dni=interwal_dni,
            automatyczne=True,
            priorytet=2 if roslina.czy_potrzebuje_podlewania() else 1,
            status='oczekujace',
        )

def aktualizuj_przypomnienia_uzytkownika(uzytkownik: User):
    """
    Dla każdej aktywnej rośliny użytkownika:
    - zapewnij, że istnieje dokładnie JEDNO oczekujące przypomnienie o podlewaniu,
      wyliczone wg ML (ONE-OPEN).
    """
    rosliny = Roslina.objects.filter(wlasciciel=uzytkownik, is_active=True)

    for roslina in rosliny:
        utworz_przypomnienie_podlewanie(roslina)


# ======= FORUM + BAZA WIEDZY =======

class Kategoria(models.Model):
    """Kategorie forum (pielęgnacja, choroby, gatunki, etc.)"""
    TYPY_KATEGORII = [
        ('forum', 'Forum'),
        ('baza', 'Baza wiedzy'),
    ]

    nazwa = models.CharField(max_length=100, verbose_name="Nazwa kategorii")
    slug = models.SlugField(unique=True, verbose_name="URL slug")
    opis = models.TextField(blank=True, verbose_name="Opis")
    typ = models.CharField(max_length=10, choices=TYPY_KATEGORII, default='forum', verbose_name="Typ")
    ikona = models.CharField(max_length=50, blank=True, verbose_name="Ikona Bootstrap",
                             help_text="np. bi-chat, bi-book")

    # Hierarchia kategorii
    rodzic = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='podkategorie',
                               verbose_name="Kategoria nadrzędna")

    kolejnosc = models.IntegerField(default=0, verbose_name="Kolejność wyświetlania")
    aktywna = models.BooleanField(default=True, verbose_name="Aktywna")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kategoria"
        verbose_name_plural = "Kategorie"
        ordering = ['kolejnosc', 'nazwa']

    def __str__(self):
        return self.nazwa

    def liczba_postow(self):
        """Ile postów w tej kategorii"""
        return self.post_set.count()


class Post(models.Model):

    STATUSY = [
        ('published', 'Opublikowany'),
    ]

    # Podstawowe info
    tytul = models.CharField(max_length=200, verbose_name="Tytuł")
    slug = models.SlugField(unique=True, verbose_name="URL slug")
    tresc = models.TextField(verbose_name="Treść")

    # Relacje
    autor = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Autor")
    kategoria = models.ForeignKey(Kategoria, on_delete=models.CASCADE, verbose_name="Kategoria")

    # Metadata
    status = models.CharField(max_length=20, choices=STATUSY, default='published', verbose_name="Status")
    zablokowany = models.BooleanField(default=False, verbose_name="Zablokowany (brak komentarzy)")

    # Statystyki
    wyswietlenia = models.IntegerField(default=0, verbose_name="Wyświetlenia")

    # Daty
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Data utworzenia")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Data aktualizacji")
    opublikowany_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Post"
        verbose_name_plural = "Posty"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['kategoria', 'status']),
            models.Index(fields=['autor']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return self.tytul

    def save(self, *args, **kwargs):
        # Automatyczne ustawienie daty publikacji
        if self.status == 'published' and not self.opublikowany_at:
            self.opublikowany_at = timezone.now()

        # Automatyczne tworzenie slug
        if not self.slug:
            from django.utils.text import slugify
            base_slug = slugify(self.tytul)
            slug = base_slug
            counter = 1
            while Post.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        super().save(*args, **kwargs)


class Komentarz(models.Model):

    post = models.ForeignKey(Post, on_delete=models.CASCADE, verbose_name="Post")
    autor = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Autor")

    tresc = models.TextField(verbose_name="Treść komentarza")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Data utworzenia")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Data edycji")

    class Meta:
        verbose_name = "Komentarz"
        verbose_name_plural = "Komentarze"
        ordering = ['created_at']

    def __str__(self):
        return f"Komentarz {self.autor.username} do {self.post.tytul}"


class BazaRoslin(models.Model):
    """Encyklopedia roślin - baza wiedzy"""
    POZIOMY_TRUDNOSCI = [
        ('latwy', 'Łatwy'),
        ('sredni', 'Średni'),
        ('trudny', 'Trudny'),
    ]

    # Podstawowe informacje
    nazwa_polska = models.CharField(max_length=200, verbose_name="Nazwa polska")
    nazwa_naukowa = models.CharField(max_length=200, verbose_name="Nazwa naukowa (łacińska)")
    slug = models.SlugField(unique=True, verbose_name="URL slug")

    # Opis
    opis_krotki = models.TextField(max_length=500, verbose_name="Krótki opis")
    opis_szczegolowy = models.TextField(verbose_name="Szczegółowy opis")

    # Klasyfikacja
    rodzina = models.CharField(max_length=100, blank=True, verbose_name="Rodzina botaniczna")
    rodzaj = models.CharField(max_length=100, blank=True, verbose_name="Rodzaj")

    # Wymagania pielęgnacyjne
    poziom_trudnosci = models.CharField(max_length=10, choices=POZIOMY_TRUDNOSCI, verbose_name="Poziom trudności")
    wymagania_swiatla = models.CharField(max_length=100, verbose_name="Wymagania świetlne",
                                         help_text="np. pełne słońce, półcień")
    czestotliwosc_podlewania = models.CharField(max_length=100, verbose_name="Częstotliwość podlewania")
    wilgotnosc_powietrza = models.CharField(max_length=100, blank=True, verbose_name="Wilgotność powietrza")
    temperatura_min = models.IntegerField(null=True, blank=True, verbose_name="Temperatura minimalna (°C)")
    temperatura_max = models.IntegerField(null=True, blank=True, verbose_name="Temperatura maksymalna (°C)")

    # Dodatkowe info
    podloz = models.CharField(max_length=200, blank=True, verbose_name="Typ podłoża")
    nawozenie = models.TextField(blank=True, verbose_name="Nawożenie")
    rozmnazanie = models.TextField(blank=True, verbose_name="Rozmnażanie")
    choroby_szkodniki = models.TextField(blank=True, verbose_name="Choroby i szkodniki")
    ciekawostki = models.TextField(blank=True, verbose_name="Ciekawostki")

    # Toksyczność
    toksyczna_dla_ludzi = models.BooleanField(default=False, verbose_name="Toksyczna dla ludzi")
    toksyczna_dla_zwierzat = models.BooleanField(default=False, verbose_name="Toksyczna dla zwierząt")

    # Zdjęcia
    zdjecie_glowne = models.ImageField(upload_to='baza_roslin/', blank=True, null=True, verbose_name="Zdjęcie główne")

    # Metadata
    autor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="Dodane przez")
    zweryfikowane = models.BooleanField(default=False, verbose_name="Zweryfikowane przez eksperta")

    # Statystyki
    wyswietlenia = models.IntegerField(default=0, verbose_name="Wyświetlenia")

    # Daty
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Roślina w bazie wiedzy"
        verbose_name_plural = "Baza wiedzy - rośliny"
        ordering = ['nazwa_polska']
        indexes = [
            models.Index(fields=['nazwa_polska']),
            models.Index(fields=['nazwa_naukowa']),
        ]

    def __str__(self):
        return f"{self.nazwa_polska} ({self.nazwa_naukowa})"

    def save(self, *args, **kwargs):
        # Automatyczne tworzenie slug
        if not self.slug:
            from django.utils.text import slugify
            base_slug = slugify(self.nazwa_polska)
            slug = base_slug
            counter = 1
            while BazaRoslin.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug

        super().save(*args, **kwargs)


# ======= ANALITYKA I ML =======

class AnalizaPielegnacji(models.Model):
    """Model przechowujący analizę ML dla rośliny"""

    # NOWE - typ modelu ML
    TYPY_MODELU = [
        ('RF', 'Random Forest'),
        ('GB', 'Gradient Boosting'),
    ]

    roslina = models.OneToOneField(
        'Roslina',
        on_delete=models.CASCADE,
        related_name='analiza'
    )
    uzytkownik = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    # Statystyki
    srednia_czestotliwosc_dni = models.FloatField(default=0)
    odchylenie_standardowe = models.FloatField(default=0)
    liczba_podlan = models.IntegerField(default=0)

    # Analiza pór dnia
    podlewa_rano = models.BooleanField(default=False)
    podlewa_po_poludniu = models.BooleanField(default=False)
    podlewa_wieczorem = models.BooleanField(default=False)

    # Rekomendacje ML
    rekomendowana_czestotliwosc = models.IntegerField(default=7)
    pewnosc_rekomendacji = models.FloatField(default=0.5)

    # NOWE - typ użytego modelu
    typ_modelu = models.CharField(
        max_length=2,
        choices=TYPY_MODELU,
        default='RF',
        verbose_name="Typ modelu ML"
    )

    # NOWE - dodatkowe metryki ML (opcjonalne, ale przydatne)
    r2_score = models.FloatField(null=True, blank=True, verbose_name="R² Score")
    mae = models.FloatField(null=True, blank=True, verbose_name="MAE (Mean Absolute Error)")
    rmse = models.FloatField(null=True, blank=True, verbose_name="RMSE")
    cv_mae = models.FloatField(null=True, blank=True, verbose_name="CV MAE (Cross-Validation)")

    # NOWE - składowe pewności
    pewnosc_model = models.FloatField(default=0.0, verbose_name="Pewność - jakość modelu")
    pewnosc_regularnosc = models.FloatField(default=0.0, verbose_name="Pewność - regularność")
    pewnosc_biologia = models.FloatField(default=0.0, verbose_name="Pewność - zgodność biologiczna")

    # Metadane
    data_aktualizacji = models.DateTimeField(auto_now=True, verbose_name="Ostatnia aktualizacja")
    data_utworzenia = models.DateTimeField(auto_now_add=True, verbose_name="Data utworzenia")

    class Meta:
        verbose_name = "Analiza Pielęgnacji"
        verbose_name_plural = "Analizy Pielęgnacji"

    def __str__(self):
        return f"Analiza: {self.roslina.nazwa} - {self.rekomendowana_czestotliwosc} dni ({self.get_typ_modelu_display()})"