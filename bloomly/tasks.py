"""
Zadania Celery dla aplikacji Bloomly
- Przypomnienia (ONE-OPEN) oparte o predykcję RF
- Analiza ML roślin
- Automatyczne aktualizacje
"""

# Django core
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from datetime import timedelta, datetime
import logging

# Celery
from celery import shared_task

# Modele
from .models import (
    Przypomnienie,
    Roslina,
    CzynoscPielegnacyjna,
    AnalizaPielegnacji,
)

# ML Utils
from .ml_utils import (
    zaktualizuj_analize_rosliny,
    zastosuj_rekomendacje_ml,
    retrenuj_wszystkie_modele,
    przewidz_czestotliwosc_ml,
    analizuj_wzorce_statystyczne,
)

# Logger
logger = logging.getLogger(__name__)

# Godzina, o której „kotwiczymy” przypomnienia (lokalnie)
REMINDER_HOUR = 9  # 09:00 czasu Europe/Warsaw

# Jakie statusy traktujemy jako „otwarte”
OPEN_STATUSES = ("oczekujace", "wyslane")


# ============================================
# POMOCNICZE — ONE-OPEN refresher
# ============================================

def _tzaware(dt: datetime) -> datetime:
    """Zwraca dt świadomy strefy (lokalny)."""
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt.astimezone(timezone.get_current_timezone())


def _nastepny_termin_podlewania(roslina: Roslina):
    """
    Oblicz (data_przypomnienia, meta, zrodlo) bazując na:
    - ostatnim podlaniu (wpis t),
    - predykcji RF (fallback: statystyka).
    Zwraca None, jeśli brak ostatniego podlania.
    """
    last = (
        CzynoscPielegnacyjna.objects
        .filter(roslina=roslina, typ="podlewanie", wykonane=True)
        .order_by("-data")
        .first()
    )
    if not last:
        return None

    # RF → fallback stat
    w = przewidz_czestotliwosc_ml(roslina) or analizuj_wzorce_statystyczne(roslina)
    days = int(w["rekomendowana_czestotliwosc"])

    base = _tzaware(last.data)
    due = base + timedelta(days=days)
    due = due.replace(hour=REMINDER_HOUR, minute=0, second=0, microsecond=0)

    zrodlo = w.get("model_type", "Statystyczny (backup)")
    return due, w, zrodlo


@shared_task
def odswiez_przypomnienie_rosliny(roslina_id: int):
    """
    Idempotentnie utrzymuje JEDNO otwarte przypomnienie dla rośliny.
    - Jeśli istnieje otwarte → AKTUALIZUJE datę/treść i re-armuje wysyłkę,
    - Jeśli nie istnieje → TWORZY jedno,
    - Jeśli brak danych (brak ostatniego podlewania) → zamyka otwarte.
    """
    try:
        with transaction.atomic():
            r = Roslina.objects.select_for_update().get(pk=roslina_id, is_active=True)
            calc = _nastepny_termin_podlewania(r)

            open_qs = Przypomnienie.objects.filter(
                roslina=r, typ="podlewanie", status__in=OPEN_STATUSES
            ).order_by("data_przypomnienia")

            if not calc:
                # brak danych → zamknij otwarte
                if open_qs.exists():
                    open_qs.update(status="anulowane")
                logger.info(f"[ONE-OPEN] {r.nazwa}: brak ostatniego podlewania – anulowano otwarte.")
                return "brak danych"

            due, meta, zrodlo = calc
            tytul = f"Podlej {r.nazwa}"
            # krótka, czytelna treść – bez pól, których nie ma w modelu
            tresc = (
                f"Rekomendacja: za {meta['rekomendowana_czestotliwosc']} dni. "
                f"Źródło: {zrodlo}."
            )

            if open_qs.exists():
                pr = open_qs.first()
                # re-arm: ustaw nową datę i przywróć do 'oczekujące' jeśli była 'wysłane'
                pr.data_przypomnienia = due
                pr.tytul = tytul
                pr.tresc = tresc
                pr.status = "oczekujace"
                pr.wyslane = False
                pr.automatyczne = True
                pr.interwal_dni = None  # nie powtarzamy „z automatu”
                pr.save(update_fields=[
                    "data_przypomnienia", "tytul", "tresc",
                    "status", "wyslane", "automatyczne", "interwal_dni"
                ])
                logger.info(f"[ONE-OPEN] Zaktualizowano przypomnienie dla {r.nazwa} -> {due}.")
                return "zaktualizowano"
            else:
                Przypomnienie.objects.create(
                    roslina=r,
                    uzytkownik=r.wlasciciel,
                    typ="podlewanie",
                    tytul=tytul,
                    tresc=tresc,
                    data_przypomnienia=due,
                    status="oczekujace",
                    wyslane=False,
                    powtarzalne=False,
                    interwal_dni=None,
                    automatyczne=True,
                    priorytet=2,
                )
                logger.info(f"[ONE-OPEN] Utworzono przypomnienie dla {r.nazwa} -> {due}.")
                return "utworzono"
    except Roslina.DoesNotExist:
        logger.warning(f"[ONE-OPEN] roślina id={roslina_id} nie istnieje lub nieaktywna.")
        return "brak rosliny"
    except Exception as e:
        logger.exception(f"[ONE-OPEN] Błąd odświeżania przypomnienia dla roslina_id={roslina_id}: {e}")
        return f"błąd: {e}"


# ============================================
# PRZYPOMNIENIA - EMAIL
# ============================================

@shared_task
def wyslij_email_przypomnienie(przypomnienie_id):
    """
    Wysyła email z przypomnieniem do użytkownika (3 dni przed terminem).
    """
    try:
        pr = Przypomnienie.objects.get(id=przypomnienie_id)

        # Konwersja na czas lokalny
        data_lokalna = timezone.localtime(pr.data_przypomnienia)

        # Oblicz ile dni pozostało
        dni_do = (pr.data_przypomnienia.date() - timezone.now().date()).days

        subject = f"🌱 {pr.tytul} - za {dni_do} dni"
        message = f"""
Cześć {pr.uzytkownik.first_name or pr.uzytkownik.username}!

⏰ Za {dni_do} dni nadchodzi termin podlewania Twojej rośliny:

🌱 Roślina: {pr.roslina.nazwa} ({pr.roslina.gatunek})
📅 Termin podlewania: {data_lokalna.strftime('%d.%m.%Y %H:%M')}
📍 Lokalizacja: {getattr(pr.roslina, 'lokalizacja', '') or 'nie podano'}

{pr.tresc}

Wskazówki przed podlewaniem:
- Sprawdź wilgotność gleby (powinna być sucha)
- Przygotuj odpowiednią ilość wody
- Podlewaj rano lub wieczorem
- Nie zalewaj rośliny

Link do przypomnienia: http://127.0.0.1:8000/przypomnienia/{pr.id}/

Pozdrawiamy,
Zespół Bloomly 🌿
        """.strip()

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[pr.uzytkownik.email],
            fail_silently=False,
        )

        # Oznacz jako wysłane
        pr.status = "wyslane"
        pr.wyslane = True
        pr.data_wyslania = timezone.now()
        pr.save(update_fields=["status", "wyslane", "data_wyslania"])

        logger.info(f"Email wysłany dla przypomnienia {przypomnienie_id} ({dni_do} dni przed terminem)")
        return f"Email wysłany dla przypomnienia {przypomnienie_id}"

    except Przypomnienie.DoesNotExist:
        logger.error(f"Przypomnienie {przypomnienie_id} nie istnieje")
        return f"Przypomnienie {przypomnienie_id} nie istnieje"
    except Exception as e:
        logger.error(f"Błąd wysyłania emaila: {str(e)}")
        return f"Błąd wysyłania emaila: {str(e)}"

@shared_task
def sprawdz_przypomnienia():
    """
    Wysyła emaile 3 dni przed terminem podlewania.
    Uruchamiane co godzinę przez Celery Beat.
    """
    teraz = timezone.now()
    za_3_dni = teraz + timedelta(days=3)
    za_3_dni_koniec = za_3_dni + timedelta(hours=1)  # Okno 1h

    qs = Przypomnienie.objects.filter(
        data_przypomnienia__gte=za_3_dni,
        data_przypomnienia__lte=za_3_dni_koniec,
        status="oczekujace",
        wyslane=False,
    )

    wyslane = 0
    for pr in qs.select_related("uzytkownik", "roslina"):
        # tylko jeśli user ma włączone maile
        if hasattr(pr.uzytkownik, "profiluzytkownika") and pr.uzytkownik.profiluzytkownika.powiadomienia_email:
            wyslij_email_przypomnienie.delay(pr.id)
            wyslane += 1

    logger.info(f"Zaplanowano wysłanie {wyslane} przypomnień (3 dni przed terminem) z {qs.count()} dostępnych")
    return f"Zaplanowano wysłanie {wyslane} przypomnień"

# ============================================
# PRZYPOMNIENIA - ODSWIEZANIE (zamiast 'generowania w przód')
# ============================================

@shared_task
def odswiez_przypomnienia_dla_wszystkich():
    """
    Dzienny refresh: dla każdej aktywnej rośliny utrzymuj JEDNO otwarte przypomnienie
    (RF → fallback stat). Uruchamiane np. codziennie o 06:00.
    """
    rosliny = Roslina.objects.filter(is_active=True).values_list("id", flat=True)
    ok = err = 0
    for rid in rosliny:
        res = odswiez_przypomnienie_rosliny.delay(rid)
        ok += 1 if res else 0
    logger.info(f"[ONE-OPEN] Odświeżono przypomnienia dla {ok}/{len(rosliny)} roślin.")
    return f"Odświeżono {ok}/{len(rosliny)} roślin"

# Zachowaj zgodność nazw z istniejącym harmonogramem (stara nazwa → nowa logika)
generuj_przypomnienia_dla_wszystkich = odswiez_przypomnienia_dla_wszystkich




@shared_task
def sprawdz_inteligentne_przypomnienia():
    """
    (Zachowane dla zgodności) – tylko „odświeża” przypomnienia RF/stat,
    bez tworzenia duplikatów. Możesz usunąć to zadanie z harmonogramu,
    jeśli używasz wyłącznie odswiez_przypomnienia_dla_wszystkich + sprawdz_przypomnienia.
    """
    return odswiez_przypomnienia_dla_wszystkich()


# ============================================
# ANALIZA ML - AKTUALIZACJE
# ============================================

@shared_task
def analizuj_wszystkie_rosliny():
    """
    Analizuje wzorce podlewania dla wszystkich roślin. Uruchamiane codziennie o 3:00.
    """
    rosliny = Roslina.objects.filter(is_active=True)

    zaktualizowane = 0
    pominiete = 0
    bledy = 0

    for roslina in rosliny:
        try:
            wynik = zaktualizuj_analize_rosliny(roslina)
            if wynik["analiza"]:
                zaktualizowane += 1
            else:
                pominiete += 1
        except Exception as e:
            bledy += 1
            logger.error(f"Błąd analizy rośliny {roslina.nazwa} (ID: {roslina.id}): {str(e)}")

    logger.info(
        f"Analiza zakończona: zaktualizowane={zaktualizowane}, "
        f"pominięte={pominiete}, błędy={bledy}"
    )

    return f"Przeanalizowano {zaktualizowane}/{rosliny.count()} roślin (pominięto: {pominiete}, błędy: {bledy})"


@shared_task
def retrenuj_modele_ml():
    """
    Retrenuje wszystkie modele ML (np. raz w tygodniu w nocy).
    """
    logger.info("Rozpoczęcie retrenowania modeli ML...")

    wynik = retrenuj_wszystkie_modele()

    logger.info(
        f"Retrenowanie zakończone: wytrenowane={wynik['wytrenowane']}, "
        f"pominięte={wynik.get('pominiete', 0)}, błędy={wynik['bledy']}"
    )

    return (f"Wytrenowano {wynik['wytrenowane']}/{wynik['total']} modeli "
            f"(błędy: {wynik['bledy']})")


@shared_task
def zastosuj_rekomendacje_automatycznie():
    """
    Automatycznie stosuje rekomendacje ML gdzie pewność >= 0.5
    Uruchamiane np. raz w tygodniu (sobota, 4:00)
    """
    analizy = AnalizaPielegnacji.objects.filter(
        pewnosc_rekomendacji__gte=0.7,
        liczba_podlan__gte=8
    ).select_related("roslina")

    zastosowano = 0
    pominiete = 0
    bledy = 0

    for analiza in analizy:
        try:
            wynik = zastosuj_rekomendacje_ml(analiza.roslina, min_pewnosc=0.5)
            if wynik["zastosowano"]:
                zastosowano += 1
                logger.info(
                    f"Zastosowano rekomendację dla {analiza.roslina.nazwa}: "
                    f"{wynik['stara']} → {wynik['nowa']} dni"
                )
            else:
                pominiete += 1
                logger.debug(f"Pominięto {analiza.roslina.nazwa}: {wynik['powod']}")
        except Exception as e:
            bledy += 1
            logger.error(
                f"Błąd zastosowania rekomendacji dla {analiza.roslina.nazwa} "
                f"(ID: {analiza.roslina.id}): {str(e)}"
            )

    logger.info(
        f"Automatyczne rekomendacje: zastosowano={zastosowano}, "
        f"pominięto={pominiete}, błędy={bledy}"
    )

    return (f"Automatycznie zaktualizowano {zastosowano}/{analizy.count()} roślin "
            f"(pominięto: {pominiete}, błędy: {bledy})")


# ============================================
# RAPORTY I PODSUMOWANIA
# ============================================

@shared_task
def test_ml_pipeline():
    """
    Testuje cały pipeline ML (analiza → trening)
    """
    wyniki = {
        "rosliny_przeanalizowane": 0,
        "modele_wytrenowane": 0,
        "rekomendacje_zastosowane": 0,
        "bledy": [],
    }

    try:
        rosliny = Roslina.objects.filter(is_active=True)[:5]
        # Analiza
        for r in rosliny:
            try:
                zaktualizuj_analize_rosliny(r)
                wyniki["rosliny_przeanalizowane"] += 1
            except Exception as e:
                wyniki["bledy"].append(f"Analiza {r.nazwa}: {str(e)}")

        # Trening
        from .ml_utils import trenuj_model_ml
        for r in rosliny:
            try:
                model = trenuj_model_ml(r)
                if model:
                    wyniki["modele_wytrenowane"] += 1
            except Exception as e:
                wyniki["bledy"].append(f"Trenowanie {r.nazwa}: {str(e)}")

        logger.info(f"Test ML pipeline zakończony: {wyniki}")
        return wyniki

    except Exception as e:
        logger.error(f"Błąd test ML pipeline: {e}")
        wyniki["bledy"].append(str(e))
        return wyniki


# ============================================
# UTRZYMANIE
# ============================================

@shared_task
def czyszczenie_starych_przypomnien():
    """
    Usuwa stare wykonane przypomnienia (starsze niż 3 miesiące)
    """
    try:
        granica = timezone.now() - timedelta(days=90)

        stare = Przypomnienie.objects.filter(
            status="wykonane",
            data_utworzenia__lt=granica,
        )

        liczba = stare.count()
        stare.delete()

        logger.info(f"Usunięto {liczba} starych przypomnień")
        return f"Usunięto {liczba} starych przypomnień"

    except Exception as e:
        logger.error(f"Błąd czyszczenia przypomnień: {e}")
        return f"Błąd: {str(e)}"

# alias wstecznej kompatybilności (jeśli masz gdzieś starą nazwę)
czyszczenie_starych_przypomnie = czyszczenie_starych_przypomnien
